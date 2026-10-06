"""诊断：网络和规划器挑得不一样的局面，用新种子把两手各重推 M 遍（同一批种子配对），看谁真的更好。
回答「网络在留出局面上看着更好、实战却更差」是标签有偏（只推 3 遍被淘汰的偏低、时限截断等），还是网络自己打出来的局面分布不同。
做法和推演完全一样（policy/search.py 的新引擎推演：只按看得见的局面摆战斗，种子是新的，之后规划器接着打到战斗结束）。
用法：STS2_CLI_DIR=... python3 tools/nn_reroll.py 模型.npz 输出.jsonl 份号 总份数 [M] [每份局面数] 记录文件...
"""
import copy, json, os, random, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import numpy as np
import params
from params import P
import policy
from policy import combat, rerank, nnpolicy, search
from policy.knowledge import cid

model_path, outp, part, nparts = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
M = int(sys.argv[5]); NMAX = int(sys.argv[6]); files = sys.argv[7:]
m = nnpolicy.load(model_path)
P['search_public'] = True; P['search_public_fast'] = True; P['search_on'] = False; P['nn_on'] = False


def cands_of(st):
    """规划器前 K 名候选（和推演同一套），带打分明细和出牌顺序 / 目标"""
    res = combat.plan(st, {}, set(), topk=-1)
    if not res or not isinstance(res, dict): return None
    ctx = res['ctx']; pool = {i: t for i, t in enumerate(res['pool'][1:])}          # pool[0] 是「什么都不打」
    out = []
    enc = rerank.enc_of(st); mv = rerank.phase(ctx)
    for sc, combo in combat.candidates(pool, ctx, P['search_k']):
        pt = rerank.parts(combo, ctx, combat.evaluate)
        if pt is None: continue
        f = rerank.feats(combo, ctx, pt, enc, mv, sc)
        if combo:
            _, tgt, p = combat.evaluate(combo, ctx, want_targets=True)
            seq = [(c, (tgt.get(id(c)) or p)['index']) for c in sorted(combo, key=combat.ORDER)]
        else:
            seq = []
        out.append(dict(sc=sc, combo=combo, seq=seq, f={k: f[k] for k in nnpolicy.CORE}, cards=[nnpolicy.spec(c) for c in combo]))
    return out


def reroll(st, seq, seeds):
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
        except Exception as e:
            vals.append(None)
            if sim.broken: sim.restart()
    return vals


from sim import aux
rng = random.Random(1000 + part)
LINES = {f: open(f).read().splitlines() for f in files}
jobs = [(f, i) for f in files for i in range(len(LINES[f]))]
rng.shuffle(jobs)
done = 0; t0 = time.time()
with open(outp, 'a') as fo:
    for f, i in jobs[part::nparts]:
        if done >= NMAX: break
        try: r = json.loads(LINES[f][i])
        except Exception: continue
        if r.get('room') not in ('Monster', 'Elite'): continue
        st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
        enc = (st.get('context') or {}).get('encounter')
        search._IN['on'] = True
        try:
            with params.scoped(params.for_encounter(enc)), params.scoped({'simeval_pick': False, 'simeval_route': False}):
                cs = cands_of(st)
                if not cs or len(cs) < 2: continue
                out = nnpolicy.scores(m, nnpolicy.featurize(nnpolicy.encode_state(st), cs, m['V']))
                k = int(np.argmax(out)); p = int(np.argmax([c['sc'] for c in cs]))
                if k == p: continue
                seeds = [rng.randrange(1 << 30) for _ in range(M)]
                vk = reroll(st, cs[k]['seq'], seeds); vp = reroll(st, cs[p]['seq'], seeds)
        finally:
            search._IN['on'] = False
        # 原记录里这两手的推演值（若有）
        key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))
        orig = {key(c['cards']): (c['v'], c.get('n')) for c in r.get('all') or [] if not c.get('potion')}
        ok = lambda c: orig.get(key(cid(x) for x in c['combo']))
        fo.write(json.dumps({'file': f, 'line': i, 'room': r.get('room'), 'enc': r.get('enc'), 'nn': cs[k]['cards'], 'pl': cs[p]['cards'],
                             'v_nn': vk, 'v_pl': vp, 'orig_nn': ok(cs[k]), 'orig_pl': ok(cs[p]), 'margin': float(out[k] - out[p])}, ensure_ascii=False) + '\n')
        fo.flush(); done += 1
        print(f'{done} 个局面，{time.time() - t0:.0f} 秒', flush=True)
