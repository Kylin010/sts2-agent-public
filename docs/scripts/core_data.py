"""输出核心研究 · 公共数据层：把社区对局（铁甲 A10 v0.111.0，单人、无模组、无放弃）还原成逐节点的时间线。

用法（被其他脚本 import）：
    from core_data import load_runs, ZH, name
    for r in load_runs(): ...

每局 r 是一个 dict：
    win            最终是否通关
    acts           走到了第几幕（1~3）
    killed_by      死在哪个遭遇（ENCOUNTER.xxx 去前缀；赢了为 None）
    points         节点列表，每个节点：
        act, floor（全局层数，和 floor_added_to_deck 一致）, type（monster/elite/boss/...）, enc（遭遇 id）,
        hp, maxhp（进节点前后见下）, dmg（本节点 damage_taken）, hp_after（离开节点时的 current_hp）,
        deck（进入该节点时的牌组：tuple，升级过的牌 id 后加 '+'）,
        picks（本节点的选牌：[(出现的牌 id 列表, 拿了哪张 or None)]，只含 card_choices）,
        relics（进入节点时持有的遗物数，含初始遗物）, ups（进入节点时牌组里升级过的张数）, elites（本幕在此之前打过几个精英）
    c1             第一幕结束时（进入第二幕第一个节点时）的牌组；没进第二幕为 None
    c2             进第二幕 Boss 前的牌组；没打到第二幕 Boss 为 None
    c1_idx / c2_idx  对应节点在 points 里的下标（方便取 relics / hp）
    pass_a2_boss   打到第二幕 Boss 的局里，是否打过了（进了第三幕）
    first          {牌 id: 第一次进牌组的全局层数}

牌组还原方式：初始 5 打击 4 防御 1 痛击 + 进阶之灾，按每个节点的 cards_gained / cards_removed / cards_transformed /
upgraded_cards / downgraded_cards 正推。已验证：前 3000 局正推的最终牌组和对局记录里的最终牌组 2999 局完全一致。
"""
import gzip, json, collections, os

ROOT = '/opt/slay-the-spire-2'
SRC = f'{ROOT}/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
ZH_DIR = f'{ROOT}/sources/spire-codex/data-beta/v0.111.0/zhs'
ZH = {c['id']: c['name'] for c in json.load(open(f'{ZH_DIR}/cards.json'))}
CARD_INFO = {c['id']: c for c in json.load(open(f'{ZH_DIR}/cards.json'))}
try:
    ENC_ZH = {e['id']: e['name'] for e in json.load(open(f'{ZH_DIR}/encounters.json'))}
except Exception:
    ENC_ZH = {}
BASIC = {'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'ASCENDERS_BANE'}


def name(c):
    c = str(c)
    up = c.endswith('+')
    c = c.rstrip('+')
    return ZH.get(c, c) + ('+' if up else '')


def ename(e):
    return ENC_ZH.get(e, e)


def cid(x):
    return (x.get('id') if isinstance(x, dict) else str(x)).replace('CARD.', '')


def _snap(deck, up):
    out = []
    for c, n in deck.items():
        u = min(up.get(c, 0), n)
        out += [c + '+'] * u + [c] * (n - u)
    return tuple(sorted(out))


def base(c):
    return c.rstrip('+')


def ids(deck):
    """牌组 tuple → 去掉升级标记的 id 集合"""
    return {base(c) for c in deck}


def counts(deck):
    return collections.Counter(base(c) for c in deck)


def load_runs(src=SRC, keep_points=True):
    with gzip.open(src, 'rt') as f:
        for line in f:
            d = json.loads(line)
            yield parse(d, keep_points)


def parse(d, keep_points=True):
    deck = collections.Counter({'STRIKE_IRONCLAD': 5, 'DEFEND_IRONCLAD': 4, 'BASH': 1, 'ASCENDERS_BANE': 1})
    up = collections.Counter()
    relic_floors = sorted(r.get('floor_added_to_deck', 0) for r in d['players'][0].get('relics') or [])
    first = {}
    pts = []
    fl = 0
    c1 = c2 = None; c1_idx = c2_idx = None
    mph = d.get('map_point_history') or []
    total_ups = 0
    for ai, act in enumerate(mph):
        elites = 0
        for pi, p in enumerate(act):
            fl += 1
            s = (p.get('player_stats') or [{}])[0]
            rooms = p.get('rooms') or [{}]
            enc = str(rooms[0].get('model_id') or '').replace('ENCOUNTER.', '').replace('EVENT.', 'EVENT:')
            snap = _snap(deck, up)
            if ai == 1 and pi == 0: c1 = snap; c1_idx = len(pts)
            if ai == 1 and p.get('map_point_type') == 'boss' and c2 is None: c2 = snap; c2_idx = len(pts)
            nrel = sum(1 for x in relic_floors if x < fl)
            picks = []
            for_choice = s.get('card_choices') or []
            if for_choice:
                offered = [cid(cc['card']) for cc in for_choice]
                picked = [cid(cc['card']) for cc in for_choice if cc.get('was_picked')]
                picks.append((offered, picked[0] if picked else None))
            hp_after = s.get('current_hp'); dmg = s.get('damage_taken') or 0
            rec = {'act': ai + 1, 'i': pi, 'floor': fl, 'type': p.get('map_point_type'), 'enc': enc,
                   'dmg': dmg, 'hp_after': hp_after, 'maxhp': s.get('max_hp'), 'deck': snap, 'picks': picks,
                   'relics': nrel, 'ups': sum(min(up[c], deck[c]) for c in up), 'elites': elites,
                   'healed': s.get('hp_healed') or 0, 'rest': s.get('rest_site_choices') or []}
            pts.append(rec)
            if p.get('map_point_type') == 'elite': elites += 1
            # 应用本节点的牌组变化
            for c in s.get('cards_gained') or []:
                k = cid(c); deck[k] += 1
                if isinstance(c, dict) and c.get('current_upgrade_level'): up[k] += 1
                first.setdefault(k, fl)
            for c in s.get('cards_removed') or []:
                k = cid(c)
                if deck[k] > 0:
                    deck[k] -= 1
                    if isinstance(c, dict) and c.get('current_upgrade_level') and up[k] > 0: up[k] -= 1
            for t in s.get('cards_transformed') or []:
                o, fi = cid(t.get('original_card', {})), cid(t.get('final_card', {}))
                if deck[o] > 0: deck[o] -= 1
                deck[fi] += 1; first.setdefault(fi, fl)
            for c in s.get('upgraded_cards') or []:
                k = cid(c)
                if up[k] < deck[k]: up[k] += 1
            for c in s.get('downgraded_cards') or []:
                k = cid(c)
                if up[k] > 0: up[k] -= 1
            deck = +deck
    # 进入第一个节点前的「上一节点离开血量」→ 进节点血量
    prev = None
    for rec in pts:
        rec['hp_in'] = prev if prev is not None else None
        prev = rec['hp_after']
    acts = len(mph)
    win = bool(d.get('win'))
    pass_a2 = None
    if c2 is not None:
        pass_a2 = acts >= 3
    kb = str(d.get('killed_by_encounter') or '').replace('ENCOUNTER.', '')
    return {'win': win, 'acts': acts, 'killed_by': None if win else kb, 'points': pts if keep_points else None,
            'c1': c1, 'c2': c2, 'c1_idx': c1_idx, 'c2_idx': c2_idx, 'pass_a2_boss': pass_a2, 'first': first,
            'final': _snap(deck, up), 'seed': d.get('seed'), 'hash': d.get('run_hash'),
            'elites_a1': sum(1 for p in pts if p['act'] == 1 and p['type'] == 'elite'),
            'elites_a2': sum(1 for p in pts if p['act'] == 2 and p['type'] == 'elite')}


def load_all():
    """全部对局（list）。设置环境变量 CORE_CACHE=某个文件路径 时，第一次解析后存成 pickle，之后直接读（机器忙时解析要 2 分多钟）"""
    import pickle
    cache = os.environ.get('CORE_CACHE')
    if cache and os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(SRC) and os.path.getmtime(cache) > os.path.getmtime(__file__):
        with open(cache, 'rb') as f: return pickle.load(f)
    runs = list(load_runs())
    if cache:
        with open(cache, 'wb') as f: pickle.dump(runs, f, protocol=pickle.HIGHEST_PROTOCOL)
    return runs


def wr(xs):
    xs = list(xs)
    return (sum(xs) / len(xs) if xs else float('nan')), len(xs)


def fmt_wr(xs):
    p, n = wr(xs)
    return f'{p:.0%}（{n}）' if n else '—（0）'


if __name__ == '__main__':
    import time
    t = time.time(); n = 0; c = collections.Counter()
    for r in load_runs():
        n += 1; c['c1'] += r['c1'] is not None; c['c2'] += r['c2'] is not None; c['win'] += r['win']
    print(n, dict(c), f'{time.time() - t:.1f}s')
