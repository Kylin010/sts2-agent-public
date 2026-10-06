"""构筑规则（来自另一个代理的研究：ironclad/16-联动目录与输出终端、17-牌组构建与长线规划），给选牌和商店的牌估值加修正。

1. 先引擎后终端（16 号第零节）：终端牌没有对应引擎时基本是废牌（势不可当单独 38%、配无惧疼痛 63%；契约终结 34% → 53%；
   地狱狂徒 21% → 配剑柄打击 44%；撕裂 36% → 配放血 49%）。所以终端在牌组里没有引擎时减分。
2. 陷阱牌（17 号 4.1）：第一幕拿了，过第一幕率和最终通关率都更低；有配套时（比如撕裂已有两个以上自伤来源）不算陷阱。
3. 第二幕起学会跳过（17 号 7.4）：赢家第二幕跳过约 39%，新牌要解决考题或补全引擎 → 第二幕起跳过门槛抬高。
分数单位和选牌模型一样（logit），权重：br_terminal_pen、br_trap_pen、br_engine_bonus、br_skip_a2（都可设 0 关掉，用于对照实验）。
"""
from params import P

EXHAUST_SRC = {'BURNING_PACT', 'TRUE_GRIT', 'SECOND_WIND', 'FIEND_FIRE', 'STOKE', 'BRAND'}   # 能稳定烧牌的手段
EXHAUST_ENGINE = {'FEEL_NO_PAIN', 'DARK_EMBRACE'}                                           # 每当有牌被消耗
SELF_DMG = {'BLOODLETTING', 'CRIMSON_MANTLE', 'BREAKTHROUGH', 'BLOOD_WALL', 'OFFERING', 'HEMOKINESIS'}
BLOCK_ENGINE = {'FEEL_NO_PAIN', 'RAGE', 'BARRICADE', 'UNMOVABLE', 'STONE_ARMOR', 'CRIMSON_MANTLE'}
STRIKE_TAG = {'STRIKE_IRONCLAD', 'POMMEL_STRIKE', 'PERFECTED_STRIKE', 'ASHEN_STRIKE', 'SETUP_STRIKE', 'TWIN_STRIKE', 'WILD_STRIKE'}


def _n(deck, s):
    return sum(1 for c in deck if c in s)


# 终端 → 「牌组里已经有配套」的判断
TERMINALS = {
    'ASHEN_STRIKE': lambda d: _n(d, EXHAUST_SRC) >= 2,             # 至少要有几个稳定烧牌的手段，否则就是一张 6 伤打击
    'PACTS_END': lambda d: _n(d, EXHAUST_SRC) >= 2,                # 消耗堆 ≥3 张才生效
    'HOWL_FROM_BEYOND': lambda d: _n(d, {'BURNING_PACT', 'TRUE_GRIT', 'FIEND_FIRE', 'STOKE', 'BRAND'}) >= 1,   # 要靠烧掉它来打
    'BODY_SLAM': lambda d: 'BARRICADE' in d or _n(d, BLOCK_ENGINE) >= 2,
    'JUGGERNAUT': lambda d: _n(d, BLOCK_ENGINE) >= 1,
    'PERFECTED_STRIKE': lambda d: _n(d, STRIKE_TAG) >= 7,
    'HELLRAISER': lambda d: 'POMMEL_STRIKE' in d,
    'RUPTURE': lambda d: _n(d, SELF_DMG) >= 2,
    'INFERNO': lambda d: _n(d, SELF_DMG) >= 1,
}
# 第一幕的陷阱（前后都负）；在 TERMINALS 里且配套已齐的不算
TRAPS_ACT1 = {'RUPTURE', 'CRUELTY', 'DRUM_OF_BATTLE', 'EXPECT_A_FIGHT', 'STAMPEDE', 'HEMOKINESIS', 'IRON_WAVE', 'THUNDERCLAP', 'SETUP_STRIKE'}


def card_bonus(card_id, deck, act):
    """这张牌加进当前牌组的构筑修正（logit 单位，正 = 更该拿）"""
    if not P.get('br_on', True): return 0.0
    b = 0.0
    ok = TERMINALS.get(card_id)
    if ok is not None and not ok(deck):
        b -= P.get('br_terminal_pen', 0.0)
    if act == 1 and card_id in TRAPS_ACT1 and not (ok is not None and ok(deck)):
        b -= P.get('br_trap_pen', 0.0)
    if card_id in EXHAUST_ENGINE and _n(deck, EXHAUST_SRC) >= 1:      # 引擎配上了燃料
        b += P.get('br_engine_bonus', 0.0)
    if card_id in EXHAUST_SRC and _n(deck, EXHAUST_ENGINE) >= 1:      # 燃料配上了引擎
        b += P.get('br_engine_bonus', 0.0) * 0.5
    return b


def skip_shift(act):
    """第二幕起抬高跳过门槛（新牌要补引擎或考题才拿）"""
    if not P.get('br_on', True): return 0.0
    return P.get('br_skip_a2', 0.0) if act >= 2 else 0.0


# 4. 准备度（17 号 4.2、考题表第二节）：每幕 Boss 要求的每回合单体输出。牌组差得越多，拿牌时越看重「这张牌能加多少输出」
BOSS_DPT = {'VANTOM_BOSS': 29, 'THE_KIN_BOSS': 30, 'CEREMONIAL_BEAST_BOSS': 35,     # 第一幕：墨影幻灵前 6 回合 174、同族小队每回合约 30、仪式兽前 2~3 回合打 102
            'KNOWLEDGE_DEMON_BOSS': 57, 'KAISER_CRAB_BOSS': 50, 'THE_INSATIABLE_BOSS': 55,   # 第二幕
            'QUEEN_BOSS': 80, 'TEST_SUBJECT_BOSS': 80, 'AEONGLASS_BOSS': 80}              # 第三幕：第二幕结束要一回合 80+
ACT_DPT = {1: 30, 2: 50, 3: 80}


MULTI_BOSS = {'THE_KIN_BOSS', 'KAISER_CRAB_BOSS'}       # 多个目标的 Boss（同族小队：神官 + 两个信徒；帝皇蟹：碾碎爪 + 火箭）


def readiness_bonus(card_id, st, act, mem=None):
    """这张牌对「达到本幕 Boss 的输出要求」的帮助（logit 单位）。ready_w = 0 时关
    10/3 加动态群伤（ready_aoe_dyn）：下一个精英是多怪的概率 / 本幕 Boss 是多目标 × 群伤还差多少 → 群伤牌加分"""
    from policy import deckeval, kb
    b = 0.0
    dyn = P.get('ready_aoe_dyn', 0.0)
    if dyn and act <= 3 and 'aoe' in kb.tags(card_id):
        from policy import elites
        seen = list(((mem or {}).get('elites_seen') or {}).get(act, []))
        boss = ((st.get('context') or {}).get('boss') or {}).get('id')
        need_aoe = max(elites.p_multi(act, seen, 0), 0.7 if boss in MULTI_BOSS else 0.0)
        b += dyn * need_aoe * (1 - elites.aoe_capacity(st))
    w = P.get('ready_w', 0.0)
    if not w and not P.get('ready_aoe_bonus', 0.0): return b
    deck = (st.get('player') or {}).get('deck') or []
    boss = ((st.get('context') or {}).get('boss') or {}).get('id')
    target = BOSS_DPT.get(boss) or ACT_DPT.get(act, 50)
    d0 = deckeval.evaluate(deck)['dmg_per_turn']
    if w and d0 < target:
        d1 = deckeval.evaluate(list(deck) + [{'id': 'CARD.' + card_id, 'upgraded': False}])['dmg_per_turn']
        b += w * (target - d0) / target * max(0.0, d1 - d0) / 5        # 差得越多、这张加得越多，分越高（每 5 点输出算 1 个单位）
    if act <= 2 and 'aoe' in kb.tags(card_id) and not any('aoe' in kb.tags(str(c.get('id', '')).replace('CARD.', '')) for c in deck):
        b += P.get('ready_aoe_bonus', 0.0)                                 # 一张群伤都没有（17 号：第一幕要 1~2 张）
    return b
