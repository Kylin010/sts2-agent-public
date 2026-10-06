"""神经网络策略模型的数据。
输入：search_teach_log 记录（主线 iter-pub 的 selfplay.*，每个局面有推演给全部候选打的结局值 all[].v）。
输出：每个局面一条 —— 玩家看得见的局面（自己 / 手牌 / 三个牌堆内容 / 敌人 / 能力 / 药水 / 遭遇）+ 每个出牌候选（打哪些牌、规划器分、打分明细、推演值 v 和推演遍数 n）。
喝药候选先不收（单独的决定）。规划器明细用 policy/rerank.py 的 feats（和实战同一套遭遇专属参数）。
用法：python3 tools/nn_dataset.py 输出.pkl 进程数 记录...
环境变量 NN_BOSS_AFTER=UTC 时间戳（秒）：修改时间早于它的记录文件不收 Boss 战局面——
主线 57bcc80（10/5 00:35 UTC）之前，新引擎推演会把「打死 Boss」的模拟当报错作废，Boss 局面的推演值偏向不打死 Boss。
"""
import copy, json, os, pickle, sys
from multiprocessing import Pool
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


from policy.nnpolicy import spec as _spec, encode_state   # 局面编码和下场共用一份


def one(args):
    path, n0, lines, no_boss = args
    import params
    params.P['rerank_on'] = False
    from policy import combat, rerank
    from policy.knowledge import cid
    key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))
    out = []; fight = None; prev = None
    for k, line in enumerate(lines):
        try: r = json.loads(line)
        except Exception: continue
        rd = r.get('round') or 0
        if prev is None or rd < prev: fight = f'{path}#{n0 + k}'
        prev = rd
        if no_boss and r.get('room') == 'Boss': continue
        cands = [c for c in (r.get('all') or []) if not c.get('potion')]
        if len(cands) < 2: continue
        st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
        try:
            with params.scoped(params.for_encounter((st.get('context') or {}).get('encounter'))):
                res = combat.plan(st, {}, set(), topk=-1)
                if not res or not isinstance(res, dict): continue
                pool = {key(cid(c) for c in cb): (ev, cb) for ev, cb in res['pool']}
                enc = rerank.enc_of(st) or (r.get('enc') or ''); mv = rerank.phase(res['ctx'])
                cs = []
                for c in cands:
                    kk = key(c['cards'])
                    if kk not in pool: continue
                    ev, cb = pool[kk]
                    pt = rerank.parts(cb, res['ctx'], combat.evaluate)
                    if pt is None: continue
                    f = {k: v for k, v in rerank.feats(cb, res['ctx'], pt, enc, mv, ev).items() if k in rerank.CORE}
                    cs.append(dict(cards=[_spec(x) for x in cb], sc=float(ev), f=f, v=float(c['v']), n=int(c.get('n') or 1)))
        except Exception:
            continue
        if len(cs) >= 2:
            out.append(dict(fight=fight, s=encode_state(r['state']), c=cs))
    return out


if __name__ == '__main__':
    outp, procs, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    jobs = []; cut = float(os.environ.get('NN_BOSS_AFTER') or 0); nb = 0
    for p in files:
        lines = open(p).read().splitlines(); no_boss = os.path.getmtime(p) < cut; nb += no_boss
        for i in range(0, len(lines), 400):                 # 按块切；块边界可能把一场战斗切开，fight 编号只用来分训练 / 检验
            jobs.append((p, i, lines[i:i + 400], no_boss))
    print(f'{len(files)} 个文件，其中 {nb} 个早于修复、不收 Boss 局面', flush=True)
    data = []
    with Pool(procs) as pool:
        for k, res in enumerate(pool.imap_unordered(one, jobs)):
            data += res
            if k % 20 == 0: print(f'{k + 1}/{len(jobs)} 块，{len(data)} 个局面', flush=True)
    pickle.dump(data, open(outp, 'wb'))
    print(f'共 {len(data)} 个局面，{sum(len(d["c"]) for d in data)} 个候选 → {outp}')
