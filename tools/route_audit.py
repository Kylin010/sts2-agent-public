"""路线分数体检（10/3）：本机跑几局（不推演），记录每个岔路各选项的路线价值，看有没有「全同分」或「被重复扣死亡」的退化。用法：python3 tools/route_audit.py 起 止 [on=打开 route_survival]"""
import json, sys
sys.path.insert(0, '.')
import params, run
from policy import route
LOG = []
orig = route.choose
def wrap(sim_map, st, mem):
    r = orig(sim_map, st, mem)
    sc = mem.get('route_scores') or {}
    if len(sc) > 1:
        ctx = st.get('context') or {}; pl = st.get('player') or {}
        LOG.append({'act': ctx.get('act'), 'floor': ctx.get('floor'), 'hp': pl.get('hp'), 'max': pl.get('max_hp'), 'scores': sorted(round(v, 1) for v in sc.values())})
    return r
route.choose = wrap
seeds = [l.strip() for l in open('lab/bundle/s120.txt') if l.strip()][int(sys.argv[1]):int(sys.argv[2])]
with params.scoped({'search_on': False, 'route_survival': len(sys.argv) > 3}):
    for s in seeds:
        try: r = run.play_one(s, stop_act=2)
        except Exception as e: print(s, '出错', e); continue
        print(s, '幕', r.get('act'), '层', r.get('floor'), flush=True)
tie = [x for x in LOG if x['scores'][0] == x['scores'][-1]]
low = [x for x in LOG if x['scores'][-1] < -300]
print(f'岔路 {len(LOG)} 个；所有选项同分 {len(tie)}；最好的选项也 < -300 的 {len(low)}')
for x in LOG[:40]: print('  ', x)
