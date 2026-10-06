"""联动计分。

数据：kb/combos.json（研究代理按 ironclad/15~17 号 + 社区数据整理：105 条联动 / 10 条线、7 个输出核心、强力牌 / 遗物 / 药水单件分），
给人看的版本：docs/联动计分表.md。匹配和合分照搬 docs/scripts/check_combos.py 的 match_combo / match_core / score_deck
（表里有 need_one、req_relics、req_potions、per_extra、anti、核心的 min_cards / count_mode / requires_cores，不能用简单的「差几张」算）。

用途：
  score(st)            → 准备度里的联动分（合计封顶 scoring.total_cap = 20，再乘 combo_scale），以及凑齐 / 差一张的联动
  aoe_extra(st)        → 凑齐的群伤联动（给 elites.aoe_capacity 加）
  pick_bonus(card, st) → 选牌：拿这张后联动分涨多少（logit 单位，combo_pick_w × 涨的分 / 10）
"""
import collections, json, os
from params import P
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kb', 'combos.json')
_D = {'mtime': None, 'data': {}}


def data():
    try:
        m = os.path.getmtime(_PATH)
    except OSError:
        return {}
    if _D['mtime'] != m:
        try:
            _D['data'] = json.load(open(_PATH)); _D['mtime'] = m
        except Exception:
            _D['data'] = {}
    return _D['data']


def _state(st, extra_card=None):
    pl = st.get('player') or {}
    deck = collections.Counter(str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '') for c in pl.get('deck') or [])
    if extra_card: deck[extra_card] += 1
    relics = frozenset(str(r.get('id') or '').replace('RELIC.', '') for r in pl.get('relics') or [])
    from policy import kb
    pots = frozenset(str(p.get('id') or kb.id_by_name('potions', p.get('name')) or '').replace('POTION.', '')
                     for p in pl.get('potions') or [] if p and p.get('name'))
    return deck, relics, pots


def match_combo(c, deck, relics=frozenset(), potions=frozenset(), use_potions=True):
    """(状态, 分数)。状态 'full' 凑齐 / 'partial' 差一张 / None。deck：去掉 '+' 的 Counter"""
    miss = sum(1 for x in c.get('need_all') or [] if deck.get(x, 0) <= 0)
    if c.get('need_one') and not any(deck.get(x, 0) > 0 for x in c['need_one']): miss += 1
    n = sum(deck.get(x, 0) for x in c.get('need_any') or []) + sum(1 for r in c.get('relics_any') or [] if r in relics)
    if use_potions: n += sum(1 for p in c.get('potions_any') or [] if p in potions)
    miss += max(0, (c.get('min_any') or 0) - n)
    if c.get('req_relics') and not any(r in relics for r in c['req_relics']): return None, 0
    if c.get('req_potions') and not any(p in potions for p in c['req_potions']): return None, 0
    has_key = any(deck.get(x, 0) > 0 for x in (c.get('need_all') or []) + (c.get('need_one') or [])) or bool(c.get('req_relics') or c.get('req_potions'))
    if miss == 0:
        st, pts = 'full', c['points'] + c.get('per_extra', 0) * min(c.get('max_extra', 0), max(0, n - (c.get('min_any') or 0)))
    elif miss == 1 and has_key:
        st, pts = 'partial', c.get('partial', 0)
    else:
        return None, 0
    a = c.get('anti')
    if a and (any(deck.get(x, 0) > 0 for x in a.get('cards', [])) or any(r in relics for r in a.get('relics', []))):
        pts *= a['mult']
    return st, pts


def match_core(core, deck, relics=frozenset()):
    k = sum(1 for x in core['cards'] if deck.get(x, 0) > 0)
    if k < core.get('min_cards', 1): return False
    if core.get('count_mode') == 'copies': m = sum(deck.get(x, 0) for x in core.get('companions') or [])
    else: m = sum(1 for x in core.get('companions') or [] if deck.get(x, 0) > 0)
    m += sum(1 for r in core.get('relic_companions', []) if r in relics)
    own = [x for x in core['cards'] if deck.get(x, 0) > 0]
    if len(own) == core.get('min_cards', 1):
        for x in own:
            if x in (core.get('companions') or []): m -= deck.get(x, 0) if core.get('count_mode') == 'copies' else 1
    return m >= core.get('min_companions', 0)


def score_deck(D, full_deck, relics, potions):
    sc = D.get('scoring', {})
    deck = collections.Counter()
    for x, k in full_deck.items(): deck[x.rstrip('+')] += k
    caps = sc.get('line_caps', {}); per_line = collections.defaultdict(float); hits = []
    for c in D.get('combos') or []:
        st, pts = match_combo(c, deck, relics, potions)
        if st: per_line[c.get('line')] += pts; hits.append((c, st, pts))
    combo = min(sum(min(v, caps.get(k, 99)) for k, v in per_line.items()), sc.get('combo_cap', 99))
    ok = [c for c in D.get('cores') or [] if not c.get('requires_cores') and match_core(c, deck, relics)]
    ok_ids = {c['id'] for c in ok}
    extra = [c for c in D.get('cores') or [] if c.get('requires_cores') and all(r in ok_ids for r in c['requires_cores'])]
    cp = sorted((c['points'] for c in ok), reverse=True)
    core = min((cp[0] if cp else 0) + (cp[1] / 2 if len(cp) > 1 else 0) + sum(c['points'] for c in extra), sc.get('core_cap', 99))
    ub = D.get('upgrade_bonus', {})
    tiers = sorted((D.get('card_tier', {}).get(x.rstrip('+'), 0) + (ub.get(x.rstrip('+'), 0) if x.endswith('+') else 0)
                    for x, k in full_deck.items() for _ in range(k)), reverse=True)
    card = min(sum(tiers[:sc.get('card_top_n', 8)]) * sc.get('card_weight', 1), sc.get('card_cap', 99))
    relic = min(sum(D.get('relic_tier', {}).get(r, 0) for r in relics) * sc.get('relic_weight', 1), sc.get('relic_cap', 99))
    potion = min(sum(D.get('potion_tier', {}).get(p, 0) for p in potions) * sc.get('potion_weight', 1), sc.get('potion_cap', 99))
    total = min((combo + core + card + relic + potion) * sc.get('total_scale', 1), sc.get('total_cap', 99))
    return total, hits, ok + extra


def score(st):
    """返回 (分数, 凑齐的联动和核心, 差一张的联动)"""
    D = data()
    if not D: return 0.0, [], []
    deck, relics, pots = _state(st)
    total, hits, cores = score_deck(D, deck, relics, pots)
    full = [c for c, s, _ in hits if s == 'full'] + cores
    near = [c for c, s, _ in hits if s == 'partial']
    return total * P.get('combo_scale', 1.0), full, near


def aoe_extra(st):
    D = data()
    if not D: return 0.0
    deck, relics, pots = _state(st)
    plain = collections.Counter()
    for x, k in deck.items(): plain[x.rstrip('+')] += k
    return sum(0.5 for c in D.get('combos') or [] if 'aoe' in (c.get('gives') or []) and match_combo(c, plain, relics, pots)[0] == 'full')


def pick_bonus(card_id, st):
    """选牌：拿这张后联动分（未封顶前的合计 × total_scale）涨了多少 → logit"""
    w = P.get('combo_pick_w', 0.0)
    D = data()
    if not w or not D: return 0.0
    deck, relics, pots = _state(st)
    t0 = score_deck(D, deck, relics, pots)[0]
    deck[card_id] += 1
    t1 = score_deck(D, deck, relics, pots)[0]
    return w * (t1 - t0) / 10
