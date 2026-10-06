"""输出核心规则。

数据里真正算核心的只有两种：消耗引擎、格挡转伤害。第一幕结束时有其中之一，最终通关 +11 个百分点（调整后）。
我们死在第二幕的局只有 8% 有核心（人类赢家第二幕 Boss 前 31%）：选牌时的模拟实打只看本幕 / 下一幕 Boss 和精英，
看得见攻击牌马上多打的伤害、看不见引擎的长期回报 → 所以这些分**加在模拟之后**（rewards.choose），系数 core_w。
分数单位 = 选牌模型的 logit。阶段：A1a = 第一幕前 9 层（过渡攻击照拿，不追核心），A1b = 第一幕后半（含第一幕 Boss 奖励），A2a / A2b = 第二幕前后半，A3。
"""
from params import P

EXH_ENGINE = {'FEEL_NO_PAIN', 'DARK_EMBRACE', 'CORRUPTION'}
EXH_SRC = {'BURNING_PACT', 'TRUE_GRIT', 'SECOND_WIND', 'STOKE', 'FIEND_FIRE', 'HAVOC', 'BRAND', 'CINDER', 'THRASH'}
BLOCK_ENG = {'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT', 'FEEL_NO_PAIN'}
JUG_FEED = {'FEEL_NO_PAIN', 'BARRICADE', 'UNMOVABLE', 'STONE_ARMOR', 'RAGE', 'CRIMSON_MANTLE'}
TEMPO = {'OFFERING', 'BATTLE_TRANCE', 'BLOODLETTING', 'FORGOTTEN_RITUAL', 'PYRE'}
VULN_SRC = {'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}


def kinds(d, s): return len(set(d) & s)
def core_exh(d): return kinds(d, EXH_ENGINE) >= 1 and kinds(d, EXH_SRC) >= 2
def core_blk(d): return ('BODY_SLAM' in d and kinds(d, BLOCK_ENG) >= 1) or ('JUGGERNAUT' in d and kinds(d, JUG_FEED) >= 1)
def has_core(d): return core_exh(d) or core_blk(d)


# 规则 2：还没核心时的零件和周转牌 [A1a, A1b, A2a/A2b]
PARTS = {'FEEL_NO_PAIN': (0, .4, .7), 'DARK_EMBRACE': (0, .2, .7), 'STOKE': (.3, .65, .65), 'SECOND_WIND': (.3, .65, .35),
         'BURNING_PACT': (0, .3, .6), 'FIEND_FIRE': (0, .35, .45), 'HAVOC': (0, .15, .35), 'TRUE_GRIT': (0, .15, 0),
         'ASHEN_STRIKE': (0, .25, .25), 'UNMOVABLE': (.35, .35, 0), 'BARRICADE': (0, .3, .15), 'BATTLE_TRANCE': (.6, .6, .1),
         'OFFERING': (.35, .35, .35), 'FORGOTTEN_RITUAL': (0, .3, 0), 'BLOODLETTING': (0, .25, .2)}
# 规则 3：有核心以后
IF_EXH = {'DRUM_OF_BATTLE': 1.3, 'DARK_EMBRACE': .9, 'FEEL_NO_PAIN': .7, 'ASHEN_STRIKE': .7, 'JUGGERNAUT': .7,
          'EVIL_EYE': .5, 'PACTS_END': .5, 'BURNING_PACT': .4, 'HOWL_FROM_BEYOND': .4, 'STOKE': .3,
          'DISMANTLE': -2.0, 'PERFECTED_STRIKE': -2.0, 'INFERNO': -2.0, 'BLUDGEON': -2.0, 'RAMPAGE': -2.0,
          'PRIMAL_FORCE': -1.8, 'CINDER': -1.6, 'ANGER': -1.5, 'SETUP_STRIKE': -1.5, 'HELLRAISER': -1.4,
          'BREAKTHROUGH': -1.4, 'HEMOKINESIS': -1.4}
IF_BLK = {'BARRICADE': 1.3, 'BODY_SLAM': 1.2, 'IMPERVIOUS': .4, 'STONE_ARMOR': .4, 'DRUM_OF_BATTLE': .4, 'FEEL_NO_PAIN': .3,
          'BLUDGEON': -2.0, 'INFLAME': -2.0, 'PERFECTED_STRIKE': -2.0, 'BULLY': -2.0, 'DISMANTLE': -2.0, 'TWIN_STRIKE': -2.0,
          'SETUP_STRIKE': -1.7, 'UNRELENTING': -1.7, 'CINDER': -1.6, 'SPITE': -1.5, 'HEMOKINESIS': -1.4, 'DOMINATE': -1.4}
# 规则 4：没有核心时的独立攻击牌 [A1a, A1b, A2]
STANDALONE = {'RAMPAGE': (0, -.5, -1.4), 'SETUP_STRIKE': (-.5, -.5, -1.1), 'HEMOKINESIS': (-.7, -.7, -.85), 'STOMP': (0, -.4, -.8)}
for _c in ('STAMPEDE', 'IRON_WAVE', 'FEED'): STANDALONE[_c] = (-.45, -.45, -.75)        # 惊逃、铁斩波、狂宴
for _c in ('BREAKTHROUGH', 'INFLAME', 'PRIMAL_FORCE', 'CINDER', 'ANGER', 'FIGHT_ME', 'TWIN_STRIKE'): STANDALONE[_c] = (0, -.3, -.65)
for _c in ('MOLTEN_FIST', 'INFERNAL_BLADE', 'BLUDGEON', 'UNRELENTING', 'WHIRLWIND', 'RAGE'): STANDALONE[_c] = (0, -.2, -.5)
for _c in ('ONE_TWO_PUNCH', 'SPITE', 'CRUELTY', 'THUNDERCLAP'): STANDALONE[_c] = (-.5, -.4, -.4)
BOSS_A2B = {'KAISER_CRAB_BOSS': {'FEEL_NO_PAIN': .7, 'UNMOVABLE': .7}, 'KNOWLEDGE_DEMON_BOSS': {'DEMON_FORM': .5, 'UNMOVABLE': .4},
            'THE_INSATIABLE_BOSS': {'DEMON_FORM': .4}}


def phase(act, floor):
    if act == 1: return 'A1a' if (floor or 0) <= 9 else 'A1b'
    if act == 2: return 'A2a' if (floor or 0) <= 9 else 'A2b'
    return 'A3'


def bonus(card, deck, act, floor, boss=None):
    """一张牌的核心加减分（logit，乘 core_w 之前）。deck：去掉 '+' 的 id 列表"""
    c = card.rstrip('+'); ph = phase(act, floor); i = {'A1a': 0, 'A1b': 1}.get(ph, 2)
    d = list(deck)
    if has_core(d):
        vals = []
        if core_exh(d): vals.append(IF_EXH.get(c, 0.0))
        if core_blk(d): vals.append(IF_BLK.get(c, 0.0))
        return max(vals, key=abs) if vals else 0.0
    b = 0.0
    if ph != 'A1a' and has_core(d + [c]): b += P.get('core_complete_bonus', 0.6)        # 规则 1：能立刻凑齐核心
    part = PARTS.get(c, (0, 0, 0))[i]
    if ph == 'A2b': part *= 0.5                                                        # 规则 5：第二幕后半零件分减半，转向 Boss
    b += part
    if c == 'VICIOUS':                                                                 # 凶恶（易伤来源 ≥2 种）
        if kinds(d, VULN_SRC) >= 2: b += (0, .2, .4)[i]
    if c == 'DRUM_OF_BATTLE':
        b += (-.8, -.3, .5 if kinds(d, EXH_SRC) >= 1 else 0)[i]
    if c == 'BODY_SLAM' and not kinds(d, BLOCK_ENG):
        b += (-.5, 0, .2)[i]
    if c == 'PERFECTED_STRIKE' and sum(1 for x in d if 'STRIKE' in x) < 7: b += (0, -.3, -.85)[i]
    if c == 'HELLRAISER' and 'POMMEL_STRIKE' not in d: b -= 1.0
    if c == 'RUPTURE' and sum(1 for x in d if x in ('BLOODLETTING', 'HEMOKINESIS', 'OFFERING', 'BLOOD_WALL', 'INFERNO', 'BREAKTHROUGH')) < 2: b += (-.5, -.4, -.4)[i]
    if c == 'PACTS_END' and not kinds(d, EXH_ENGINE): b += (-.8, -.6, -.3)[i]
    if c == 'JUGGERNAUT' and not kinds(d, JUG_FEED): b -= 1.0
    b += STANDALONE.get(c, (0, 0, 0))[i]
    if ph == 'A2b' and boss in BOSS_A2B: b += BOSS_A2B[boss].get(c, 0.0)
    return b
