"""Pure terminal regressions; no native state injection or game process."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb; require_kb(__name__)
import params
import policy
import run
from terminal import victory_evidence


def boss(floor):
    return dict(act=3, floor=floor, room='Boss', enemies=['Visible boss'])


def won():
    return dict(type='decision', decision='game_over', victory=True,
                act=3, floor=16, context=dict(act=3, floor=16),
                player=dict(hp=10, max_hp=80))


class TerminalChecks(unittest.TestCase):
    def test_first_final_boss_is_not_a_full_win(self):
        evidence = victory_evidence(won(), [boss(15)])
        self.assertFalse(evidence['verified'])
        self.assertEqual(evidence['observed_final_bosses'], 1)

    def test_two_distinct_final_bosses_and_terminal_win(self):
        self.assertTrue(victory_evidence(won(), [boss(15), boss(16)])['verified'])

    def test_duplicate_observations_do_not_invent_another_boss(self):
        self.assertFalse(victory_evidence(won(), [boss(15), boss(15)])['verified'])

    def test_death_or_partial_or_early_victory_cannot_pass(self):
        for changes in (dict(victory=False), dict(decision='map_select'),
                        dict(act=2), dict(player=dict(hp=0)), dict(victory=1)):
            with self.subTest(changes=changes):
                self.assertFalse(victory_evidence(dict(won(), **changes),
                                                  [boss(15), boss(16)])['verified'])

    def test_lower_ascension_requires_its_single_final_boss(self):
        self.assertTrue(victory_evidence(won(), [boss(15)], ascension=9)['verified'])

    def drive_double(self, floors, stop_act=None):
        states = [dict(type='decision', decision='combat_play', round=1,
                       context=dict(act=3, floor=floor, room_type='Boss'),
                       player=dict(hp=10), enemies=[dict(name='Visible boss', hp=1)])
                  for floor in floors] + [won()]
        class Double:
            rec = None
            def act(self, *args, **kwargs):
                return deepcopy(states.pop(0))
        first = deepcopy(states.pop(0))
        with params.scoped(dict(search_on=False, simeval_pick=False,
                                simeval_route=False, follow_human=False)), \
                patch.object(policy, 'decide', return_value=('end_turn', {})):
            return run.drive(Double(), first, {}, stop_act=stop_act)

    def test_driver_rejects_old_engine_premature_victory(self):
        result = self.drive_double([15])
        self.assertFalse(result['win'])
        self.assertTrue(result['terminal_victory_reported'])
        self.assertEqual(result['victory_evidence']['observed_final_bosses'], 1)

    def test_driver_accepts_required_fights(self):
        result = self.drive_double([15, 16])
        self.assertTrue(result['win'])
        self.assertEqual(len(result['combats']), 2)

    def test_act_two_segment_keeps_its_separate_clear(self):
        state = dict(type='decision', decision='map_select',
                     context=dict(act=3, floor=1), player=dict(hp=40))
        with params.scoped(dict(search_on=False, simeval_pick=False,
                                simeval_route=False)):
            result = run.drive(object(), state, {}, stop_act=2)
        self.assertTrue(result['win'])
        self.assertEqual(result['cleared'], 2)
        self.assertNotIn('victory_evidence', result)


if __name__ == '__main__':
    unittest.main()
