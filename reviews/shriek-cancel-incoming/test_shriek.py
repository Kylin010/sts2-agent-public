from pathlib import Path
from copy import deepcopy
import sys,unittest,subprocess
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def blocked(*a,**kw):raise AssertionError('No native/process starts')
subprocess.Popen=blocked
from params import P,scoped
from policy import enemy_powers as EP,combat

def foe(hp=76,threshold=75):return {'index':0,'name':'Terror Eel','hp':hp,'max_hp':150,'block':0,'powers':[{'id':'SHRIEK_POWER','name':'Shriek','amount':threshold}],'intents':[{'type':'Attack','damage':24,'hits':1}]}
def card():return {'index':0,'id':'CARD.STRIKE_IRONCLAD','name':'Strike','type':'Attack','target_type':'AnyEnemy','cost':1,'can_play':True,'stats':{'damage':6},'damage_by_target':[{'target_index':0,'damage':6}]}
def state():return {'context':{'encounter':'TERROR_EEL_ELITE','act':1,'floor':8,'room_type':'Elite'},'round':3,'energy':1,'hand':[card()],'player':{'hp':10,'max_hp':80,'block':0,'deck':[]},'player_powers':[],'enemies':[foe()]}
class Checks(unittest.TestCase):
 def test_exact_threshold_source(self):self.assertTrue(EP.shriek_stuns_after_damage(foe(),1))
 def test_positive_damage_below_threshold_still_triggers(self):self.assertTrue(EP.shriek_stuns_after_damage(foe(hp=74),1))
 def test_no_hp_damage_does_not_trigger(self):self.assertFalse(EP.shriek_stuns_after_damage(foe(hp=74),0))
 def test_above_threshold_not_stunned(self):self.assertFalse(EP.shriek_stuns_after_damage(foe(hp=82),6))
 def test_dead_target_does_not_need_stun(self):self.assertFalse(EP.shriek_stuns_after_damage(foe(),76))
 def test_visible_threshold_not_half_maxhp(self):self.assertTrue(EP.shriek_stuns_after_damage(foe(hp=90,threshold=85),6))
 def test_missing_or_bad_threshold_rejected(self):
  e=foe();e['powers']=[];self.assertFalse(EP.shriek_stuns_after_damage(e,6));self.assertFalse(EP.shriek_stuns_after_damage(foe(threshold=True),6))
 def test_score_removes_cancelled_lethal_incoming(self):
  st=state();c=st['hand'][0];parts=[]
  for flag in [False,True]:
   with scoped({'combat_public_shriek_stun':flag,'cv_weight':0,'imit_w':0}):x=combat.plan(st,{},set(),topk=-1)['ctx'];x['_parts']={};sc=combat.evaluate([c],x);parts.append((sc,x['_parts']['cur']))
  self.assertEqual([p[1]['unblocked']for p in parts],[24,0]);self.assertGreater(parts[1][0],parts[0][0]+P['death_penalty'])
 def test_value_network_intent_synchronized(self):
  st=state();c=st['hand'][0]
  with scoped({'combat_public_shriek_stun':True,'cv_weight':.3,'imit_w':0}):x=combat.plan(st,{},set(),topk=-1)['ctx'];x['_parts']={};combat.evaluate([c],x);self.assertEqual(x['_parts']['cur']['sit']['enemies'][0]['intent'],0)
 def test_no_crossing_exact_legacy(self):
  st=state();st['enemies'][0]['hp']=100;c=st['hand'][0]
  with scoped({'combat_public_shriek_stun':False,'cv_weight':0,'imit_w':0}):x=combat.plan(st,{},set(),topk=-1)['ctx'];a=combat.evaluate([c],x)
  with scoped({'combat_public_shriek_stun':True,'cv_weight':0,'imit_w':0}):b=combat.evaluate([c],x)
  self.assertEqual(a,b)
 def test_candidate_stun_does_not_leak_to_empty_combo(self):
  st=state();c=st['hand'][0]
  with scoped({'combat_public_shriek_stun':True,'cv_weight':0,'imit_w':0}):
   x=combat.plan(st,{},set(),topk=-1)['ctx'];x['_parts']={};combat.evaluate([c],x);combat.evaluate([],x);self.assertEqual(x['_parts']['cur']['unblocked'],24);self.assertNotIn('_stunned',x)
 def test_observation_not_mutated(self):
  st=state();old=deepcopy(st)
  with scoped({'combat_public_shriek_stun':True}):combat.plan(st,{},set(),topk=3)
  self.assertEqual(st,old)
 def test_default_off_preserved(self):self.assertFalse(P['combat_public_shriek_stun'])

if __name__=='__main__':unittest.main(verbosity=2)
