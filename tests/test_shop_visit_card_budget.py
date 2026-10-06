"""Regression coverage for replanning within one shop; no native game IO."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from params import P
from policy import shop


def state():
    return {
        'context': {'act': 2},
        'player': {'gold': 100, 'deck': [], 'relics': [], 'potions': [], 'potion_slots': 2},
        'cards': [{'index': i, 'id': 'CARD.TEST_' + str(i), 'cost': 1,
                   'is_stocked': True, 'type': 'Skill'} for i in range(4)],
        'relics': [], 'potions': [],
    }


class ShopVisitBudget(unittest.TestCase):
    def setUp(self):
        mocks = [
            patch.dict(P, {'shop_max_cards': 2, 'shop_visit_card_cap': True,
                          'shop_mode': 'calibrated', 'shop_card_min': .5,
                          'shop_card_unit': 1, 'shop_v_gold': .01, 'core_w': 0}),
            patch.object(shop.rewards, 'value', return_value=10),
            patch.object(shop.pickmodel, 'with_relics', side_effect=lambda deck, st: list(deck)),
            patch.object(shop.pickmodel, 'available', return_value=True),
            patch.object(shop.pickmodel, 'utility', return_value=10),
            patch.object(shop.pickmodel, 'skip_utility', return_value=0),
            patch.object(shop.valuemodel, 'available', return_value=True),
            patch.object(shop.valuemodel, 'state_of', side_effect=lambda st: {
                'gold': st['player']['gold'], 'deck': list(st['player']['deck']),
                'relics': [], 'pots': 0}),
            patch.object(shop.valuemodel, 'with_card', side_effect=lambda s, i: {
                **s, 'deck': s['deck'] + [i]}),
            patch.object(shop.valuemodel, 'win_prob', side_effect=lambda s:
                len(s['deck']) * .05 + len(s['relics']) * .05 + s['pots'] * .05
                - (100 - s['gold']) * .0001),
            patch('subprocess.Popen', side_effect=AssertionError('Native process forbidden')),
        ]
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def visit(self, mem=None):
        st = state()
        mem = {} if mem is None else mem
        bought = []
        for _ in range(8):
            action, args = shop.decide(st, mem)
            if action == 'leave_room':
                return bought, mem
            self.assertEqual(action, 'buy_card')
            card = next(c for c in st['cards'] if c['index'] == args['card_index'])
            self.assertTrue(card['is_stocked'])
            card['is_stocked'] = False
            st['player']['gold'] -= card['cost']
            st['player']['deck'].append(copy.deepcopy(card))
            bought.append(card['index'])
        self.fail('Shop did not finish')

    def test_replanning_stops_after_two_cards_in_both_modes(self):
        for mode in ('calibrated', 'value'):
            with self.subTest(mode=mode), patch.dict(P, {'shop_mode': mode}):
                bought, mem = self.visit()
                self.assertEqual(len(bought), 2)
                self.assertNotIn('shop_done', mem)

    def test_disabled_keeps_legacy_replanning_in_both_modes(self):
        for mode in ('calibrated', 'value'):
            with self.subTest(mode=mode), patch.dict(P, {'shop_mode': mode, 'shop_visit_card_cap': False}):
                bought, _ = self.visit()
                self.assertEqual(len(bought), 4)

    def test_next_shop_gets_a_new_budget(self):
        bought, mem = self.visit()
        again, mem = self.visit(mem)
        self.assertEqual((len(bought), len(again)), (2, 2))
        self.assertNotIn('shop_done', mem)

    def test_spent_card_budget_keeps_remove_relic_potion_available(self):
        st = state()
        st['card_removal_cost'] = 1
        st['player']['deck'] = [{'id': 'CARD.STRIKE_IRONCLAD'}]
        st['relics'] = [{'index': 0, 'id': 'RELIC.TEST', 'cost': 1}]
        st['potions'] = [{'index': 0, 'cost': 1}]
        done = {('card', 10), ('card', 11)}
        with patch.object(shop, 'remove_value', return_value=(10, 'STRIKE_IRONCLAD')), \
                patch.object(shop, 'relic_value', return_value=10), \
                patch.dict(P, {'shop_v_potion': 10, 'potion_key_on': False}):
            kinds = {x[0] for x in shop.plan(st, done)}
        self.assertEqual(kinds, {'remove', 'relic', 'potion'})

    def test_value_mode_respects_zero_and_remaining_bundle_budget(self):
        st = state()
        self.assertEqual(sum(x[0] == 'card' for x in shop.plan_value(st, {('card', 10)})), 1)
        self.assertEqual(shop.plan_value(st, {('card', 10), ('card', 11)}), ())
        with patch.dict(P, {'shop_max_cards': 0}):
            self.assertEqual(shop.plan(st), ())
            self.assertEqual(shop.plan_value(st), ())

    def test_noncard_ledger_entries_do_not_consume_card_budget(self):
        done = {('remove', None), ('relic', 0), ('potion', 1)}
        self.assertEqual(shop.remaining_card_budget(done), 2)
        self.assertEqual(sum(x[0] == 'card' for x in shop.plan(state(), done)), 2)


if __name__ == '__main__':
    unittest.main()
