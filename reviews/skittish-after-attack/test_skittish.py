from pathlib import Path
from copy import deepcopy
import sys,unittest,subprocess
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def blocked(*a,**kw):raise AssertionError('No native/process starts')
subprocess.Popen=blocked
from params import scoped,P
from policy import enemy_powers as EP,combat

def foe(hp=30,block=0):return {'index':0,'name':'Phantasmal Gardener','hp':hp,'max_hp':30,'block':block,'powers':[{'name':'Skittish','id':'SKITTISH_POWER','amount':7}],'intents':[{'type':'Attack','damage':7,'hits':1}]}
def twin():return {'index':0,'id':'CARD.TWIN_STRIKE','name':'Twin Strike','type':'Attack','target_type':'AnyEnemy','cost':1,'can_play':True,'stats':{'damage':7,'repeat':2},'damage_by_target':[{'target_index':0,'damage':7,'repeat':2}]}
class Checks(unittest.TestCase):
 def test_two_hits_shield_after_both(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe());f.hit(7,2);self.assertEqual((f.lost,f.blk,f.skit),(14,7,0))
 def test_legacy_interposes_shield_between_hits(self):
  with scoped({'combat_skittish_after_attack':False}):f=EP.Foe(foe());f.hit(7,2);self.assertEqual((f.lost,f.blk),(7,0))
 def test_first_fully_blocked_second_unblocked_does_not_trigger(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe(block=7));f.hit(7,2);self.assertEqual((f.lost,f.blk,f.skit),(7,0,7))
 def test_first_partly_blocked_triggers_after_all(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe(block=3));f.hit(7,2);self.assertEqual((f.lost,f.blk,f.skit),(11,7,0))
 def test_later_command_can_trigger_after_blocked_first_command(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe(block=7));f.hit(7,2);f.hit(6,1);self.assertEqual((f.lost,f.blk,f.skit),(13,7,0))
 def test_subsequent_command_cannot_retrigger_in_same_projection(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe(hp=80));f.hit(7,2);f.hit(10,1);self.assertEqual((f.lost,f.blk),(17,0))
 def test_dead_target_no_shield(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe(hp=12));f.hit(7,2);self.assertEqual((f.blk,f.skit),(0,0));self.assertGreaterEqual(f.lost,12)
 def test_zero_or_no_hits_no_trigger(self):
  with scoped({'combat_skittish_after_attack':True}):
   f=EP.Foe(foe());f.hit(0,3);self.assertEqual((f.lost,f.blk,f.skit),(0,0,7));f.hit(7,0);self.assertEqual(f.skit,7)
 def test_peek_does_not_consume_real_projection(self):
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(foe());self.assertEqual(f.peek(7,2),14);self.assertEqual((f.lost,f.blk,f.skit),(0,0,7))
 def test_non_skittish_exact(self):
  e=foe();e['powers']=[]
  with scoped({'combat_skittish_after_attack':False}):a=EP.Foe(e);a.hit(7,3)
  with scoped({'combat_skittish_after_attack':True}):b=EP.Foe(e);b.hit(7,3)
  self.assertEqual((a.lost,a.blk),(b.lost,b.blk))
 def test_card_damage_and_kill_projection(self):
  c=twin();e=foe(hp=12);st={'context':{'encounter':'PHANTASMAL_GARDENERS_ELITE','act':1,'floor':8,'room_type':'Elite'},'round':1,'energy':1,'hand':[c],'player':{'hp':40,'max_hp':80,'block':0,'deck':[]},'player_powers':[],'enemies':[e]}
  parts=[]
  for flag in [False,True]:
   with scoped({'combat_skittish_after_attack':flag,'cv_weight':0,'imit_w':0}):ctx=combat.plan(st,{},set(),topk=-1)['ctx'];ctx['_parts']={};combat.evaluate([c],ctx);parts.append(ctx['_parts']['cur'])
  self.assertEqual([x['dealt']for x in parts],[7,12]);self.assertGreater(parts[1]['killed'],parts[0]['killed'])
 def test_copy_and_observation_invariance(self):
  e=foe();old=deepcopy(e)
  with scoped({'combat_skittish_after_attack':True}):f=EP.Foe(e);g=f.copy();g.hit(7,2);self.assertEqual(f.lost,0);self.assertEqual(e,old)
 def test_default_off_preserved(self):self.assertFalse(P['combat_skittish_after_attack'])

if __name__=='__main__':unittest.main(verbosity=2)
