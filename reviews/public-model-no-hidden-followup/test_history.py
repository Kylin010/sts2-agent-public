from pathlib import Path
from copy import deepcopy
import sys, subprocess, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No process starts'))
from policy.public_stun_history import observe_completed,followup
from policy import search
from params import scoped
def power(key,n):return dict(id=key,amount=n)
def card(key='STRIKE_IRONCLAD'):return dict(index=0,id='CARD.'+key,type='Attack',cost=1,can_play=True)
def state(name='Terror Eel',hp=76,stun=False):
 return dict(type='decision',decision='combat_play',context=dict(act=1,floor=12,encounter='TERROR_EEL_ELITE'),round=2,energy=3,draw_pile=[],discard_pile=[],exhaust_pile=[],hand=[card()],player=dict(hp=50,max_hp=80,block=0,deck=[],relics=[],potions=[]),player_powers=[],enemies=[dict(index=0,name=name,monster_id='TERROR_EEL',max_hp=150,hp=hp,block=0,move_id='STUNNED'if stun else'CRASH_MOVE',move_next='REAL_HIDDEN_MOVE',powers=[]if stun else[power('SHRIEK_POWER',75)],intents=[dict(type='Stun')]if stun else[dict(type='Attack',damage=18)])])
class ModelDouble:
 def __init__(self,after):self.after=after;self.commands=[]
 def send(self,cmd):
  self.commands.append(deepcopy(cmd))
  if cmd['cmd']=='set_combat':return deepcopy(self.after)
  return dict(type='ok')
class Checks(unittest.TestCase):
 def test_cold_stun_no_hidden_followup(self):
  st=state(hp=70,stun=True)
  for hidden in ['TERROR_MOVE','CRASH_MOVE','THRASH_MOVE']:
   st['enemies'][0]['move_next']=hidden;s=ModelDouble(st)
   self.assertIsNone(search.build_public(s,st,123));self.assertEqual(s.commands,[])
 def test_completed_shriek_crossing_proves_terror(self):
  a,b=state(),state(hp=70,stun=True);m={};observe_completed(a,'play_card',dict(card_index=0,target_index=0),b,m)
  self.assertEqual(followup(b,m),'TERROR_MOVE')
 def test_builder_uses_proof_not_native_followup(self):
  a,b=state(),state(hp=70,stun=True);m={};observe_completed(a,'play_card',dict(card_index=0),b,m)
  for hidden in ['CRASH_MOVE','THRASH_MOVE','OTHER_PRIVATE_MOVE']:
   b['enemies'][0]['move_next']=hidden;s=ModelDouble(b)
   with scoped(dict(search_public_fast=False)):
    self.assertIsNotNone(search.build_public(s,b,123,public_history=m))
   cmd=next(c for c in s.commands if c['cmd']=='set_combat')
   self.assertEqual(cmd['enemies'][0]['move_next'],'TERROR_MOVE')
 def test_private_current_id_cannot_override_visible_stun(self):
  a,b=state(),state(hp=70,stun=True);m={};observe_completed(a,'play_card',dict(card_index=0),b,m);b['enemies'][0]['move_id']='UNKNOWN_PRIVATE'
  s=ModelDouble(b)
  with scoped(dict(search_public_fast=False)):self.assertIsNotNone(search.build_public(s,b,123,public_history=m))
  self.assertEqual(next(c for c in s.commands if c['cmd']=='set_combat')['enemies'][0]['move'],'STUNNED')
 def test_error_or_no_damage_not_proof(self):
  for hp,error in [(76,False),(70,True)]:
   a,b=state(),state(hp=hp,stun=True)
   if error:b['type']='error'
   m={};observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
 def test_missing_badge_does_not_prove_cause(self):
  a,b=state(),state(hp=70,stun=True);a['enemies'][0]['powers']=[];m={};observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
 def test_unknown_card_or_enchantment_defer(self):
  for key,enchant in [('UNKNOWN_ATTACK',None),('STRIKE_IRONCLAD','Unknown')]:
   a,b=state(),state(hp=70,stun=True);a['hand']=[card(key)]
   if enchant:a['hand'][0]['enchantment']=enchant
   m={};observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
 def test_round_or_floor_gap_defer(self):
  for field in ['round','floor']:
   a,b=state(),state(hp=70,stun=True)
   if field=='round':b['round']+=1
   else:b['context']['floor']+=1
   m={};observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
 def test_matriarch_wake_proof(self):
  a,b=state('Lagavulin Matriarch',100),state('Lagavulin Matriarch',94,True)
  for st in (a,b):st['enemies'][0]['max_hp']=233
  a['enemies'][0]['powers']=[power('ASLEEP_POWER',3)];m={}
  observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertEqual(followup(b,m),'SLASH_MOVE')
 def test_same_pending_stun_survives_later_plain_card(self):
  a,b=state(),state(hp=70,stun=True);m={};observe_completed(a,'play_card',dict(card_index=0),b,m)
  c=deepcopy(b);c['enemies'][0]['hp']=64;observe_completed(b,'play_card',dict(card_index=0),c,m)
  self.assertEqual(followup(c,m),'TERROR_MOVE')
 def test_end_turn_clears_proof(self):
  a,b=state(),state(hp=70,stun=True);m={};observe_completed(a,'play_card',dict(card_index=0),b,m)
  c=deepcopy(b);c['round']+=1;observe_completed(b,'end_turn',{},c,m);self.assertIsNone(followup(c,m))
 def test_nonstun_no_next_field_copied(self):
  st=state();s=ModelDouble(st)
  with scoped(dict(search_public_fast=False)):self.assertIsNotNone(search.build_public(s,st,123))
  self.assertIsNone(next(c for c in s.commands if c['cmd']=='set_combat')['enemies'][0]['move_next'])
 def test_input_not_mutated(self):
  a,b=state(),state(hp=70,stun=True);old=deepcopy((a,b));m={};observe_completed(a,'play_card',dict(card_index=0),b,m)
  self.assertEqual((a,b),old)
 def test_preexisting_whistle_stun_cannot_be_promoted_by_shriek(self):
  a,b=state(hp=76,stun=True),state(hp=70,stun=True);a['enemies'][0]['powers']=[power('SHRIEK_POWER',75)];m={}
  observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
 def test_preexisting_whistle_stun_cannot_be_promoted_by_asleep(self):
  a,b=state('Lagavulin Matriarch',100,True),state('Lagavulin Matriarch',94,True);a['enemies'][0]['powers']=[power('ASLEEP_POWER',3)];m={}
  observe_completed(a,'play_card',dict(card_index=0),b,m);self.assertIsNone(followup(b,m))
if __name__=='__main__':unittest.main(verbosity=2)
