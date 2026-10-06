"""训练出牌模仿层（policy/imitation.py）：让规划器在人类回放的局面里，把人类实际打的那组牌排到前面。

数据：sources/community-runs/replays/ironclad-a10/*.ndjson.gz（v7 回放：每回合抽到的牌、能量、敌人意图、打出的牌）。
局面还原沿用 tools/replay_compare.py（近似：卡牌数值按未升级算，意图按 intent 事件）。
每个回合：规划器列出所有可行的出牌组合（combat.plan(topk=-1)），人类打的那组（回合开始就在手里的牌）在其中才算一条样本。
模型：组合的分 = a × 规划器分 / 10 + θ · 特征；对每个回合的所有组合做 softmax，最大化人类那组的概率（L2 正则）。
按回放文件划分训练 / 检验（8:2），报告检验集上「和人类整组一致」的比例：只用规划器分 vs 加上模仿层。
用法：python3 tools/train_imitation.py [--max-files 0] [--l2 0.01] [--epochs 300]   → data/imitation.json
"""
import argparse, collections, glob, gzip, json, math, os, random, sys
from multiprocessing import Pool
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
params.P['imit_w'] = 0.0; params.P['cv_weight'] = params.P.get('cv_weight', 0.3)
from policy import combat, imitation
C = json.load(open(f'{HERE}/kb/cards.json'))
SRC = '/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10'


def card_dict(cid_, idx, strength):
    c = C.get(cid_, {})
    cost = c.get('cost') if isinstance(c.get('cost'), int) else 1
    dmg = (c.get('damage') or 0); blk = c.get('block') or 0
    t = c.get('type') or 'Skill'
    return {'index': idx, 'id': 'CARD.' + cid_, 'name': c.get('name') or cid_, 'cost': cost, 'type': t, 'can_play': t not in ('Curse', 'Status') or cid_ in ('SLIMED',),
            'stats': {'damage': dmg + (strength if dmg else 0), 'block': blk}, 'target_type': 'AnyEnemy' if t == 'Attack' else 'Self'}


MON = json.load(open(f'{HERE}/kb/monsters.json'))


def move_damage(mon, move):
    """怪物出招表（源码提取，进阶 10 数值）里这一招的总伤害"""
    mv = ((MON.get(mon) or {}).get('moves') or {}).get(move) or {}
    tot = 0
    for it in mv.get('intents') or []:
        if it.get('type') == 'attack':
            v = lambda x: (x.get('a10') or x.get('a0') or 0) if isinstance(x, dict) else (x or 0)
            dmg = v(it.get('damage')); hits = v(it.get('hits')) or 1
            tot += (dmg if isinstance(dmg, (int, float)) else 0) * max(hits if isinstance(hits, (int, float)) else 1, 1)
    return tot


def turns_from(path):
    """回放 → 每个玩家回合：回合开始时的手牌、能量、血量、力量、敌人（血量、意图伤害）、人类打出的牌。
    v7 有 intent 事件直接用；v4–v6 没有，就用「敌人回合实际出的招」（就是玩家这回合看到的意图）查出招表算伤害。"""
    lines = [json.loads(l) for l in gzip.open(path, 'rt')]
    ver = lines[0].get('replay_version') or 0
    if ver < 4: return
    enemies = {}; hand = {}; hp = 80; mx = 80; strength = 0; energy = 3; enc = None
    cur = None; pend = None; seen_intent = False

    def finish(t):
        if t is None: return None
        for k, e in t['enemies'].items():
            if e.get('intent') is None: e['intent'] = 0
        return t
    for d in lines:
        t = d.get('t')
        if t == 'hp': hp = d.get('hp', hp); mx = d.get('max_hp', mx) or mx
        if t == 'combat_start':
            enc = d.get('encounter'); enemies = {e.get('cid', ('i', e.get('i'))): {'id': e['id'], 'hp': e['hp']} for e in d.get('enemies') or []}
            hand = {}; strength = 0; cur = None; pend = None
            continue
        if not enc: continue
        if t == 'combat_end':
            r = finish(pend); pend = None
            if r: yield r
            enc = None; continue
        if t == 'energy': energy = d.get('energy', energy)
        elif t == 'draw': hand[d['c']] = d['id']
        elif t == 'power' and d.get('id') == 'STRENGTH_POWER' and d.get('tgt') == 'IRONCLAD': strength = d.get('amount', strength)
        elif t == 'hit' and d.get('src') == 'player' or (t == 'hit' and d.get('dst_cid') in enemies):
            k = d.get('dst_cid') if d.get('dst_cid') in enemies else next((k for k, e in enemies.items() if e['id'] == d.get('dst') and e['hp'] > 0), None)
            if k in enemies: enemies[k]['hp'] -= d.get('dmg') or 0     # v4–v5 没有 dst_cid，按名字找第一个活着的
        elif t == 'turn' and d.get('side') == 'player':
            r = finish(pend); pend = None
            if r: yield r
            cur = {'enc': enc, 'hand': dict(hand), 'energy': energy if ver >= 6 else 3, 'hp': hp, 'mx': mx, 'strength': strength, 'played': [], 'pc': set(),
                   'enemies': {k: {'id': v['id'], 'hp': v['hp'], 'intent': None} for k, v in enemies.items() if v['hp'] > 0}, 'round': d.get('round') or d.get('n')}
        elif t == 'intent' and cur is not None and d.get('src_cid') in cur['enemies'] and d.get('at') == 'turn_start':
            cur['enemies'][d['src_cid']]['intent'] = (d.get('dmg') or 0) * (d.get('hits') or 1) if 'attack' in (d.get('intents') or []) else 0
        elif t == 'play' and cur is not None and not d.get('auto'):
            if d['c'] in cur['hand'] and d['c'] not in cur['pc']:          # 同一张牌可能记两条 play（余烬、柄击），按实例去重
                cur['played'].append(d['id']); cur['pc'].add(d['c'])
            if ver < 6: cur['energy'] = max(cur['energy'], sum(1 for _ in cur['played']) and cur['energy'])
            hand.pop(d['c'], None)
        elif t == 'end_turn' and d.get('side') == 'player' and cur is not None:
            pend = cur; cur = None; hand = {}
        elif t == 'move' and pend is not None:                            # 敌人回合实际出的招 = 玩家刚才看到的意图
            cid_ = d.get('src_cid')
            if cid_ not in pend['enemies']:
                cid_ = next((k for k, e in pend['enemies'].items() if e['id'] == d.get('src') and e.get('_mv') is None), None)
            if cid_ in pend['enemies'] and pend['enemies'][cid_].get('intent') is None:
                e = pend['enemies'][cid_]; e['_mv'] = d.get('id')
                e['intent'] = move_damage(d.get('src'), d.get('id')) if 'attack' in (d.get('intents') or []) else 0


def samples_of(path):
    """一个回放文件 → [(各组合特征列表, 各组合规划器分, 人类那组的下标)]"""
    out = []
    try:
        for tr in turns_from(path):
            if not tr['hand'] or not tr['enemies']: continue
            hand = [card_dict(i, n, tr['strength']) for n, i in enumerate(tr['hand'].values())]
            ens = [{'index': n, 'name': v['id'], 'hp': v['hp'], 'max_hp': v['hp'], 'block': 0,
                    'intents': [{'type': 'Attack', 'damage': v['intent']}] if v['intent'] else [{'type': 'Buff'}], 'powers': []}
                   for n, v in enumerate(tr['enemies'].values())]
            st = {'decision': 'combat_play', 'hand': hand, 'energy': tr['energy'], 'enemies': ens, 'round': tr['round'],
                  'player': {'hp': tr['hp'], 'max_hp': tr['mx'], 'block': 0, 'deck': []}, 'player_powers': [],
                  'context': {'encounter': tr['enc'], 'floor': 1, 'room_type': 'Monster'}}
            res = combat.plan(st, {}, set(), topk=-1)
            if not res or not isinstance(res, dict): continue
            ctx, pool = res['ctx'], res['pool']
            want = collections.Counter(tr['played'])
            k = next((j for j, (_, cb) in enumerate(pool) if collections.Counter(str(c['id']).replace('CARD.', '') for c in cb) == want), None)
            if k is None or len(pool) < 2: continue
            out.append(([imitation.feats(cb, ctx) for _, cb in pool], [ev / 10 for ev, _ in pool], k, tr['enc']))
    except Exception:
        pass
    return out


def fit(data, keys, l2, epochs, lr=0.05, fix_a=False):
    """softmax 似然（每个回合的所有组合一组），参数 θ（特征）+ a（规划器分）。稀疏矩阵 + Adam"""
    import numpy as np, scipy.sparse as sp
    idx = {k: i for i, k in enumerate(keys)}; n = len(keys) + 1
    rows, cols, vals, grp, target = [], [], [], [], []
    r = 0
    for g, (fs, evs, k, _) in enumerate(data):
        for j, (f, e) in enumerate(zip(fs, evs)):
            for a_, b in f.items():
                if a_ in idx: rows.append(r); cols.append(idx[a_]); vals.append(b)
            rows.append(r); cols.append(n - 1); vals.append(e)
            grp.append(g); target.append(1.0 if j == k else 0.0); r += 1
    X = sp.csr_matrix((np.array(vals, dtype=np.float64), (rows, cols)), shape=(r, n))
    grp = np.array(grp); y = np.array(target); G = len(data)
    starts = np.r_[0, np.flatnonzero(np.diff(grp)) + 1]
    w = np.zeros(n); w[-1] = 1.0; m = np.zeros(n); v = np.zeros(n)
    reg = np.full(n, l2); reg[-1] = 0.0
    for ep in range(epochs):
        z = X @ w
        mx = np.maximum.reduceat(z, starts); ez = np.exp(z - mx[grp]); zs = np.add.reduceat(ez, starts)
        p = ez / zs[grp]
        ll = float(np.sum(np.log(np.maximum(p[y == 1], 1e-12))))
        g = X.T @ (y - p) / G - reg * w
        if fix_a: g[-1] = 0.0
        m = 0.9 * m + 0.1 * g; v = 0.999 * v + 0.001 * g * g
        w += lr * (m / (1 - 0.9 ** (ep + 1))) / (np.sqrt(v / (1 - 0.999 ** (ep + 1))) + 1e-8)
        if ep % 50 == 0: print(f'  第 {ep} 轮 平均对数似然 {ll / G:.4f}', flush=True)
    return {k: float(w[idx[k]]) for k in keys}, float(w[-1])


def agree(data, theta, a):
    ok = 0
    for fs, evs, k, _ in data:
        sc = [a * e + sum(theta.get(x, 0.0) * y for x, y in f.items()) for f, e in zip(fs, evs)]
        ok += max(range(len(sc)), key=lambda j: sc[j]) == k
    return ok / max(1, len(data))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--max-files', type=int, default=0); ap.add_argument('--l2', type=float, default=0.01)
    ap.add_argument('--epochs', type=int, default=400); ap.add_argument('--min-card', type=int, default=30)
    ap.add_argument('--fresh', action='store_true'); ap.add_argument('--fix-a', action='store_true', help='规划器分权重固定为 1，只学修正')
    a = ap.parse_args()
    files = sorted(glob.glob(f'{SRC}/*.ndjson.gz'))
    if a.max_files: files = files[:a.max_files]
    random.Random(7).shuffle(files)
    cut = int(len(files) * 0.8)
    cache = f'{HERE}/lab/imitation_samples.pkl.gz'          # 提取很慢（每个回合跑一次规划器），存一份；改了特征要加 --fresh
    import pickle
    if os.path.exists(cache) and not a.fresh and not a.max_files:
        parts = pickle.load(gzip.open(cache, 'rb'))
    else:
        with Pool(8) as pool:
            parts = pool.map(samples_of, files, chunksize=4)
        if not a.max_files: pickle.dump(parts, gzip.open(cache, 'wb'))
    tr = [s for p in parts[:cut] for s in p]; va = [s for p in parts[cut:] for s in p]
    print(f'回合样本：训练 {len(tr)}，检验 {len(va)}（回放 {len(files)} 个）')
    cnt = collections.Counter(k for fs, _, _, _ in tr for f in fs for k in f)
    keys = [k for k, n in cnt.items() if not k.startswith('c:') or n >= a.min_card]
    print(f'特征 {len(keys)} 个')
    print(f'只用规划器分：训练一致 {agree(tr, {}, 1.0):.1%}，检验一致 {agree(va, {}, 1.0):.1%}')
    theta, aw = fit(tr, keys, a.l2, a.epochs, fix_a=a.fix_a)
    print(f'加模仿层：训练一致 {agree(tr, theta, aw):.1%}，检验一致 {agree(va, theta, aw):.1%}；规划器分权重 a={aw:.3f}')
    # 用的时候规划器分权重固定为 1：把 θ 除以 a 换算到规划器分的单位
    scale = 10.0 / max(aw, 1e-3)
    out = f'{HERE}/data/imitation' + ('_fixa' if a.fix_a else '') + '.json'
    json.dump({'_说明': '出牌模仿层权重（tools/train_imitation.py），combat.evaluate 加 imit_w × Σθ·特征 × scale', 'a': aw, 'scale': scale,
               'theta': {k: round(v, 5) for k, v in theta.items()}, 'n_train': len(tr), 'n_val': len(va),
               'agree_val_base': agree(va, {}, 1.0), 'agree_val': agree(va, theta, aw)},
              open(out, 'w'), ensure_ascii=False, indent=1)
    top = sorted(theta.items(), key=lambda t: -abs(t[1]))[:25]
    print('权重最大的：', [(k, round(v, 2)) for k, v in top])
