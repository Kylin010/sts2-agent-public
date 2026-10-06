"""训练重排函数（policy/rerank.py）：推演老师记录 → 「同一局面里哪种出法结局更好」的线性函数。
每个局面：老师给前几种出法打过推演结局值 v；规划器重新算这些出法的打分明细当特征；同一局面内减平均后岭回归。
检验：按战斗分出 20% 不参与训练，比较三种挑法在老师眼里的遗憾（老师最好的 v − 挑中那种的 v）：
  规划器原样（候选里规划器分最高的）/ 重排函数 / 随便挑（平均）。
用法：python3 tools/train_rerank.py [--lam 1,3,10] [--out rerank.json] [--min 15] 记录1 记录2 ...
"""
import collections, copy, json, os, random, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
params.P['rerank_on'] = False
from policy import combat, rerank
from policy.knowledge import cid

args = sys.argv[1:]; lams = [1.0, 3.0, 10.0, 30.0]; out = 'rerank.json'; mincnt = 15; files = []; mode = 'full'
i = 0
while i < len(args):
    if args[i] == '--lam': lams = [float(x) for x in args[i + 1].split(',')]; i += 2
    elif args[i] == '--out': out = args[i + 1]; i += 2
    elif args[i] == '--min': mincnt = int(args[i + 1]); i += 2
    elif args[i] == '--mode': mode = args[i + 1]; i += 2       # core = 只用通用打分明细；enc = 再加按遭遇；full = 再加每张牌 / 招式
    else: files.append(args[i]); i += 1
key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))


def keep(k):
    if mode == 'core': return k in rerank.CORE
    if mode == 'enc': return k in rerank.CORE or (k.count('|') == 1 and k.split('|')[1] in rerank.CORE)
    return True


def load():
    S = []
    for p in files:
        fight = None; prev = None
        for n, line in enumerate(open(p)):
            r = json.loads(line)
            rd = r.get('round') or 0
            if prev is None or rd < prev: fight = f'{p}#{n}'
            prev = rd
            cands = [c for c in (r.get('all') or r.get('cands') or []) if not c.get('potion')]   # 有全部候选就用全部（喝药的先不管）
            if len(cands) < 2: continue
            st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
            try:
                with params.scoped(params.for_encounter((st.get('context') or {}).get('encounter'))):   # 和实战一样先套遭遇专属参数
                    res = combat.plan(st, {}, set(), topk=-1)
            except Exception: continue
            if not res or not isinstance(res, dict): continue
            ctx = res['ctx']; pool = {key(cid(c) for c in cb): (ev, cb) for ev, cb in res['pool']}
            enc = rerank.enc_of(st) or (r.get('enc') or ''); mv = rerank.phase(ctx)
            rows = []
            for c in cands:
                if key(c['cards']) not in pool: continue
                ev, cb = pool[key(c['cards'])]
                pt = rerank.parts(cb, ctx, combat.evaluate)
                if pt is None: continue
                rows.append(({k: x for k, x in rerank.feats(cb, ctx, pt, enc, mv, ev).items() if keep(k)}, c['v'], ev))
            if len(rows) >= 2: S.append(dict(rows=rows, enc=enc, fight=fight))
    return S


S = load()
fights = sorted({s['fight'] for s in S}); random.Random(7).shuffle(fights); va_f = set(fights[:max(1, len(fights) // 5)])
tr = [s for s in S if s['fight'] not in va_f]; va = [s for s in S if s['fight'] in va_f]
cnt = collections.Counter(k for s in tr for f, _, _ in s['rows'] for k in f)
keys = sorted(k for k, c in cnt.items() if c >= mincnt)
ix = {k: j for j, k in enumerate(keys)}
print(f'局面：训练 {len(tr)}，检验 {len(va)}（战斗 {len(fights)}）；特征 {len(keys)}（{mode}）')


def mats(SS):
    X = []; y = []
    for s in SS:
        A = np.zeros((len(s['rows']), len(keys)))
        for r, (f, v, _) in enumerate(s['rows']):
            for k, x in f.items():
                if k in ix: A[r, ix[k]] = x
        b = np.array([v for _, v, _ in s['rows']], float)
        X.append(A - A.mean(0)); y.append(b - b.mean())
    return np.vstack(X), np.concatenate(y)


def regret(SS, theta):
    out = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0, 0])   # 局面, 规划器遗憾, 重排遗憾, 随便挑遗憾, 规划器挑到最好, 重排挑到最好
    for s in SS:
        vs = [v for _, v, _ in s['rows']]; best = max(vs)
        if best - min(vs) <= 1: continue
        p = max(s['rows'], key=lambda t: t[2])[1]
        q = s['rows'][int(np.argmax([sum(theta[ix[k]] * x for k, x in f.items() if k in ix) for f, _, _ in s['rows']]))][1] if theta is not None else p
        o = out[s['enc']]; o[0] += 1; o[1] += best - p; o[2] += best - q; o[3] += best - sum(vs) / len(vs); o[4] += p >= best - 1e-6; o[5] += q >= best - 1e-6
    return out


def solve(X, y, lam):
    # 以规划器为锚：规划器自己的分（sc）不罚，其余修正项按 λ 罚——证据不够时退回原规划器
    pen = lam * np.eye(len(keys))
    if 'sc' in ix: pen[ix['sc'], ix['sc']] = 1e-6
    return np.linalg.solve(X.T @ X + pen, X.T @ y)


Xt, yt = mats(tr)
best = None
for lam in lams:
    th = solve(Xt, yt, lam)
    o = regret(va, th); n = sum(x[0] for x in o.values())
    rp = sum(x[1] for x in o.values()) / max(n, 1); rr = sum(x[2] for x in o.values()) / max(n, 1)
    print(f'λ={lam:5.1f}  检验局面 {n}  遗憾：规划器 {rp:.2f} → 重排 {rr:.2f}')
    if best is None or rr < best[0]: best = (rr, lam, th)
rr, lam, th = best
print(f'选 λ={lam}；分遭遇（检验）：')
for e, x in sorted(regret(va, th).items()):
    print(f'  {e:28s} 局面 {x[0]:4d}  遗憾 规划器 {x[1] / x[0]:5.2f} → 重排 {x[2] / x[0]:5.2f}（随便挑 {x[3] / x[0]:5.2f}）  挑到最好 {x[4] / x[0]:.0%} → {x[5] / x[0]:.0%}')
# 用全部数据重训存盘
Xa, ya = mats(S)
cnt = collections.Counter(k for s in S for f, _, _ in s['rows'] for k in f)
keys = sorted(k for k, c in cnt.items() if c >= mincnt); ix = {k: j for j, k in enumerate(keys)}
Xa, ya = mats(S)
th = solve(Xa, ya, lam)
json.dump({'_说明': '推演老师蒸馏的重排函数（tools/train_rerank.py）', 'lam': lam, 'mode': mode, 'n_states': len(S), 'files': files,
           'theta': {k: round(float(v), 5) for k, v in zip(keys, th) if abs(v) > 1e-6}},
          open(f'{HERE}/data/{out}', 'w'), ensure_ascii=False, indent=1)
top = sorted(zip(keys, th), key=lambda t: -abs(t[1]))[:15]
print('已存 data/' + out + '；权重最大的：', ', '.join(f'{k} {v:+.2f}' for k, v in top))
