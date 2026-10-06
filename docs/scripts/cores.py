"""输出核心的定义（研究用，和程序 policy/buildrules.py 无关）。

每个核心 = 引擎（成长 / 转化来源）+ 兑现（把积累变成伤害的牌）+ 燃料（喂引擎的牌）。
定义来自 core_discover.py 的共现聚类（数据自己分出来的簇），再按 16 号文档的源码机制归类。
函数接收 Counter（牌 id → 张数，不含升级标记）。
"""

EXH_ENGINE = {'FEEL_NO_PAIN', 'DARK_EMBRACE', 'CORRUPTION'}
# 主动烧别的牌的手段（不含只烧自己的牌）
EXH_SRC = {'BURNING_PACT', 'TRUE_GRIT', 'SECOND_WIND', 'STOKE', 'FIEND_FIRE', 'HAVOC', 'BRAND', 'CINDER', 'THRASH'}
EXH_PAY = {'ASHEN_STRIKE', 'PACTS_END', 'HOWL_FROM_BEYOND', 'FIEND_FIRE', 'EVIL_EYE', 'DRUM_OF_BATTLE'}
BLOCK_PAY = {'BODY_SLAM', 'JUGGERNAUT'}
BLOCK_ENGINE = {'BARRICADE', 'UNMOVABLE', 'FEEL_NO_PAIN', 'STONE_ARMOR', 'CRIMSON_MANTLE', 'RAGE'}
STR_SRC = {'DEMON_FORM', 'INFLAME', 'FIGHT_ME', 'RUPTURE', 'BRAND', 'DOMINATE'}
MULTI = {'WHIRLWIND', 'CONFLAGRATION', 'SWORD_BOOMERANG', 'TWIN_STRIKE', 'FIGHT_ME', 'THRASH', 'TEAR_ASUNDER', 'EXPECT_A_FIGHT'}
SELF_ENGINE = {'INFERNO', 'RUPTURE'}
SELF_SRC = {'BLOODLETTING', 'CRIMSON_MANTLE', 'OFFERING', 'HEMOKINESIS', 'BREAKTHROUGH', 'BLOOD_WALL', 'BRAND'}
SELF_PAY = {'SPITE', 'TEAR_ASUNDER'}
VULN_PAY = {'VICIOUS', 'CRUELTY', 'BULLY', 'DOMINATE', 'DISMANTLE', 'MOLTEN_FIST'}
VULN_SRC = {'BASH', 'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}
STRIKE_PAY = {'PERFECTED_STRIKE', 'HELLRAISER'}
STRIKE_TAG = {'STRIKE_IRONCLAD', 'POMMEL_STRIKE', 'PERFECTED_STRIKE', 'ASHEN_STRIKE', 'SETUP_STRIKE', 'TWIN_STRIKE', 'ULTIMATE_STRIKE', 'SEEKER_STRIKE'}
BIG_SINGLE = {'BLUDGEON', 'UNRELENTING', 'MANGLE', 'STAMPEDE'}


def n_of(k, s):
    return sum(k.get(c, 0) for c in s)


def kinds(k, s):
    return sum(1 for c in s if k.get(c, 0) > 0)


CORES = {
    # 名字: (判定函数, 定义说明)
    '消耗引擎': (lambda k: kinds(k, EXH_ENGINE) >= 1 and kinds(k, EXH_SRC) >= 2,
             '无惧疼痛/黑暗之拥/腐化 ≥1 种 + 主动消耗牌（燃烧契约、坚毅、重振精神、添柴、恶魔之焰、破灭、烙印、余烬、痛殴）≥2 种'),
    '格挡转伤害': (lambda k: (k.get('BODY_SLAM', 0) and (kinds(k, {'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT', 'FEEL_NO_PAIN'}) >= 1))
                       or (k.get('JUGGERNAUT', 0) and kinds(k, BLOCK_ENGINE) >= 1),
              '全身撞击 + 壁垒/坚定不移/势不可当/无惧疼痛之一；或 势不可当 + 壁垒/坚定不移/无惧疼痛/岩石铠甲/绯红披风/狂怒之一'),
    '力量多段': (lambda k: kinds(k, STR_SRC - {'RUPTURE'}) >= 1 and kinds(k, MULTI) >= 2,
             '力量来源（恶魔形态、燃烧、与我一战！、烙印、主宰）≥1 + 多段牌（旋风斩、焚烧、飞剑回旋镖、双重打击、与我一战！、痛殴、扯碎、跃跃欲试）≥2 种'),
    '自伤': (lambda k: kinds(k, SELF_ENGINE) >= 1 and kinds(k, SELF_SRC) >= 2,
           '狱火/撕裂 ≥1 + 自伤牌（放血、绯红披风、祭品、御血术、突破、血墙、烙印）≥2 种'),
    '易伤': (lambda k: kinds(k, VULN_PAY) >= 2 and kinds(k, VULN_SRC - {'BASH'}) >= 1,
           '凶恶/残酷/欺凌/主宰/拆卸/熔融之拳 ≥2 种 + 痛击以外的易伤来源（战栗、上勾拳、挑衅、闪电霹雳、震荡波）≥1'),
    '打击': (lambda k: kinds(k, STRIKE_PAY) >= 1 and n_of(k, STRIKE_TAG) >= 7,
           '完美打击/地狱狂徒 + 带打击标签的牌 ≥7 张'),
}

# 每个核心的关键牌（用于时间线、伴随牌分析）
KEY = {
    '消耗引擎': {'engine': EXH_ENGINE, 'fuel': EXH_SRC, 'pay': EXH_PAY | {'BODY_SLAM', 'JUGGERNAUT'}},
    '格挡转伤害': {'engine': {'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT', 'FEEL_NO_PAIN'}, 'fuel': BLOCK_ENGINE, 'pay': BLOCK_PAY},
    '力量多段': {'engine': STR_SRC - {'RUPTURE'}, 'fuel': set(), 'pay': MULTI},
    '自伤': {'engine': SELF_ENGINE, 'fuel': SELF_SRC, 'pay': SELF_PAY},
    '易伤': {'engine': VULN_PAY, 'fuel': VULN_SRC, 'pay': set()},
    '打击': {'engine': STRIKE_PAY, 'fuel': STRIKE_TAG, 'pay': set()},
}


def which(k):
    """牌组有哪些核心（list）"""
    return [n for n, (f, _) in CORES.items() if f(k)]


def has_good_core(k):
    """数据上胜率为正的核心：消耗引擎、格挡转伤害"""
    return CORES['消耗引擎'][0](k) or CORES['格挡转伤害'][0](k)
