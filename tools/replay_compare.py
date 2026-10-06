"""同一个局面，人类出了什么、脚本会出什么：从 v7 社区回放还原每回合开始时的局面，交给 policy/combat.plan 算，和人类实际出的牌比较。

还原（近似）：手牌 = 回合开始时抽到的牌（不含回合中途抽到的）；能量 = energy 事件；
敌人 = combat_start 的血量 − 之后的命中伤害，意图 = intent 事件（伤害 × 段数）；我的力量 = power 事件里的 STRENGTH_POWER；
卡牌数值来自 kb/cards.json（升级的数值没有，按未升级算，只当参考）。
只比较「脚本会选的整组牌」和「人类这回合打出的牌（回合开始就在手里的那些）」。
用法：python3 tools/replay_compare.py [--enc BOSS] [--n 40]   打印分歧的例子 + 一致率
"""
import argparse, glob, gzip, json, os, sys, collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy import combat, kb
ap = argparse.ArgumentParser(); ap.add_argument('--enc', default='BOSS'); ap.add_argument('--n', type=int, default=40)
ap.add_argument('--max-turns', type=int, default=4000)
a = ap.parse_args()
C = json.load(open(f'{HERE}/kb/cards.json'))
SRC = '/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10'


def card_dict(cid_, idx, strength):
    c = C.get(cid_, {})
    cost = c.get('cost') if isinstance(c.get('cost'), int) else 1
    dmg = (c.get('damage') or 0); blk = c.get('block') or 0
    t = c.get('type') or 'Skill'
    return {'index': idx, 'id': 'CARD.' + cid_, 'name': c.get('name') or cid_, 'cost': cost, 'type': t, 'can_play': t not in ('Curse', 'Status'),
            'stats': {'damage': dmg + (strength if dmg else 0), 'block': blk}, 'target_type': 'AnyEnemy' if t == 'Attack' else 'Self'}


def turns_from(path):
    lines = [json.loads(l) for l in gzip.open(path, 'rt')]
    if lines[0].get('replay_version') != 7: return
    enemies = {}; hand = {}; hp = mx = 80; block = 0; strength = 0; energy = 3; enc = None; turn = None
    for d in lines:
        t = d.get('t')
        if t == 'combat_start':
            enc = d.get('encounter'); enemies = {e['cid']: {'id': e['id'], 'hp': e['hp'], 'block': 0, 'intent': 0, 'hits': 1} for e in d.get('enemies') or []}
            hand = {}; strength = 0; block = 0
        elif t == 'combat_end': enc = None
        if not enc:
            if t == 'hp': hp = d.get('hp', hp)
            continue
        if t == 'hp': hp = d.get('hp', hp)
        elif t == 'energy': energy = d.get('energy', energy)
        elif t == 'draw': hand[d['c']] = d['id']
        elif t == 'intent' and d.get('src_cid') in enemies:
            enemies[d['src_cid']]['intent'] = (d.get('dmg') or 0) * (d.get('hits') or 1) if 'attack' in (d.get('intents') or []) else 0
        elif t == 'power' and d.get('id') == 'STRENGTH_POWER' and d.get('tgt') == 'IRONCLAD': strength = d.get('amount', strength)
        elif t == 'hit' and d.get('dst_cid') in enemies: enemies[d['dst_cid']]['hp'] -= d.get('dmg') or 0
        elif t == 'turn' and d.get('side') == 'player':
            turn = {'enc': enc, 'hand': dict(hand), 'energy': energy, 'hp': hp, 'strength': strength, 'played': [],
                    'enemies': {k: dict(v) for k, v in enemies.items() if v['hp'] > 0}, 'round': d.get('round')}
        elif t == 'play' and turn is not None and not d.get('auto'):
            if d['c'] in turn['hand']: turn['played'].append(d['id'])
            hand.pop(d['c'], None)
        elif t == 'end_turn' and d.get('side') == 'player' and turn is not None:
            yield turn; turn = None; hand = {}


def our_choice(tr):
    hand = [card_dict(i, n, tr['strength']) for n, i in enumerate(tr['hand'].values())]
    ens = [{'index': n, 'name': v['id'], 'hp': v['hp'], 'max_hp': v['hp'], 'block': 0,
            'intents': [{'type': 'Attack', 'damage': v['intent']}] if v['intent'] else [{'type': 'Buff'}], 'powers': []}
           for n, v in enumerate(tr['enemies'].values())]
    st = {'decision': 'combat_play', 'hand': hand, 'energy': tr['energy'], 'enemies': ens, 'round': tr['round'],
          'player': {'hp': tr['hp'], 'max_hp': 80, 'block': 0, 'deck': []}, 'player_powers': [], 'context': {'encounter': tr['enc'], 'floor': 1}}
    chosen = []; mem = {}; bad = set()
    for _ in range(12):                                  # 逐张出：每出一张就从手里拿掉、扣能量，再规划
        r = combat.plan(st, mem, bad)
        if r is None: break
        c, _ = r; chosen.append(c['id'].replace('CARD.', ''))
        st['energy'] -= c['cost'] if c['cost'] >= 0 else st['energy']
        st['hand'] = [x for x in st['hand'] if x is not c]
        for n, x in enumerate(st['hand']): x['index'] = n
        if st['energy'] < 0: break
    return chosen


agree = 0; tot = 0; examples = []
cnt_h = collections.Counter(); cnt_s = collections.Counter()
for f in sorted(glob.glob(f'{SRC}/*.ndjson.gz')):
    for tr in turns_from(f):
        if a.enc not in (tr['enc'] or ''): continue
        if not tr['hand'] or not tr['enemies']: continue
        ours = our_choice(tr); hum = tr['played']
        tot += 1; same = collections.Counter(ours) == collections.Counter(hum); agree += same
        for x in hum: cnt_h[x] += 1
        for x in ours: cnt_s[x] += 1
        if not same and len(examples) < a.n: examples.append((tr, ours, hum))
        if tot >= a.max_turns: break
    if tot >= a.max_turns: break
print(f'{a.enc}：{tot} 个回合，整组一致 {agree / max(tot, 1):.0%}')
for tr, ours, hum in examples[:a.n]:
    en = '; '.join(f"{v['id']} {v['hp']}血 意图{v['intent']}" for v in tr['enemies'].values())
    print(f"[{tr['enc']} R{tr['round']}] 血{tr['hp']} 能{tr['energy']} 力{tr['strength']} | {en} | 手 {list(tr['hand'].values())}\n    人类：{hum}\n    脚本：{ours}")
diff = sorted(set(cnt_h) | set(cnt_s), key=lambda k: -(cnt_h[k] - cnt_s[k]))
print('人类比脚本多打的牌：', [(k, cnt_h[k], cnt_s[k]) for k in diff[:12]])
print('脚本比人类多打的牌：', [(k, cnt_h[k], cnt_s[k]) for k in diff[-10:]])
