"""遭遇实验室：给每种遭遇随机搜索一套最优的战斗参数，写进 kb/encounter_params.json。

原理（不作弊）：
- 用战斗基准里真人当时的牌组 / 遗物 / 药水 / 血量（data/bench.json、bench_normals.json）打同一个遭遇；
- 每组候选参数都在「同样的若干个种子」上打（抽牌顺序随机但各组一致，比较才公平），按平均掉血排名；
- 第一轮每个遭遇试 K 组随机参数 + 当前默认；第二轮只留前几名，换一批新种子再打，防止只是运气好；
- 合并两轮，比默认好得明显（平均少掉 min_gain 以上、配对检验 t > t_min）才采用。
  学到的是「打这种怪该多挡还是多打、该不该早喝药」这类倾向，正式对局照样能用，不靠偷看牌序。

用法（在 agent/ 目录）：
  python3 lab.py                       # 所有基准里有的遭遇
  python3 lab.py --only VANTOM_BOSS,THE_KIN_BOSS --k 32
  python3 lab.py --act 1               # 只做第一幕的遭遇
结果：kb/encounter_params.json（采用的参数）、lab/LOG.md（每次实验的记录）、results/lab-*.jsonl（原始数据）
"""
import argparse, collections, json, math, os, random, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from params import P

# 参数 → (下限, 上限, 取值方式)；log = 按比例均匀（乘法性质的参数），int / choice 照字面
SPACE = {
    'alpha_base': (0.05, 0.8, 'lin'), 'alpha_max': (0.8, 2.5, 'lin'), 'alpha_min': (0.1, 0.6, 'lin'),
    'risk_hp': (10, 60, 'lin'), 'kill_bonus': (1, 15, 'log'), 'power_weight': (0.1, 1.5, 'log'),
    'draw_value': (0.3, 3.0, 'log'), 'long_max': (0.8, 2.5, 'lin'), 'block_mult': (0.6, 2.0, 'log'),
    'self_hp_weight': (0.2, 1.5, 'log'), 'threshold_bonus': (0, 15, 'lin'),
    'potion_boss_rounds': ([0, 1, 2, 3], None, 'choice'), 'potion_elite_need': (0.15, 0.8, 'lin'),
    'potion_elite_r1': ([0, 1], None, 'choice'), 'potion_monster_need': (0.3, 1.0, 'lin'),
}
DEATH = 30          # 打输了额外记多少分（相当于多掉 30 血）
POTION = {'Monster': 10, 'Elite': 6, 'Boss': 3}   # 每用一瓶药扣几分：单场测试看不到「药留给后面」的价值，普通战扣得最多
# 个别遭遇额外要试的参数（列表 = 候选值，随机挑一个）
EXTRA = {
    'KNOWLEDGE_DEMON_BOSS': {'curse_order': [                 # 知识恶魔的二选一：瓦解（每回合掉血）还是 心灵腐化 / 懒惰 / 衰朽
        ['MIND_ROT', 'SLOTH', 'DISINTEGRATION', 'WASTE_AWAY'], ['DISINTEGRATION', 'MIND_ROT', 'SLOTH', 'WASTE_AWAY'],
        ['MIND_ROT', 'DISINTEGRATION', 'SLOTH', 'WASTE_AWAY'], ['SLOTH', 'MIND_ROT', 'DISINTEGRATION', 'WASTE_AWAY'],
        ['MIND_ROT', 'WASTE_AWAY', 'SLOTH', 'DISINTEGRATION'], ['DISINTEGRATION', 'SLOTH', 'MIND_ROT', 'WASTE_AWAY']]},
}

ap = argparse.ArgumentParser()
ap.add_argument('--only', default=None); ap.add_argument('--act', type=int, default=None)
ap.add_argument('--k', type=int, default=24, help='第一轮每个遭遇试几组随机参数')
ap.add_argument('--keep', type=int, default=4, help='第二轮留几组')
ap.add_argument('--cases', type=int, default=8, help='每个遭遇最多用几个基准案例')
ap.add_argument('--reps1', type=int, default=2); ap.add_argument('--reps2', type=int, default=4)
ap.add_argument('--min-gain', type=float, default=2.0); ap.add_argument('--t-min', type=float, default=2.0)
ap.add_argument('--tag', default=None); ap.add_argument('--seed', type=int, default=0)
ap.add_argument('--hosts', default='l,r,h,g')
a = ap.parse_args()
rng = random.Random(a.seed or int(time.time()))
tag = a.tag or time.strftime('lab-%m%d-%H%M')
os.makedirs(f'{HERE}/lab', exist_ok=True)

# ---------- 遭遇和案例 ----------
cases = collections.defaultdict(list)
for bf in ('bench.json', 'bench_normals.json'):
    for i, c in enumerate(json.load(open(f'{HERE}/data/{bf}'))):
        if a.act and c.get('act') != a.act: continue
        cases[c['encounter']].append((bf, i))
encs = sorted(cases)
if a.only: encs = [e for e in encs if e in set(a.only.split(','))]
for e in encs:
    rng.shuffle(cases[e]); cases[e] = cases[e][:a.cases]
print(f'{len(encs)} 个遭遇，每个最多 {a.cases} 个案例')


def sample(e=None):
    d = {k: rng.choice(v) for k, v in EXTRA.get(e, {}).items()}
    for k, (lo, hi, how) in SPACE.items():
        if how == 'choice': d[k] = rng.choice(lo)
        elif how == 'log': d[k] = round(math.exp(rng.uniform(math.log(max(lo, 1e-3)), math.log(hi))), 3)
        else: d[k] = round(rng.uniform(lo, hi), 3)
    return d


def run_batch(cands, rep_base, reps, name):
    """cands = {遭遇: [参数组, ...]}，第 0 组是默认参数。返回 {遭遇: {组号: [每个(案例,种子)的分数]}}"""
    flat = []; tasks = []
    for e in encs:
        for ci, c in enumerate(cands[e]):
            gid = len(flat); flat.append(c)
            for bf, i in cases[e]:
                for r in range(reps):
                    tasks.append({'bench': bf, 'case': i, 'rep': rep_base + r, 'cand': gid, 'enc': e, 'ci': ci})
    spec = f'lab/spec_{tag}_{name}.json'
    json.dump({'candidates': flat, 'tasks': tasks}, open(f'{HERE}/{spec}', 'w'))
    t = time.time()
    subprocess.run([sys.executable, f'{HERE}/dist.py', '0', '--lab', spec, '--tag', f'{tag}-{name}', '--hosts', a.hosts], cwd=HERE,
                   capture_output=True, text=True)
    rs = [json.loads(l) for l in open(f'{HERE}/results/{tag}-{name}.jsonl')]
    print(f'  {name}：{len(tasks)} 个任务，回来 {len(rs)} 个，用时 {time.time() - t:.0f} 秒', flush=True)
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in rs:
        j = r.get('task')
        if j is None or isinstance(j, list): continue
        tk = tasks[j]
        sc = 60 + DEATH if 'crash' in r else (r.get('dmg') or 0) + (0 if r.get('survived') else DEATH)
        sc += (r.get('potions') or 0) * POTION.get(str(r.get('room', '')).capitalize(), 6)
        out[tk['enc']][tk['ci']][(tk['bench'], tk['case'], tk['rep'])] = sc
    return out


def paired(a_scores, b_scores):
    """b 比 a 平均少多少（正数 = b 更好）和配对 t 值"""
    ks = [k for k in a_scores if k in b_scores]
    if len(ks) < 3: return 0.0, 0.0
    d = [a_scores[k] - b_scores[k] for k in ks]
    m = sum(d) / len(d); sd = (sum((x - m) ** 2 for x in d) / (len(d) - 1)) ** 0.5
    return m, (m / (sd / len(d) ** 0.5) if sd > 0 else (9.9 if m > 0 else 0.0))


default = {k: P[k] for k in SPACE}
c1 = {e: [dict(default, **{k: P[k] for k in EXTRA.get(e, {})})] + [sample(e) for _ in range(a.k)] for e in encs}
print('第一轮：每个遭遇', a.k + 1, '组参数 ×', a.reps1, '个种子', flush=True)
r1 = run_batch(c1, 0, a.reps1, 'r1')
c2 = {}; keep_idx = {}
for e in encs:
    means = {ci: sum(v.values()) / len(v) for ci, v in r1[e].items() if v}
    top = [ci for ci in sorted(means, key=means.get) if ci != 0][:a.keep]
    keep_idx[e] = [0] + top
    c2[e] = [c1[e][ci] for ci in keep_idx[e]]
print('第二轮：每个遭遇留', a.keep + 1, '组 × 新的', a.reps2, '个种子', flush=True)
r2 = run_batch(c2, 100, a.reps2, 'r2')

path = f'{HERE}/kb/encounter_params.json'
store = json.load(open(path)) if os.path.exists(path) else {}
store['_说明'] = '遭遇实验室（lab.py）找出来的按遭遇参数；战斗里自动换上。score = 平均掉血（打输 +30），越低越好'
log = [f'\n## {tag}（{time.strftime("%m-%d %H:%M")}）K={a.k} keep={a.keep} 案例≤{a.cases} 种子 {a.reps1}+{a.reps2}\n',
       '| 遭遇 | 默认 | 最好 | 少掉 | t | 采用 |', '|---|---|---|---|---|---|']
for e in encs:
    base = {**r1[e].get(0, {}), **r2[e].get(0, {})}
    best = None
    for j, ci in enumerate(keep_idx[e]):
        if ci == 0: continue
        sc = {**r1[e].get(ci, {}), **r2[e].get(j, {})}
        gain, t = paired(base, sc)
        if best is None or gain > best[0]: best = (gain, t, ci, sum(sc.values()) / max(len(sc), 1))
    if not base or best is None: continue
    bmean = sum(base.values()) / len(base)
    ok = best[0] >= a.min_gain and best[1] >= a.t_min
    if ok:
        keep = {k: v for k, v in c1[e][best[2]].items() if v != default.get(k)}
        if e.endswith('_NORMAL') or e.endswith('_WEAK'):
            keep = {k: v for k, v in keep.items() if not k.startswith('potion_')}   # 普通战的喝药倾向不采用（单场看不到药水留给后面的价值）
        store[e] = {'params': keep,
                    'default_score': round(bmean, 1), 'best_score': round(best[3], 1), 'gain': round(best[0], 1), 't': round(best[1], 1),
                    'n': len(base), 'tag': tag}
    if not ok and e in store and store[e].get('tag') != tag:
        store.pop(e)                      # 旧代码上找到的专属参数，这次没比过默认值：删掉，回到默认（不然正式对局还在用过时的参数）
    log.append(f'| {e} | {bmean:.1f} | {best[3]:.1f} | {best[0]:.1f} | {best[1]:.1f} | {"✅" if ok else ""} |')
json.dump(store, open(path, 'w'), ensure_ascii=False, indent=1)
open(f'{HERE}/lab/LOG.md', 'a').write('\n'.join(log) + '\n')
print('\n'.join(log))
