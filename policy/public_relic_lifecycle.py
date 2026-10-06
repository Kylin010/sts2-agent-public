"""Only visible wax/melted flags may restore lifecycle in an independent model."""
import json
from pathlib import Path
_USED_UP = set(json.loads(Path(__file__).with_name('public_used_up_relics.json').read_text()))
_USED_UP_IN_COMBAT = {'LIZARD_TAIL', 'BONE_TEA'}   # 源码：AfterPreventingDeath / AfterPlayerTurnStart


def model_flags(relics):
    """None means the old UI export cannot prove the lifecycle for this root.

    Status alone is insufficient: Disabled can mean used-up rather than melted.
    Active ToyBox needs its own public lifetime proof; do not reset its private
    combat count to a guessed value merely to make a model root match.
    """
    if not isinstance(relics, list): return None
    result = {}
    for relic in relics:
        key = str(relic.get('id') or '').replace('RELIC.', '')
        if not key or key in result: return None
        if type(relic.get('is_wax')) is not bool or type(relic.get('is_melted')) is not bool:
            return None
        if relic['is_melted'] and not relic['is_wax']: return None
        # 10/5 主线：玩具盒只在 AfterCombatEnd 计数 / 融化蜡制遗物，战斗中不起任何作用；推演停在选卡奖励前，
        # 它的私有计数不影响战斗结果（界面计数 = CombatsSeen % 3 也是公开的）。原来遇到玩具盒整局不推演（2 局里 843 次摆不出）
        if key == 'TOY_BOX':
            result[key] = {'is_wax': relic['is_wax'], 'is_melted': relic['is_melted']}; continue
        # These native hooks consult IsUsedUp, not Status. Until the model can
        # derive the corresponding consumed state, a gray icon is not enough.
        # 10/5 主线：只有战斗中会起作用的才挡（蜥蜴尾巴 = 濒死复活、骨茶 = 回合开始）；其余在进房间 / 战斗开始前 / 战斗后 / 商店起作用，
        # 推演是战斗中重摆、停在选卡奖励前，用不用完不影响（原来带茶类遗物用完后整局不推演）
        # 引擎 p29 起：骨茶 / 蜥蜴尾巴按公开的灰图标（Disabled）设回「用完」，不再需要挡（_USED_UP_IN_COMBAT 只作记录）
        result[key] = {'is_wax': relic['is_wax'], 'is_melted': relic['is_melted']}
    return result
