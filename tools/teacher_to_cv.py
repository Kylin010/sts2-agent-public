"""推演老师记录 → 战斗估值模型的训练样本（tools/train_combat_value.py 读的 turns 格式）。
每个局面的每个候选出法：规划器算出「打完这组牌、结束回合时」的局面（situation），目标 = 推演打到战斗结束的掉血（含死亡罚分）减去这回合自伤。
推演的 v = −(到战斗结束掉的血) + 5（赢）或 −(当前血 + 30~60)（死）→ 掉血 = 5 − v。一个局面一组（同一场战斗的局面放一起，按战斗分训练 / 检验）。
用法：python3 tools/teacher_to_cv.py 输出.jsonl 记录...
"""
import copy, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
params.P['cv_weight'] = max(params.P.get('cv_weight', 0), 0.3); params.P['rerank_on'] = False
from policy import combat, rerank
from policy.knowledge import cid
key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))
out = open(sys.argv[1], 'w'); n_rows = n_fights = 0
for p in sys.argv[2:]:
    prev = None; buf = []
    def flush():
        global n_rows, n_fights
        if buf: out.write(json.dumps({'turns': buf}, ensure_ascii=False) + '\n'); n_rows += len(buf); n_fights += 1
    for line in open(p):
        r = json.loads(line); rd = r.get('round') or 0
        if prev is not None and rd < prev: flush(); buf = []
        prev = rd
        cands = [c for c in (r.get('all') or r.get('cands') or []) if not c.get('potion')]
        if not cands: continue
        st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
        try:
            with params.scoped(params.for_encounter((st.get('context') or {}).get('encounter'))):
                res = combat.plan(st, {}, set(), topk=-1)
                if not res or not isinstance(res, dict): continue
                pool = {key(cid(c) for c in cb): cb for _, cb in res['pool']}
                for c in cands:
                    cb = pool.get(key(c['cards']))
                    if cb is None: continue
                    pt = rerank.parts(cb, res['ctx'], combat.evaluate)
                    if not pt or not pt.get('sit') or not pt['sit']['enemies']: continue    # 打完战斗就结束的不要（模型对赢了直接给 0）
                    buf.append({'s': pt['sit'], 'future': max(0.0, 5 - c['v'] - pt['self_hp']), 'died': False, 'n': c.get('n', 1)})
        except Exception as e:
            continue
    flush()
print(f'{n_rows} 个样本，{n_fights} 场战斗')
