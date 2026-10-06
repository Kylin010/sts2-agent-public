"""Marginal Body Slam damage in a public, energy-limited five-card hand model.

This estimates one component of route strength, not an entire combat. Only
card IDs/upgrades and static card knowledge are inputs. The sampler owns its
random stream and canonicalizes card order; no native state or run seed exists.
"""
from functools import lru_cache
import random
from policy import kb

# Source-checked printed block amounts. Draw/retaliation/setup benefits are
# outside this component, while True Grit's in-hand exhaustion is modeled.
BLOCK = {'DEFEND_IRONCLAD': (5, 8), 'TRUE_GRIT': (7, 9),
         'SHRUG_IT_OFF': (8, 11), 'IRON_WAVE': (5, 7),
         'ULTIMATE_DEFEND': (11, 15), 'FLAME_BARRIER': (12, 16)}
FIXED_ATTACK = {'STRIKE_IRONCLAD': (6, 9), 'BASH': (8, 10), 'IRON_WAVE': (5, 7)}


def effect(ident, upgraded=False):
    """(id, energy cost, damage, block, exhaustion). Opaque cards are fillers."""
    if ident == 'BODY_SLAM':
        return (ident, 0 if upgraded else 1, 0.0, 0, '')
    entry = kb.card(ident)
    cost = entry.get('cost')
    block = BLOCK.get(ident, (0, 0))[int(bool(upgraded))]
    if not isinstance(cost, int) or cost < 0:
        return (ident, 99, 0.0, 0, '')
    # Conditional attack availability, repeated upgrades and self-damage are
    # outside the abstract target/HP model; do not invent plays for them.
    if ident in ('CLASH', 'SEARING_BLOW') or entry.get('self_hp'):
        damage = 0.0
    elif ident in FIXED_ATTACK:
        damage = float(FIXED_ATTACK[ident][int(bool(upgraded))])
    elif entry.get('type') == 'Attack':
        damage = float(entry.get('damage') or 0) * (entry.get('hits') or 1) * (1.3 if upgraded else 1)
    else:
        damage = 0.0
    if not block and not damage:
        cost = 99
    exhaust = ('choose' if upgraded else 'random') if ident == 'TRUE_GRIT' else ''
    return (ident, cost, damage, block, exhaust)


def hand_damage(hand, energy=3, allow_slam=True):
    """Max expected damage under the shared energy budget and legal Grit burns.

    A damage target with enough HP, zero modifiers and zero initial block is
    assumed. Drawn/generated cards and power setup are deliberately omitted.
    """
    @lru_cache(maxsize=None)
    def best(mask, remaining_energy, block):
        result = 0.0       # Ending the abstract hand is always an option.
        for index, card in enumerate(hand):
            if not mask & (1 << index):
                continue
            ident, cost, damage, gain, exhaust = card
            if cost > remaining_energy or (ident == 'BODY_SLAM' and not allow_slam):
                continue
            left = mask ^ (1 << index)
            next_energy = remaining_energy - cost
            next_block = block + gain
            dealt = block if ident == 'BODY_SLAM' else damage
            targets = [j for j in range(len(hand)) if left & (1 << j)]
            if exhaust and targets:
                continuations = [best(left ^ (1 << j), next_energy, next_block) for j in targets]
                follow = max(continuations) if exhaust == 'choose' else sum(continuations) / len(continuations)
            else:
                follow = best(left, next_energy, next_block)
            result = max(result, dealt + follow)
        return result

    return best((1 << len(hand)) - 1, energy, 0)


@lru_cache(maxsize=512)
def _increment(signature, samples, energy):
    if not signature or not any(ident == 'BODY_SLAM' for ident, _ in signature):
        return 0.0
    if any(ident == 'NORMALITY' for ident, _ in signature):
        return 0.0         # Card-play limits need their own temporal model.
    cards = tuple(effect(ident, upgraded) for ident, upgraded in signature)
    if not any(card[3] for card in cards):
        return 0.0
    rng = random.Random(20261005)       # Independent stream; never game RNG.
    total = 0.0
    for _ in range(samples):
        hand = tuple(rng.sample(cards, min(5, len(cards))))
        total += max(0.0, hand_damage(hand, energy, True) - hand_damage(hand, energy, False))
    return total / samples


def increment(deck, samples=160, energy=3):
    signature = tuple(sorted((str(c.get('id') or '').removeprefix('CARD.').rstrip('+'),
                              bool(c.get('upgraded')) or str(c.get('id') or '').endswith('+'))
                             for c in deck))
    return _increment(signature, max(1, int(samples)), max(0, int(energy)))
