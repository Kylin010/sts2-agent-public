import copy
import unittest
from unittest.mock import patch

import params
from policy import route, rest, deckeval, elites, combos, learn


class RouteRestConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(params.P)
        params.P.update(route_rest_below=.55,route_rest_boss_heal_below=None,
                        route_rest_boss_heal_acts=[2],rest_mode='rule',
                        rest_boss_sim=False,rest_potion_smith=False,
                        heal_below=.55,heal_below_before_boss=.75)

    def tearDown(self):
        params.P.clear();params.P.update(self.saved)

    def test_default_and_other_acts_keep_old_forecast(self):
        self.assertEqual(route._projected_rest_threshold(2,True),.55)
        params.P['route_rest_boss_heal_below']=.75
        self.assertEqual(route._projected_rest_threshold(1,True),.55)
        self.assertEqual(route._projected_rest_threshold(3,True),.55)
        self.assertEqual(route._projected_rest_threshold(2,False),.55)

    def test_base_camp_rule_aligned_without_changing_real_choice(self):
        params.P['route_rest_boss_heal_below']=.75
        for hp in [44,50,59,60,70]:
            state=dict(context={'act':2},player={'hp':hp,'max_hp':80,'deck':[]},
                       options=[dict(option_id='HEAL',index=0),dict(option_id='SMITH',index=1)])
            actual=rest._rule(state,{'next_is_boss':True})
            forecast_heal=hp<route._projected_rest_threshold(2,True)*80
            self.assertEqual(forecast_heal,actual==0)

    def test_custom_camp_policies_and_bad_values_fall_back(self):
        params.P['route_rest_boss_heal_below']=.75
        for name,value in [('rest_mode','value'),('rest_boss_sim',True),('rest_potion_smith',True)]:
            previous=params.P[name];params.P[name]=value
            self.assertEqual(route._projected_rest_threshold(2,True),.55)
            params.P[name]=previous
        for value in [float('nan'),float('inf'),True,'0.75']:
            params.P['route_rest_boss_heal_below']=value
            self.assertEqual(route._projected_rest_threshold(2,True),.55)

    def test_visible_route_fork_changes_only_when_enabled(self):
        # Low-risk treasure versus a camp immediately before the displayed Boss.
        # This checks a route decision, not merely the threshold helper.
        graph=dict(rows=[[dict(col=0,row=1,type='RestSite',children=[dict(col=0,row=2)]),
                          dict(col=1,row=1,type='Treasure',children=[dict(col=0,row=2)])]],
                   boss=dict(col=0,row=2))
        state=dict(context={'act':2},player=dict(hp=50,max_hp=80,gold=0,deck=[],relics=[],potions=[]),
                   choices=[dict(col=0,row=1),dict(col=1,row=1)])
        params.P.update(route_ready_on=False,route_survival=False,deck_mc=False,simeval_route=False,
                        route_dmg_boss=[55,55,55],route_deck_gamma=0,
                        route_v_upgrade=8,route_v_relic=25,route_v_boss_hp=.6)
        with patch.object(deckeval,'evaluate',return_value=dict(dmg_per_turn=30,block_per_turn=20,scaling=0,aoe=0)), \
             patch.object(elites,'dist',return_value={}), \
             patch.object(elites,'aoe_capacity',return_value=0), \
             patch.object(combos,'score',return_value=(0,[],[])), \
             patch.object(learn,'pick',side_effect=lambda kind,options,st,mem:max(options,key=lambda x:x[1])[0]):
            old=route.choose(graph,state,{})
            params.P['route_rest_boss_heal_below']=.75
            aligned=route.choose(graph,state,{})
        self.assertEqual(old['col'],1)
        self.assertEqual(aligned['col'],0)


if __name__=='__main__':
    unittest.main()
