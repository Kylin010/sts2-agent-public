"""Possible current moves from visible intent shapes and public turn history.

No actual move_id, future move, RNG or hidden counters. Shapes deliberately
retain damage ambiguity when unreviewed modifiers prevent exact inversion.
"""
from policy import foresight


def candidates(enemy):
    model = foresight.BY_NAME.get(enemy.get('name'))
    if model is None: return None
    intents = enemy.get('intents')
    if not isinstance(intents, list) or not intents: return None
    shape = []
    for intent in intents:
        if not isinstance(intent, dict): return None
        kind = str(intent.get('type', '')).lower()
        hits = intent.get('hits', 1)
        if type(hits) is not int or hits < 1: return None
        if kind == 'stun': return None
        shape.append((kind, hits if kind == 'attack' else 1))
    possible = []
    for key, move in model.get('moves', {}).items():
        sig = [(kind, int(hits) if kind == 'attack' else 1)
               for kind, damage, hits in foresight._move_sig(move)]
        if sig == shape: possible.append(key)
    return tuple(sorted(possible)) if possible else None


def _frame(st):
    ctx = st.get('context') or {}
    return ctx.get('act'), ctx.get('floor'), ctx.get('encounter'), st.get('round')


def _single(st):
    rows = [e for e in st.get('enemies') or [] if e.get('hp', 0) > 0]
    return rows[0] if len(rows) == 1 else None


# Only these source-reviewed deterministic cycles have no surviving-enemy
# reactive move changes. Generic KB successors are not public history proof.
HISTORY_NAMES = {'The Insatiable', 'Cubex Construct', 'Kin Priest'}
PLAIN_CARDS = {'STRIKE_IRONCLAD', 'STRIKE', 'ANGER', 'TWIN_STRIKE', 'BLUDGEON',
               'BASH', 'DEFEND_IRONCLAD', 'DEFEND'}


def _identity(e):
    return e.get('name'), e.get('index'), e.get('max_hp')


def _prior(st, enemy, memory):
    prior = (memory or {}).get('_public_move_belief')
    if (isinstance(prior, dict) and prior.get('frame') == _frame(st)
            and prior.get('identity') == _identity(enemy)
            and enemy.get('name') in HISTORY_NAMES):
        return prior.get('keys')
    return None


def _next(enemy, keys):
    model = foresight.BY_NAME.get(enemy.get('name'))
    result = set()
    for key in keys:
        move = model.get('moves', {}).get(key)
        if not move: return set()
        nxt = move.get('next')
        # No guesses about private conditions or random branch probabilities.
        if nxt not in model.get('moves', {}): return set()
        result.add(nxt)
    return result


def observe_completed(before, action, args, after, memory):
    """Called after one actual action returns, never from a hypothetical score."""
    e, f = _single(before), _single(after)
    memory_before = dict(memory)
    memory.pop('_public_move_belief', None)
    if (e is None or f is None or before.get('decision') != 'combat_play'
            or after.get('decision') != 'combat_play' or after.get('type') == 'error'
            or _identity(e) != _identity(f) or f.get('name') not in HISTORY_NAMES):
        return
    frame_b, frame_a = _frame(before), _frame(after)
    if any(x is None for x in frame_b) or type(e.get('max_hp')) is not int or e['max_hp'] <= 0: return
    keys, old_ui = candidates(f), candidates(e)
    if not keys or not old_ui: return
    prior_keys = _prior(before, e, memory_before) or old_ui
    if (action == 'end_turn' and frame_b[:3] == frame_a[:3]
            and type(frame_b[3]) is int and frame_a[3] == frame_b[3] + 1):
        successors = _next(e, prior_keys)
        narrowed = set(keys) & successors
        if not narrowed: return  # stale/inconsistent graph cannot certify a move
        keys = tuple(sorted(narrowed))
    elif action == 'play_card' and frame_a == frame_b:
        card = next((c for c in before.get('hand') or []
                     if c.get('index') == args.get('card_index')), None)
        if (not card or str(card.get('id', '')).replace('CARD.', '') not in PLAIN_CARDS
                or card.get('enchantment') or card.get('affliction')
                or any(ch in str(card.get('spec', '')) for ch in '#!%')):
            return
        narrowed = set(keys) & set(prior_keys)
        if not narrowed: return
        keys = tuple(sorted(narrowed))
    else:
        return  # gaps, unknown actions, extra turns: forget historical evidence
    memory['_public_move_belief'] = dict(frame=frame_a, identity=_identity(f), keys=keys)


def unique_move(st, enemy, memory=None):
    keys = candidates(enemy)
    if keys is None: return None
    prior = _prior(st, enemy, memory)
    if prior:
        keys = tuple(sorted(set(keys) & set(prior)))
    return keys[0] if len(keys) == 1 else None
