"""纯公开局面核对：升级抽牌量、不能抽牌和打完战斗；不启动引擎。"""
import importlib.util
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('port_fixtures', ROOT / 'tests/test_codex_ports.py')
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
from params import P, scoped
from policy import combat


class PublicDrawPreviewTest(unittest.TestCase):
    def score(self, cards, enabled, **kwargs):
        st = fx.state(cards, [fx.enemy(0, 200)], **kwargs)
        with scoped({'combat_public_draw': enabled}):
            return combat.evaluate(tuple(cards), fx.ctx_of(st))

    def card(self, ident, n, index=0, **kwargs):
        return fx.card(ident, index, typ='Skill', cost=0, target='Self', stats={'cards': n}, **kwargs)

    def test_all_four_upgrades_change_full_planner_score(self):
        for ident, base, upgraded in [('BATTLE_TRANCE', 3, 4), ('POMMEL_STRIKE', 1, 2),
                                     ('BURNING_PACT', 2, 3), ('OFFERING', 3, 5)]:
            with self.subTest(card=ident):
                c = self.card(ident, upgraded)
                if ident == 'POMMEL_STRIKE':
                    c = fx.card(ident, 0, dmg=10, stats={'cards': upgraded})
                delta = self.score([c], True) - self.score([c], False)
                self.assertAlmostEqual(delta, (upgraded - base) * P['draw_value'])

    def test_base_cards_preserve_full_score(self):
        for ident, n in [('BATTLE_TRANCE', 3), ('POMMEL_STRIKE', 1), ('BURNING_PACT', 2), ('OFFERING', 3)]:
            c = self.card(ident, n)
            self.assertEqual(self.score([c], True), self.score([c], False))

    def test_no_draw_suppresses_extra_score(self):
        c = self.card('OFFERING', 5)
        powers = {'No Draw': 1}
        self.assertEqual(self.score([c], True, player_powers=powers), self.score([c], False, player_powers=powers))

    def test_trance_still_blocks_other_draws(self):
        combo = [self.card('BATTLE_TRANCE', 4), self.card('OFFERING', 5, index=1)]
        self.assertAlmostEqual(self.score(combo, True) - self.score(combo, False), P['draw_value'])

    def test_kill_does_not_reward_future_draw(self):
        c = fx.card('POMMEL_STRIKE', 0, dmg=300, stats={'cards': 2})
        self.assertEqual(self.score([c], True), self.score([c], False))

    def test_unknown_cardsvar_does_not_become_draw(self):
        c = self.card('PACTS_END', 3)
        with scoped({'combat_public_draw': True}):
            self.assertEqual(combat.draw_amount(c), 0)

    def test_missing_and_invalid_preview_use_public_upgrade_only(self):
        with scoped({'combat_public_draw': True}):
            for n in [None, True, '4', -1, 2.5, math.inf, math.nan]:
                with self.subTest(value=n):
                    c = self.card('BATTLE_TRANCE', n, upgraded=True)
                    self.assertEqual(combat.draw_amount(c), 4)
            self.assertEqual(combat.draw_amount(self.card('BATTLE_TRANCE', None)), 3)

    def test_switch_off_ignores_preview_and_upgrade(self):
        with scoped({'combat_public_draw': False}):
            self.assertEqual(combat.draw_amount(self.card('OFFERING', 5, upgraded=True)), 3)


if __name__ == '__main__':
    unittest.main()
