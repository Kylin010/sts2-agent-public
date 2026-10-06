"""Fairness regression checks using doubles; no native engine or save/load."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import params
import policy
import sim
from policy import search


class EngineDouble:
    broken = False
    rec = None

    def __init__(self, overrides):
        self.overrides = overrides

    def send(self, command):
        replies = dict(shuffle_draw=dict(type='ok', draw_pile_count=5),
                       reseed_rng=dict(type='ok', run_rngs=7, monster_rngs=1))
        replies.update(self.overrides)
        return deepcopy(replies[command['cmd']])


class ResetContract(unittest.TestCase):
    def search(self, replies):
        state = dict(decision='combat_play', context=dict(act=1, floor=12, room_type='Elite'),
                     round=2, energy=3, player=dict(hp=50, block=0), hand=[],
                     enemies=[dict(index=0, name='Visible enemy', hp=30, block=0)])
        memory = dict(recipe=dict(kind='node', path='not-a-real-save'), clog=[])
        played = []
        def play(*args):
            played.append(True)
            return deepcopy(state)
        with params.scoped(dict(search_on=True, search_reseed=True, search_samples=1,
                                search_refine_samples=0, search_time_cap=30)), \
                patch.object(search.combat, 'plan', return_value=[(1, []), (0, [])]), \
                patch.object(search, '_reset', return_value=deepcopy(state)), \
                patch.object(search, '_play_turn', side_effect=play), \
                patch.object(search, '_value', return_value=10), \
                patch.object(sim, 'aux', return_value=EngineDouble(replies)):
            result = search.search_turn(state, memory)
        return result, played

    def test_explicit_reset_failures_never_score(self):
        for cmd in ('shuffle_draw', 'reseed_rng'):
            with self.subTest(cmd=cmd):
                result, played = self.search({cmd: dict(type='error', message='Unsupported command')})
                self.assertIsNone(result)
                self.assertEqual(played, [])

    def test_successful_reset_scores_candidates(self):
        result, played = self.search({})
        self.assertIsNotNone(result)
        self.assertEqual(len(played), 2)

    def test_empty_draw_pile_is_a_valid_success(self):
        result, played = self.search(dict(shuffle_draw=dict(type='ok', draw_pile_count=0)))
        self.assertIsNotNone(result)
        self.assertEqual(len(played), 2)

    def test_incomplete_shuffle_ack_never_scores(self):
        for reply in ({}, dict(type='decision'), dict(type='ok'),
                      dict(type='ok', draw_pile_count=-1), dict(type='ok', draw_pile_count=True)):
            with self.subTest(reply=reply):
                result, played = self.search(dict(shuffle_draw=reply))
                self.assertIsNone(result)
                self.assertEqual(played, [])

    def test_incomplete_battle_rng_ack_never_scores(self):
        for reply in (dict(type='ok', run_rngs=0, monster_rngs=1),
                      dict(type='ok', run_rngs=True, monster_rngs=1),
                      dict(type='ok', run_rngs=7),
                      dict(type='ok', run_rngs=7, monster_rngs=0)):
            with self.subTest(reply=reply):
                result, played = self.search(dict(reseed_rng=reply))
                self.assertIsNone(result)
                self.assertEqual(played, [])

    def test_unseen_reward_hp_cannot_change_current_score(self):
        scores = []
        def never_step(*args):
            raise AssertionError('Reward continuation must not execute')
        for hp in (53, 63, 999):
            scores.append(search._value(50, dict(decision='card_reward', player=dict(hp=hp)),
                                        {'_ehp0': 40}, never_step, None))
        self.assertEqual(scores, [scores[0]] * 3)


if __name__ == '__main__':
    unittest.main()
