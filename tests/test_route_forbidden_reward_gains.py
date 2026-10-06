"""Source-defined unavailable rewards must not finance a projected route."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from params import P
from policy import route, deckeval, elites, combos, learn


def player(*relics):
    return {'hp': 100, 'max_hp': 100, 'gold': 40, 'deck': [],
            'relics': [{'id': 'RELIC.' + name} for name in relics],
            'potions': [{'name': 'Existing Potion'}]}


class ForbiddenRewardGains(unittest.TestCase):
    def setUp(self):
        flags = patch.dict(P, {'route_forbidden_reward_gains': True,
            'route_forbidden_reward_gains_acts': [2], 'route_ready_on': False,
            'route_survival': False, 'deck_mc': False, 'simeval_route': False,
            'route_body_slam_strength': False, 'route_entry_relic_heal': False,
            'route_deck_gamma': 0, 'route_elite_bonus': [0, 0, 0],
            'route_v_gold': .2, 'route_v_potion': 5,
            'route_v_shop': 20, 'route_shop_cap': 1, 'route_shop_min_gold': 50})
        flags.start(); self.addCleanup(flags.stop)
        native = patch('subprocess.Popen', side_effect=AssertionError('Native process forbidden'))
        native.start(); self.addCleanup(native.stop)

    def score(self, kinds, owned):
        rows = [[{'col': 0, 'row': i + 1, 'type': kind,
                  'children': [{'col': 0, 'row': i + 2}]}] for i, kind in enumerate(kinds)]
        graph = {'rows': rows, 'boss': {'col': 0, 'row': len(kinds) + 1}}
        state = {'context': {'act': 2}, 'player': owned, 'choices': [{'col': 0, 'row': 1}]}
        before = copy.deepcopy(state); mem = {'act_fights': {2: 2}}
        with patch.object(deckeval, 'evaluate', return_value=dict(dmg_per_turn=30, block_per_turn=20, scaling=0, aoe=0)), \
             patch.object(elites, 'dist', return_value={}), \
             patch.object(elites, 'aoe_capacity', return_value=0), \
             patch.object(combos, 'score', return_value=(0, [], [])), \
             patch.object(learn, 'pick', side_effect=lambda kind, options, st, mem: max(options, key=lambda x: x[1])[0]):
            route.choose(graph, state, mem)
        self.assertEqual(state, before)
        return mem['route_scores'][(0, 1)]

    def test_known_prohibitions_stack_without_erasing_other_rewards(self):
        plain = route._combat_reward_amounts(player(), 2)
        ecto = route._combat_reward_amounts(player('ECTOPLASM'), 2)
        sozu = route._combat_reward_amounts(player('SOZU'), 2)
        both = route._combat_reward_amounts(player('ECTOPLASM', 'SOZU'), 2)
        self.assertEqual(plain, dict(monster_gold=11, elite_gold=30, monster_potion=.4, elite_potion=.52))
        self.assertEqual((ecto['monster_gold'], ecto['elite_gold']), (0, 0))
        self.assertEqual(ecto['elite_potion'], plain['elite_potion'])
        self.assertEqual((sozu['monster_potion'], sozu['elite_potion']), (0, 0))
        self.assertEqual(sozu['elite_gold'], plain['elite_gold'])
        self.assertTrue(all(value == 0 for value in both.values()))

    def test_disabled_or_other_acts_preserve_legacy_amounts(self):
        expected = route._combat_reward_amounts(player(), 2)
        for act in [1, 3]:
            self.assertEqual(route._combat_reward_amounts(player('ECTOPLASM', 'SOZU'), act), expected)
        with patch.dict(P, {'route_forbidden_reward_gains': False}):
            self.assertEqual(route._combat_reward_amounts(player('ECTOPLASM', 'SOZU'), 2), expected)
        self.assertEqual(route._combat_reward_amounts(player('UNREVIEWED_RELIC'), 2), expected)

    def test_direct_and_unknown_fights_drop_only_forbidden_gold_value(self):
        kinds = ['Monster', 'Elite', 'Unknown']; owned = player('ECTOPLASM')
        with patch.dict(P, {'route_forbidden_reward_gains': False}):
            old = self.score(kinds, owned)
        new = self.score(kinds, owned)
        # The question mark also has a 3% shop branch: impossible prior gold
        # otherwise inflates that branch's spending budget from 40 to 81.
        self.assertAlmostEqual(old - new, .2 * (11 + 30 + .1 * 11) + .03 * 20 * 31 / 150)

    def test_existing_money_is_preserved_but_impossible_new_gold_cannot_fund_shop(self):
        owned = player('ECTOPLASM')
        with patch.dict(P, {'route_forbidden_reward_gains': False}):
            old = self.score(['Monster', 'Shop'], owned)
        new = self.score(['Monster', 'Shop'], owned)
        # 40 existing gold stays 40, rather than being forecast as 51 (>50 shop threshold).
        self.assertAlmostEqual(old - new, .2 * 11 + 20 / 150)
        self.assertEqual(owned['gold'], 40)

    def test_sozu_keeps_existing_potion_risk_relief_and_other_route_values(self):
        owned = player('SOZU')
        with patch.dict(P, {'route_forbidden_reward_gains': False}):
            old = self.score(['Monster', 'Elite', 'Unknown'], owned)
        new = self.score(['Monster', 'Elite', 'Unknown'], owned)
        self.assertAlmostEqual(old - new, 5 * (.4 + .52))
        self.assertEqual(owned['potions'], [{'name': 'Existing Potion'}])

    def test_unaffected_relics_and_noncombat_choices_keep_exact_scores(self):
        for owned in [player(), player('PUMPKIN_CANDLE')]:
            with patch.dict(P, {'route_forbidden_reward_gains': False}):
                old = self.score(['Monster', 'Elite', 'Unknown'], owned)
            self.assertEqual(self.score(['Monster', 'Elite', 'Unknown'], owned), old)
        owned = player('ECTOPLASM', 'SOZU')
        with patch.dict(P, {'route_forbidden_reward_gains': False}):
            old = self.score(['Shop', 'RestSite', 'Treasure'], owned)
        self.assertEqual(self.score(['Shop', 'RestSite', 'Treasure'], owned), old)


if __name__ == '__main__':
    unittest.main()
