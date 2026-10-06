#!/usr/bin/env python3
"""联动计分表 kb/combos.json 的校验 + 社区数据统计。

用法（在任何目录都能跑，路径写死在下面）：
    python3 check_combos.py                 # 只校验：id 是否真实存在、字段是否齐全、取值范围、有没有单人拿不到的牌
    python3 check_combos.py --stats         # 校验 + 用社区对局算每条联动 / 核心的数据（单进程，约 1~3 分钟）
    python3 check_combos.py --stats --json out.json   # 同上，并把统计结果写成 json（给人工核对分数用）
    python3 check_combos.py --deck BURNING_PACT FEEL_NO_PAIN ... [--relics X ...] [--potions Y ...]
                                            # 给一副牌（可以只写关键牌）看哪些联动凑齐 / 差一张、各得几分

校验失败时退出码为 1。

匹配规则（程序实现时照这个来，和 combos.json 的 _说明 一致）：
  - need_all 每张都要有；need_one 里至少有一张（空表示不要求）；
  - req_relics 非空时至少持有其中一件遗物；req_potions 非空时至少持有其中一瓶药水；
  - need_any 按「张数」计（同名多张都算），relics_any / potions_any 每持有一件算一张；计数 ≥ min_any 才够；
  - 全部满足 = 凑齐，得 points + per_extra × min(max_extra, 计数 − min_any)；
  - 遗物 / 药水条件都满足、牌只差一张（need_all 缺一张，或 need_one 没有，或 need_any 差一张），
    并且「关键件」已经在手（need_all / need_one 里至少有一张在牌组里；靠遗物 / 药水起头的条目视为已有）= 差一张，得 partial。
    只有燃料、没有引擎 / 终端时不给 partial（例：牌组里有力量来源但没有焚烧，不算「焚烧 + 力量」差一张）；
    差的是遗物或药水时也不给（遗物、药水不能像牌一样去拿）；
  - anti 里的牌在牌组里、或 anti 里的遗物持有时，得分 × anti.mult。
社区统计只看牌和遗物（社区记录里看不到某一刻手上有哪些药水）；要药水的联动改用「用了这瓶药水的那场精英 / Boss 战，
比同一遭遇的平均多掉 / 少掉多少血」，按牌组凑没凑齐分两组比较。
"""
import argparse, collections, gzip, json, math, os, sys

ROOT = '/opt/slay-the-spire-2'
COMBOS = f'{ROOT}/agent/kb/combos.json'
KB = f'{ROOT}/agent/kb'
CODEX = f'{ROOT}/sources/spire-codex/data-beta/v0.111.0/zhs'
RUNS = f'{ROOT}/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'

LINES = ['消耗线', '自伤线', '格挡线', '力量多段线', '易伤线', '打击线', '出牌数线', '能力牌线', '能量线', '药水×牌']
GIVES = {'aoe', 'single', 'scaling', 'block', 'draw', 'energy', 'sustain'}
VS = {'multi', 'single', 'all'}
# 单人模式拿不到的多人专属牌（16 号文档「通用规则」、源码 Factories/CardFactory.cs:25-32）
MULTIPLAYER_ONLY = {'MIDNIGHT', 'BLAZE', 'DEMONIC_SHIELD', 'TANK', 'OUTRAGE', 'KNOCKDOWN', 'COORDINATE', 'TAG_TEAM',
                    'BEACON_OF_HOPE', 'LIFT', 'HUDDLE_UP', 'MIMIC', 'INTERCEPT', 'BELIEVE_IN_YOU', 'GANG_UP', 'RALLY',
                    'THE_BALL'}
CARD_COLORS_OK = {'ironclad', 'colorless', 'event', 'token', 'curse', 'status'}
RELIC_POOLS_OK = {'shared', 'ironclad'}
POTION_POOLS_OK = {'shared', 'ironclad', 'event'}

COMBO_FIELDS = {  # 字段: (类型, 必填)
    'id': (str, True), 'zh': (str, True), 'line': (str, True),
    'need_all': (list, True), 'need_one': (list, False), 'need_any': (list, True), 'min_any': (int, True),
    'relics_any': (list, True), 'potions_any': (list, True), 'req_relics': (list, False), 'req_potions': (list, False),
    'per_extra': (int, False), 'max_extra': (int, False), 'anti': (dict, False),
    'gives': (list, True), 'vs': (str, True), 'points': (int, True), 'partial': (int, True),
    'source': (str, True), 'note': (str, False), 'data': (dict, False),
}
CORE_FIELDS = {
    'id': (str, True), 'zh': (str, True), 'cards': (list, True), 'min_cards': (int, True),
    'companions': (list, True), 'min_companions': (int, True), 'count_mode': (str, True),
    'relic_companions': (list, False), 'requires_cores': (list, False),
    'points': (int, True), 'source': (str, True), 'note': (str, False), 'data': (dict, False),
}


# ---------------------------------------------------------------- 数据表
def load_ids():
    cards, relics, potions = {}, {}, {}
    for c in json.load(open(f'{CODEX}/cards.json')):
        cards[c['id']] = {'name': c['name'], 'color': c.get('color')}
    for k, v in json.load(open(f'{KB}/cards.json')).items():
        cards.setdefault(k, {'name': v.get('name'), 'color': v.get('color')})
    for r in json.load(open(f'{CODEX}/relics.json')):
        relics[r['id']] = {'name': r['name'], 'pool': r.get('pool')}
    for k, v in json.load(open(f'{KB}/relics.json')).items():
        relics.setdefault(k, {'name': v.get('name'), 'pool': v.get('pool')})
    for p in json.load(open(f'{CODEX}/potions.json')):
        potions[p['id']] = {'name': p['name'], 'pool': p.get('pool')}
    for k, v in json.load(open(f'{KB}/potions.json')).items():
        potions.setdefault(k, {'name': v.get('name'), 'pool': None})
    return cards, relics, potions


# ---------------------------------------------------------------- 校验
def validate(db, cards, relics, potions):
    errs, warns = [], []

    def chk_card(x, where):
        if x not in cards:
            errs.append(f'{where}: 牌 id 不存在 {x}')
        else:
            if x in MULTIPLAYER_ONLY:
                errs.append(f'{where}: {x}（{cards[x]["name"]}）是多人专属牌，单人拿不到')
            col = cards[x]['color']
            if col not in CARD_COLORS_OK:
                errs.append(f'{where}: {x}（{cards[x]["name"]}）是其他角色的牌（{col}）')

    def chk_relic(x, where):
        if x not in relics:
            errs.append(f'{where}: 遗物 id 不存在 {x}')
        elif relics[x]['pool'] not in RELIC_POOLS_OK:
            errs.append(f'{where}: 遗物 {x}（{relics[x]["name"]}）不是铁甲能拿到的（pool={relics[x]["pool"]}）')

    def chk_potion(x, where):
        if x not in potions:
            errs.append(f'{where}: 药水 id 不存在 {x}')
        elif potions[x]['pool'] not in POTION_POOLS_OK and potions[x]['pool'] is not None:
            errs.append(f'{where}: 药水 {x}（{potions[x]["name"]}）不是铁甲能拿到的（pool={potions[x]["pool"]}）')

    def chk_fields(obj, spec, where):
        for f, (t, req) in spec.items():
            if f not in obj:
                if req:
                    errs.append(f'{where}: 缺字段 {f}')
                continue
            if not isinstance(obj[f], t) or (t is int and isinstance(obj[f], bool)):
                errs.append(f'{where}: 字段 {f} 类型应为 {t.__name__}，实际 {type(obj[f]).__name__}')
        for f in obj:
            if f not in spec:
                errs.append(f'{where}: 多余字段 {f}（拼错了？）')

    for top in ('_说明', 'combos', 'cores', 'card_tier', 'relic_tier', 'potion_tier'):
        if top not in db:
            errs.append(f'缺顶层字段 {top}')
    seen = set()
    for i, c in enumerate(db.get('combos', [])):
        w = f'combos[{i}] {c.get("id", "?")}'
        chk_fields(c, COMBO_FIELDS, w)
        if c.get('id') in seen:
            errs.append(f'{w}: id 重复')
        seen.add(c.get('id'))
        if c.get('line') not in LINES:
            errs.append(f'{w}: line 不在 {LINES}')
        for g in c.get('gives', []):
            if g not in GIVES:
                errs.append(f'{w}: gives 里的 {g} 不在 {sorted(GIVES)}')
        if not c.get('gives'):
            errs.append(f'{w}: gives 为空')
        if c.get('vs') not in VS:
            errs.append(f'{w}: vs 应为 {sorted(VS)}')
        p, pa = c.get('points', -1), c.get('partial', -1)
        if not (0 <= p <= 10):
            errs.append(f'{w}: points 超出 0~10')
        if not (0 <= pa <= p):
            errs.append(f'{w}: partial 应在 0~points 之间')
        if c.get('min_any', 0) < 0:
            errs.append(f'{w}: min_any < 0')
        for k in ('need_all', 'need_one', 'need_any'):
            for x in c.get(k, []):
                chk_card(x, f'{w}.{k}')
            if len(set(c.get(k, []))) != len(c.get(k, [])):
                errs.append(f'{w}: {k} 里有重复 id')
        for x in c.get('relics_any', []) + c.get('req_relics', []):
            chk_relic(x, w)
        for x in c.get('potions_any', []) + c.get('req_potions', []):
            chk_potion(x, w)
        ov = set(c.get('need_all', [])) & (set(c.get('need_any', [])) | set(c.get('need_one', [])))
        if ov:
            errs.append(f'{w}: need_all 和 need_any/need_one 重复了 {sorted(ov)}（同一张牌会被算两次）')
        ov = set(c.get('relics_any', [])) & set(c.get('req_relics', []))
        if ov:
            errs.append(f'{w}: relics_any 和 req_relics 重复 {sorted(ov)}')
        if c.get('min_any', 0) > 0 and not (c.get('need_any') or c.get('relics_any') or c.get('potions_any')):
            errs.append(f'{w}: min_any>0 但没有可计数的东西')
        if not (c.get('need_all') or c.get('need_one') or c.get('req_relics') or c.get('req_potions')):
            errs.append(f'{w}: 没有任何「必须有」的条件（need_all / need_one / req_relics / req_potions 至少一个）')
        if ('per_extra' in c) != ('max_extra' in c):
            errs.append(f'{w}: per_extra 和 max_extra 要成对出现')
        if c.get('per_extra', 0) * c.get('max_extra', 0) + p > 10:
            errs.append(f'{w}: points + per_extra×max_extra 超过 10')
        a = c.get('anti')
        if a is not None:
            for x in a.get('cards', []):
                chk_card(x, f'{w}.anti')
            for x in a.get('relics', []):
                chk_relic(x, f'{w}.anti')
            if not isinstance(a.get('mult'), (int, float)) or not (0 <= a['mult'] < 1):
                errs.append(f'{w}: anti.mult 应在 [0,1)')
            if not a.get('why'):
                errs.append(f'{w}: anti 要写 why')
        if not c.get('source'):
            errs.append(f'{w}: source 为空')
    core_ids = set()
    for i, c in enumerate(db.get('cores', [])):
        w = f'cores[{i}] {c.get("id", "?")}'
        chk_fields(c, CORE_FIELDS, w)
        core_ids.add(c.get('id'))
        for x in c.get('cards', []) + c.get('companions', []):
            chk_card(x, w)
        for x in c.get('relic_companions', []):
            chk_relic(x, w)
        if c.get('count_mode') not in ('kinds', 'copies'):
            errs.append(f'{w}: count_mode 应为 kinds / copies')
        if not (0 <= c.get('points', -1) <= 10):
            errs.append(f'{w}: points 超出 0~10')
    for i, c in enumerate(db.get('cores', [])):
        for r in c.get('requires_cores', []):
            if r not in core_ids:
                errs.append(f'cores[{i}]: requires_cores 引用了不存在的核心 {r}')
    for k, v in db.get('card_tier', {}).items():
        chk_card(k, 'card_tier')
        if not isinstance(v, int) or not 0 <= v <= 5:
            errs.append(f'card_tier.{k}: 分数应为 0~5 的整数')
    for k, v in db.get('upgrade_bonus', {}).items():
        chk_card(k, 'upgrade_bonus')
        if not isinstance(v, int) or not 0 <= v <= 2:
            errs.append(f'upgrade_bonus.{k}: 分数应为 0~2 的整数')
    for k, v in db.get('relic_tier', {}).items():
        chk_relic(k, 'relic_tier')
        if not isinstance(v, int) or not 0 <= v <= 5:
            errs.append(f'relic_tier.{k}: 分数应为 0~5 的整数')
    for k, v in db.get('potion_tier', {}).items():
        chk_potion(k, 'potion_tier')
        if not isinstance(v, int) or not 0 <= v <= 3:
            errs.append(f'potion_tier.{k}: 分数应为 0~3 的整数')
    lc = db.get('scoring', {}).get('line_caps', {})
    for k in lc:
        if k not in LINES:
            errs.append(f'scoring.line_caps: 未知的线 {k}')
    for k in LINES:
        if not any(c.get('line') == k for c in db.get('combos', [])):
            warns.append(f'线 {k} 没有任何联动')
    # 覆盖：铁甲能拿到的遗物 / 药水都应有分数（没有的会被程序当成 0，给个提醒）
    miss_r = [r for r, v in relics.items() if v['pool'] in RELIC_POOLS_OK and r not in db.get('relic_tier', {})]
    miss_p = [p for p, v in potions.items() if v['pool'] in POTION_POOLS_OK and p not in db.get('potion_tier', {})]
    if miss_r:
        warns.append(f'relic_tier 没写的遗物 {len(miss_r)} 件（按 0 分）：{", ".join(sorted(miss_r))}')
    if miss_p:
        warns.append(f'potion_tier 没写的药水 {len(miss_p)} 瓶（按 0 分）：{", ".join(sorted(miss_p))}')
    return errs, warns


# ---------------------------------------------------------------- 匹配（程序照这个实现）
def match_combo(c, deck, relics=frozenset(), potions=frozenset(), use_potions=True):
    """返回 (状态, 分数, 计数)。状态：'full' 凑齐 / 'partial' 差一张 / None。deck 是 Counter（牌 id → 张数）"""
    miss_cards = sum(1 for x in c['need_all'] if deck.get(x, 0) <= 0)
    if c.get('need_one') and not any(deck.get(x, 0) > 0 for x in c['need_one']):
        miss_cards += 1
    n = sum(deck.get(x, 0) for x in c['need_any']) + sum(1 for r in c['relics_any'] if r in relics)
    if use_potions:
        n += sum(1 for p in c['potions_any'] if p in potions)
    miss_cards += max(0, c['min_any'] - n)
    miss_other = 0
    if c.get('req_relics') and not any(r in relics for r in c['req_relics']):
        miss_other += 1
    if c.get('req_potions') and not any(p in potions for p in c['req_potions']):
        miss_other += 1
    if miss_other:
        return None, 0, n
    # 「关键件」：need_all / need_one 里至少有一张已经在牌组里，或者这条本来就靠遗物 / 药水起头（req_relics / req_potions 已满足）
    has_key = (any(deck.get(x, 0) > 0 for x in c['need_all'] + c.get('need_one', []))
               or bool(c.get('req_relics') or c.get('req_potions')))
    if miss_cards == 0:
        st, pts = 'full', c['points'] + c.get('per_extra', 0) * min(c.get('max_extra', 0), n - c['min_any'])
    elif miss_cards == 1 and has_key:
        st, pts = 'partial', c['partial']
    else:
        return None, 0, n
    a = c.get('anti')
    if a and (any(deck.get(x, 0) > 0 for x in a.get('cards', [])) or any(r in relics for r in a.get('relics', []))):
        pts = pts * a['mult']
    return st, pts, n


def match_core(core, deck, relics=frozenset()):
    k = sum(1 for x in core['cards'] if deck.get(x, 0) > 0)
    if k < core['min_cards']:
        return False
    if core['count_mode'] == 'copies':
        m = sum(deck.get(x, 0) for x in core['companions'])
    else:
        m = sum(1 for x in core['companions'] if deck.get(x, 0) > 0)
    m += sum(1 for r in core.get('relic_companions', []) if r in relics)
    # 同一张牌不能既当核心又当伴随：伴随里如果有核心牌，而它是唯一的核心牌，就不算它
    own = [x for x in core['cards'] if deck.get(x, 0) > 0]
    if len(own) == core['min_cards']:
        for x in own:
            if x in core['companions']:
                m -= deck.get(x, 0) if core['count_mode'] == 'copies' else 1
    return m >= core['min_companions']


def score_deck(db, deck, relics=frozenset(), potions=frozenset()):
    """按 scoring 里的建议聚合一副牌的构筑分（只是参考实现）。deck 的 id 可以带 '+'，匹配联动时去掉"""
    sc = db.get('scoring', {})
    plain = collections.Counter()
    for x, k in deck.items():
        plain[x.rstrip('+')] += k
    full_deck, deck = deck, plain
    caps = sc.get('line_caps', {})
    per_line = collections.defaultdict(float)
    hits = []
    for c in db['combos']:
        st, pts, n = match_combo(c, deck, relics, potions)
        if st:
            per_line[c['line']] += pts
            hits.append((c, st, pts))
    combo = sum(min(v, caps.get(k, 99)) for k, v in per_line.items())
    combo = min(combo, sc.get('combo_cap', 99))
    cores = {c['id']: c for c in db['cores']}
    ok = [c for c in db['cores'] if not c.get('requires_cores') and match_core(c, deck, relics)]
    ok_ids = {c['id'] for c in ok}
    extra = [c for c in db['cores'] if c.get('requires_cores') and all(r in ok_ids for r in c['requires_cores'])]
    pts = sorted((c['points'] for c in ok), reverse=True)
    core = (pts[0] if pts else 0) + (pts[1] / 2 if len(pts) > 1 else 0) + sum(c['points'] for c in extra)
    core = min(core, sc.get('core_cap', 99))
    ub = db.get('upgrade_bonus', {})
    # deck 里的 id 可以带 '+'（升级过），升级过的加 upgrade_bonus
    tiers = sorted((db['card_tier'].get(x.rstrip('+'), 0) + (ub.get(x.rstrip('+'), 0) if x.endswith('+') else 0)
                    for x, k in full_deck.items() for _ in range(k)), reverse=True)
    card = min(sum(tiers[:sc.get('card_top_n', 8)]) * sc.get('card_weight', 1), sc.get('card_cap', 99))
    relic = min(sum(db['relic_tier'].get(r, 0) for r in relics) * sc.get('relic_weight', 1), sc.get('relic_cap', 99))
    potion = min(sum(db['potion_tier'].get(p, 0) for p in potions) * sc.get('potion_weight', 1), sc.get('potion_cap', 99))
    total = min((combo + core + card + relic + potion) * sc.get('total_scale', 1), sc.get('total_cap', 99))
    return {'合计': round(total, 1), '联动': round(combo, 1), '核心': core, '强力牌': card, '遗物': relic, '药水': potion,
            '核心成型': [c['zh'] for c in ok + extra], 'hits': hits, 'per_line': dict(per_line)}


# ---------------------------------------------------------------- 社区数据
def cid(x):
    return (x.get('id') if isinstance(x, dict) else str(x)).replace('CARD.', '')


def runs_iter():
    with gzip.open(RUNS, 'rt') as f:
        for line in f:
            d = json.loads(line)
            if d.get('modifiers') or d.get('was_abandoned'):
                continue
            yield d


def parse_run(d):
    """返回 (win, c1, c2, uses)。c1 = 进第二幕第一个节点时、c2 = 进第二幕 Boss 时的 (deck Counter, relic set)；
    uses = [(enc, type, dmg, potions_used, deck, relics)]（精英 / Boss 节点里用了药水的）"""
    deck = collections.Counter({'STRIKE_IRONCLAD': 5, 'DEFEND_IRONCLAD': 4, 'BASH': 1, 'ASCENDERS_BANE': 1})
    rel = [(r.get('floor_added_to_deck', 0), r['id'].replace('RELIC.', '')) for r in d['players'][0].get('relics') or []]
    c1 = c2 = None
    uses, fights = [], []
    fl = 0
    for ai, act in enumerate(d.get('map_point_history') or []):
        for pi, p in enumerate(act):
            fl += 1
            s = (p.get('player_stats') or [{}])[0]
            held = frozenset(r for f, r in rel if f < fl)
            if ai == 1 and pi == 0:
                c1 = (+deck, held)
            if ai == 1 and p.get('map_point_type') == 'boss' and c2 is None:
                c2 = (+deck, held)
            t = p.get('map_point_type')
            if t in ('elite', 'boss'):
                enc = str(((p.get('rooms') or [{}])[0]).get('model_id') or '')
                pu = [str(x).replace('POTION.', '') for x in s.get('potion_used') or []]
                fights.append((enc, s.get('damage_taken') or 0))
                if pu:
                    uses.append((enc, t, s.get('damage_taken') or 0, pu, +deck, held))
            for c in s.get('cards_gained') or []:
                deck[cid(c)] += 1
            for c in s.get('cards_removed') or []:
                if deck[cid(c)] > 0:
                    deck[cid(c)] -= 1
            for tr in s.get('cards_transformed') or []:
                o, f2 = cid(tr.get('original_card', {})), cid(tr.get('final_card', {}))
                if deck[o] > 0:
                    deck[o] -= 1
                deck[f2] += 1
    return bool(d.get('win')), c1, c2, uses, fights


def stats(db):
    combos = db['combos']
    cores = db['cores']
    deck_combos = [c for c in combos if not c.get('req_potions')]
    pot_combos = [c for c in combos if c.get('req_potions')]
    agg = {k: collections.defaultdict(lambda: [0, 0, 0, 0]) for k in ('c1', 'c2')}  # id -> [有且赢, 有, 没有且赢, 没有]
    base = {'c1': [0, 0], 'c2': [0, 0]}
    enc_dmg = collections.defaultdict(list)
    all_uses = []
    n_runs = 0
    for d in runs_iter():
        n_runs += 1
        win, c1, c2, uses, fights = parse_run(d)
        for enc, dmg in fights:
            enc_dmg[enc].append(dmg)
        all_uses += uses
        for key, cp in (('c1', c1), ('c2', c2)):
            if cp is None:
                continue
            deck, held = cp
            base[key][0] += win
            base[key][1] += 1
            for c in deck_combos:
                st, _, _ = match_combo(c, deck, held, use_potions=False)
                a = agg[key][c['id']]
                if st == 'full':
                    a[0] += win; a[1] += 1
                else:
                    a[2] += win; a[3] += 1
            ok = {co['id'] for co in cores if not co.get('requires_cores') and match_core(co, deck, held)}
            for co in cores:
                full = (all(r in ok for r in co['requires_cores']) if co.get('requires_cores') else co['id'] in ok)
                a = agg[key]['core:' + co['id']]
                if full:
                    a[0] += win; a[1] += 1
                else:
                    a[2] += win; a[3] += 1
    out = {'runs': n_runs, 'base': {k: {'n': v[1], 'wr': round(v[0] / v[1], 3) if v[1] else None} for k, v in base.items()},
           'combos': {}, 'cores': {}, 'potions': {}}
    for key in ('c1', 'c2'):
        W, N = base[key]
        L = N - W
        for cid_, (hw, hn, nw, nn) in agg[key].items():
            rec = {'n': hn, 'wr': round(hw / hn, 3) if hn else None, 'wr_without': round(nw / nn, 3) if nn else None,
                   'win_share': round(hw / W, 3) if W else None, 'lose_share': round((hn - hw) / L, 3) if L else None}
            tgt = out['cores'] if cid_.startswith('core:') else out['combos']
            tgt.setdefault(cid_.replace('core:', ''), {})[key] = rec
    enc_mean = {e: sum(v) / len(v) for e, v in enc_dmg.items() if v}
    for c in pot_combos:
        w, wo = [], []
        for enc, t, dmg, pu, deck, held in all_uses:
            if not any(p in pu for p in c['req_potions']):
                continue
            st, _, _ = match_combo(c, deck, held, potions=frozenset(pu))
            (w if st == 'full' else wo).append(dmg - enc_mean.get(enc, dmg))
        out['potions'][c['id']] = {'uses_with': len(w), 'd_dmg_with': round(sum(w) / len(w), 1) if w else None,
                                   'uses_without': len(wo), 'd_dmg_without': round(sum(wo) / len(wo), 1) if wo else None}
    return out


def fmt_rec(r):
    if not r or not r.get('n'):
        return '—'
    return (f"{r['n']:>5} 局 {r['wr']:.0%} vs 没有 {r['wr_without']:.0%}（{(r['wr'] - r['wr_without']) * 100:+.0f}）"
            f" 赢家 {r['win_share']:.1%} / 输家 {r['lose_share']:.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--json')
    ap.add_argument('--deck', nargs='*')
    ap.add_argument('--relics', nargs='*', default=[])
    ap.add_argument('--potions', nargs='*', default=[])
    ap.add_argument('--file', default=COMBOS)
    a = ap.parse_args()
    db = json.load(open(a.file))
    cards, relics, potions = load_ids()
    errs, warns = validate(db, cards, relics, potions)
    lines = collections.Counter(c['line'] for c in db['combos'])
    print(f'联动 {len(db["combos"])} 条，{len(lines)} 条线：' + '、'.join(f'{k} {lines[k]}' for k in LINES if lines[k]))
    print(f'核心 {len(db["cores"])} 个；单卡分 {len(db["card_tier"])} 张；遗物分 {len(db["relic_tier"])} 件；药水分 {len(db["potion_tier"])} 瓶')
    for w in warns:
        print('提醒：' + w)
    if errs:
        print(f'\n校验失败，{len(errs)} 处：')
        for e in errs:
            print('  ✗ ' + e)
        sys.exit(1)
    print('校验通过：所有 id 都真实存在、都是单人铁甲能拿到的，字段齐全，取值在范围内。')

    if a.deck is not None:
        deck = collections.Counter(a.deck)
        r = score_deck(db, deck, frozenset(a.relics), frozenset(a.potions))
        for c, st, p in sorted(r['hits'], key=lambda x: -x[2]):
            print(f"  {'凑齐' if st == 'full' else '差一张'} {p:>4.1f}  [{c['line']}] {c['zh']}")
        print('（上面是每条的原始分；下面的合计按 scoring 的封顶和权重聚合）')
        print({k: v for k, v in r.items() if k != 'hits'})

    if a.stats:
        print('\n读社区对局（单进程）……')
        s = stats(db)
        print(f"对局 {s['runs']}；第一幕结束 {s['base']['c1']}；进第二幕 Boss {s['base']['c2']}")
        print('\n== 联动（进第二幕 Boss 时凑齐 vs 没凑齐，最终胜率）')
        for c in db['combos']:
            if c.get('req_potions'):
                continue
            print(f"{c['id']:<28} {fmt_rec(s['combos'].get(c['id'], {}).get('c2'))}")
        print('\n== 药水联动（用这瓶药水的精英 / Boss 战，比同遭遇平均多掉的血；负数 = 少掉）')
        for k, v in s['potions'].items():
            print(f'{k:<28} 凑齐 {v["uses_with"]} 次 {v["d_dmg_with"]}；没凑齐 {v["uses_without"]} 次 {v["d_dmg_without"]}')
        print('\n== 核心')
        for c in db['cores']:
            print(f"{c['id']:<20} c2 {fmt_rec(s['cores'].get(c['id'], {}).get('c2'))}")
            print(f"{'':<20} c1 {fmt_rec(s['cores'].get(c['id'], {}).get('c1'))}")
        if a.json:
            json.dump(s, open(a.json, 'w'), ensure_ascii=False, indent=1)
            print('统计写到', a.json)


if __name__ == '__main__':
    main()
