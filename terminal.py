"""Verify full-run wins against the fights actually observed by the driver."""


def victory_evidence(state, combats, ascension=10):
    """A segmented clear or one A10 final boss is never a full-run victory."""
    required = 2 if ascension >= 10 else 1
    floors = sorted({c['floor'] for c in combats
                     if c.get('act') == 3 and c.get('room') == 'Boss'
                     and type(c.get('floor')) is int and c['floor'] > 0})
    result = dict(verified=False, required_final_bosses=required,
                  observed_final_bosses=len(floors), final_boss_floors=floors)
    if state.get('decision') != 'game_over' or state.get('victory') is not True:
        result['reason'] = 'no_terminal_victory'
    elif (state.get('act') or (state.get('context') or {}).get('act')) != 3:
        result['reason'] = 'victory_before_final_act'
    elif len(floors) < required:
        result['reason'] = 'missing_final_boss_fights'
    elif (state.get('player') or {}).get('hp', 0) <= 0:
        result['reason'] = 'victory_without_living_player'
    else:
        result.update(verified=True, reason='terminal_and_required_final_boss_fights')
    return result
