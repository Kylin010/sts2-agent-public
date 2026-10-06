"""从自我对弈推演记录（主线 iter-pub 的 selfplay.*）拼同牌组测试案例：每场指定遭遇的开场状态（我们自己的牌组 / 遗物 / 药水 / 血量）。
人类回放的测试集（data/bench_t_*.json）只有人类打过的牌组；这里用我们自己打到那一战时的家底，和整局里的实际情况一致。
用法：python3 tools/build_selfplay_bench.py 遭遇ID [更多遭遇...]  → data/bench_sp_<遭遇小写>.json（每个案例的 human_dmg 填 0，只做配对对比用）
"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy.nnpolicy import spec

ROOM = {'Monster': 'monster', 'Elite': 'elite', 'Boss': 'boss'}
for enc in sys.argv[1:]:
    seen = set(); cases = []
    for f in sorted(glob.glob(f'{HERE}/../selfplay/*/selfplay.[0-9]*')):
        for l in open(f):
            if f'"{enc}"' not in l: continue
            r = json.loads(l)
            if r.get('enc') != enc or r.get('round') != 1: continue
            key = (r.get('seed'), r.get('floor'))
            if key in seen: continue
            st = r['state']; pl = st['player']
            if any((e.get('hp') or 0) < (e.get('max_hp') or 0) for e in st.get('enemies') or []): continue   # 已经被打过：不是开场
            seen.add(key)
            cases.append({'encounter': enc, 'act': int(r.get('act') or 1), 'room': ROOM.get(r.get('room'), 'monster'), 'deck': [spec(c) for c in pl['deck']],
                          'relics': [str(x.get('id')) for x in pl.get('relics') or []],
                          'potions': [str(p.get('id')) for p in pl.get('potions') or [] if p and p.get('id')],
                          'hp': pl['hp'], 'max_hp': pl['max_hp'], 'human_dmg': 0, 'human_survived': True, 'human_won_run': None,
                          'enchanted': 0, 'max_hp_known': True, 'src': list(key)})
    out = f'{HERE}/data/bench_sp_{enc.lower()}.json'
    json.dump(cases, open(out, 'w'), ensure_ascii=False)
    print(f'{enc}: {len(cases)} 个案例 → {out}')
