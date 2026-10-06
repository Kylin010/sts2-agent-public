"""第二幕高死亡率战斗的单场案例。

每个案例 = 一场第二幕战斗 + 我们程序自己选出来的牌组（实战走到这场战斗时的牌组）+ 随机遗物（人类在第二幕 Boss 前常有的遗物，按出现频率抽）
+ 两瓶随机药水 + 典型进场血量。遗物两档：我们现在的数量（10 个）、人类的数量（15 个）——顺便量「遗物差距」有多大影响。
输出 data/bench_a2ours.json（格式同 data/bench.json），用法：STS2_BENCH=bench_a2ours.json python3 dist.py 0 --bench --reps 1 --tag xxx --set search_on=true
"""
import collections, glob, gzip, json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
TARGETS = {   # 遭遇 id → (房间, 进场血量)
    'KAISER_CRAB_BOSS': ('boss', 70), 'KNOWLEDGE_DEMON_BOSS': ('boss', 70), 'THE_INSATIABLE_BOSS': ('boss', 70),
    'DECIMILLIPEDE_ELITE': ('elite', 60), 'ENTOMANCER_ELITE': ('elite', 60), 'INFESTED_PRISMS_ELITE': ('elite', 60),
    'SLUMBERING_BEETLE_NORMAL': ('monster', 55), 'HUNTER_KILLER_NORMAL': ('monster', 55)}
MAX_HP = 85


def human_pools():
    """人类在第二幕 Boss 前持有的遗物（不含初始）和药水，按出现次数"""
    rel = collections.Counter(); pot = collections.Counter()
    with gzip.open(f'{os.path.dirname(HERE)}/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz', 'rt') as f:
        for line in f:
            d = json.loads(line)
            if len(d.get('map_point_history') or []) < 2: continue
            fl = len(d['map_point_history'][0]) + len(d['map_point_history'][1])
            for r in d['players'][0].get('relics') or []:
                if r.get('floor_added_to_deck', 99) < fl:
                    rid = r['id'].replace('RELIC.', '')
                    if rid not in ('BURNING_BLOOD', 'BLACK_BLOOD'): rel[rid] += 1
            for p in d['players'][0].get('potions') or []:
                pot[str(p.get('id', '')).replace('POTION.', '')] += 1
    return rel, pot


def our_decks():
    """我们实战走到各目标战斗时的牌组：死在这场的局，最后牌组就是这场的牌组；Boss 另加打完第二幕的局（Boss 后最多多一张奖励牌）"""
    from run import match_baseline as _mb

    def match_baseline(c):                        # 残杀千足虫：实战敌人名是 Decimillipede ×3，人类数据里是三种节段名，按名字对不上
        if any('Decimillipede' in str(e) for e in c.get('enemies') or []) and c.get('room') == 'Elite': return 'DECIMILLIPEDE_ELITE'
        return _mb(c)
    out = collections.defaultdict(list)
    for f in glob.glob(f'{HERE}/results/bdla2-g*.jsonl') + [f'{HERE}/results/v16h-hp80.jsonl', f'{HERE}/results/fresh300-hp80.jsonl']:
        if not os.path.exists(f): continue
        for l in open(f):
            r = json.loads(l)
            if 'crash' in r or not r.get('deck'): continue
            if r.get('act') == 2 and not r.get('win'):
                k = match_baseline({'enemies': r.get('enemies') or [], 'room': r.get('room')})
                if k in TARGETS: out[k].append(r['deck'])
            elif r.get('win') or (r.get('act') or 1) >= 3:
                for c in r.get('combats') or []:
                    if c['act'] == 2 and c['room'] == 'Boss':
                        k = match_baseline(c)
                        if k in TARGETS: out[k].append(r['deck'])
    return out


def main(per=20, seed=7):
    rng = random.Random(seed)
    rel, pot = human_pools()
    rel_ids, rel_w = list(rel), [rel[k] for k in rel]
    pot_ids, pot_w = list(pot), [pot[k] for k in pot]
    base = json.load(open(f'{HERE}/data/baselines.json'))
    decks = our_decks()
    cases = []
    for enc, (room, hp) in TARGETS.items():
        ds = decks.get(enc) or []
        rng.shuffle(ds)
        for deck in ds[:per]:
            for n_rel, tag in ((9, '我们'), (14, '人类')):
                rs = set()
                while len(rs) < n_rel: rs.add(rng.choices(rel_ids, rel_w)[0])
                cases.append({'encounter': enc, 'act': 2, 'room': room, 'deck': deck, 'relics': ['BURNING_BLOOD'] + sorted(rs),
                              'potions': [rng.choices(pot_ids, pot_w)[0] for _ in range(2)], 'hp': hp, 'max_hp': MAX_HP,
                              'human_dmg': round((base.get(enc) or {}).get('win_avg', 0)), 'human_survived': True, 'human_won_run': True,
                              'relic_level': tag, 'deck_src': 'ours'})
        print(enc, '我们的牌组', len(ds), '个，用', min(per, len(ds)))
    json.dump(cases, open(f'{HERE}/data/bench_a2ours.json', 'w'), ensure_ascii=False)
    print('案例', len(cases))


if __name__ == '__main__':
    main()
