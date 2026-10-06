"""Public room-entry mechanics and route choice regression, without native IO."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb; require_kb(__name__)
from params import P
from policy import route, deckeval, elites, combos, learn, rest


def player(*relics, cards=20):
    return {'hp': 36, 'max_hp': 80, 'gold': 0,
            'deck': [{'id': 'CARD.DEFEND_IRONCLAD'} for _ in range(cards)],
            'relics': [{'id': rid} for rid in relics], 'potions': []}


class RouteEntryRelicHealing(unittest.TestCase):
    def setUp(self):
        self.params = patch.dict(P, {'route_entry_relic_heal': True,
                                    'route_entry_relic_heal_acts': [2]})
        self.params.start()
        self.addCleanup(self.params.stop)
        self.native = patch('subprocess.Popen', side_effect=AssertionError('Native IO forbidden'))
        self.native.start()
        self.addCleanup(self.native.stop)

    def test_ticket_heals_before_shop_risk_without_requiring_gold(self):
        pl = player('RELIC.MEAL_TICKET')
        self.assertEqual(route._project_entry_hp(36, 80, 'Shop', pl, 2), 51)
        self.assertEqual(route._project_entry_hp(77, 80, 'Shop', pl, 2), 80)
        self.assertEqual(route._project_entry_hp(36, 80, 'Unknown', pl, 2), 36)

    def test_feather_counts_full_groups_of_five_public_cards(self):
        for count, amount in [(4, 0), (5, 3), (9, 3), (10, 6), (24, 12), (25, 15)]:
            with self.subTest(cards=count):
                pl = player('ETERNAL_FEATHER', cards=count)
                before = copy.deepcopy(pl)
                self.assertEqual(route._entry_relic_heal('RestSite', pl), amount)
                self.assertEqual(pl, before)
        self.assertEqual(route._project_entry_hp(75, 80, 'RestSite', player('ETERNAL_FEATHER'), 2), 80)

    def test_missing_relic_and_other_room_do_not_create_healing(self):
        self.assertEqual(route._project_entry_hp(36, 80, 'Shop', player(), 2), 36)
        self.assertEqual(route._project_entry_hp(36, 80, 'Monster', player('MEAL_TICKET'), 2), 36)
        self.assertEqual(route._entry_relic_heal('Shop', player('ETERNAL_FEATHER')), 0)
        self.assertEqual(route._entry_relic_heal('RestSite', player('MEAL_TICKET')), 0)

    def test_disabled_and_other_acts_preserve_projection(self):
        pl = player('MEAL_TICKET')
        with patch.dict(P, {'route_entry_relic_heal': False}):
            self.assertEqual(route._project_entry_hp(36, 80, 'Shop', pl, 2), 36)
        for act in [1, 3]:
            self.assertEqual(route._project_entry_hp(36, 80, 'Shop', pl, act), 36)
        with patch.dict(P, {'route_entry_relic_heal_acts': [1, 2, 3]}):
            self.assertEqual(route._project_entry_hp(36, 80, 'Shop', pl, 3), 51)

    def test_negative_projection_is_not_revived_by_entry_effect(self):
        pl = player('MEAL_TICKET', 'ETERNAL_FEATHER')
        for hp in [-10, 0]:
            for room in ['Shop', 'RestSite']:
                self.assertEqual(route._project_entry_hp(hp, 80, room, pl, 2), hp)

    def test_feather_entry_precedes_nonboss_camp_decision(self):
        pl = player('ETERNAL_FEATHER')
        pl['hp'] = 39
        projected = route._project_entry_hp(pl['hp'], 80, 'RestSite', pl, 2)
        self.assertEqual(projected, 51)
        st = {'context': {'act': 2}, 'player': {**pl, 'hp': projected},
              'options': [{'option_id': 'HEAL', 'index': 0}, {'option_id': 'SMITH', 'index': 1}]}
        with patch.dict(P, {'rest_mode': 'rule', 'rest_boss_sim': False,
                            'rest_potion_smith': False, 'heal_below': .55,
                            'heal_below_a23': None}), \
                patch.object(rest.longterm, 'rest_choice', return_value=None):
            self.assertEqual(rest._rule(st, {'next_is_boss': False}), 1)

    def test_visible_shop_treasure_fork_changes_only_for_owned_ticket(self):
        graph = {'rows': [[
            {'col': 0, 'row': 1, 'type': 'Shop', 'children': [{'col': 0, 'row': 2}]},
            {'col': 1, 'row': 1, 'type': 'Treasure', 'children': [{'col': 0, 'row': 2}]},
        ]], 'boss': {'col': 0, 'row': 2}}
        st = {'context': {'act': 2}, 'player': player('MEAL_TICKET'),
              'choices': [{'col': 0, 'row': 1}, {'col': 1, 'row': 1}]}
        before = copy.deepcopy(st)
        with patch.dict(P, {'route_ready_on': False, 'route_survival': False,
                            'deck_mc': False, 'simeval_route': False,
                            'route_deck_gamma': 0, 'route_dmg_boss': [55, 55, 55],
                            'route_v_relic': 25, 'route_v_boss_hp': .6}), \
                patch.object(deckeval, 'evaluate', return_value={
                    'dmg_per_turn': 30, 'block_per_turn': 20, 'scaling': 0, 'aoe': 0}), \
                patch.object(elites, 'dist', return_value={}), \
                patch.object(elites, 'aoe_capacity', return_value=0), \
                patch.object(combos, 'score', return_value=(0, [], [])), \
                patch.object(learn, 'pick', side_effect=lambda kind, opts, st, mem: max(opts, key=lambda x: x[1])[0]):
            with patch.dict(P, {'route_entry_relic_heal': False}):
                legacy = route.choose(graph, st, {})
            candidate = route.choose(graph, st, {})
            no_ticket = copy.deepcopy(st)
            no_ticket['player']['relics'] = []
            without = route.choose(graph, no_ticket, {})
        self.assertEqual(legacy['col'], 1)
        self.assertEqual(candidate['col'], 0)
        self.assertEqual(without['col'], 1)
        self.assertEqual(st, before)


if __name__ == '__main__':
    unittest.main()
