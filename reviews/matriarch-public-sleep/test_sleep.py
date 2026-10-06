from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import sys, unittest, subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
def blocked(*args,**kwargs): raise AssertionError('No native/process starts')
subprocess.Popen=blocked
from params import P,scoped
from policy import foresight,mentalmodel,combat,combatvalue
from policy.public_matriarch import future_moves
FLAG={'foresight_public_matriarch_sleep':True}
def enemy(amount=3,typ='Sleep'):
 return {'index':0,'name':'Lagavulin Matriarch','hp':233,'max_hp':233,'block':12,'intents':[{'type':typ}], 'powers':([{'id':'ASLEEP_POWER','name':'Asleep','amount':amount}] if amount is not None else [])}
def f(e,n=6,d=0):return foresight.future(e,foresight.identify(e),n,projected_hp_damage=d)
class Checks(unittest.TestCase):
 def test_three_sleep_badges(self):
  with scoped(FLAG):self.assertEqual(f(enemy()),[0,0,21,20,14,0])
 def test_two_sleep_badges(self):
  with scoped(FLAG):self.assertEqual(f(enemy(2)),[0,21,20,14,0,23])
 def test_last_sleep_badge(self):
  with scoped(FLAG):self.assertEqual(f(enemy(1)),[21,20,14,0,23,24])
 def test_positive_hp_damage_wakes(self):
  with scoped(FLAG):self.assertEqual(f(enemy(),d=1),[21,20,14,0,23,24])
 def test_no_hp_damage_preserves_sleep(self):
  with scoped(FLAG):self.assertEqual(f(enemy(),d=0)[:3],[0,0,21])
 def test_visible_stun_is_ambiguous_defer(self):
  with scoped(FLAG):self.assertIsNone(f(enemy(None,'Stun')))
 def test_bad_sleep_amounts_defer(self):
  for x in [None,0,4,True,1.5,'3']:
   self.assertIsNone(future_moves(enemy(x),3))
 def test_duplicate_badges_defer(self):
  e=enemy();e['powers']*=2;self.assertIsNone(future_moves(e,3))
 def test_stun_with_sleep_contradiction_defer(self):self.assertIsNone(future_moves(enemy(2,'Stun'),3))
 def test_other_monster_defer(self):
  e=enemy();e['name']='Knowledge Demon';self.assertIsNone(future_moves(e,3))
 def test_fixed_loop_strength_scaling(self):
  e=enemy(1);e['powers'].append({'name':'Strength','amount':3})
  with scoped(FLAG):self.assertEqual(f(e),[24,26,17,0,26,30])
 def test_root_mental_schedule_alignment(self):
  with scoped(FLAG):s=mentalmodel.schedule([enemy()],6,{})
  self.assertEqual(s,(0,0,[[0,0,0],[0,0,0],[21,0,0],[20,0,0],[14,0,14],[0,0,0]]))
 def test_projected_mental_schedule_alignment(self):
  with scoped(FLAG):s=mentalmodel.schedule([enemy()],3,{},hp_damage_by_index={0:1})
  self.assertEqual(s,(0,0,[[21,0,0],[20,0,0],[14,0,14]]))
 def test_root_cv_future(self):
  with scoped(FLAG):s=combatvalue.situation_from_state({'player':{'hp':50},'enemies':[enemy()]})
  self.assertEqual(s['enemies'][0]['fut'],7)
 def test_private_fields_and_input_order_invariance(self):
  e=enemy();old=deepcopy(e);e.update({'next_move':'SOUL_SIPHON_MOVE','move_id':'SLASH_MOVE','rng':987654,'private_phase':9})
  with scoped(FLAG):self.assertEqual(f(e),f(old));self.assertEqual(f(e),f(e))
  self.assertEqual({k:e[k] for k in old},old)
 def test_candidate_local_cv_wake_no_leak(self):
  card={'index':0,'id':'CARD.STRIKE_IRONCLAD','name':'Strike','type':'Attack','target_type':'AnyEnemy','cost':1,'can_play':True,'stats':{'damage':13},'damage_by_target':[{'target_index':0,'damage':13,'repeat':1}]}
  st={'context':{'encounter':'LAGAVULIN_MATRIARCH_BOSS','act':1,'floor':16},'round':1,'energy':1,'hand':[card],'player':{'hp':50,'max_hp':80,'block':0,'deck':[]},'enemies':[enemy()]}
  with scoped(dict(FLAG,cv_weight=0,mental_on=False,imit_w=0)):
   ctx=combat.plan(st,{},set(),topk=-1)['ctx'];ctx['sit']=combatvalue.situation_from_state(st)
  seen=[]
  with scoped(dict(FLAG,cv_weight=1,mental_on=False,imit_w=0)),patch.object(combatvalue,'available',return_value=True),patch.object(combatvalue,'predict',side_effect=lambda s:seen.append(deepcopy(s)) or 0):
   combat.evaluate((),ctx);combat.evaluate((card,),ctx);combat.evaluate((),ctx)
  self.assertEqual([s['enemies'][0]['fut'] for s in seen],[7,55/3,7])
  self.assertEqual(st['enemies'][0],enemy())
 def test_default_off_legacy(self):
  self.assertFalse(P['foresight_public_matriarch_sleep'])
  with scoped({'foresight_public_matriarch_sleep':False}):a=f(enemy())
  self.assertEqual(a[:3],[10.5,15.25,14.625])
if __name__=='__main__':unittest.main(verbosity=2)
