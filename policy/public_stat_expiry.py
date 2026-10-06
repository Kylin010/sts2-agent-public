"""Visible temporary stat expiry rules, source v0.111.0.

resolve_subphase is a composable amount subphase, not a full end-turn simulator.
It must not certify unrelated power/relic/card listeners or pre-phase damage.
"""

RULES = {
    'ANTICIPATE_POWER': ('dex', 1), 'COORDINATE_POWER': ('str', 1),
    'CRUSH_UNDER_POWER': ('str', -1), 'DARK_SHACKLES_POWER': ('str', -1),
    'DYING_STAR_POWER': ('str', -1), 'ENFEEBLING_TOUCH_POWER': ('str', -1),
    'FADE_POWER': ('dex', 1), 'FEEDING_FRENZY_POWER': ('str', 1),
    'FLEX_POTION_POWER': ('str', 1), 'HELICAL_DART_POWER': ('dex', 1),
    'MANGLE_POWER': ('str', -1), 'MONARCHS_GAZE_STRENGTH_DOWN_POWER': ('str', -1),
    'PIERCING_WAIL_POWER': ('str', -1), 'REPTILE_TRINKET_POWER': ('str', 1),
    'SETUP_STRIKE_POWER': ('str', 1), 'SHACKLING_POTION_POWER': ('str', -1),
    'SPEED_POTION_POWER': ('dex', 1),
}


def _id(power):
    return str(power.get('id', '')).split('.')[-1]


def negative_strength_return(powers):
    """Known negative temporary Strength restored after THIS owner's turn.

    Positive Strength is a buff, so Artifact does not block restoration.
    An existing positive temporary Strength makes this narrow estimate defer.
    A missing/bad recognized counter is never silently replaced by a guess.
    """
    total = 0; seen = set()
    for p in powers or []:
        key = _id(p); rule = RULES.get(key)
        if not key and str(p.get('name', '')).lower() not in ('strength', 'dexterity', 'artifact'):
            return None             # name-only unknown badges may be temporary
        if rule is None or rule[0] != 'str': continue
        amount = p.get('amount')
        if key in seen or type(amount) is not int or amount <= 0: return None
        seen.add(key)
        if rule[1] > 0: return None
        total += amount
    return total


def resolve_subphase(powers, *, order_is_public=False, helmet='absent'):
    """Apply only recognized expiry commands in public icon order.

    Base Strength/Dexterity already include applied temporary contributions.
    helmet: absent/used/unused/unknown; any claimed used state must come from
    completed public history. No internal UsedThisCombat flag is inspected.
    Other listeners are returned as unhandled, never certified harmless.
    """
    if helmet not in ('absent', 'used', 'unused', 'unknown'): return None
    core = {'STRENGTH_POWER': 'str', 'DEXTERITY_POWER': 'dex', 'ARTIFACT_POWER': 'artifact'}
    names = {'strength': 'str', 'dexterity': 'dex', 'artifact': 'artifact'}
    state = {'str': 0, 'dex': 0, 'artifact': 0}; seen = set(); expiries = []; unhandled = []
    for p in powers or []:
        key = _id(p); stat = core.get(key) or names.get(str(p.get('name', '')).lower())
        if stat:
            amount = p.get('amount')
            if stat in seen or type(amount) is not int or (stat == 'artifact' and amount < 0): return None
            seen.add(stat); state[stat] = amount
        elif key in RULES:
            amount = p.get('amount')
            if key in seen or type(amount) is not int or amount <= 0: return None
            seen.add(key); expiries.append((key, amount))
        else:
            unhandled.append(key or p.get('name'))
    if len(expiries) > 1 and order_is_public is not True: return None
    trace = []; initial = dict(state)
    for key, amount in expiries:
        stat, sign = RULES[key]; change = -sign * amount; blocked = False
        if change < 0 and state['artifact'] > 0:
            state['artifact'] -= 1; change = 0; blocked = True
        if change > 0 and stat == 'str':
            if helmet == 'unknown': return None
            if helmet == 'unused': change *= 2; helmet = 'used'
        state[stat] += change
        trace.append({'power': key, 'stat': stat, 'change': change, 'blocked_by_artifact': blocked})
    return {'after': state, 'delta': {k: state[k] - initial[k] for k in state},
            'expired': [key for key, _ in expiries], 'trace': trace,
            'helmet': helmet, 'unhandled_power_ids': unhandled,
            'scope': 'recognized stat-expiry amount subphase only'}
