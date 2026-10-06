"""Matriarch's fixed sleep/wake sequence from visible badges and intents only."""
from math import isfinite

_NEXT = {'SLASH_MOVE': 'DISEMBOWEL_MOVE',
         'DISEMBOWEL_MOVE': 'SLASH2_MOVE',
         'SLASH2_MOVE': 'SOUL_SIPHON_MOVE',
         'SOUL_SIPHON_MOVE': 'SLASH_MOVE'}


def future_moves(enemy, turns, projected_hp_damage=0):
    """Moves AFTER the currently displayed enemy turn, or None to defer.

    This covers visible Sleep and its projected damage-triggered wake only.
    A generic Stun is ambiguous (Whistle also stuns) and always defers.
    Badges are decremented at enemy turn end before the next intent is rolled.
    projected_hp_damage is candidate-local unblocked damage, never a real
    engine state change. No private move id, RNG, round or counter is read.
    """
    if enemy.get('name') != 'Lagavulin Matriarch': return None
    if type(turns) is not int or turns < 0: return None
    if type(projected_hp_damage) not in (int, float) or not isfinite(projected_hp_damage) or projected_hp_damage < 0:
        return None
    intents = enemy.get('intents') or []
    if len(intents) != 1: return None
    typ = str(intents[0].get('type', '')).lower()
    if typ != 'sleep': return None
    badges = [p for p in enemy.get('powers') or []
              if p.get('id') == 'ASLEEP_POWER'
              or str(p.get('name', '')).lower() == 'asleep']
    if len(badges) != 1: return None
    sleep = badges[0].get('amount')
    if type(sleep) is not int or not 1 <= sleep <= 3: return None
    # HP damage removes Asleep and replaces THIS turn with Stun.
    remaining = 0 if projected_hp_damage > 0 else sleep - 1
    out = []
    move = 'SLASH_MOVE'
    for _ in range(turns):
        if remaining:
            out.append('SLEEP_MOVE'); remaining -= 1
        else:
            out.append(move); move = _NEXT[move]
    return out
