"""Source mechanics and route-only integration; no native game IO."""
import copy
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb; require_kb(__name__)
from params import P
from policy import route_body_slam as model, route, deckeval, elites, combos, learn


def card(ident, upgraded=False):
    return {'id': 'CARD.' + ident, 'upgraded': upgraded}


class BodySlamRoute(unittest.TestCase):
    def setUp(self):
        guard = patch('subprocess.Popen', side_effect=AssertionError('Native process forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_block_precedes_slam_and_upgrade_changes_energy_cost(self):
        block = model.effect('ULTIMATE_DEFEND', True)
        self.assertEqual(model.hand_damage((block, model.effect('BODY_SLAM')), 1), 0)
        self.assertEqual(model.hand_damage((block, model.effect('BODY_SLAM', True)), 1), 15)
        self.assertEqual(model.hand_damage((block, model.effect('BODY_SLAM')), 2), 15)

    def test_shared_energy_keeps_opportunity_cost_of_other_attacks(self):
        hand = tuple(model.effect(i) for i in ['BASH','ULTIMATE_DEFEND','BODY_SLAM'])
        self.assertEqual(model.hand_damage(hand, 2, False), 8)
        self.assertEqual(model.hand_damage(hand, 2, True), 11)
        self.assertEqual(model.hand_damage(hand, 2, True)-model.hand_damage(hand, 2, False), 3)

    def test_grit_must_burn_slam_when_no_other_hand_card_remains(self):
        for upgraded in [False, True]:
            hand = (model.effect('TRUE_GRIT', upgraded), model.effect('BODY_SLAM', True))
            self.assertEqual(model.hand_damage(hand), 0)

    def test_grit_upgrade_chooses_filler_while_random_grit_uses_public_probability(self):
        filler = model.effect('ASCENDERS_BANE')
        slam = model.effect('BODY_SLAM', True)
        self.assertEqual(model.hand_damage((model.effect('TRUE_GRIT',True), slam, filler)), 9)
        self.assertEqual(model.hand_damage((model.effect('TRUE_GRIT'), slam, filler)), 3.5)

    def test_no_supported_engine_and_normality_add_zero(self):
        self.assertEqual(model.increment([card('BODY_SLAM'),card('STRIKE_IRONCLAD')]),0)
        self.assertEqual(model.increment([card('ULTIMATE_DEFEND')]),0)
        self.assertEqual(model.increment([card('BODY_SLAM',True),card('ULTIMATE_DEFEND'),card('NORMALITY')]),0)

    def test_sampler_is_card_order_invariant_and_does_not_touch_global_rng(self):
        deck = [card('BODY_SLAM',True),card('ULTIMATE_DEFEND'),card('TRUE_GRIT',True)] + [card('DEFEND_IRONCLAD')]*6
        before = copy.deepcopy(deck)
        rng_before = random.getstate()
        one = model.increment(deck,80)
        self.assertGreater(one,0)
        self.assertEqual(one,model.increment(list(reversed(deck)),80))
        altered = [{**c,'rng':123,'draw_position':99,'private_counter':7} for c in deck]
        self.assertEqual(one,model.increment(altered,80))
        self.assertEqual(random.getstate(),rng_before)
        self.assertEqual(deck,before)

    def risk_inputs(self, enabled, act=2, snecko=False, mc=False, readiness=False):
        st = {'context':{'act':act},'choices':[{'col':0,'row':1}],
              'player':{'hp':60,'max_hp':80,'gold':0,'potions':[],
                        'deck':[card('BODY_SLAM',True),card('ULTIMATE_DEFEND')],
                        'relics':[{'id':'RELIC.SNECKO_EYE'}] if snecko else []}}
        graph = {'rows':[[{'col':0,'row':1,'type':'Monster','children':[{'col':0,'row':2}]}]],
                 'boss':{'col':0,'row':2}}
        calls=[]
        original=route._death_p
        def capture(hp,e):
            calls.append((hp,e))
            return original(hp,e)
        with patch.dict(P,{'route_body_slam_strength':enabled,'route_body_slam_strength_acts':[2],
                          'simeval_route':False,'deck_mc':mc,'route_ready_on':False}), \
                patch.object(deckeval,'evaluate_mc',return_value=(2.0,4.0)), \
                patch.object(elites,'dist',return_value={}), \
                patch.object(elites,'aoe_capacity',return_value=0), \
                patch.object(combos,'score',return_value=(0,[],[])), \
                patch.object(learn,'pick',side_effect=lambda kind,opts,st,mem:opts[0][0]), \
                patch.object(route,'_death_p',side_effect=capture):
            mem={'act_fights':{act:2}}
            route.choose(graph,st,mem)
        return mem['route_ready'][0] if readiness else calls

    def test_route_only_changes_when_enabled_in_act2_without_snecko(self):
        self.assertLess(self.risk_inputs(True)[0][1],self.risk_inputs(False)[0][1])
        for act in [1,3]:
            self.assertEqual(self.risk_inputs(True,act),self.risk_inputs(False,act))
        self.assertEqual(self.risk_inputs(True,snecko=True),self.risk_inputs(False,snecko=True))
        baseline = deckeval.evaluate([card('BODY_SLAM',True),card('ULTIMATE_DEFEND')])
        with patch.dict(P,{'route_body_slam_strength':True}):
            self.assertEqual(deckeval.evaluate([card('BODY_SLAM',True),card('ULTIMATE_DEFEND')]),baseline)

    def test_existing_mc_mode_gets_the_same_marginal_in_readiness(self):
        self.assertGreater(self.risk_inputs(True,mc=True,readiness=True),
                           self.risk_inputs(False,mc=True,readiness=True))


if __name__ == '__main__':
    unittest.main()
