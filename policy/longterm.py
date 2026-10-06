"""跨战斗的长期收益：遗物计数、永久成长的牌、战斗结束时的血量门槛、加牌触发的遗物……

这些东西单看一回合不值钱，但会让「下一场 / 后面所有战斗」更轻松，所以在规划时额外加分。
所有分值都在 params.json 里（longterm_ 开头），可以用基准测出来调。
"""
from params import P

cid = lambda c: str(c.get('id') or '').replace('CARD.', '')


def relics(st):
    """{遗物 id: (计数, 状态)}；计数为 None 表示这个遗物没有计数"""
    return {str(r.get('id') or ''): (r.get('counter'), r.get('status')) for r in (st.get('player') or {}).get('relics') or []}


def combat_bonus(combo, ctx, out):
    """组合规划里的额外分数。out = 这组牌的估算结果：dmg_by_card（每张攻击的伤害）、ends_fight（打完战斗就结束）、
    killed_focus（打死了集火目标）、self_hp（自伤）"""
    rel = ctx['relics']; bonus = 0.0
    ids = [cid(c) for c in combo]
    attacks = [c for c in combo if c.get('type') == 'Attack']
    # 钢笔尖：第 10 张攻击伤害翻倍
    if 'PEN_NIB' in rel and rel['PEN_NIB'][0] is not None:
        cnt = rel['PEN_NIB'][0]; n = len(attacks)
        fires = cnt + n >= 10
        if fires and not out['ends_fight'] and cnt != 9:
            # 计数 9 时手牌预览已经含翻倍（combat 里只给第一张留着翻倍），不再加分（梳理表 C14）；
            # 计数更低、这组里第 10 张才翻倍时预览不含，按「最大那张吃到翻倍」近似加分
            bonus += ctx['alpha'] * max((out['dmg_by_card'].get(id(c), 0) for c in attacks), default=0)   # 让最大的那张吃到翻倍
        if out['ends_fight']:
            end_cnt = (cnt + n) % 10
            if fires: bonus -= P['longterm_pen_nib_waste']           # 战斗结束前把翻倍浪费在溢出伤害上
            if end_cnt == 9: bonus += P['longterm_pen_nib_charged']  # 留到下一场：一开局第一张攻击就翻倍
    # 狂宴：斩杀时永久 +3 最大生命
    if 'FEED' in ids and out['killed_focus']:
        bonus += P['longterm_feed_kill']
    # 每打一次就永久成长的牌
    bonus += P['longterm_perm_growth'] * sum(1 for i in ids if i in ('GENETIC_ALGORITHM', 'THE_SCYTHE'))
    # 带骨肉：战斗结束时血量 ≤ 一半就回 12。最后一回合用自伤牌把血压到线下
    if 'MEAT_ON_THE_BONE' in rel and out['ends_fight']:
        hp, mx = ctx['hp'], ctx['max_hp']
        if hp > mx / 2 >= hp - out['self_hp'] > 0:
            bonus += 12 - out['self_hp']
    return bonus


def order_key(c):
    """出牌顺序微调：狂宴放到攻击的最后，用它补刀"""
    return 6.5 if cid(c) == 'FEED' else None


# 按药水 ID 精确认（Codex 发现，梳理表 C01）：原来用名字子串 ('Fruit', 'Juice', 'Capacity')，
# 「甲虫汁 Beetle Juice」也含 Juice，被当成永久药水每回合一开始就不带目标去喝——多个敌人时引擎报错，
# run.py 的出错处理接着拉黑上一张牌、再退到结束回合，结果每回合一张牌都不打
PERMANENT_POTION_IDS = {'FRUIT_JUICE', 'POTION_OF_CAPACITY'}       # 果汁（+最大生命）、扩容药水（+药水栏）


def potion_id(p):
    from policy import kb
    return str(p.get('id') or kb.id_by_name('potions', p.get('name')) or '').replace('POTION.', '')


def permanent_potion(st):
    """有永久效果的药水（加最大生命等），拿到就喝"""
    for p in (st.get('player') or {}).get('potions') or []:
        if p and potion_id(p) in PERMANENT_POTION_IDS:
            return p
    return None


def reward_threshold_shift(st):
    """加牌触发的遗物：让「拿牌」的门槛变低（返回要减掉多少）"""
    rel = relics(st); shift = 0.0
    if 'BOOK_OF_FIVE_RINGS' in rel and rel['BOOK_OF_FIVE_RINGS'][0] == 4:      # 再加 1 张就回 20 血
        pl = st.get('player') or {}
        shift += P['longterm_book_of_rings'] * (1.5 if pl.get('hp', 1) < 0.7 * pl.get('max_hp', 1) else 1)
    if 'LUCKY_FYSH' in rel: shift += P['longterm_lucky_fysh']
    return shift


def rest_choice(opts):
    """篝火：有壶铃时优先「举重」（永久 +1 力量，最多 3 次）"""
    for k in ('LIFT', 'GIRYA'):
        if k in opts: return opts[k]['index']
    return None
