"""卡牌和敌人的知识表，以及从玩家数据算出的分数。其他策略模块都从这里取。"""
import json, os
from policy import kb

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_SCORES = json.load(open(f'{HERE}/data/card_scores.json'))
NEOW_SCORES = json.load(open(f'{HERE}/data/neow_scores.json'))

cid = lambda c: str(c.get('id') or '').replace('CARD.', '')

# ---- 卡牌分类（铁甲战士）----
EXHAUST_ENGINE = kb.ids_with('exhaust_engine')
EXHAUST_FUEL = kb.ids_with('exhaust_fuel')
BLOCK_PAYOFF = kb.ids_with('block_payoff') | kb.ids_with('exhaust_payoff')
STRIKE_ARCH = kb.ids_with('strike_arch')
EXHAUST_PICKERS = {'BURNING_PACT', 'TRUE_GRIT', 'BRAND'}        # 打出后要选一张牌消耗

HITS = {k: v['hits'] for k, v in kb.CARDS.items() if (v.get('hits') or 1) > 1}
AOE = kb.ids_with('aoe')
VULN = {'BASH': 2, 'TREMBLE': 3, 'UPPERCUT': 1, 'THUNDERCLAP': 1, 'TAUNT': 1, 'BREAK': 5, 'DOMINATE': 1, 'SHOCKWAVE': 3}
WEAK = {'UPPERCUT': 1, 'SHOCKWAVE': 3}
DRAW = {k: v['draw'] for k, v in kb.CARDS.items() if v.get('draw')}
DRAW.update({'PILLAGE': 1, 'HAVOC': 1})
DRAW.pop('PACTS_END', None)     # 契约终结：牌面 Cards=3 是「消耗堆至少 3 张才造成伤害」的门槛（源码 CanDealDamage），不抽牌（Codex 发现，梳理表 C08）
ENERGY = {k: v['energy'] for k, v in kb.CARDS.items() if v.get('energy')}
# 下面几张牌面上的能量不是「打出立刻」到账（源码核对，Codex 发现，梳理表 C09）：
#   战鼓 DRUM_OF_BATTLE：打出只抽 2，**被消耗时**才 +2 能量（AfterCardExhausted；腐化下打出即消耗，combat.evaluate 单独算）
#   薪火 PYRE：PyrePower 只改最大能量，下回合起每回合 +1
#   智取 OUTMANEUVER、放松 RELAX：EnergyNextTurnPower，下回合才给
# 原来规划器以为打了它们这回合还有能量付别的牌，计划打不完
for _k in ('DRUM_OF_BATTLE', 'PYRE', 'OUTMANEUVER', 'RELAX'): ENERGY.pop(_k, None)
SELF_HP = {k: v['self_hp'] for k, v in kb.CARDS.items() if v.get('self_hp')}
XCOST = {k for k, v in kb.CARDS.items() if v.get('x_cost')}       # X 费：旋风斩、齐射、瀑流（引擎手牌里报费用 0）
STR_NOW = {'INFLAME': 2, 'SETUP_STRIKE': 3, 'FIGHT_ME': 3}
POWER_VALUE_DEFAULT = {   # 一张能力牌大约值多少分（再乘「战斗还要打多久」）；知识库里写了 power_value 的以知识库为准
    'DEMON_FORM': 9, 'FEEL_NO_PAIN': 6, 'DARK_EMBRACE': 6, 'CORRUPTION': 7, 'PYRE': 7, 'JUGGERNAUT': 6,
    'CRIMSON_MANTLE': 7, 'INFLAME': 6, 'BARRICADE': 4, 'STONE_ARMOR': 6, 'UNMOVABLE': 4, 'RUPTURE': 3,
    'AGGRESSION': 5, 'CRUELTY': 4, 'VICIOUS': 4, 'HELLRAISER': 4, 'INFERNO': 4, 'JUGGLING': 3, 'STAMPEDE': 3,
}
POWER_VALUE = dict(POWER_VALUE_DEFAULT)
POWER_VALUE.update({k: v['power_value'] for k, v in kb.CARDS.items() if v.get('power_value')})
BAD_IDS = {'ASCENDERS_BANE', 'GUILTY', 'GREED', 'DOUBT', 'CLUMSY'}


def card_score(card_id, act):
    """玩家数据里的选牌分（奖励里出现时赢家 / 高手拿它的比例）"""
    s = CARD_SCORES.get(card_id, {})
    v = s.get(str(min(max(act or 1, 1), 3))) or s.get('1') or s.get('2') or {}
    return v.get('score', 0.05)


def is_bad(c):
    return c.get('type') in ('Curse', 'Status') or cid(c) in BAD_IDS


def worst_first(cards):
    """消耗 / 删除的顺序：诅咒和状态 → 打击 → 防御 → 分最低的"""
    def k(c):
        i = cid(c)
        if i == 'FRANTIC_ESCAPE': return (9, 0)   # 无厌沙虫的狂乱逃离：打一张多活一回合，烧掉等于少一回合（研究 12 号）——永远最后才烧
        if is_bad(c): return (0, 0)
        if i == 'STRIKE_IRONCLAD': return (1, c.get('upgraded', False))
        if i == 'DEFEND_IRONCLAD': return (2, c.get('upgraded', False))
        return (3, card_score(i, 2) + (0.3 if c.get('upgraded') else 0))
    return sorted(cards, key=k)


try:
    UPGRADE = json.load(open(f'{HERE}/data/upgrade_stats.json'))     # 社区赢家篝火升级的优先级（tools/upgrade_stats.py）
except Exception:
    UPGRADE = {}


# 升级会改变机制或费用的牌（研究 17 号 7.2：第一次锻造优先它们）
QUALITATIVE_UPG = {'TRUE_GRIT', 'BODY_SLAM', 'BARRICADE', 'DARK_EMBRACE', 'UNMOVABLE', 'HELLRAISER', 'HAVOC'}


def best_upgrade(cards, act=2):
    """升级顺序：按赢家「这张牌在场时被选中升级的比例」排；没有数据的用旧的估计。
    upg_doc_bonus > 0 时给质变升级加分（坚毅随机→自选消耗、全身撞击 1→0 费……数据里坚毅只排第 24）"""
    from params import P
    def k(c):
        i = cid(c)
        if c.get('upgraded') or is_bad(c): return -9
        u = UPGRADE.get(i)
        v = u.get('by_act', {}).get(str(act), u['rate']) if u else 0.6 * (POWER_VALUE.get(i, 0) / 10 + card_score(i, 2)) * 0.3
        return v + (P.get('upg_doc_bonus', 0.0) if i in QUALITATIVE_UPG else 0.0)
    return sorted(cards, key=k, reverse=True)


# ---- 敌人 ----
def is_attack_intent(it):
    """这个意图会不会打人。10/3（B-021，Codex 发现）：瀑布巨兽 / 毒气弹的爆炸是 DeathBlow 意图（源码 DeathBlowIntent : SingleAttackIntent，
    界面显示伤害），原来只认类型里带 attack 的，爆炸回合算成 0 伤害——不挡不喝药被一下炸死（读档学习里瀑布巨兽 7 次高血量死亡老师也救不了）。
    intent_deathblow 参数开着才认（先在迭代里量效果，采用后改默认）"""
    from params import P
    t = str(it.get('type', '')).lower()
    return 'attack' in t or (P.get('intent_deathblow', False) and 'deathblow' in t.replace('_', ''))


def intent_damage(e):
    """敌人这回合要打多少（多段 = 每段 × 段数）"""
    tot = 0
    for it in e.get('intents') or []:
        if is_attack_intent(it):
            d = it.get('damage') or 0
            tot += d * (it.get('hits') or 1) if it.get('hits') else d
    return tot


def has_power(e, word):
    return any(word in str(p.get('name', '')).lower() for p in e.get('powers') or [])


def deck_ids(st):
    return [cid(c) for c in (st.get('player') or {}).get('deck') or []]


# 10/4 每个精英 / Boss 的专属打法（tools/phase_alpha.py → data/phase_alpha.json），phase_alpha="file" 时用
try:
    import os as _os, json as _json
    PHASE_ALPHA = _json.load(open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'data', 'phase_alpha.json')))
except Exception:
    PHASE_ALPHA = {}
