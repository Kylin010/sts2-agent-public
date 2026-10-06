"""用推演老师的打分拟合规划器参数（离线，不开游戏、不推演）。
老师记录（search_teach_log，最好是 search_teach_only 的 all = 全部候选）里每个局面有若干出法的推演结局值 v。
给一组规划器参数，在每个局面上重新跑规划器，看它挑的那手的 v（不在老师候选里的按该局面最差的 v 算——保守，不鼓励乱挑），
目标 = 平均（挑中的 v − 该局面最好的 v）。随机搜索 + 在当前最好附近扰动；按战斗分训练 / 检验，检验集只用来报告和选最终参数。
用法：python3 tools/fit_params_teacher.py --n 80 --procs 3 记录...
"""
import copy, json, math, multiprocessing as mp, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
SPACE = {'alpha_base': (0.1, 0.6), 'alpha_max': (1.0, 2.5), 'alpha_scaling_enemy': (0.0, 1.0), 'kill_bonus': (2.0, 15.0),
         'block_mult': (0.6, 1.6), 'risk_hp': (15.0, 50.0), 'vuln_future': (0.5, 4.0), 'weak_future': (0.3, 3.0),
         'power_weight': (0.5, 3.0), 'str_future_weight': (0.2, 1.5), 'draw_value': (0.5, 3.0), 'self_hp_weight': (0.3, 1.2),
         'imit_w': (0.0, 2.0), 'cv_weight': (0.0, 0.8), 'long_max': (0.8, 2.5)}
key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))
S = []


def load(files):
    out = []
    for p in files:
        fight = None; prev = None
        for n, line in enumerate(open(p)):
            r = json.loads(line); rd = r.get('round') or 0
            if prev is None or rd < prev: fight = f'{p}#{n}'
            prev = rd
            cands = [c for c in (r.get('all') or r.get('cands') or []) if not c.get('potion')]
            if len(cands) < 2: continue
            vs = {}
            for c in cands: vs[key(c['cards'])] = max(vs.get(key(c['cards']), -1e9), c['v'])
            if max(vs.values()) - min(vs.values()) <= 1: continue
            st = r['state']; st['decision'] = 'combat_play'
            out.append(dict(st=st, vs=vs, vmax=max(vs.values()), vmin=min(vs.values()), fight=fight, enc=r.get('enc'), room=r.get('room')))
    return out


def _init(files):
    global S
    S = load(files)


def score(args):
    params_over, idx = args
    import params
    from policy import combat
    from policy.knowledge import cid
    params.P.update(params_over)
    tot = 0.0; cov = 0
    for i in idx:
        s = S[i]
        try:
            with params.scoped(params.for_encounter((s['st'].get('context') or {}).get('encounter'))):   # 和实战一样先套遭遇专属参数
                res = combat.plan(copy.deepcopy(s['st']), {}, set(), topk=-1)
        except Exception: res = None
        if not res or not isinstance(res, dict): tot += s['vmin'] - s['vmax']; continue
        ev, cb = max(res['pool'], key=lambda t: t[0])
        k = key(cid(c) for c in cb)
        if k in s['vs']: cov += 1; tot += s['vs'][k] - s['vmax']
        else: tot += s['vmin'] - s['vmax']
    return tot / max(len(idx), 1), cov / max(len(idx), 1)


def perturb(base, rng, k=3):
    out = dict(base)
    for name in rng.sample(list(SPACE), k):
        lo, hi = SPACE[name]
        out[name] = round(min(hi, max(lo, out[name] + rng.gauss(0, 0.35) * (hi - lo))), 3)
    return out


if __name__ == '__main__':
    args = sys.argv[1:]; N = 80; procs = 3; files = []
    i = 0
    while i < len(args):
        if args[i] == '--n': N = int(args[i + 1]); i += 2
        elif args[i] == '--procs': procs = int(args[i + 1]); i += 2
        else: files.append(args[i]); i += 1
    import params
    base = {k: params.P[k] for k in SPACE}
    allS = load(files)
    fights = sorted({s['fight'] for s in allS}); random.Random(9).shuffle(fights); va_f = set(fights[:len(fights) // 4])
    tr = [i for i, s in enumerate(allS) if s['fight'] not in va_f]; va = [i for i, s in enumerate(allS) if s['fight'] in va_f]
    print(f'有区分度的局面 {len(allS)}：训练 {len(tr)} / 检验 {len(va)}（战斗 {len(fights)}）', flush=True)
    chunks = lambda idx: [idx[j::procs] for j in range(procs)]
    with mp.Pool(procs, initializer=_init, initargs=(files,)) as pool:
        def ev(par, idx):
            rs = pool.map(score, [(par, c) for c in chunks(idx)])
            n = [len(c) for c in chunks(idx)]
            return sum(r[0] * m for r, m in zip(rs, n)) / sum(n), sum(r[1] * m for r, m in zip(rs, n)) / sum(n)
        b_tr = ev(base, tr); b_va = ev(base, va)
        print(f'默认参数：训练 {b_tr[0]:.3f}（覆盖 {b_tr[1]:.0%}） 检验 {b_va[0]:.3f}（覆盖 {b_va[1]:.0%}）', flush=True)
        rng = random.Random(1); hist = [(b_tr[0], base)]; best = (b_tr[0], base)
        for t in range(N):
            par = perturb(best[1], rng, k=rng.choice([1, 2, 3])) if t % 3 else {k: round(rng.uniform(*SPACE[k]), 3) for k in SPACE}
            sc, cv = ev(par, tr); hist.append((sc, par))
            if sc > best[0]: best = (sc, par); print(f'  第 {t} 组 训练 {sc:.3f}（覆盖 {cv:.0%}）↑ {json.dumps({k: v for k, v in par.items() if v != base[k]}, ensure_ascii=False)}', flush=True)
        hist.sort(key=lambda t: -t[0])
        print('训练前 5 组在检验集：', flush=True)
        res = []
        for sc, par in hist[:5]:
            v = ev(par, va); res.append((v[0], sc, par))
            print(f'  训练 {sc:.3f} 检验 {v[0]:.3f}（覆盖 {v[1]:.0%}） {json.dumps({k: v for k, v in par.items() if v != base[k]}, ensure_ascii=False)}', flush=True)
        res.sort(key=lambda t: -t[0])
        json.dump({'base_train': b_tr[0], 'base_val': b_va[0], 'best_val': res[0][0], 'best': res[0][2], 'diff': {k: v for k, v in res[0][2].items() if v != base[k]}},
                  open(f'{HERE}/data/fit_params_teacher.json', 'w'), ensure_ascii=False, indent=1)
        print('已存 data/fit_params_teacher.json')
