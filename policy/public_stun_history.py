"""Stun follow-up proofs from completed public card actions, never native IDs."""
from policy.knowledge import cid

_PLAIN = {'STRIKE_IRONCLAD', 'ANGER', 'TWIN_STRIKE', 'BLUDGEON', 'BASH', 'WHISTLE'}


def _frame(st):
    ctx = st.get('context') or {}
    return (ctx.get('act'), ctx.get('floor'), ctx.get('encounter'), st.get('round'))


def _single(st):
    rows = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    return rows[0] if len(rows) == 1 else None


def _stunned(e):
    intents = e.get('intents') or []
    return len(intents) == 1 and str(intents[0].get('type', '')).lower() == 'stun'


def _amount(e, key):
    rows = [p for p in e.get('powers') or [] if str(p.get('id', '')).split('.')[-1] == key]
    if not rows: return 0
    if len(rows) != 1 or type(rows[0].get('amount')) is not int: return None
    return rows[0]['amount']


def observe_completed(before, action, args, after, memory):
    """Called after a successful real/public action, not candidate evaluation."""
    prior = memory.get('_public_stun_proof')
    e, f = _single(before), _single(after)
    if (after.get('type') == 'error' or after.get('decision') != 'combat_play'
            or before.get('decision') != 'combat_play' or e is None or f is None
            or _frame(before) != _frame(after) or e.get('name') != f.get('name')
            or e.get('index') != f.get('index') or not _stunned(f)):
        memory.pop('_public_stun_proof', None); return
    identity = (_frame(after), f.get('name'), f.get('index'), f.get('max_hp'))
    if prior and prior['identity'] == identity and _stunned(e):
        # MustPerformOnceBeforeTransitioning prevents subsequent stuns from
        # replacing this pending stun before its enemy turn completes.
        return
    memory.pop('_public_stun_proof', None)
    # A new Shriek/Asleep callback cannot replace an already pending stun.
    # Removing the badge in that state is not a proof of its saved follow-up.
    if _stunned(e): return
    if action != 'play_card': return
    cards = [c for c in before.get('hand') or [] if c.get('index') == args.get('card_index')]
    if len(cards) != 1 or cid(cards[0]) not in _PLAIN: return
    c = cards[0]
    if c.get('enchantment') or c.get('affliction'): return
    if args.get('target_index', e.get('index')) != e.get('index'): return
    if type(e.get('hp')) is not int or type(f.get('hp')) is not int or not 0 < f['hp'] < e['hp']: return
    move = None; cause = None
    shriek = _amount(e, 'SHRIEK_POWER')
    if (f.get('name') == 'Terror Eel' and f.get('max_hp') == 150
            and shriek is not None and shriek > 0 and f['hp'] <= shriek
            and _amount(f, 'SHRIEK_POWER') == 0):
        move = 'TERROR_MOVE'; cause = 'completed_plain_attack_crossed_visible_shriek'
    asleep = _amount(e, 'ASLEEP_POWER')
    if (f.get('name') == 'Lagavulin Matriarch' and f.get('max_hp') == 233 and asleep is not None and asleep > 0
            and _amount(f, 'ASLEEP_POWER') == 0):
        move = 'SLASH_MOVE'; cause = 'completed_plain_attack_removed_visible_asleep'
    if move:
        memory['_public_stun_proof'] = dict(identity=identity, next_move=move, cause=cause)


def followup(st, memory):
    e = _single(st); proof = (memory or {}).get('_public_stun_proof')
    if e is None or proof is None or not _stunned(e): return None
    identity = (_frame(st), e.get('name'), e.get('index'), e.get('max_hp'))
    return proof['next_move'] if proof['identity'] == identity else None
