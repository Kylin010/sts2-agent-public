"""选牌：战斗奖励三选一 / 商店买牌时，每张牌值多少。

pick_mode = model（默认）：用选牌模型（policy/pickmodel.py，从社区赢家的选择学的，带牌组联动和重复惩罚），
  分数 = 「拿这张」比「跳过」的效用高多少 + Boss / 精英对策分；大于 pick_skip_margin 才拿。
pick_mode = legacy：旧打分 = 玩家数据的拿取分 + 联动规则（kb/synergies.json）+ 遗物偏好 + 牌组缺什么补什么 − 惩罚
"""
from params import P
from policy import longterm, kb, deckeval, pickmodel, valuemodel
from policy.knowledge import cid, card_score, deck_ids, STRIKE_ARCH


def use_model():
    return P.get('pick_mode', 'model') in ('model', 'blend', 'value') and pickmodel.available()


import json as _json, math as _math, os as _os
try:
    _ARCH = _json.load(open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'kb', 'archetype_companions.json')))['core']
except Exception:
    _ARCH = {}


def archetype_lift(card_id, deck):
    """流派加分（kb/archetype_companions.json，学自社区赢家牌组）：
    牌组里有核心牌 → 它的搭档牌加分；候选牌本身是核心牌 → 牌组里它的搭档越多加得越多。按共现倍数的对数加，封顶。"""
    have = set(deck); b = 0.0
    for core, v in _ARCH.items():
        if core in have and card_id in v['companions']: b += _math.log(v['companions'][card_id])
    if card_id in _ARCH:
        b += sum(_math.log(l) for c, l in _ARCH[card_id]['companions'].items() if c in have)
    return min(b, P['arch_cap'])


def value_delta(card, st):
    """胜率模型：拿这张牌比不拿，最终胜率高多少（百分点）"""
    if not valuemodel.available(): return 0.0
    s0 = valuemodel.state_of(st)
    return 100 * (valuemodel.win_prob(valuemodel.with_card(s0, card.get('id'), bool(card.get('upgraded')))) - valuemodel.win_prob(s0))


def archetype_bonus(t):
    arch = P.get('force_archetype')
    if arch and arch != 'default':                       # 种子研究：强制某个流派
        import json, os
        A = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'seedlab', 'archetypes.json')))
        if t & set(A[arch]['tags']): return A[arch]['bonus']
    return 0


def value(card, st, mem=None):
    act = (st.get('context') or {}).get('act', 1)
    pl = st.get('player') or {}
    i = cid(card); deck = deck_ids(st)
    if use_model():
        mode = P.get('pick_mode', 'model')
        deck = pickmodel.with_relics(deck, st)            # 遗物也进牌组画像（新模型学了遗物和牌的配合）
        u = pickmodel.utility(i, card.get('type'), deck, act)
        if mode == 'value':
            s = P['value_weight'] * value_delta(card, st)
        elif u is not None:
            s = u - pickmodel.skip_utility(deck, act)
            if mode == 'blend': s += P['value_weight'] * value_delta(card, st)
        else:
            return P['pick_unknown_value']
        s += P['pick_counter_weight'] * kb.counter_bonus(i, act, ((st.get('context') or {}).get('boss') or {}).get('id'))
        if P['arch_weight']: s += P['arch_weight'] * archetype_lift(i, deck)
        from policy import buildrules                 # 构筑规则（研究 16、17 号）：先引擎后终端、陷阱牌
        s += buildrules.card_bonus(i, deck_ids(st), act) + buildrules.readiness_bonus(i, st, act, mem)
        from policy import combos                      # 联动：拿这张能让联动 / 核心更接近成型 → 加分（combo_pick_w）
        s += combos.pick_bonus(i, st)
        return s + archetype_bonus(kb.tags(i))
    s = card_score(i, act)
    relic_ids = [r.get('id') for r in pl.get('relics') or []]
    potion_ids = [str(p.get('name', '')) for p in pl.get('potions') or [] if p]
    s += kb.synergy_bonus(i, deck, relic_ids, potion_ids, act)
    s += P['counter_weight'] * kb.counter_bonus(i, act, ((st.get('context') or {}).get('boss') or {}).get('id'))   # 提前拿对策牌
    ev = deckeval.evaluate(pl.get('deck') or [])
    t = kb.tags(i)
    need_d = {1: P['elite_dpt_act1'], 2: P['elite_dpt_act2'], 3: P['elite_dpt_act3']}.get(act, 30)
    need_b = {1: P['block_target_act1'], 2: P['block_target_act2'], 3: P['block_target_act3']}.get(act, 20)
    if 'damage' in t and ev['dmg_per_turn'] < need_d: s += P['need_damage'] * min(1.0, (need_d - ev['dmg_per_turn']) / need_d * 2)
    if 'block' in t and ev['block_per_turn'] < need_b: s += P['need_block'] * min(1.0, (need_b - ev['block_per_turn']) / need_b * 2)
    s += archetype_bonus(t)
    if i in STRIKE_ARCH: s -= P['reward_strike_penalty']
    if card.get('type') == 'Power' and deck.count(i) >= 1: s -= 0.2
    if len(deck) > P['reward_big_deck']: s -= P['reward_big_deck_penalty']
    return s


def choose(st, mem=None):
    """返回要拿的牌的下标；都不值得拿返回 None（跳过）。每张牌和「跳过」一起交给 learn.pick（学出来的偏好 + 训练时探索）"""
    from policy import learn
    cards = st.get('cards') or []
    if not cards: return None
    from policy import offclass                       # 全是别家角色的牌（色彩哲学家等）：按分档表选，不走模型和模拟实打
    oc = offclass.choose_reward(st, mem)
    if oc != 'n/a': return oc
    if use_model():
        skip = P['pick_skip_margin'] - P['pick_shift_scale'] * longterm.reward_threshold_shift(st)
    else:
        skip = P['reward_skip_below'] - longterm.reward_threshold_shift(st)
    from policy import buildrules                      # 第二幕起学会跳过（研究 17 号 7.4）
    skip += buildrules.skip_shift((st.get('context') or {}).get('act', 1))
    opts = [(c['index'], value(c, st, mem), learn.feats('pick', cid(c), st)) for c in cards] + [(None, skip, learn.feats('pick', 'SKIP', st))]
    act_now = (st.get('context') or {}).get('act', 1)
    if P.get('simeval_pick') and len(opts) > 1 and act_now in P.get('simeval_pick_acts', [1, 2, 3]):
        # 10/3 研究（输出核心 7）：模拟只打本幕 / 下一幕 Boss 和精英，看得见攻击牌马上多打的伤害、看不见引擎的长期回报，
        # 把学自赢家的模型分（第二幕本来偏好引擎牌）压下去了 → 可按幕关掉
        # 实打评估（policy/simeval.py）：每个选项变成一副牌，拿去打这一幕和下一幕的 Boss / 精英，比掉血；
        # 底分 = 实打分 / simeval_pick_scale（每少掉这么多血算 1 分）+ 原来的模型分 × simeval_prior_w
        from policy import simeval
        base = simeval.deck_ids(st)
        decks = [base + ([str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '')] if i is not None else [])
                 for i, c in [(o[0], next((c for c in cards if c['index'] == o[0]), None)) for o in opts]]
        sc = simeval.eval_decks(st, decks, tag='pick')
        if mem is not None:
            ctx_ = st.get('context') or {}; pl_ = st.get('player') or {}
            mem.setdefault('simeval_log', []).append({
                'floor': ctx_.get('floor'), 'act': ctx_.get('act'), 'act_name': ctx_.get('act_name'), 'boss': (ctx_.get('boss') or {}).get('id'),
                'opts': [(cid(c) + ('+' if c.get('upgraded') else '')) if c is not None else 'SKIP' for c in [next((c for c in cards if c['index'] == o[0]), None) for o in opts]],
                'sim': [round(x, 2) for x in sc], 'prior': [round(o[1], 3) for o in opts],       # prior = 实打前的模型分（学的是实打相对模型的修正）
                'deck': base, 'relics': [r.get('id') for r in pl_.get('relics') or []], 'hp': pl_.get('hp'), 'max_hp': pl_.get('max_hp'), 'gold': pl_.get('gold')})
        opts = [(o[0], v / P['simeval_pick_scale'] + P['simeval_prior_w'] * o[1], o[2]) for o, v in zip(opts, sc)]
    rvw = P.get('run_value_pick_w', 0.0)
    if rvw:
        # 10/4 整局价值网络（社区 5.3 万局，policy/runvalue.py）：拿这张牌让「这局通关的概率」变化几个百分点，× run_value_pick_w 加到选牌分上
        # （子代理建议 0.2：选牌模型 + 0.2 × 百分点，和赢家选牌一致率 56.8% → 57.8%）。跳过 = 不变
        from policy import runvalue
        if runvalue.available():
            by_rv = {c['index']: (cid(c), bool(c.get('upgraded'))) for c in cards}
            opts = [(o[0], o[1] + (rvw * 100 * runvalue.delta_card(st, by_rv[o[0]][0], by_rv[o[0]][1]) if o[0] is not None else 0.0), o[2]) for o in opts]
    dw = P.get('pick_distill_w', 0.0)
    if dw and not (P.get('simeval_pick') and act_now in P.get('simeval_pick_acts', [1, 2, 3])):
        # 10/4 选牌蒸馏：不实打时，用从实打老师学来的函数（policy/pickdistill.py）补上「这副牌打这一幕 Boss / 精英会更好还是更差」
        from policy import pickdistill
        by_d = {c['index']: (cid(c) + ('+' if c.get('upgraded') else '')) for c in cards}
        opts = [(o[0], o[1] + dw * pickdistill.score(by_d[o[0]] if o[0] is not None else 'SKIP', st), o[2]) for o in opts]
    bw = P.get('boss_prep_w', 0.0)
    if bw:                                             # 第二幕 Boss 备战（docs/高手怎么打第二幕Boss.md S1 / S2）：加在模拟之后
        from policy import bossprep
        by_ = {c['index']: cid(c) for c in cards}
        opts = [(o[0], o[1] + (bw * bossprep.bonus(by_[o[0]], st) if o[0] is not None else 0.0), o[2]) for o in opts]
    mw = P.get('mapprep_w', 0.0)
    if mw:                                             # 按地图 / 本幕 Boss 提前准备（policy/mapprep.py，暗港第一幕）
        from policy import mapprep
        by_m = {c['index']: cid(c) for c in cards}
        opts = [(o[0], o[1] + (mw * mapprep.bonus(by_m[o[0]], st) if o[0] is not None else 0.0), o[2]) for o in opts]
    cw = P.get('core_w', 0.0)
    if cw:                                             # 输出核心规则（docs/输出核心研究.md 第五节）：加在模拟之后，不被打对折
        from policy import corerules
        ctx = st.get('context') or {}
        deck = [str(c.get('id', '')).replace('CARD.', '') for c in (st.get('player') or {}).get('deck') or []]
        by = {c['index']: cid(c) for c in cards}
        opts = [(o[0], o[1] + (cw * corerules.bonus(by[o[0]], deck, ctx.get('act', 1), ctx.get('floor', 0), (ctx.get('boss') or {}).get('id'))
                                if o[0] is not None else 0.0), o[2]) for o in opts]
    k = learn.pick('pick', opts, st, mem)
    if P.get('pick_teach_log'):
        # 选牌实打当老师：记下牌组、选项、各项分数和最终选择，
        # 离线学一个加在选牌模型上的修正，下场 simeval_pick=false 也能选出老师会选的牌
        try:
            import json as _j, os as _o
            ctx = st.get('context') or {}
            rec = {'act': ctx.get('act'), 'floor': ctx.get('floor'), 'boss': (ctx.get('boss') or {}).get('id'),
                   'deck': [str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '') for c in (st.get('player') or {}).get('deck') or []],
                   'relics': [r.get('id') for r in (st.get('player') or {}).get('relics') or []],
                   'hp': (st.get('player') or {}).get('hp'), 'max_hp': (st.get('player') or {}).get('max_hp'),
                   'opts': [{'idx': o[0], 'id': (cid(next((c for c in cards if c['index'] == o[0]), {})) if o[0] is not None else 'SKIP'), 'score': round(o[1], 3)} for o in opts],
                   'chosen': k}
            with open(f"{P['pick_teach_log']}.{_o.getpid()}", 'a') as f: f.write(_j.dumps(rec, ensure_ascii=False) + '\n')
        except Exception:
            pass
    return k
