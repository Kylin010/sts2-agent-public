"""核对评分已承诺的逃离是否会在执行时被提前消耗；只用公开局面，不启动引擎。"""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('port_fixtures', ROOT / 'tests/test_codex_ports.py')
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
from params import scoped
from policy import combat


class SandpitEscapeOrderTest(unittest.TestCase):
    def escape(self, index=1):
        return fx.card('FRANTIC_ESCAPE', index, typ='Status', target='Self')

    def state(self, hand):
        return fx.state(hand, [fx.enemy(0, 341, 31, powers={'Sandpit': 1}, name='The Insatiable')],
                        energy=2, hp=60, max_hp=80, rnd=5)

    def test_full_planner_preserves_escape_before_random_exhaust(self):
        tg = fx.card('TRUE_GRIT', 0, typ='Skill', block=7, target='Self', upgraded=False)
        fe = self.escape()
        st = self.state([tg, fe])
        with scoped({'sandpit_escape_first': False}):
            old = combat.plan(st, {}, set(), topk=3)
            self.assertEqual([combat.cid(c) for c, _ in old[0][1]], ['TRUE_GRIT', 'FRANTIC_ESCAPE'])
        with scoped({'sandpit_escape_first': True}):
            new = combat.plan(st, {}, set(), topk=3)
            self.assertEqual([combat.cid(c) for c, _ in new[0][1]], ['FRANTIC_ESCAPE', 'TRUE_GRIT'])
            self.assertEqual(combat.cid(combat.plan(st, {}, set())[0]), 'FRANTIC_ESCAPE')
        self.assertEqual(old[0][0], new[0][0])  # 修正执行顺序，评分参数没有变。

    def test_certain_death_witness_uses_source_rules(self):
        # TrueGrit.cs:39-43 从当前手牌随机选 1；仅剩逃离时概率=1。
        # FranticEscape.cs:43 加 1；SandpitPower.cs:74 敌方开始减 1，归零强制死亡。
        tg = fx.card('TRUE_GRIT', 0, typ='Skill', block=7, target='Self', upgraded=False)
        fe = self.escape()
        def symbolic_sand(sequence):
            hand = list(sequence); sand = 1
            for c in sequence:
                if c not in hand: continue
                hand.remove(c)
                if combat.cid(c) == 'FRANTIC_ESCAPE': sand += 1
                if combat.cid(c) == 'TRUE_GRIT' and len(hand) == 1: hand.clear()
            return sand - 1
        with scoped({'sandpit_escape_first': False}):
            self.assertEqual(symbolic_sand(sorted([tg, fe], key=combat.ORDER)), 0)
        with scoped({'sandpit_escape_first': True}):
            self.assertEqual(symbolic_sand(sorted([tg, fe], key=combat.ORDER)), 1)

    def test_verified_exhaust_cards_follow_escape(self):
        fe = self.escape()
        with scoped({'sandpit_escape_first': True}):
            for ident, typ in [('TRUE_GRIT', 'Skill'), ('SECOND_WIND', 'Skill'),
                               ('STOKE', 'Skill'), ('CINDER', 'Attack'), ('FIEND_FIRE', 'Attack')]:
                with self.subTest(card=ident):
                    c = fx.card(ident, 0, typ=typ)
                    self.assertEqual(combat.cid(sorted([c, fe], key=combat.ORDER)[0]), 'FRANTIC_ESCAPE')

    def test_draw_energy_and_powers_keep_their_priorities(self):
        hand = [fx.card('BATTLE_TRANCE', 0, typ='Skill', cost=0),
                fx.card('BLOODLETTING', 1, typ='Skill'), fx.card('INFLAME', 2, typ='Power'),
                self.escape(3), fx.card('TRUE_GRIT', 4, typ='Skill')]
        with scoped({'sandpit_escape_first': True}):
            self.assertEqual([combat.cid(c) for c in sorted(reversed(hand), key=combat.ORDER)],
                             ['BATTLE_TRANCE', 'BLOODLETTING', 'INFLAME', 'FRANTIC_ESCAPE', 'TRUE_GRIT'])

    def test_other_cards_keep_identical_order_keys(self):
        hand = [fx.card('DEFEND_IRONCLAD', 0, typ='Skill'), fx.card('STRIKE_IRONCLAD', 1),
                fx.card('FEED', 2), fx.card('FIEND_FIRE', 3), fx.card('BURNING_PACT', 4, typ='Skill')]
        with scoped({'sandpit_escape_first': False}): old = [combat.ORDER(c) for c in hand]
        with scoped({'sandpit_escape_first': True}): new = [combat.ORDER(c) for c in hand]
        self.assertEqual(old, new)

    def test_switch_off_preserves_original_status_order(self):
        with scoped({'sandpit_escape_first': False}):
            self.assertEqual(combat.ORDER(self.escape()), 6)


if __name__ == '__main__':
    unittest.main()
