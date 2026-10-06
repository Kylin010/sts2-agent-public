# 战斗基准：从玩家对局里还原「打某场战斗时的牌组（含升级）、遗物、进场血量」和这个人实际掉了多少血。
# 脚本用同样的配置打同一个敌人，掉血和人比，就只剩「打得好不好」这一个变量。
# 在项目根目录运行：python3 agent/build_bench.py [每个遭遇取几局，默认 12]
import json, gzip, random, sys, collections
K = int(sys.argv[1]) if len(sys.argv) > 1 else 12
ALL_NORMALS = '--all-normals' in sys.argv          # 把所有普通战也收进来（另存 bench_normals.json）
cid = lambda x: (x.get('id') if isinstance(x, dict) else str(x)).replace('CARD.', '')
HARD_NORMALS = {'EXOSKELETONS_NORMAL', 'THIEVING_HOPPER_WEAK', 'MYTES_NORMAL', 'SLUMBERING_BEETLE_NORMAL', 'NIBBITS_NORMAL',
                'RUBY_RAIDERS_NORMAL', 'SNAPPING_JAXFRUIT_NORMAL', 'LOUSE_PROGENITOR_NORMAL', 'HUNTER_KILLER_NORMAL', 'BOWLBUGS_NORMAL'}
cases = collections.defaultdict(list)
for line in gzip.open('sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt'):
    d = json.loads(line)
    if d.get('modifiers'): continue
    relics = [(r.get('floor_added_to_deck') or 0, str(r.get('id', '')).replace('RELIC.', '')) for r in d['players'][0].get('relics') or []]
    deck = collections.Counter({'STRIKE_IRONCLAD': 5, 'DEFEND_IRONCLAD': 4, 'BASH': 1, 'ASCENDERS_BANE': 1})
    up = collections.Counter()           # 每种牌升级了几张
    pots = []                            # 手上的药水（按拿到 / 买到 / 用掉 / 丢掉还原）
    g = 0
    for a, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            g += 1
            s = (p.get('player_stats') or [{}])[0]
            rm = (p.get('rooms') or [{}])[0]
            enc = str(rm.get('model_id', '')).replace('ENCOUNTER.', '')
            if (rm.get('room_type') == 'monster' and ALL_NORMALS) or (not ALL_NORMALS and (rm.get('room_type') in ('elite', 'boss') or enc in HARD_NORMALS)):
                hp_in = s.get('current_hp', 0) + s.get('damage_taken', 0) - s.get('hp_healed', 0)
                if hp_in > 0:
                    cards = []
                    for c, n in deck.items():
                        u = min(up[c], n)
                        cards += [c + '+'] * u + [c] * (n - u)
                    cases[enc].append({'encounter': enc, 'act': a + 1, 'room': rm.get('room_type'), 'deck': cards,
                                       'relics': [r for f, r in relics if f <= g], 'potions': list(pots), 'hp': hp_in, 'max_hp': s.get('max_hp', 80),
                                       'human_dmg': s.get('damage_taken', 0), 'human_survived': s.get('current_hp', 0) > 0,
                                       'human_won_run': bool(d.get('win'))})
            pid = lambda x: str(x.get('choice') if isinstance(x, dict) else x).replace('POTION.', '')
            for x in s.get('potion_used') or []:
                if pid(x) in pots: pots.remove(pid(x))
            for x in s.get('potion_discarded') or []:
                if pid(x) in pots: pots.remove(pid(x))
            pots += [pid(x) for x in s.get('potion_choices') or [] if isinstance(x, dict) and x.get('was_picked')]
            pots += [pid(x) for x in s.get('bought_potions') or []]
            pots = pots[-3:]
            for c in s.get('cards_gained') or []:
                deck[cid(c)] += 1
                if (c.get('current_upgrade_level') or 0) > 0: up[cid(c)] += 1
            for c in s.get('cards_removed') or []:
                if deck[cid(c)] > 0: deck[cid(c)] -= 1
            for t in s.get('cards_transformed') or []:
                o, f = cid(t.get('original_card', {})), cid(t.get('final_card', {}))
                if deck[o] > 0: deck[o] -= 1
                deck[f] += 1
            for c in s.get('upgraded_cards') or []:
                up[cid(c)] += 1
            deck = +deck
random.seed(1)
out = []
for enc, cs in sorted(cases.items()):
    random.shuffle(cs); out += cs[:K]
json.dump(out, open('agent/data/bench_normals.json' if ALL_NORMALS else 'agent/data/bench.json', 'w'), ensure_ascii=False)
print(f'{len(out)} 个基准战斗，{len(cases)} 种遭遇；人类平均掉血 {sum(c["human_dmg"] for c in out) / len(out):.1f}，人类撑过去的比例 {sum(c["human_survived"] for c in out) / len(out):.0%}')
