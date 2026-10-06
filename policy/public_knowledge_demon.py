"""Knowledge Demon's completed curse stages inferred from public effects only.

Source: slots Disintegration6/MindRot1, Disintegration7/Sloth3,
Disintegration8/WasteAway1. Artifact can suppress a selected effect. Missing
badges therefore do not prove a curse has not happened. No native counter,
round number, real RNG, move-after-current field, or future action is read.
"""
from itertools import product

_IDS=('DISINTEGRATION_POWER','MIND_ROT_POWER','SLOTH_POWER','WASTE_AWAY_POWER')
_SLOTS=(((0,6),(1,1),None),((0,7),(2,3),None),((0,8),(3,1),None))
_OBSERVATIONS={}
for stage in range(4):
    for choices in product(*_SLOTS[:stage]):
        amounts=[0]*4
        for selected in choices:
            if selected is not None:amounts[selected[0]]+=selected[1]
        _OBSERVATIONS.setdefault(tuple(amounts),set()).add(stage)


def possible_curse_stages(public_player_powers):
    """Consistent completed stages; None means missing/malformed/contradictory.

    () is never used to imply zero. A public effect proving the third slot
    yields (3,); earlier effects can remain ambiguous because of Artifact.
    """
    if public_player_powers is None:return None
    amounts=[0]*4;seen=set()
    for power in public_player_powers:
        ident=str(power.get('id','')).split('.')[-1]
        if ident not in _IDS:continue
        if ident in seen:return None
        value=power.get('amount')
        if type(value)is not int or value<=0:return None
        seen.add(ident);amounts[_IDS.index(ident)]=value
    stages=_OBSERVATIONS.get(tuple(amounts))
    return tuple(sorted(stages))if stages else None
