"""离线评规划器：拿推演老师记下的局面（search_teach_log），看规划器这一回合挑的出法在老师眼里差多少（不开游戏、不推演）。
老师每个局面给前 8 种出法打过分（v = 推演打到底的平均结局值）。规划器挑的那组如果在其中，遗憾 = 老师最好的 v − 它的 v。
只统计「老师认为出法之间有差别」的局面（最好和最差差 > 1）。
用法：python3 tools/teacher_eval.py 记录1 记录2 ... [--set 参数=值 ...]
"""
import collections, copy, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
args = sys.argv[1:]; files = []; sets = {}
i = 0
while i < len(args):
    if args[i] == '--set': k, v = args[i + 1].split('=', 1); sets[k] = json.loads(v) if v[:1] in '-0123456789[{tf' else v; i += 2
    else: files.append(args[i]); i += 1
params.P.update(sets)
from policy import combat

key = lambda ids: tuple(sorted(str(x).replace('CARD.', '') for x in ids))
by_enc = collections.defaultdict(lambda: [0, 0, 0, 0.0, 0])   # 局面, 和老师一致, 在老师名单里, 遗憾和, 挑到老师最好
for p in files:
    for line in open(p):
        r = json.loads(line)
        cands = r.get('cands') or []
        if len(cands) < 2: continue
        vs = [c['v'] for c in cands]
        if max(vs) - min(vs) <= 1: continue
        st = copy.deepcopy(r['state']); st['decision'] = 'combat_play'
        try:
            with params.scoped(params.for_encounter((st.get('context') or {}).get('encounter'))):   # 和实战一样先套遭遇专属参数
                res = combat.plan(st, {}, set(), topk=-1)
        except Exception: continue
        if not res or not isinstance(res, dict): continue
        ev, cb = max(res['pool'], key=lambda x: x[0])
        pick = key(str(c.get('id') or c.get('name')) for c in cb)
        s = by_enc[r.get('enc')]; s[0] += 1
        if pick == key(r['chosen']): s[1] += 1
        m = {key(c['cards']): c['v'] for c in cands}
        if pick in m:
            s[2] += 1; s[3] += max(vs) - m[pick]; s[4] += m[pick] >= max(vs) - 1e-6
tot = [0, 0, 0, 0.0, 0]
for e, s in sorted(by_enc.items()):
    print(f'{e:28s} 局面 {s[0]:4d}  和老师一致 {s[1] / max(s[0], 1):5.1%}  在老师名单里 {s[2] / max(s[0], 1):5.1%}  平均遗憾 {s[3] / max(s[2], 1):5.2f}  挑到最好 {s[4] / max(s[2], 1):5.1%}')
    tot = [a + b for a, b in zip(tot, s)]
print(f'{"合计":28s} 局面 {tot[0]:4d}  和老师一致 {tot[1] / max(tot[0], 1):5.1%}  在老师名单里 {tot[2] / max(tot[0], 1):5.1%}  平均遗憾 {tot[3] / max(tot[2], 1):5.2f}  挑到最好 {tot[4] / max(tot[2], 1):5.1%}')
