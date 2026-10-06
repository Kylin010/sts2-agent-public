"""Public candle counter and offered camp choices; no native game IO."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from params import P
from policy import rest, learn


def state(counter=0, hp=80, act=2):
    return {'context': {'act': act},
        'player': {'hp':hp, 'max_hp':80, 'deck':[],
                   'relics':[{'id':'RELIC.PUMPKIN_CANDLE','counter':counter}]},
        'options':[{'option_id':'HEAL','index':0}, {'option_id':'SMITH','index':1},
                   {'option_id':'KINDLE','index':2}]}


class PumpkinRekindle(unittest.TestCase):
    def setUp(self):
        flags=patch.dict(P,{'rest_pumpkin_rekindle':True,'rest_pumpkin_rekindle_acts':[2],
            'rest_pumpkin_rekindle_max':1,'rest_mode':'rule','rest_boss_sim':False,
            'rest_potion_smith':False,'heal_below':.55,'heal_below_before_boss':.75,
            'heal_below_a23':None,'rest_learn_acts':[1,2,3]})
        flags.start();self.addCleanup(flags.stop)
        native=patch('subprocess.Popen',side_effect=AssertionError('Native process forbidden'))
        native.start();self.addCleanup(native.stop)

    def test_expired_or_last_charge_replaces_an_upgrade(self):
        for counter in [0,1]:
            with self.subTest(counter=counter):
                self.assertEqual(rest.pumpkin_kindling_choice(state(counter),{},1),2)
        self.assertIsNone(rest.pumpkin_kindling_choice(state(2),{},1))

    def test_keeps_heal_and_other_already_selected_options(self):
        for selected in [0,2,99]:
            self.assertIsNone(rest.pumpkin_kindling_choice(state(),{},selected))
        with patch.object(learn,'pick',return_value=0):
            self.assertEqual(rest.choose(state(hp=35),{}),0)

    def test_counter_for_imminent_boss_and_disabled_option(self):
        self.assertIsNone(rest.pumpkin_kindling_choice(state(1),{'next_is_boss':True},1))
        self.assertEqual(rest.pumpkin_kindling_choice(state(0),{'next_is_boss':True},1),2)
        st=state();st['options'][2]['is_enabled']=False
        self.assertIsNone(rest.pumpkin_kindling_choice(st,{},1))

    def test_absent_unknown_private_or_malformed_counter_is_not_inferred(self):
        for counter in [None,-1,True,'0']:
            self.assertIsNone(rest.pumpkin_kindling_choice(state(counter),{},1))
        st=state(None);st['player']['relics'][0]['KindleCount']=0
        self.assertIsNone(rest.pumpkin_kindling_choice(st,{},1))
        st=state();st['player']['relics']=[]
        self.assertIsNone(rest.pumpkin_kindling_choice(st,{},1))

    def test_default_other_acts_and_custom_camp_models_keep_their_choice(self):
        with patch.dict(P,{'rest_pumpkin_rekindle':False}):
            self.assertIsNone(rest.pumpkin_kindling_choice(state(),{},1))
        for act in [1,3]:
            self.assertIsNone(rest.pumpkin_kindling_choice(state(act=act),{},1))
        for key,value in [('rest_mode','imitate'),('rest_mode','value'),('rest_boss_sim',True)]:
            with patch.dict(P,{key:value}):
                self.assertIsNone(rest.pumpkin_kindling_choice(state(),{},1))

    def test_wrapper_clears_upgrade_selector_and_does_not_mutate_public_state(self):
        st=state();before=copy.deepcopy(st);mem={}
        with patch.object(learn,'pick',return_value=1):
            self.assertEqual(rest.choose(st,mem),2)
        self.assertNotIn('select_purpose',mem)
        self.assertEqual(mem['rest_pumpkin_rule']['public_counter'],0)
        self.assertEqual(st,before)
        mem={}
        with patch.dict(P,{'rest_pumpkin_rekindle':False}),patch.object(learn,'pick',return_value=1):
            self.assertEqual(rest.choose(st,mem),1)
        self.assertEqual(mem['select_purpose'],'upgrade')


if __name__=='__main__':
    unittest.main()
