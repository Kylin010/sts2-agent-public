"""干净标签（10/5）：自我对弈局面上，规划器前 K 名候选「全部」用同一批新种子各推演 M 遍（不淘汰、不截时限）。
原推演为了省时间先各推 3 遍、前 4 名再加 6 遍，被淘汰的候选标签又少又偏；网络学了这种标签，新种子重推下和规划器打平
（tools/nn_reroll.py：296 个局面 +0.02±0.20，网络挑到被淘汰的候选平均 −1.29）。
推演方法和正式推演一样（新引擎、只按看得见的局面摆战斗、新种子、之后规划器打到战斗结束），只是每个候选推得一样多。
输出每行一个局面，格式和 tools/nn_dataset.py 一样（s / c[cards, sc, f, v, n] / fight），另存每次推演的值 vs，可直接给 nn_train.py。
用法：STS2_CLI_DIR=... python3 tools/nn_relabel.py 输出.jsonl 份号 总份数 M 记录文件...（可续跑：已做过的局面跳过）
  记录文件可以写成 @清单.txt（一行一个，相对 NN_SP_ROOT 的路径，比如 a/selfplay.794821；Windows 命令行有长度上限）
环境变量 NN_ROOMS=Monster,Elite,Boss（默认全收）、NN_BOSS_SHARE=0.25（Boss 局面最多占几成，Boss 推一遍慢）
  NN_SP_ROOT=自我对弈记录根目录（默认 ../selfplay）；NN_SKIP=别的机器做过的结果（逗号分隔的 .jsonl，按 file + line 跳过）；NN_MAX=最多做几个局面
输出里 file 是相对记录根目录的路径（两台机器能对上）
"""
import copy, json, os, random, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
from params import P
import policy
from policy import combat, rerank, nnpolicy, search
from sim import aux

outp, part, nparts, M = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
SP_ROOT = os.environ.get('NN_SP_ROOT') or os.path.join(HERE, '..', 'selfplay')
NMAX = int(os.environ.get('NN_MAX') or 10 ** 9)
rel = lambda f: '/'.join(os.path.normpath(f).replace('\\', '/').split('/')[-2:])     # a/selfplay.794821
files = []
for a_ in sys.argv[5:]:
    if a_.startswith('@'):
        files += [os.path.join(SP_ROOT, x.strip()) for x in open(a_[1:], encoding='utf-8') if x.strip()]
    else:
        files.append(a_)
ROOMS = set((os.environ.get('NN_ROOMS') or 'Monster,Elite,Boss').split(','))
BOSS_SHARE = float(os.environ.get('NN_BOSS_SHARE') or 0.25)
P['search_public'] = True; P['search_public_fast'] = True; P['search_on'] = False; P['nn_on'] = False; P['search_k'] = 8   # 和 iter-pub 一样前 8 名


def cands_of(st):
    res = combat.plan(st, {}, set(), topk=-1)
    if not res or not isinstance(res, dict): return None
    ctx = res['ctx']; pool = {i: t for i, t in enumerate(res['pool'][1:])}
    enc = rerank.enc_of(st); mv = rerank.phase(ctx); out = []
    for sc, combo in combat.candidates(pool, ctx, P['search_k']):
        pt = rerank.parts(combo, ctx, combat.evaluate)
        if pt is None: continue
        f = rerank.feats(combo, ctx, pt, enc, mv, sc)
        seq = []
        if combo:
            _, tgt, p = combat.evaluate(combo, ctx, want_targets=True)
            seq = [(c, (tgt.get(id(c)) or p)['index']) for c in sorted(combo, key=combat.ORDER)]
        out.append(dict(sc=float(sc), seq=seq, f={k: float(f[k]) for k in nnpolicy.CORE}, cards=[nnpolicy.spec(c) for c in combo]))
    return out


def rollouts(st, seq, seeds):
    sim = aux(); hp0 = (st.get('player') or {}).get('hp', 0); vals = []
    seq_ref = [(c, search.tgt_ref_of(st, ti)) for c, ti in seq]
    for sd in seeds:
        try:
            if sim.broken: sim.restart()
            st0p = search.build_public(sim, st, sd)
            if st0p is None: vals.append(None); continue
            m2 = {'_ehp0': search._ehp(st)}
            c0 = st0p.get('context') or {}; m2['turn_key'] = (c0.get('floor'), st0p.get('round') or 1); m2['combat_key'] = (c0.get('act'), c0.get('floor'))
            st1 = search._play_turn(sim, st0p, seq_ref, m2, policy.decide)
            vals.append(None if st1 is None else search._value(hp0, st1, m2, policy.decide, sim))
        except Exception:
            vals.append(None)
            if sim.broken: sim.restart()
    return vals


done = set()
for p_ in [outp] + [x for x in (os.environ.get('NN_SKIP') or '').split(',') if x]:
    if not os.path.exists(p_): continue
    for l in open(p_, encoding='utf-8'):
        try: x = json.loads(l); done.add((rel(x['file']), x['line']))
        except Exception: pass
rng = random.Random(2000 + part)
jobs = []
for f in files:
    for i, line in enumerate(open(f, encoding='utf-8')):
        jobs.append((f, i))
random.Random(99).shuffle(jobs)                       # 所有份用同一个顺序，按下标取模分份
LC = {}
def line_of(f, i):
    if f not in LC:
        if len(LC) > 50: LC.clear()
        LC[f] = open(f, encoding='utf-8').read().splitlines()
    return LC[f][i]

n = nb = 0; t0 = time.time()
with open(outp, 'a', encoding='utf-8') as fo:
    for f, i in jobs[part::nparts]:
        if n >= NMAX: break
        if (rel(f), i) in done: continue
        try: r = json.loads(line_of(f, i))
        except Exception: continue
        room = r.get('room')
        if room not in ROOMS: continue
        if room == 'Boss' and nb > BOSS_SHARE * max(n, 1): continue
        st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
        enc = (st.get('context') or {}).get('encounter')
        search._IN['on'] = True
        try:
            with params.scoped(params.for_encounter(enc)), params.scoped({'simeval_pick': False, 'simeval_route': False}):
                cs = cands_of(st)
                if not cs or len(cs) < 2: continue
                seeds = [rng.randrange(1 << 30) for _ in range(M)]
                for c in cs: c['vs'] = rollouts(st, c['seq'], seeds[:2])
                # 先各推 2 遍：所有候选结局完全一样（多半是怎么打都一样，或者怎么打都死）就不再推——这种局面训练时本来就跳过
                if len({tuple(c['vs']) for c in cs}) > 1:
                    for c in cs: c['vs'] += rollouts(st, c['seq'], seeds[2:])
                for c in cs:
                    ok = [v for v in c['vs'] if v is not None]; c['n'] = len(ok); c['v'] = sum(ok) / len(ok) if ok else None
        finally:
            search._IN['on'] = False
        cs = [c for c in cs if c['v'] is not None]
        if len(cs) < 2: continue
        for c in cs: c.pop('seq')
        fo.write(json.dumps({'file': rel(f), 'line': i, 'fight': f'{rel(f)}#relabel', 'room': room, 'enc': r.get('enc'),
                             's': nnpolicy.encode_state(r['state']), 'c': cs}, ensure_ascii=False) + '\n')
        fo.flush(); n += 1; nb += room == 'Boss'
        if n % 10 == 0: print(f'{n} 个局面（Boss {nb}），{time.time() - t0:.0f} 秒', flush=True)
