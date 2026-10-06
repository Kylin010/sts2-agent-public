"""商店：在预算内挑「总价值最高」的买法（每次调用返回一个动作，买完一样再重新算）。

每样东西都按「当前牌组」折算成「值多少血」（params 里 shop_*），删牌不是固定先做的：
  牌：选牌模型「在这副牌里拿它比跳过好多少」（联动、重复、高手会不会拿）× shop_card_unit
  删牌：同一个模型反过来问——把这张牌从牌组拿掉后，模型有多不想把它加回来（越不想要，删它越值）；
        挑最该删的那张。诅咒（模型里没有）按 shop_remove_curse_logit 算；牌组还薄时打击也有用，删它就不值钱
  遗物：遗物模型（policy/relicmodel.py，学自社区商店的买 / 不买，带遗物和牌组的配合）
        价值 = shop_relic_base + shop_relic_unit × (logit − 平均水平)；模型没见过的遗物用胜率提升（relic_stats）兜底
  药水：有空栏位才买
  留着的金币：每金币也值 shop_v_gold 血（战未来：后面还有商店、精英后的商店、事件要钱）
枚举所有组合（东西不多，2^n 很快），选「价值 − 花掉的金币 × 金币价值」最高的，按 删牌 → 遗物 → 牌 → 药水 的顺序执行第一步。
注意：商店里的牌和遗物只有英文名没有 id，用 kb/names_en.json 对回 id。
"""
import itertools, json, os
from params import P
from policy.knowledge import cid, is_bad
from policy import rewards, kb, pickmodel, relicmodel, valuemodel

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    RELIC = json.load(open(f'{HERE}/data/relic_stats.json'))
except Exception:
    RELIC = {}

SLOT_RELICS = {'POTION_BELT': 2, 'PHIAL_HOLSTER': 1, 'ALCHEMICAL_COFFER': 4}     # 加药水栏的遗物（源码 PotionSlots）


def remaining_card_budget(done):
    """The existing visit ledger includes cards already selected for purchase.

    Successful normal purchases remain in it until leave_room clears the visit.
    This uses no future inventory or native transport and leaves other kinds
    of purchases outside the card limit.
    """
    if not P.get('shop_visit_card_cap', False):
        return P.get('shop_max_cards', 9)
    cap = max(0, int(P.get('shop_max_cards', 9)))
    return max(0, cap - sum(kind == 'card' for kind, _ in done))


def free_potion_slots(pl):
    """还有几个空药水栏。10/3 修：原来数 potions 列表里的空项，可引擎导出用的 Player.Potions 会把空栏滤掉，
    结果永远是 0——第八代 360 局商店一瓶药水都没买过。补丁 13 起引擎导出 potion_slots；旧引擎按 A10「紧腰带」2 栏 + 遗物推算"""
    have = sum(1 for p in pl.get('potions') or [] if p and p.get('name'))
    slots = pl.get('potion_slots')
    if slots is None:
        rel = {str(r.get('id') or '').replace('RELIC.', '') for r in pl.get('relics') or []}
        slots = 2 + sum(v for k, v in SLOT_RELICS.items() if k in rel)
    return max(0, slots - have)


def relic_value(r, deck_ids, act):
    i = r.get('id') or kb.id_by_name('relics', r.get('name')) or ''
    z = relicmodel.logit(i, deck_ids, act)
    if z is not None:
        return P['shop_relic_base'] + P['shop_relic_unit'] * (z - P['shop_relic_logit_ref'])
    s = RELIC.get(i)
    return P['shop_relic_base'] + P['shop_relic_lift_scale'] * (s['lift'] if s else 0.0)


def remove_value(deck, act):
    """最该删的那张牌值多少血（返回 价值, 牌 id）"""
    ids = [cid(c) for c in deck]
    best, which = 0.0, None
    for c in deck:
        i = cid(c)
        if i == 'ASCENDERS_BANE' or 'Eternal' in str(c.get('keywords') or ''): continue        # 永恒牌删不掉
        if c.get('type') == 'Curse' or c.get('type') == 'Status':
            v = P['shop_remove_curse_logit']
        elif i in ('STRIKE_IRONCLAD', 'DEFEND_IRONCLAD'):          # 基础牌不会出现在奖励里，选牌模型没学过，单独定
            v = P['shop_remove_strike_logit' if i == 'STRIKE_IRONCLAD' else 'shop_remove_defend_logit'] - (0.5 if c.get('upgraded') else 0)
        elif pickmodel.available():
            rest = list(ids); rest.remove(i)
            u = pickmodel.utility(i, c.get('type'), rest, act)
            if u is None: continue
            v = pickmodel.skip_utility(rest, act) - u + (0.3 if c.get('upgraded') else 0) * -1
        else:
            v = {'STRIKE_IRONCLAD': 2.0, 'DEFEND_IRONCLAD': 1.2}.get(i, 0)
        if v > best: best, which = v, i
    return best * P['shop_card_unit'], which


def plan(st, done=()):
    pl = st.get('player') or {}; gold = pl.get('gold', 0); deck = pl.get('deck') or []
    act = (st.get('context') or {}).get('act', 1)
    items = []          # (类别, 下标, 价格, 价值)
    card_budget = remaining_card_budget(done)
    rc = st.get('card_removal_cost')
    if rc and ('remove', None) not in done:
        v, _ = remove_value(deck, act)
        if v > 0: items.append(('remove', None, rc, v))
    dids = pickmodel.with_relics([cid(c) for c in deck], st)          # 遗物也进牌组画像（遗物和遗物、遗物和牌的配合）
    for r in st.get('relics') or []:
        if r.get('is_stocked', True) and r.get('cost') is not None:
            items.append(('relic', r['index'], r['cost'], relic_value(r, dids, act)))
    for c in st.get('cards') or []:
        if c.get('is_stocked', True) and c.get('cost') is not None:
            i = c.get('id') or kb.id_by_name('cards', c.get('name'))
            if not i: continue
            v = rewards.value({**c, 'id': i}, st)
            if P.get('core_w', 0.0):                  # 商店买牌也按输出核心规则加减分
                from policy import corerules
                ctx = st.get('context') or {}
                v += P['core_w'] * corerules.bonus(i, [str(x.get('id', '')).replace('CARD.', '') for x in (st.get('player') or {}).get('deck') or []],
                                                   ctx.get('act', 1), ctx.get('floor', 0), (ctx.get('boss') or {}).get('id'))
            # 10/2：以前「比跳过好一点（>0）」就算值得买，第一幕两家店买了 5 张，牌组 29 张又散又弱；人类第一幕平均每局只从商店买约 1 张
            if v > P.get('shop_card_min', 0.0): items.append(('card', c['index'], c['cost'], v * P['shop_card_unit']))
    free = free_potion_slots(pl)
    for p in st.get('potions') or []:
        if p.get('is_stocked', True) and p.get('cost') is not None and free > 0:
            v = P['shop_v_potion']
            if P.get('potion_key_on', False):          # 能力药水 / 欧洛巴斯之酸 / 士兵炖汤打 Boss、精英非常强 → 商店里多值几倍
                from policy.potions import pid, KEY_RANK
                if pid(p) in KEY_RANK: v *= P.get('potion_key_mult', 3.0)
            items.append(('potion', p['index'], p['cost'], v))
    items = [x for x in items if x[2] <= gold]
    items.sort(key=lambda x: -x[3] / max(x[2], 1)); items = items[:11]
    card_id = {c['index']: (c.get('id') or kb.id_by_name('cards', c.get('name')), c.get('type')) for c in st.get('cards') or []}
    cache = {}

    def cards_value(idxs):
        """几张牌一起买：按顺序加进牌组，后一张在「已经加了前几张」的牌组上估值（牌组变稀，后面的就没那么值）"""
        key = tuple(sorted(idxs))
        if key in cache: return cache[key]
        if len(idxs) <= 1:
            v = sum(x[3] for x in items if x[0] == 'card' and x[1] in idxs)
        else:
            d = list(dids); v = 0.0
            for j in sorted(idxs, key=lambda j: -next(x[3] for x in items if x[0] == 'card' and x[1] == j)):
                i, t = card_id[j]
                u = pickmodel.utility(i, t, d, act) if pickmodel.available() else None
                v += (u - pickmodel.skip_utility(d, act)) * P['shop_card_unit'] if u is not None else 0
                d.append(i)
        cache[key] = v
        return v

    best, best_set = 0.0, ()
    for k in range(1, len(items) + 1):
        for comb in itertools.combinations(items, k):
            cost = sum(x[2] for x in comb)
            if cost > gold or sum(1 for x in comb if x[0] == 'potion') > free: continue
            cards = [x[1] for x in comb if x[0] == 'card']
            if len(cards) > card_budget: continue          # 本次规划只用当前进店剩余买牌预算
            v = sum(x[3] for x in comb if x[0] != 'card') + cards_value(cards) - cost * P['shop_v_gold']
            if v > best: best, best_set = v, comb
    return best_set


def plan_value(st, done=()):
    """shop_mode = value：直接用胜率模型。每种买法（买哪几样、删不删）都算出买完后的局面（金币扣掉），挑胜率最高的。
    金币是模型的特征之一，所以「钱留着值多少」不用手工定。删牌删「拿掉后胜率最高」的那张。"""
    pl = st.get('player') or {}; gold = pl.get('gold', 0); s0 = valuemodel.state_of(st)
    items = []
    card_budget = remaining_card_budget(done)
    rc = st.get('card_removal_cost')
    if rc and rc <= gold and ('remove', None) not in done:
        cands = [c for c in pl.get('deck') or [] if cid(c) != 'ASCENDERS_BANE' and 'Eternal' not in str(c.get('keywords') or '')]
        if cands:
            best_rm = max(cands, key=lambda c: valuemodel.win_prob(valuemodel.without_card(s0, c.get('id'))))
            items.append(('remove', None, rc, best_rm.get('id')))
    for r in st.get('relics') or []:
        if r.get('is_stocked', True) and r.get('cost') is not None and r['cost'] <= gold:
            items.append(('relic', r['index'], r['cost'], r.get('id') or kb.id_by_name('relics', r.get('name'))))
    for c in st.get('cards') or []:
        if c.get('is_stocked', True) and c.get('cost') is not None and c['cost'] <= gold:
            i = c.get('id') or kb.id_by_name('cards', c.get('name'))
            if i: items.append(('card', c['index'], c['cost'], i))
    free = free_potion_slots(pl)
    for p in st.get('potions') or []:
        if p.get('is_stocked', True) and p.get('cost') is not None and p['cost'] <= gold and free > 0:
            items.append(('potion', p['index'], p['cost'], None))
    items = items[:12]
    best, best_set = valuemodel.win_prob(s0), ()
    for k in range(1, len(items) + 1):
        for comb in itertools.combinations(items, k):
            cost = sum(x[2] for x in comb)
            if cost > gold or sum(1 for x in comb if x[0] == 'potion') > free: continue
            if P.get('shop_visit_card_cap', False) and sum(x[0] == 'card' for x in comb) > card_budget:
                continue
            s = dict(s0, gold=gold - cost, deck=list(s0['deck']), relics=list(s0['relics']))
            for kind, _, _, ident in comb:
                if kind == 'card': s = valuemodel.with_card(s, ident)
                elif kind == 'relic' and ident: s['relics'] = s['relics'] + [ident]
                elif kind == 'remove': s = valuemodel.without_card(s, ident)
                elif kind == 'potion': s['pots'] = s['pots'] + 1
            v = valuemodel.win_prob(s)
            if v > best + 1e-6: best, best_set = v, comb
    return best_set


def decide(st, mem):
    done = mem.setdefault('shop_done', set())
    order = {'remove': 0, 'relic': 1, 'card': 2, 'potion': 3}
    use_v = P.get('shop_mode') == 'value' and valuemodel.available()
    todo = [x for x in sorted((plan_value if use_v else plan)(st, done), key=lambda x: order[x[0]]) if (x[0], x[1]) not in done]
    if todo:
        kind, idx, _, _ = todo[0]; done.add((kind, idx))
        if kind == 'remove': mem['select_purpose'] = 'remove'; return ('remove_card', {})
        if kind == 'relic': return ('buy_relic', {'relic_index': idx})
        if kind == 'card': return ('buy_card', {'card_index': idx})
        return ('buy_potion', {'potion_index': idx})
    mem.pop('shop_done', None)
    return ('leave_room', {})
