"""Synthetic public transport checks; no native game, save, RNG, or remote IO."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import params
import policy
import run


def state(hp, decision='combat_play'):
    return {'decision': decision, 'context': {'act': 2, 'floor': 16, 'room_type': 'Boss'},
            'player': {'hp': hp, 'max_hp': 80, 'deck': [], 'relics': []},
            'enemies': [{'name': 'Visible Boss'}], 'round': 1,
            'victory': False, 'act': 2, 'floor': 16}


class PublicTransport:
    def __init__(self, states):
        self.states = iter(copy.deepcopy(states))
        self.actions = []

    def act(self, action, **args):
        self.actions.append((action, args))
        return next(self.states)

    def send(self, command):
        raise AssertionError('Non-player transport forbidden: ' + str(command))


class PublicCombatHpMetrics(unittest.TestCase):
    def setUp(self):
        self.flags = patch.dict(params.P, {'combat_hp_metrics': True,
            'search_on': False, 'sl_on': False, 'simeval_pick': False, 'simeval_route': False})
        self.flags.start()
        self.addCleanup(self.flags.stop)
        blocked = patch('subprocess.Popen', side_effect=AssertionError('Native process forbidden'))
        blocked.start()
        self.addCleanup(blocked.stop)

    def drive(self, hp_states, enabled=True):
        sim = PublicTransport(hp_states[1:])
        with patch.dict(params.P, {'combat_hp_metrics': enabled}), \
                patch.object(run, 'LOG_TURNS', False), patch.object(run, 'LOG_PLAYS', False), \
                patch.object(policy, 'decide', side_effect=lambda st, mem, sim:
                    ('select_cards', {'indices': []}) if st['decision'] == 'card_select' else ('end_turn', {})):
            result = run.drive(sim, copy.deepcopy(hp_states[0]), {}, combat_only=True)
        return result, sim.actions

    def test_death_endpoint_records_the_missing_fatal_hp_drop(self):
        result, _ = self.drive([state(50), state(45), state(0, 'game_over')])
        fight = result['combats'][0]
        self.assertEqual((fight['dmg'], fight['hp']), (5, 45))
        self.assertEqual(fight['hp_metrics']['sampled_loss'], 50)
        self.assertEqual(fight['hp_metrics']['net_loss'], 50)
        self.assertEqual(fight['hp_metrics']['end'], 0)
        self.assertFalse(result['win'])

    def test_survival_healing_has_separate_net_and_positive_drop_metrics(self):
        result, _ = self.drive([state(50), state(45), state(42, 'card_select'),
                                state(42), state(48, 'card_reward')])
        fight = result['combats'][0]
        self.assertEqual((fight['dmg'], fight['hp']), (8, 42))
        self.assertEqual(fight['hp_metrics']['sampled_loss'], 8)
        self.assertEqual(fight['hp_metrics']['net_loss'], 2)
        self.assertEqual(fight['hp_metrics']['observations'], 5)
        self.assertTrue(result['win'])

    def test_final_self_damage_and_net_gain_are_not_discarded(self):
        damaged, _ = self.drive([state(50), state(43, 'card_reward')])
        healed, _ = self.drive([state(50), state(56, 'card_reward')])
        self.assertEqual(damaged['combats'][0]['hp_metrics']['sampled_loss'], 7)
        self.assertEqual(healed['combats'][0]['hp_metrics']['net_loss'], -6)
        self.assertEqual(healed['combats'][0]['hp_metrics']['sampled_loss'], 0)

    def test_default_off_keeps_legacy_result_and_actions_identical(self):
        states = [state(50), state(45), state(0, 'game_over')]
        enabled, enabled_actions = self.drive(states, enabled=True)
        disabled, disabled_actions = self.drive(states, enabled=False)
        self.assertNotIn('hp_metrics', disabled['combats'][0])
        enabled['combats'][0].pop('hp_metrics')
        self.assertEqual(enabled, disabled)
        self.assertEqual(enabled_actions, disabled_actions)

    def test_missing_or_malformed_endpoint_is_incomplete(self):
        for hp in [None, True, -1, '0', float('nan')]:
            with self.subTest(hp=hp):
                result, _ = self.drive([state(50), state(hp, 'game_over')])
                metrics = result['combats'][0]['hp_metrics']
                self.assertFalse(metrics['complete'])
                self.assertIsNone(metrics['end'])
                self.assertIsNone(metrics['net_loss'])
                self.assertEqual(metrics['sampled_loss'], 0)

    def test_endpoint_without_prior_observation_cannot_invent_start(self):
        fight = {'dmg': 0, 'hp': 50}
        run.note_public_combat_hp(fight, state(0, 'game_over'), final=True)
        self.assertNotIn('hp_metrics', fight)


if __name__ == '__main__':
    unittest.main()
