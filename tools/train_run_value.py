"""整局价值网络训练

数据：社区铁甲 A10 整局记录（sources/community-runs/ironclad-a10-all.jsonl.gz，约 7 万局，全版本；去掉放弃 / 模组后 5.3 万局）。
  每局每一层「进入这一层之前」的家底（tools/runvalue_data.py 还原；牌组和结局逐张对比的一致率见输出）→ 这局最后有没有通关。
特征：policy/runvalue.py 的 features()（训练和运行同一份代码）。
模型：逻辑回归 / 宽+深（线性 + 一层隐藏层），numpy + scipy 稀疏矩阵，Adam + 早停；按对局划分（run_hash 哈希固定）：
  v0.111 的 20% 检验、10% 验证、70% 训练；其他版本的局只进训练（每 2 层取一个快照）。
比较（同一个 v0.111 检验集）：只用 v0.111 / 全版本 / 全版本 + 版本特征 / 再加水平代理（打法历史，运行时填人群平均）；线性 vs 宽+深。
  另外复现旧因子分解机（data/value_model.json）的划分，只在它没见过的局上公平比较。
采用后再拟合「下一个点」修正头（Q(家底, 下一个点类型)），最后在检验局面上算边际价值例子、和人类篝火 / 选牌的一致率，写进 meta.examples。
输出：data/run_value.json（policy/runvalue.py 读取）
用法：python3 tools/train_run_value.py [--cache 目录]                       # 全部比较，自动选
      python3 tools/train_run_value.py --quick --final style --out data/run_value_style.json --cache 目录   # 只训去混杂版
      python3 tools/train_run_value.py --examples-only --out data/run_value.json --cache 目录            # 只重算例子
单进程，BLAS 限 2 线程（本机负载高）；全量约 25 分钟（读数据 4 分钟）。
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2'); os.environ.setdefault('OMP_NUM_THREADS', '2'); os.environ.setdefault('MKL_NUM_THREADS', '2')
import argparse, array, collections, gzip, hashlib, json, math, sys, time
import numpy as np
import scipy.sparse as sp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, f'{HERE}/tools')
from policy import runvalue as RV
from runvalue_data import usable, parse_run, check_reconstruction

SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-all.jsonl.gz'
TARGET = 'v0.111.0'
ALL_OPT = {'card_act': 1, 'relic_act': 1, 'style': 1, 'version': 1}       # 先按全部特征算，再按方案挑列

ap = argparse.ArgumentParser()
ap.add_argument('--src', default=SRC); ap.add_argument('--cache', default='')
ap.add_argument('--hidden', type=int, default=32); ap.add_argument('--epochs', type=int, default=30)
ap.add_argument('--every', type=int, default=2, help='非 v0.111 的局每隔几层取一个快照（省内存）')
ap.add_argument('--min-rows', type=int, default=200, help='出现少于这么多快照的特征丢掉')
ap.add_argument('--quick', action='store_true', help='只训练最终方案（跳过对比）')
ap.add_argument('--final', default='nostyle', choices=['nostyle', 'style'], help='--quick 时训练哪个：不带 / 带水平代理（全版本 + 版本特征、线性）')
ap.add_argument('--out', default='data/run_value.json')
ap.add_argument('--examples-only', action='store_true', help='不训练，只用 --out 的模型和 --cache 的检验集算边际价值例子')
a = ap.parse_args()


def split_of(h):
    """按对局哈希固定划分：v0.111 的 20% 检验、10% 验证、其余训练"""
    x = int(hashlib.md5(str(h).encode()).hexdigest()[:8], 16) % 10
    return 'test' if x < 2 else 'val' if x == 2 else 'train'


# ================= 1. 读数据 → 稀疏特征矩阵 =================
def build():
    names = {}; ind = array.array('i'); val = array.array('f'); indptr = array.array('l', [0])
    cols = collections.defaultdict(lambda: array.array('f'))        # 每行的元数据
    test_states = []; test_picks = []
    stat = collections.Counter(); t0 = time.time()
    for ri, line in enumerate(gzip.open(a.src, 'rt')):
        if 'BaseLib' in line: stat['skip_mod'] += 1; continue
        d = json.loads(line)
        if not usable(d): stat['skip'] += 1; continue
        info, snaps = parse_run(d)
        ok, cdiff, udiff, _ = check_reconstruction(d, info)
        stat['runs'] += 1; stat['exact'] += ok; stat['ids_ok'] += (cdiff == 0)
        tgt = info['build'] == TARGET; spl = split_of(info['hash']) if tgt else 'other'
        stat['runs_' + spl] += 1
        for k, s in enumerate(snaps):
            if not tgt and a.every > 1 and k % a.every: continue
            st = {'act': s['act'], 'done': s['done'], 'hp': s['hp'], 'max_hp': s['max_hp'], 'gold': s['gold'],
                  'deck': [c for c, n in s['deck'].items() for _ in range(n)], 'relics': s['relics'], 'potions': s['potions'],
                  'chapter': info['chapter'], 'elites': s['elites'], 'elites_act': s['elites_act'], 'build': info['build'], 'hist': s['hist']}
            for nm, v in RV.features(st, ALL_OPT).items():
                j = names.get(nm)
                if j is None: j = names[nm] = len(names)
                ind.append(j); val.append(v)
            indptr.append(len(ind))
            for key, v in (('y', info['win']), ('run', ri), ('act', s['act']), ('done', s['done']), ('gfloor', s['gfloor']),
                           ('tgt', tgt), ('split', {'train': 0, 'val': 1, 'test': 2, 'other': 3}[spl]),
                           ('docks', info['chapter'] == 'UNDERDOCKS'), ('frac', s['hp'] / max(s['max_hp'], 1)),
                           ('rest', 1 if s.get('rest') else 0),
                           ('next', RV.NEXT_TYPES.index(s['next']) if s.get('next') in RV.NEXT_TYPES else -1),
                           ('rest_heal', 1 if s.get('rest') == ['HEAL'] else 0 if s.get('rest') == ['SMITH'] else -1)):
                cols[key].append(float(v))
            if spl == 'test':
                st = {k: v for k, v in st.items() if k not in ('hist', 'elites', 'elites_act')}     # 检验局面按运行时的样子存（没有打法历史）
                st['next'] = s['next']; st['rest'] = s.get('rest'); st['gfloor'] = s['gfloor']; st['win'] = info['win']; st['hash'] = info['hash']
                st['after'] = s.get('after'); st['rest_up'] = s.get('rest_up')
                test_states.append(st)
        if spl == 'test':
            for pk in info['picks']:
                pk = dict(pk, deck=[c for c, n in pk['deck'].items() for _ in range(n)], chapter=info['chapter'], build=info['build'], win=info['win'])
                test_picks.append(pk)
        if ri % 10000 == 0: print(f'  读到第 {ri} 行，{len(indptr) - 1} 个快照（{time.time() - t0:.0f} 秒）', flush=True)
    X = sp.csr_matrix((np.frombuffer(val, np.float32), np.frombuffer(ind, np.int32), np.frombuffer(indptr, np.int64)),
                      shape=(len(indptr) - 1, len(names)))
    meta = {k: np.frombuffer(v, np.float32).copy() for k, v in cols.items()}
    vocab = [None] * len(names)
    for k, j in names.items(): vocab[j] = k
    print(f'对局 {stat["runs"]}（跳过模组 {stat["skip_mod"]}、放弃 / 异常 {stat["skip"]}）；'
          f'牌组还原和结局逐张一致（含升级）{stat["exact"] / stat["runs"]:.1%}，牌 id 一致 {stat["ids_ok"] / stat["runs"]:.2%}；'
          f'v0.111 训练 {stat["runs_train"]} / 验证 {stat["runs_val"]} / 检验 {stat["runs_test"]}，其他版本 {stat["runs_other"]}；'
          f'快照 {X.shape[0]}，特征 {X.shape[1]}（{time.time() - t0:.0f} 秒）', flush=True)
    return X, meta, vocab, test_states, test_picks, dict(stat)



# ================= 边际价值例子 =================
def examples(path, states, picks, stride=1):
    """在真实检验局面上算「拿 / 不拿」「升级 / 回血」等的通关概率差，检查是否合理；再和人类（赢家）的实际选择比一致率"""
    RV.OVERRIDE = path; RV._M = None; pr = RV.prob_of; kb = RV.kb_cards(); rep = {}
    vocab_m = set(RV._load()['idx'])
    tagn = lambda s, t: sum(1 for c, _ in s['deck'] if t in (kb.get(c) or (None, ()))[1])
    has = lambda s, c: any(x == c for x, _ in s['deck'])
    early = [s for s in states if s['act'] == 1 and 2 <= s['done'] <= 6][::3]
    print(f'\n== 边际价值（通关概率差，百分点；第一幕前段 {len(early)} 个真实检验局面的平均）==')
    cards = ['DEMON_FORM', 'INFLAME', 'UPPERCUT', 'THUNDERCLAP', 'SHRUG_IT_OFF', 'OFFERING', 'FEED', 'PERFECTED_STRIKE', 'POMMEL_STRIKE',
             'TWIN_STRIKE', 'ANGER', 'BLUDGEON', 'HEMOKINESIS', 'FEEL_NO_PAIN', 'CORRUPTION', 'BARRICADE', 'BATTLE_TRANCE', 'WHIRLWIND',
             'BREAKTHROUGH', 'STOMP', 'IRON_WAVE', 'TRUE_GRIT', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'INJURY', 'CLUMSY', 'DOUBT']
    rows = []
    for c in cards:
        if 'c:' + c not in vocab_m: continue
        ss = [s for s in early if not has(s, c) or c in ('STRIKE_IRONCLAD', 'DEFEND_IRONCLAD')]
        ds = np.array([pr(RV.with_card(s, c)) - pr(s) for s in ss])
        rows.append((c, float(ds.mean() * 100), float(np.percentile(ds, 10) * 100), float(np.percentile(ds, 90) * 100)))
    rows.sort(key=lambda r: -r[1])
    for c, m, lo, hi in rows: print(f'  拿 {c:18s} {m:+5.2f}（10%~90% 分位 {lo:+.2f} ~ {hi:+.2f}）')
    rep['card_early_act1'] = rows
    # 同一张牌在不同幕
    print('  分幕（各幕全部局面平均）：')
    rep['card_by_act'] = {}
    for c in ('DEMON_FORM', 'INFLAME', 'THUNDERCLAP', 'SHRUG_IT_OFF', 'BLUDGEON', 'STRIKE_IRONCLAD'):
        if 'c:' + c not in vocab_m: continue
        v = []
        for ac in (1, 2, 3):
            ss = [s for s in states if s['act'] == ac and not (has(s, c) and c != 'STRIKE_IRONCLAD')][::7]
            v.append(float(np.mean([pr(RV.with_card(s, c)) - pr(s) for s in ss]) * 100))
        rep['card_by_act'][c] = v
        print(f'    {c:16s} 第一幕 {v[0]:+.2f} / 第二幕 {v[1]:+.2f} / 第三幕 {v[2]:+.2f}')
    # 第二张易伤（痛击之外）：牌组里易伤牌只有痛击 vs 已经有两张以上
    one = [s for s in early if tagn(s, 'vuln') == 1]; two = [s for s in states if s['act'] == 1 and 2 <= s['done'] <= 12 and tagn(s, 'vuln') >= 2][::2]
    rep['second_vuln'] = {}
    for c in ('UPPERCUT', 'THUNDERCLAP', 'TREMBLE'):
        if 'c:' + c not in vocab_m: continue
        d1 = float(np.mean([pr(RV.with_card(s, c)) - pr(s) for s in one]) * 100)
        d2 = float(np.mean([pr(RV.with_card(s, c)) - pr(s) for s in two if not has(s, c)] or [0]) * 100)
        rep['second_vuln'][c] = [d1, d2]
        print(f'  易伤递减 {c}: 只有痛击时拿 {d1:+.2f}，已有 ≥2 张易伤时拿 {d2:+.2f}（{len(one)} / {len(two)} 个局面）')
    # 同名第二张
    rep['second_copy'] = {}
    for c in ('INFLAME', 'SHRUG_IT_OFF', 'DEMON_FORM'):
        if 'c:' + c not in vocab_m: continue
        a0 = [s for s in states if s['act'] <= 2 and not has(s, c)][::9]; a1 = [s for s in states if s['act'] <= 2 and sum(1 for x, _ in s['deck'] if x == c) == 1][::2]
        d0 = float(np.mean([pr(RV.with_card(s, c)) - pr(s) for s in a0]) * 100); d1 = float(np.mean([pr(RV.with_card(s, c)) - pr(s) for s in a1] or [0]) * 100)
        rep['second_copy'][c] = [d0, d1]
        print(f'  同名递减 {c}: 第一张 {d0:+.2f}，第二张 {d1:+.2f}')
    # 删牌 / 金币 / 血量
    for lab, fn in (('删一张打击', lambda s: pr(RV.without_card(s, 'STRIKE_IRONCLAD')) - pr(s)),
                    ('删一张防御', lambda s: pr(RV.without_card(s, 'DEFEND_IRONCLAD')) - pr(s)),
                    ('+100 金币', lambda s: pr(dict(s, gold=s['gold'] + 100)) - pr(s)),
                    ('+10 血', lambda s: pr(dict(s, hp=min(s['max_hp'], s['hp'] + 10))) - pr(s)),
                    ('+1 瓶药水（随便一瓶：火焰药水）', lambda s: pr(RV.with_potion(s, 'FIRE_POTION')) - pr(s))):
        v = [float(np.mean([fn(s) for s in states if s['act'] == ac and s['hp'] < s['max_hp'] - 10][::9]) * 100) for ac in (1, 2, 3)]
        rep[lab] = v; print(f'  {lab}: 第一幕 {v[0]:+.2f} / 第二幕 {v[1]:+.2f} / 第三幕 {v[2]:+.2f}')
    # 遗物（第一幕前段，只看模型认识的）
    rel = sorted({k[2:] for k in vocab_m if k.startswith('r:') and '|' not in k})
    rr = []
    for r in rel:
        ss = [s for s in early[::2] if r not in s['relics']]
        if ss: rr.append((r, float(np.mean([pr(RV.with_relic(s, r)) - pr(s) for s in ss]) * 100)))
    rr.sort(key=lambda x: -x[1]); rep['relic_early_act1'] = rr
    print('  遗物（第一幕前段）最高：' + '，'.join(f'{r} {v:+.1f}' for r, v in rr[:10]))
    print('  遗物（第一幕前段）最低：' + '，'.join(f'{r} {v:+.1f}' for r, v in rr[-6:]))
    # 篝火：回血 vs 升级，和人类比。程序做决定时看得到地图，这里用人类实际走的下一个点当「篝火之后的点」
    rs = [dict(s, done=s['done'] + 1) for s in states if s.get('rest') in (['HEAL'], ['SMITH'])][::stride]     # 在篝火这一层做决定 = 本幕已打完 done+1 层
    rep['rest'] = {}
    for mode in ('家底', '家底+下一个点'):
        agree = collections.Counter(); bucket = collections.defaultdict(lambda: [0, 0, 0]); up_ok = collections.Counter(); ups = collections.Counter()
        for s in rs:
            nt = [s['after']] if mode != '家底' and s.get('after') else None
            v = RV.rest_values(s, next_types=nt); m_heal = v['pick'] == 'HEAL'
            h_heal = s['rest'] == ['HEAL']; w = 'win' if s['win'] else 'loss'
            agree[w + '_n'] += 1; agree[w + '_ok'] += (m_heal == h_heal)
            b = min(int(s['hp'] / max(s['max_hp'], 1) * 5), 4); k = bucket[(s['act'], b, 'boss' if s.get('after') == 'boss' else '')]
            k[0] += 1; k[1] += m_heal; k[2] += h_heal
            if not h_heal and s.get('rest_up') and s['win']:
                up_ok['n'] += 1; up_ok['ok'] += (v['SMITH'][1] == s['rest_up'][0])
            if not m_heal and v['SMITH'][1]: ups[(s['act'], v['SMITH'][1])] += 1
        r = {'agree_winners': agree['win_ok'] / max(agree['win_n'], 1), 'agree_losers': agree['loss_ok'] / max(agree['loss_n'], 1), 'n': len(rs),
             'upgrade_same_card_as_winner': up_ok['ok'] / max(up_ok['n'], 1),
             'by_bucket': {f'act{ac}_hp{b * 20}-{b * 20 + 20}%{"_beforeboss" if bb else ""}': {'n': k[0], 'model_heal': k[1] / k[0], 'human_heal': k[2] / k[0]}
                           for (ac, b, bb), k in sorted(bucket.items())}}
        rep['rest'][mode] = r
        print(f'  篝火【{mode}】（{len(rs)} 次人类回血 / 升级）：回血还是升级 模型和赢家一致 {r["agree_winners"]:.1%}，和输家一致 {r["agree_losers"]:.1%}；'
              f'赢家升级时升的是同一张 {r["upgrade_same_card_as_winner"]:.1%}')
        for key, x in r['by_bucket'].items():
            if x['n'] >= 40: print(f'    {key}: 模型回血 {x["model_heal"]:.0%} / 人类回血 {x["human_heal"]:.0%}（{x["n"]} 次）')
        print('    模型最常升级：' + '，'.join(f'第{ac}幕 {c} {n}' for (ac, c), n in ups.most_common(6)))
    # 路线：同一家底，下一步进精英 vs 普通战（按血量分档；牌组强度 = 家底的通关概率分档）
    if RV._load()['nh']:
        rows = collections.defaultdict(list)
        for s in [x for x in states if x['act'] in (1, 2) and x['next'] in ('monster', 'elite', 'unknown', 'rest_site', 'shop')][::4]:
            b = min(int(s['hp'] / max(s['max_hp'], 1) * 4), 3); q = RV.route_values(s, ['monster', 'elite', 'unknown', 'rest_site', 'shop'])
            strong = 'strong' if pr(s) >= 0.3 else 'weak'
            rows[(s['act'], b, strong)].append([q['elite'] - q['monster'], q['unknown'] - q['monster'], q['rest_site'] - q['monster'], q['shop'] - q['monster']])
        rep['route'] = {}
        print('  路线（下一步进 X 减去进普通战，百分点；按幕 / 血量 / 家底强弱）：')
        for k in sorted(rows):
            m = np.mean(rows[k], 0) * 100; rep['route'][f'act{k[0]}_hp{k[1] * 25}-{k[1] * 25 + 25}%_{k[2]}'] = {'n': len(rows[k]), 'elite': m[0], 'unknown': m[1], 'rest': m[2], 'shop': m[3]}
            if len(rows[k]) >= 30:
                print(f'    第{k[0]}幕 血 {k[1] * 25}-{k[1] * 25 + 25}% 家底{"强" if k[2] == "strong" else "弱"}（{len(rows[k])}）：精英 {m[0]:+.1f}  问号 {m[1]:+.1f}  篝火 {m[2]:+.1f}  商店 {m[3]:+.1f}')
    # 战后选牌：模型（拿了之后通关概率最高的选项，含跳过）和人类比
    pk = picks[::stride]; ok = collections.Counter(); pm_ok = collections.Counter()
    try:
        from policy import pickmodel as PM
        pm = PM.available()
    except Exception:
        pm = False
    for d in pk:
        vals = [pr(RV.with_card(d, c, u)) for c, u in d['offered']] + [pr(d)]
        ch = int(np.argmax(vals)); ch = -1 if ch == len(d['offered']) else ch
        w = 'win' if d['win'] else 'loss'; ok[w + '_n'] += 1; ok[w + '_ok'] += (ch == d['picked'])
        ok[w + '_skip_m'] += (ch == -1); ok[w + '_skip_h'] += (d['picked'] == -1)
        if pm:
            ids = [c for c, _ in d['deck']] + ['R:' + r for r in d['relics']]
            us = []
            for c, _ in d['offered']:
                t = (kb.get(c) or ('Other',))[0]
                u = PM.utility(c, t, ids, d['act']); us.append(-99 if u is None else u)
            us.append(PM.skip_utility(ids, d['act'])); c2 = int(np.argmax(us)); c2 = -1 if c2 == len(d['offered']) else c2
            pm_ok[w] += (c2 == d['picked'])
    rep['picks'] = {'n_win': ok['win_n'], 'agree_winners': ok['win_ok'] / max(ok['win_n'], 1), 'agree_losers': ok['loss_ok'] / max(ok['loss_n'], 1),
                    'skip_rate_model_win': ok['win_skip_m'] / max(ok['win_n'], 1), 'skip_rate_human_win': ok['win_skip_h'] / max(ok['win_n'], 1),
                    'pickmodel_agree_winners': pm_ok['win'] / max(ok['win_n'], 1) if pm else None}
    print(f'  战后选牌（检验局 {ok["win_n"] + ok["loss_n"]} 次）：模型和赢家一致 {rep["picks"]["agree_winners"]:.1%}，和输家一致 {rep["picks"]["agree_losers"]:.1%}；'
          f'跳过率 模型 {rep["picks"]["skip_rate_model_win"]:.0%} / 赢家 {rep["picks"]["skip_rate_human_win"]:.0%}'
          + (f'；参照：选牌模型 pick_model.json 和赢家一致 {rep["picks"]["pickmodel_agree_winners"]:.1%}（它的训练集和这批局有重叠）' if pm else ''))
    return rep


if a.examples_only:
    X = None
    if a.cache:
        extra = json.load(open(f'{a.cache}/extra.json')); ts, tp = extra['test_states'], extra['test_picks']
        for x in ts + tp: x['deck'] = [tuple(c) for c in x['deck']]
        for x in tp: x['offered'] = [tuple(c) for c in x['offered']]
        rep = examples(os.path.join(HERE, a.out), ts, tp)
        d = json.load(open(os.path.join(HERE, a.out))); d.setdefault('meta', {})['examples'] = rep
        json.dump(d, open(os.path.join(HERE, a.out), 'w'), ensure_ascii=False)
    sys.exit(0)


if a.cache and os.path.exists(f'{a.cache}/X.npz'):
    X = sp.load_npz(f'{a.cache}/X.npz'); z = np.load(f'{a.cache}/meta.npz'); meta = {k: z[k] for k in z.files}
    extra = json.load(open(f'{a.cache}/extra.json')); vocab, test_states, test_picks, STAT = extra['vocab'], extra['test_states'], extra['test_picks'], extra['stat']
    for x in test_states + test_picks: x['deck'] = [tuple(c) for c in x['deck']]
    for x in test_picks: x['offered'] = [tuple(c) for c in x['offered']]
    print(f'从缓存读入 {X.shape[0]} 个快照、{X.shape[1]} 个特征')
else:
    X, meta, vocab, test_states, test_picks, STAT = build()
    if a.cache:
        os.makedirs(a.cache, exist_ok=True); sp.save_npz(f'{a.cache}/X.npz', X); np.savez(f'{a.cache}/meta.npz', **meta)
        json.dump({'vocab': vocab, 'test_states': test_states, 'test_picks': test_picks, 'stat': STAT}, open(f'{a.cache}/extra.json', 'w'))
Y = meta['y']; SPL = meta['split']; TGT = meta['tgt'] > 0.5; ACT = meta['act']


# ================= 2. 模型：宽 + 深 =================
def sig(z): return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def forward(P, Xb):
    z = Xb @ P['w'] + P['b']
    if 'W1' in P:
        pre = Xb @ P['W1'] + P['b1']; h = np.maximum(pre, 0); z = z + h @ P['w2']
        return z, h
    return z, None


def predict(P, Xm, bs=65536):
    return np.concatenate([sig(forward(P, Xm[i:i + bs])[0]) for i in range(0, Xm.shape[0], bs)])


def logloss(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p, y):
    o = np.argsort(p, kind='mergesort'); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    # 同分取平均名次
    ps = p[o]; i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]: j += 1
        if j > i: r[o[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    pos = y > 0.5; n1 = pos.sum(); n0 = len(y) - n1
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / max(n1 * n0, 1))


def train(Xtr, ytr, Xva, yva, H, l2w, l2d, epochs, lr=2e-3, bs=1024, seed=0, verbose=True):
    rng = np.random.default_rng(seed); F = Xtr.shape[1]
    P = {'w': np.zeros(F), 'b': np.array(math.log(ytr.mean() / (1 - ytr.mean())))}
    if H: P.update({'W1': rng.normal(0, 0.05, (F, H)), 'b1': np.zeros(H), 'w2': rng.normal(0, 0.05, H)})
    Mo = {k: np.zeros_like(v, dtype=float) for k, v in P.items()}; Vo = {k: np.zeros_like(v, dtype=float) for k, v in P.items()}
    b1, b2, eps, t = 0.9, 0.999, 1e-8, 0
    best = (9e9, None, -1); bad = 0; n = Xtr.shape[0]
    for ep in range(epochs):
        perm = rng.permutation(n); t1 = time.time()
        for s0 in range(0, n, bs):
            bi = perm[s0:s0 + bs]; Xb = Xtr[bi]; yb = ytr[bi]
            z, h = forward(P, Xb); g = (sig(z) - yb) / len(bi)
            G = {'w': Xb.T @ g + l2w * P['w'], 'b': np.array(g.sum())}
            if H:
                G['w2'] = h.T @ g + l2d * P['w2']
                dh = np.outer(g, P['w2']) * (h > 0)
                G['W1'] = Xb.T @ dh + l2d * P['W1']; G['b1'] = dh.sum(0)
            t += 1
            for k in P:
                Mo[k] = b1 * Mo[k] + (1 - b1) * G[k]; Vo[k] = b2 * Vo[k] + (1 - b2) * G[k] ** 2
                P[k] = P[k] - lr * (Mo[k] / (1 - b1 ** t)) / (np.sqrt(Vo[k] / (1 - b2 ** t)) + eps)
        pv = predict(P, Xva); ll = logloss(pv, yva)
        if verbose: print(f'    第 {ep + 1} 轮 验证对数损失 {ll:.4f}  AUC {auc(pv, yva):.4f}（{time.time() - t1:.0f} 秒）', flush=True)
        if ll < best[0] - 1e-5: best = (ll, {k: v.copy() for k, v in P.items()}, ep + 1); bad = 0
        else:
            bad += 1
            if bad >= 3: break
    return best[1], best[0], best[2]


def report(p, mask, label):
    y = Y[mask]; pp = p[mask] if len(p) == len(Y) else p
    r = {'n': int(mask.sum()), 'logloss': logloss(pp, y), 'auc': auc(pp, y), 'brier': float(np.mean((pp - y) ** 2))}
    for ac in (1, 2, 3):
        m = ACT[mask] == ac
        if m.sum(): r[f'act{ac}'] = {'n': int(m.sum()), 'auc': auc(pp[m], y[m]), 'logloss': logloss(pp[m], y[m]), 'mean_pred': float(pp[m].mean()), 'win_rate': float(y[m].mean())}
    print(f'  {label}: 对数损失 {r["logloss"]:.4f}  AUC {r["auc"]:.4f}  Brier {r["brier"]:.4f}  | 分幕 AUC ' +
          ' / '.join(f'{r[f"act{ac}"]["auc"]:.3f}' for ac in (1, 2, 3) if f'act{ac}' in r), flush=True)
    return r


def calibration(p, mask):
    y = Y[mask]; pp = p[mask] if len(p) == len(Y) else p; out = {}
    edges = [0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    for ac in (1, 2, 3):
        m = ACT[mask] == ac; rows = []
        for lo, hi in zip(edges, edges[1:]):  # noqa
            k = m & (pp >= lo) & (pp < hi)
            if k.sum() >= 30: rows.append([round(lo, 2), round(min(hi, 1), 2), int(k.sum()), round(float(pp[k].mean()), 3), round(float(y[k].mean()), 3)])
        out[f'act{ac}'] = rows
    return out


# ================= 3. 方案比较 =================
def colmask(pred):
    return np.array([pred(n) for n in vocab])


def is_card_act(n): return (n.startswith('c:') or n.startswith('r:')) and '|A' in n


def keep_base(n): return not (is_card_act(n) or n.startswith('sk:') or n.startswith('v:'))


def keep_simple(n): return n.split('|')[0] in ('act1', 'act2', 'act3', 'prog', 'prog2', 'frac', 'frac*prog', 'hp', 'hp*prog', 'mhp', 'lo30', 'lo50')


def card_act(n): return keep_base(n) or is_card_act(n)


def with_version(n): return card_act(n) or n.startswith('v:')


def with_style(n): return with_version(n) or n.startswith('sk:')


tr_t = (SPL == 0); va = (SPL == 1); te = (SPL == 2); other = (SPL == 3)
DONE = meta['done']; KEY = ACT * 100 + np.minimum(DONE, 18)
print(f'检验集（v0.111，{int(te.sum())} 个快照，通关局快照占 {Y[te].mean():.1%}）；平均每个快照 {np.diff(X.indptr).mean():.0f} 个非零特征')

# 打法历史（水平代理）的人群平均：v0.111 训练局按（幕, 本幕已打完层数）取平均。运行时没有历史，就填这个
SCOL = np.array([j for j, n in enumerate(vocab) if n.startswith('sk:')])
_S = X[tr_t][:, SCOL].toarray(); _K = KEY[tr_t]
REF = {int(k): _S[_K == k].mean(0) for k in np.unique(_K)}
style_ref = {f'{k // 100}|{k % 100}': {vocab[j]: round(float(v), 5) for j, v in zip(SCOL, REF[k]) if abs(v) > 1e-9} for k in REF}


def deployed(rows, cm):
    """rows 行、cm 列的矩阵，把打法历史列换成人群平均（= 运行时的样子）"""
    Xm = X[rows][:, cm]; cols = np.where(cm)[0]
    pos = [i for i, j in enumerate(cols) if vocab[j].startswith('sk:')]
    if not pos: return Xm
    keep = np.ones(len(cols)); keep[pos] = 0; Xm = Xm @ sp.diags(keep)
    jj = [int(np.where(SCOL == cols[i])[0][0]) for i in pos]
    ks = KEY[rows]; R = np.zeros((len(ks), len(pos)))
    for k in np.unique(ks):
        ref = REF.get(int(k))
        if ref is None: ref = REF[min(REF, key=lambda x: abs(x - k))]
        R[ks == k] = ref[jj]
    Rs = sp.csr_matrix((R.ravel(), (np.repeat(np.arange(len(ks)), len(pos)), np.tile(pos, len(ks)))), shape=Xm.shape)
    return (Xm + Rs).tocsr()


def run_variant(label, train_rows, cpred, H, l2w, l2d, epochs=None, verbose=False):
    cm = colmask(cpred)
    freq = np.bincount(X[train_rows].indices, minlength=X.shape[1])
    cm &= freq >= a.min_rows
    Xtr, Xva = X[train_rows][:, cm], X[va][:, cm]
    t0 = time.time()
    P, vll, ep = train(Xtr, Y[train_rows], Xva, Y[va], H, l2w, l2d, epochs or a.epochs, verbose=verbose)
    style = any(vocab[j].startswith('sk:') for j in np.where(cm)[0])
    dva = logloss(predict(P, deployed(va, cm)), Y[va]) if style else vll        # 运行时口径（历史填人群平均）的验证损失
    print(f'[{label}] 特征 {int(cm.sum())}，训练快照 {int(train_rows.sum())}，隐藏 {H}，l2 {l2w:g}/{l2d:g}，第 {ep} 轮最好，'
          f'验证 {vll:.4f}' + (f'（运行时口径 {dva:.4f}）' if style else '') + f'（{time.time() - t0:.0f} 秒）')
    r_or = None
    if style: r_or = report(predict(P, X[te][:, cm]), te, '  检验（用真实打法历史，只作参考）')
    pte = predict(P, deployed(te, cm)); r = report(pte, te, '  检验' + ('（运行时口径：历史填人群平均）' if style else ''))
    return {'label': label, 'rows': train_rows, 'cm': cm, 'P': P, 'val_ll': dva, 'val_oracle': vll, 'test': r, 'test_oracle': r_or, 'pte': pte, 'H': H, 'l2': [l2w, l2d], 'epoch': ep, 'style': style}


base_rate = float(Y[tr_t].mean())
p_const = np.full(int(te.sum()), base_rate)
r_const = report(p_const, te, '参照：只猜平均通关率')
r_simple = run_variant('参照：只看幕 / 进度 / 血量', tr_t, keep_simple, 0, 1e-6, 0, epochs=15)

if not a.quick:
    # A. 只用 v0.111：线性挑 L2 → 加牌/遗物×幕 → 宽+深
    A = [run_variant(f'v0.111 线性 l2={l2:g}', tr_t, keep_base, 0, l2, 0) for l2 in (1e-3, 3e-3)]
    l2A = min(A, key=lambda r: r['val_ll'])['l2'][0]
    A.append(run_variant(f'v0.111 线性+牌/遗物×幕 l2={l2A:g}', tr_t, card_act, 0, l2A, 0))
    A.append(run_variant(f'v0.111 宽+深 H={a.hidden} l2={l2A:g}/1e-2', tr_t, card_act, a.hidden, l2A, 1e-2))
    # B / C. 全版本（非 v0.111 的局每 a.every 层取一个快照）+ v0.111 训练部分；同一个 v0.111 检验集
    all_rows = tr_t | other
    B = [run_variant(f'全版本 线性 l2={l2:g}', all_rows, card_act, 0, l2, 0) for l2 in (1e-4, 3e-4, 1e-3)]
    C = [run_variant(f'全版本+版本特征 线性 l2={l2:g}', all_rows, with_version, 0, l2, 0) for l2 in (1e-4, 3e-4, 1e-3)]
    l2C = min(C, key=lambda r: r['val_ll'])['l2'][0]
    C.append(run_variant(f'全版本+版本特征 宽+深 H={a.hidden} l2={l2C:g}/1e-2', all_rows, with_version, a.hidden, l2C, 1e-2))
    # D. 再加打法历史（水平代理）做去混杂；运行时历史填人群平均
    D = [run_variant(f'全版本+版本+水平代理 线性 l2={l2C:g}', all_rows, with_style, 0, l2C, 0),
         run_variant(f'全版本+版本+水平代理 宽+深 H={a.hidden} l2={l2C:g}/1e-2', all_rows, with_style, a.hidden, l2C, 1e-2)]
    results = [r_simple] + A + B + C + D
    # 选法：做决定要的是「同一局面下选项的差」，水平代理能把高手习惯从牌 / 遗物权重里剥掉，所以只要运行时口径的验证损失
    # 不比最好的无代理方案差 0.003 以上就用带代理的；宽+深只有比线性好 0.001 以上才用（线性快、好解释）
    def pick(rs):
        lin = min((r for r in rs if r['H'] == 0), key=lambda r: r['val_ll']); deep = [r for r in rs if r['H'] > 0]
        best = min(deep, key=lambda r: r['val_ll']) if deep else None
        return best if best and best['val_ll'] < lin['val_ll'] - 0.001 else lin
    no_style = pick(A + B + C); sty = pick(D)
    final = sty if sty['val_ll'] <= no_style['val_ll'] + 0.003 else no_style
else:
    final = run_variant('全版本+版本+水平代理 线性 l2=1e-4' if a.final == 'style' else '全版本+版本特征 线性 l2=1e-4', tr_t | other,
                        with_style if a.final == 'style' else with_version, 0, 1e-4, 0)
    results = [r_simple, final]
print(f'\n采用：{final["label"]}')

# ================= 4. 校准 + 保存 =================
cal = calibration(final['pte'], te)
for k, rows in cal.items():
    print(f'  校准 {k}（预测区间 / 快照数 / 平均预测 / 实际通关率）：' + '；'.join(f'{lo}-{hi} n={n} {pm:.2f}/{yr:.2f}' for lo, hi, n, pm, yr in rows))
by_ch = {}
for ch, m in (('OVERGROWTH', meta['docks'] < 0.5), ('UNDERDOCKS', meta['docks'] > 0.5)):
    k = te & m & (ACT == 1); kk = (ACT[te] == 1) & m[te]
    by_ch[ch] = {'n': int(k.sum()), 'auc': auc(final['pte'][kk], Y[k]), 'mean_pred': float(final['pte'][kk].mean()), 'win_rate': float(Y[k].mean())}
print('  第一幕按章节：', {k: {kk: round(v, 3) for kk, v in d.items()} for k, d in by_ch.items()})

# 和旧因子分解机公平比较：复现 tools/train_value_model.py 的划分，只在它没训练过的局上比
old_fm = None
try:
    from policy import valuemodel as VM
    if VM.available():
        rr = []; hh = {}
        for ri, line in enumerate(gzip.open('/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt')):
            d = json.loads(line)
            if d.get('was_abandoned') or d.get('modifiers') or len(d.get('players') or []) != 1 or 'BaseLib' in line: continue
            if sum(len(x) for x in d.get('map_point_history') or []) >= 2: rr.append(ri); hh[ri] = d.get('run_hash')
        runs = np.unique(np.array(rr, np.int32)); np.random.RandomState(2).shuffle(runs)
        fm_test = {hh[int(r)] for r in runs[:len(runs) // 5]}
        sub = np.array([s.get('hash') in fm_test for s in test_states])
        po = np.array([VM.win_prob({'deck': s['deck'], 'relics': s['relics'], 'hp': s['hp'], 'max_hp': s['max_hp'], 'gold': s['gold'],
                                    'pots': len(s['potions']), 'act': s['act'], 'floor': max(s['gfloor'], 1)}) for s in test_states])
        tem = te.copy(); tem[te] = sub
        print(f'  和旧因子分解机 value_model.json 比（只用它没训练过的 {int(sub.sum())} 个检验快照）：')
        old_fm = {'fair_old': report(po[sub], tem, '    旧模型'), 'fair_new': report(final['pte'][sub], tem, '    新模型（同一批局）')}
except Exception as e:
    print('旧模型对比跳过：', repr(e))

# ================= 5. 下一个点修正（Q 头）：logit = z(家底) + 修正(下一个点的类型 × 血量 / 牌组强度 / 进度 / 金币 / 药水) =================
# 让路线和篝火能比「下一步进精英 / 普通战 / 篝火 / Boss……」：同一家底下，人类走进不同类型的点之后的通关率差
from scipy.optimize import minimize
NX = meta['next'].astype(int)
J = {n: j for j, n in enumerate(vocab)}


def head_design(rows, z):
    cols = {}; ri, ci, vv = [], [], []
    idx = np.where(rows)[0]
    G = {k: (X[idx][:, J[k]].toarray().ravel() if k in J else np.zeros(len(idx))) for k in ('hp', 'frac', 'gold', 'pots')}
    for n, r in enumerate(idx):
        hp = G['hp'][n] * 80.0; fr = G['frac'][n]
        st_ = {'act': int(ACT[r]), 'done': int(DONE[r]), 'hp': hp, 'max_hp': hp / fr if fr > 0 else 80.0, 'gold': G['gold'][n] * 300.0,
               'potions': ['x'] * int(round(G['pots'][n] * 3))}
        for k, v in RV.next_feats(st_, float(z[n]), RV.NEXT_TYPES[NX[r]]).items():
            if v:
                c = cols.get(k)
                if c is None: c = cols[k] = len(cols)
                ri.append(n); ci.append(c); vv.append(v)
    return sp.csr_matrix((vv, (ri, ci)), shape=(len(idx), max(len(cols), 1))), cols


def zof(rows): return forward(final['P'], deployed(rows, final['cm']))[0]


fit_rows = final['rows'] & (NX >= 0)
zf = zof(fit_rows); Dm, hcols = head_design(fit_rows, zf); yf = Y[fit_rows]
L2H = 1e-4


def obj(w):
    zz = zf + Dm @ w; p = sig(zz)
    ll = float(np.mean(np.logaddexp(0, zz) - yf * zz)) + 0.5 * L2H * float(w @ w)
    return ll, Dm.T @ (p - yf) / len(yf) + L2H * w


wh = minimize(obj, np.zeros(Dm.shape[1]), jac=True, method='L-BFGS-B', options={'maxiter': 500}).x
head = {'names': [None] * len(hcols), 'w': [0.0] * len(hcols)}
for k, c in hcols.items(): head['names'][c] = k; head['w'][c] = round(float(wh[c]), 6)
nh = dict(zip(head['names'], head['w']))
head_rep = {}
for lab, rows in (('验证', va & (NX >= 0)), ('检验', te & (NX >= 0))):
    z0 = zof(rows); D2, c2 = head_design(rows, z0)
    w2 = np.array([nh.get(k, 0.0) for k in sorted(c2, key=c2.get)])
    p0, p1 = sig(z0), sig(z0 + D2 @ w2); yy = Y[rows]
    head_rep[lab] = {'n': int(rows.sum()), 'V_logloss': logloss(p0, yy), 'Q_logloss': logloss(p1, yy), 'V_auc': auc(p0, yy), 'Q_auc': auc(p1, yy)}
    print(f'  下一个点修正（{lab}，{int(rows.sum())} 个快照）：只用家底 对数损失 {head_rep[lab]["V_logloss"]:.4f} AUC {head_rep[lab]["V_auc"]:.4f} → '
          f'加下一个点类型 {head_rep[lab]["Q_logloss"]:.4f} / {head_rep[lab]["Q_auc"]:.4f}')

cm = final['cm']; P = final['P']; sel = np.where(cm)[0]
opt = {'card_act': int(any(is_card_act(vocab[j]) for j in sel)), 'relic_act': int(any(vocab[j].startswith('r:') and '|A' in vocab[j] for j in sel)),
       'style': int(any(vocab[j].startswith('sk:') for j in sel)), 'version': int(any(vocab[j].startswith('v:') for j in sel))}
sel_names = {vocab[j] for j in sel}
out = {'vocab': [vocab[j] for j in sel], 'w': [round(float(x), 6) for x in P['w']], 'b': float(P['b']), 'opt': opt,
       'style_ref': {k: {n: v for n, v in d.items() if n in sel_names} for k, d in style_ref.items()} if opt['style'] else {},
       'next_head': head,
       'meta': {'trained': time.strftime('%Y-%m-%d %H:%M'), 'variant': final['label'], 'hidden': final['H'], 'l2': final['l2'], 'epoch': final['epoch'],
                'data': STAT, 'test': final['test'], 'test_with_true_history': final['test_oracle'], 'calibration': cal, 'act1_by_chapter': by_ch,
                'base_rate_train': base_rate, 'next_head': head_rep, 'baselines': {'constant': r_const, 'simple': r_simple['test'], 'old_fm': old_fm},
                'variants': [{'label': r['label'], 'val_logloss': r['val_ll'], 'test': r['test'], 'features': int(r['cm'].sum())} for r in results],
                'note': '社区玩家（人类）接着打的通关概率；只比较同一局面下选项之间的差。'}}
if 'W1' in P:
    out.update({'W1': [[round(float(x), 6) for x in row] for row in P['W1']], 'b1': [float(x) for x in P['b1']], 'w2': [float(x) for x in P['w2']]})
OUT = os.path.join(HERE, a.out)
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(f'写入 {OUT}（{os.path.getsize(OUT) / 1e6:.1f} MB）')

# 运行时代码（纯 Python）和训练时预测（运行时口径）是否一致
RV.OVERRIDE = OUT; RV._M = None
chk = [RV.prob_of(s) for s in test_states[:500]]
diff = max(abs(x - y) for x, y in zip(chk, final['pte'][:500]))
print(f'运行时模块和训练预测最大差 {diff:.2e}（应接近 0）')

rep = examples(OUT, test_states, test_picks)
d = json.load(open(OUT)); d['meta']['examples'] = rep
json.dump(d, open(OUT, 'w'), ensure_ascii=False)
print('边际价值例子写进模型文件 meta.examples')
