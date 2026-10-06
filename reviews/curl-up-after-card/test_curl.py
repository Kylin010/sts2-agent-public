from pathlib import Path
from copy import deepcopy
import sys,unittest,subprocess
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def blocked(*a,**kw):raise AssertionError('No native/process starts')
subprocess.Popen=blocked
from params import scoped,P
from policy import enemy_powers as EP,combat

def foe(hp=90,block=0):return {'index':0,'name':'Louse Progenitor','hp':hp,'max_hp':90,'block':block,'powers':[{'name':'Curl Up','id':'CURL_UP_POWER','amount':18}],'intents':[{'type':'Attack','damage':23,'hits':1}]}
class Checks(unittest.TestCase):
 def test_multihit_card_finishes_before_curl_shield(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe());f.hit(7,2);self.assertEqual((f.lost,f.blk,f.curl),(14,18,0))
 def test_old_interposes_shield(self):
  with scoped({'combat_curl_after_card':False}):f=EP.Foe(foe());f.hit(7,2);self.assertEqual((f.lost,f.blk),(7,11))
 def test_fully_blocked_positive_attack_still_curls(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe(block=20));f.hit(7,2);self.assertEqual((f.lost,f.blk,f.curl),(0,24,0))
 def test_first_blocked_later_hp_loss_curls_after_card(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe(block=7));f.hit(7,2);self.assertEqual((f.lost,f.blk,f.curl),(7,18,0))
 def test_subsequent_card_no_second_curl(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe());f.hit(7,2);f.hit(20,1);self.assertEqual((f.lost,f.blk,f.curl),(16,0,0))
 def test_killed_target_no_block(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe(hp=12));f.hit(7,2);self.assertEqual((f.blk,f.curl),(0,0))
 def test_zero_hits_do_not_arm_curl(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe());f.hit(7,0);self.assertEqual((f.lost,f.blk,f.curl),(0,0,18))
 def test_zero_preview_retains_unresolved_scope(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe());f.hit(0,2);self.assertEqual((f.lost,f.blk,f.curl),(0,0,18))
 def test_peek_does_not_consume(self):
  with scoped({'combat_curl_after_card':True}):f=EP.Foe(foe());self.assertEqual(f.peek(7,2),14);self.assertEqual(f.curl,18)
 def test_non_curl_exact_legacy(self):
  e=foe();e['powers']=[]
  with scoped({'combat_curl_after_card':False}):a=EP.Foe(e);a.hit(7,3)
  with scoped({'combat_curl_after_card':True}):b=EP.Foe(e);b.hit(7,3)
  self.assertEqual((a.lost,a.blk),(b.lost,b.blk))
 def test_card_kill_projection_correct(self):
  c={'index':0,'id':'CARD.TWIN_STRIKE','name':'Twin Strike','type':'Attack','target_type':'AnyEnemy','cost':1,'can_play':True,'stats':{'damage':7,'repeat':2},'damage_by_target':[{'target_index':0,'damage':7,'repeat':2}]}
  st={'context':{'encounter':'LOUSE_PROGENITOR_NORMAL','act':1,'floor':10,'room_type':'Monster'},'round':1,'energy':1,'hand':[c],'player':{'hp':30,'max_hp':80,'block':0,'deck':[]},'player_powers':[],'enemies':[foe(hp=12)]};values=[]
  for flag in [False,True]:
   with scoped({'combat_curl_after_card':flag,'cv_weight':0,'imit_w':0}):x=combat.plan(st,{},set(),topk=-1)['ctx'];x['_parts']={};combat.evaluate([c],x);values.append(x['_parts']['cur'])
  self.assertEqual([p['dealt']for p in values],[7,12]);self.assertGreater(values[1]['killed'],values[0]['killed'])
 def test_observation_unchanged(self):
  e=foe();old=deepcopy(e)
  with scoped({'combat_curl_after_card':True}):EP.Foe(e).hit(7,2)
  self.assertEqual(e,old)
 def test_default_off_preserved(self):self.assertFalse(P['combat_curl_after_card'])

if __name__=='__main__':unittest.main(verbosity=2)
