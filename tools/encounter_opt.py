"""每个 Boss / 精英的专属函数：在同牌组案例上直接优化规划器参数（不开推演）。

不开推演整局 60 局约 2 分钟，所以可以在大量实打上搜参数：
  第一轮：默认 + K 组随机参数（规划器权重 + 这个遭遇每个招式的伤害估值倍数 phase_alpha），训练案例 × reps1 个种子；
  第二轮：前 keep 组 + 默认，换 reps2 个新种子；
  验证：最好那组 vs 默认，在没见过的检验案例上打 repsv 个种子，配对比较。
分数 = 掉血 + 死亡 30 + 每瓶药（Boss 3 / 精英 6 / 普通 10），越低越好（同 lab.py）。
用法：python3 tools/encounter_opt.py --enc KAISER_CRAB_BOSS --train bench_t_crab_even.json --test bench_t_crab_odd.json --workers 3
"""
import argparse, collections, json, math, os, random, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from params import P
SPACE = {
    'alpha_base': (0.05, 0.8, 'lin'), 'alpha_max': (0.8, 2.5, 'lin'), 'alpha_min': (0.1, 0.6, 'lin'),
    'risk_hp': (10, 60, 'lin'), 'kill_bonus': (1, 15, 'log'), 'power_weight': (0.1, 1.5, 'log'),
    'draw_value': (0.3, 3.0, 'log'), 'long_max': (0.8, 2.5, 'lin'), 'block_mult': (0.6, 2.0, 'log'),
    'self_hp_weight': (0.2, 1.5, 'log'), 'threshold_bonus': (0, 15, 'lin'), 'imit_w': (0.0, 3.0, 'lin'),
    'potion_boss_rounds': ([0, 1, 2, 3], None, 'choice'), 'potion_elite_need': (0.15, 0.8, 'lin'),
}
DEATH = 30; POTION = {'Monster': 10, 'Elite': 6, 'Boss': 3}
ap = argparse.ArgumentParser()
ap.add_argument('--enc', required=True); ap.add_argument('--train', required=True); ap.add_argument('--test', required=True)
ap.add_argument('--k', type=int, default=24); ap.add_argument('--keep', type=int, default=4)
ap.add_argument('--reps1', type=int, default=2); ap.add_argument('--reps2', type=int, default=3); ap.add_argument('--repsv', type=int, default=3)
ap.add_argument('--workers', type=int, default=3); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--tag', default=None)
a = ap.parse_args()
rng = random.Random(a.seed); tag = a.tag or f"eopt-{a.enc.lower()}-{time.strftime('%m%d%H%M')}"
M = json.load(open(f'{HERE}/kb/monsters.json')); B = json.load(open(f'{HERE}/data/baselines.json'))
names = set((B.get(a.enc) or {}).get('names', '').split(' + '))
MOVES = sorted({mv for k, m in M.items() if isinstance(m, dict) and m.get('name') in names for mv in (m.get('moves') or {})})
print('遭遇', a.enc, '敌人', names, '招式', MOVES, flush=True)


def sample():
    d = {}
    for k, (lo, hi, how) in SPACE.items():
        if how == 'choice': d[k] = rng.choice(lo)
        elif how == 'log': d[k] = round(math.exp(rng.uniform(math.log(max(lo, 1e-3)), math.log(hi))), 3)
        else: d[k] = round(rng.uniform(lo, hi), 3)
    if MOVES: d['phase_alpha'] = {a.enc: {mv: round(math.exp(rng.uniform(math.log(0.5), math.log(2.0))), 2) for mv in MOVES}}
    return d


def run(cands, bench, reps, rep_base, name):
    n = len(json.load(open(f'{HERE}/data/{bench}')))
    tasks = [{'bench': bench, 'case': i, 'rep': rep_base + r, 'cand': ci} for ci in range(len(cands)) for i in range(n) for r in range(reps)]
    spec = f'{HERE}/lab/spec_{tag}_{name}.json'; json.dump({'candidates': cands, 'tasks': tasks}, open(spec, 'w'))
    t = time.time()
    subprocess.run([sys.executable, f'{HERE}/run.py', '0', '--lab', spec, '--workers', str(a.workers), '--tag', f'{tag}-{name}'], cwd=HERE, capture_output=True, text=True)
    out = collections.defaultdict(dict); surv = collections.defaultdict(list); dmg = collections.defaultdict(list)
    for l in open(f'{HERE}/results/{tag}-{name}.jsonl'):
        r = json.loads(l); tk = tasks[r['task']]
        sc = 60 + DEATH if 'crash' in r else (r.get('dmg') or 0) + (0 if r.get('survived') else DEATH)
        sc += (r.get('potions') or 0) * POTION.get(str(r.get('room', '')).capitalize(), 6)
        out[tk['cand']][(tk['case'], tk['rep'])] = sc; surv[tk['cand']].append(bool(r.get('survived'))); dmg[tk['cand']].append(r.get('dmg') or 0)
    print(f'  {name}：{len(tasks)} 场，{time.time() - t:.0f} 秒', flush=True)
    return out, surv, dmg


m_ = lambda v: sum(v) / max(len(v), 1)
default = {}
c1 = [default] + [sample() for _ in range(a.k)]
r1, _, _ = run(c1, a.train, a.reps1, 0, 'r1')
top = sorted([ci for ci in r1 if ci != 0], key=lambda ci: m_(list(r1[ci].values())))[:a.keep]
c2 = [default] + [c1[ci] for ci in top]
r2, _, _ = run(c2, a.train, a.reps2, 100, 'r2')
best = min(range(1, len(c2)), key=lambda j: m_(list(r2[j].values())) + m_(list(r1[top[j - 1]].values())))
print('训练集：默认', round(m_(list(r1[0].values()) + list(r2[0].values())), 1), '最好', round(m_(list(r1[top[best - 1]].values()) + list(r2[best].values())), 1), flush=True)
cv = [default, c2[best]]
rv, sv, dv = run(cv, a.test, a.repsv, 200, 'val')
ks = [k for k in rv[0] if k in rv[1]]; d = [rv[0][k] - rv[1][k] for k in ks]
mean = m_(d); sd = (sum((x - mean) ** 2 for x in d) / max(len(d) - 1, 1)) ** 0.5; t = mean / (sd / len(d) ** 0.5) if sd > 0 else 0
human = m_([c.get('human_dmg') or 0 for c in json.load(open(f'{HERE}/data/{a.test}'))])
res = {'enc': a.enc, 'best': c2[best], 'val': {'default_surv': f'{sum(sv[0])}/{len(sv[0])}', 'best_surv': f'{sum(sv[1])}/{len(sv[1])}',
       'default_dmg': round(m_(dv[0]), 1), 'best_dmg': round(m_(dv[1]), 1), 'human_dmg': round(human, 1), 'gain': round(mean, 1), 't': round(t, 2)}}
json.dump(res, open(f'{HERE}/lab/{tag}.json', 'w'), ensure_ascii=False, indent=1)
print('检验集（没见过的案例，不推演）：', json.dumps(res['val'], ensure_ascii=False), flush=True)
print('最好参数：', json.dumps(c2[best], ensure_ascii=False), flush=True)
