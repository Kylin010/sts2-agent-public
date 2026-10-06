"""商店校准：把社区赢家的每次进店还原成局面（牌组、金币、上架的牌和遗物、删牌价格），
让 policy/shop.py 在同样局面下做决定，比较「它买的」和「赢家买的」，随机搜索 shop_* 换算系数让两者最一致。

价格按源码规则估（kb/rules.json）：牌 普通 50 / 罕见 75 / 稀有 150；遗物 普通 175 / 罕见 225 / 稀有 275 / 商店 200；
删牌 A10 100 起每用一次 +50。半价和 ±5% 的浮动数据里没有，忽略。药水不参与（数据里栏位状态不全）。
指标：每件东西（牌 / 遗物 / 删牌）买与不买的 F1，以及平均每次买几张牌、几件遗物、删几次和赢家比。
用法：python3 tools/calibrate_shop.py [--n 1500] [--trials 60] [--workers 4]   结果打印出来，最好的写进 lab/shop_calibration.json
"""
import argparse, collections, gzip, json, os, random, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
rid = lambda x: str(x).replace('RELIC.', '')
CARDS = json.load(open(f'{HERE}/kb/cards.json')); RELICS = json.load(open(f'{HERE}/kb/relics.json'))
CP = {'Common': 50, 'Uncommon': 75, 'Rare': 150}
RP = {'Common': 175, 'Uncommon': 225, 'Rare': 275, 'Shop': 200}
SPACE = {'shop_card_unit': (2, 12), 'shop_relic_base': (0, 35), 'shop_relic_unit': (3, 20), 'shop_remove_strike_logit': (0, 4),
         'shop_remove_defend_logit': (0, 3), 'shop_v_gold': (0.02, 0.2), 'shop_relic_logit_ref': (-2.5, -0.5)}


def ctype(i):
    return (CARDS.get(i) or {}).get('type') or 'Attack'


def load(n, seed=5):
    visits = []
    for line in gzip.open(SRC, 'rt'):
        d = json.loads(line)
        if not d.get('win') or d.get('modifiers') or 'BaseLib' in line: continue
        deck = list(START); removals = 0
        for ai, act in enumerate(d.get('map_point_history') or []):
            for p in act:
                ps = (p.get('player_stats') or [{}])[0]
                if p.get('map_point_type') == 'shop':
                    gold = (ps.get('current_gold') or 0) + (ps.get('gold_spent') or 0)
                    cards = []; bought = set()
                    # 商店记录的 card_choices 只有「没买走的」；买走的在 cards_gained 里（无色牌另记在 bought_colorless，不算）
                    col = collections.Counter(cid(c) for c in ps.get('bought_colorless') or [])
                    got = []
                    for c in ps.get('cards_gained') or []:
                        i = cid(c)
                        if col[i] > 0: col[i] -= 1; continue
                        got.append(i)
                    offered = [(cid(x.get('card')), False) for x in ps.get('card_choices') or []] + [(i, True) for i in got]
                    for j, (i, b) in enumerate(offered):
                        r = (CARDS.get(i) or {}).get('rarity', 'Common')
                        cards.append({'index': j, 'id': i, 'type': ctype(i), 'cost': CP.get(r, 75), 'is_stocked': True})
                        if b: bought.add(('card', j))
                    relics = []
                    for j, x in enumerate(ps.get('relic_choices') or []):
                        i = rid(x.get('choice')); r = str((RELICS.get(i) or {}).get('rarity', 'Common')).split()[0]
                        relics.append({'index': j, 'id': i, 'name': '', 'cost': RP.get(r, 200), 'is_stocked': True})
                        if x.get('was_picked'): bought.add(('relic', j))
                    rem = ps.get('cards_removed') or []
                    if rem: bought.add(('remove', None))
                    st = {'player': {'gold': gold, 'deck': [{'id': c, 'type': 'Curse' if c in ('ASCENDERS_BANE',) else ctype(c)} for c in deck], 'potions': []},
                          'context': {'act': min(ai + 1, 3)}, 'cards': cards, 'relics': relics, 'potions': [],
                          'card_removal_cost': 100 + 50 * removals}
                    visits.append((st, bought))
                    removals += len(rem)
                for c in ps.get('cards_gained') or []: deck.append(cid(c))
                for c in ps.get('cards_removed') or []:
                    if cid(c) in deck: deck.remove(cid(c))
    random.Random(seed).shuffle(visits)
    return visits[:n]


VISITS = None


def score(params):
    from params import P
    from policy import shop
    P.update(params)
    tp = fp = fn = 0; cnt = collections.Counter()
    for st, bought in VISITS:
        pred = {(x[0], x[1]) for x in shop.plan(st)}
        tp += len(pred & bought); fp += len(pred - bought); fn += len(bought - pred)
        for k, _ in pred: cnt['p_' + k] += 1
        for k, _ in bought: cnt['t_' + k] += 1
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    n = len(VISITS)
    return f1, {k: round(v / n, 2) for k, v in sorted(cnt.items())}


def init(n):
    global VISITS
    VISITS = load(n)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--n', type=int, default=1500); ap.add_argument('--trials', type=int, default=60)
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--around', action='store_true')
    a = ap.parse_args()
    from params import P
    base = {k: P[k] for k in SPACE}
    rng = random.Random(11)
    trials = [base] + [{k: round(rng.uniform(lo, hi), 3) for k, (lo, hi) in SPACE.items()} for _ in range(a.trials)]
    if a.around and os.path.exists(f'{HERE}/lab/shop_calibration.json'):     # 细调：在上次最好的附近 ±30% 扰动
        c = json.load(open(f'{HERE}/lab/shop_calibration.json'))['best']
        trials = [base, c] + [{k: round(v * rng.uniform(0.7, 1.3), 3) for k, v in c.items()} for _ in range(a.trials)]
    with Pool(a.workers, initializer=init, initargs=(a.n,)) as pool:
        res = pool.map(score, trials)
    order = sorted(range(len(trials)), key=lambda i: -res[i][0])
    print(f'现在的参数：F1 {res[0][0]:.3f} {res[0][1]}')
    for i in order[:5]:
        print(f'F1 {res[i][0]:.3f} {res[i][1]}  {trials[i]}')
    os.makedirs(f'{HERE}/lab', exist_ok=True)
    json.dump({'best': trials[order[0]], 'f1': res[order[0]][0], 'counts': res[order[0]][1], 'current_f1': res[0][0]},
              open(f'{HERE}/lab/shop_calibration.json', 'w'), ensure_ascii=False, indent=1)
