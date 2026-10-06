"""Public board boundaries; no game assembly or native game is used."""
from pathlib import Path
import copy
import importlib.util
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

path = Path(__file__).resolve().parents[1] / 'policy/crystal.py'
spec = importlib.util.spec_from_file_location('crystal_public', path)
crystal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crystal)


def board():
    return dict(width=11, height=11, divinations_left=3,
                cells=[dict(x=x, y=y, hidden=True) for x in range(11) for y in range(11)])


class PublicCrystal(unittest.TestCase):
    def test_compatible_sdk_uses_an_actually_offered_event_option(self):
        import json, params, policy
        state = json.loads((Path(__file__).parent / 'fixtures' /
                            'unfinished-crystal-public-ui.json').read_text())
        original = copy.deepcopy(state)
        class NoNative:
            def __getattr__(self, name):
                raise AssertionError('Native IO requested: ' + name)
        with patch.dict(params.P, {'event_ui_fixed': True}):
            action, args = policy.decide(state, {}, NoNative())
        self.assertEqual(action, 'choose_option')
        self.assertIn(args['option_index'], [o['index'] for o in state['options']])
        self.assertEqual(state, original)

    def test_full_fog_uses_legal_large_center(self):
        self.assertEqual(crystal.choose(board()), ('crystal_click', dict(x=5,y=5,tool='Big')))

    def test_hidden_item_metadata_cannot_change_choice(self):
        state = board()
        altered = copy.deepcopy(state)
        for c in altered['cells']:
            c.update(visible_item='CrystalSphereRelic', hidden_item='Curse', reward=999)
        self.assertEqual(crystal.choose(state), crystal.choose(altered))

    def test_avoids_spending_click_on_clear_area(self):
        state = board()
        for c in state['cells']:
            c['hidden'] = c['x'] >= 8 and c['y'] >= 8
        _, args = crystal.choose(state)
        self.assertEqual((args['x'], args['y']), (9,9))

    def test_completed_or_incomplete_board_rejected(self):
        state = board(); state['divinations_left'] = 0
        with self.assertRaises(ValueError): crystal.choose(state)
        state = board(); state['cells'].pop()
        with self.assertRaises(ValueError): crystal.choose(state)


if __name__ == '__main__':
    unittest.main()
