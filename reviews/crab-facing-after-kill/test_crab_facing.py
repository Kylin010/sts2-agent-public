from pathlib import Path
from copy import deepcopy
import sys,json,unittest,subprocess
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def forbidden(*a,**kw):raise AssertionError('Native/process starts prohibited')
subprocess.Popen=forbidden
from params import scoped,P
from policy import combat

def fixture():
 crusher={'index':0,'name':'Crusher','hp':10,'max_hp':189,'block':0,'powers':[{'id':'CRAB_RAGE_POWER','name':'Crab Rage','amount':1}], 'intents':[{'type':'Buff'}]}
 rocket={'index':1,'name':'Rocket','hp':200,'max_hp':239,'block':0,'powers':[{'id':'CRAB_RAGE_POWER','name':'Crab Rage','amount':1}],'intents':[{'type':'Attack','damage':38,'hits':1}]}
 card={'index':0,'id':'CARD.STRIKE_IRONCLAD','name':'Strike','cost':1,'type':'Attack','target_type':'AnyEnemy','can_play':True,'stats':{'damage':20},'damage_by_target':[{'target_index':0,'damage':20},{'target_index':1,'damage':20}]}
 st={'context':{'act':2,'floor':16,'room_type':'Boss','encounter':'KAISER_CRAB_BOSS'},'round':4,'energy':3,'hand':[card],
  'player':{'hp':70,'max_hp':80,'block':0,'deck':[]},'player_powers':[{'id':'SURROUNDED_POWER','name':'Surrounded','amount':1},{'id':'STRENGTH_POWER','name':'Strength','amount':14}],'enemies':[crusher,rocket]}
 ctx=combat.plan(st,{'crab_facing':'rocket'},set(),topk=-1)['ctx']
 return st,ctx,card,crusher,rocket

class Checks(unittest.TestCase):
 def test_death_autofaces_remaining_laser(self):
  st,ctx,c,crusher,rocket=fixture();t={id(c):crusher}
  with scoped({'crab_facing_after_kill':False}):self.assertEqual(combat._facing_extra([c],ctx,t,crusher,st['enemies'],0,[rocket]),19)
  with scoped({'crab_facing_after_kill':True}):self.assertEqual(combat._facing_extra([c],ctx,t,crusher,st['enemies'],0,[rocket]),0)
 def test_no_death_still_targeting_changes_direction(self):
  st,ctx,c,crusher,rocket=fixture();t={id(c):crusher}
  with scoped({'crab_facing_after_kill':True}):self.assertEqual(combat._facing_extra([c],ctx,t,crusher,st['enemies'],0,st['enemies']),19)
 def test_both_dead_no_incoming_facing_penalty(self):
  st,ctx,c,crusher,rocket=fixture()
  with scoped({'crab_facing_after_kill':True}):self.assertEqual(combat._facing_extra([c],ctx,{id(c):crusher},crusher,st['enemies'],0,[]),0)
 def test_missing_surrounded_preserves_old(self):
  st,ctx,c,crusher,rocket=fixture();ctx['player_powers']=[]
  with scoped({'crab_facing_after_kill':True}):self.assertEqual(combat._facing_extra([c],ctx,{id(c):crusher},crusher,st['enemies'],0,[rocket]),19)
 def test_revive_mechanism_rejects_new_guard(self):
  st,ctx,c,crusher,rocket=fixture();crusher['powers'].append({'name':'Adaptable','amount':1})
  with scoped({'crab_facing_after_kill':True}):self.assertEqual(combat._facing_extra([c],ctx,{id(c):crusher},crusher,st['enemies'],0,[rocket]),19)
 def test_score_integration_removes_fictional_penalty(self):
  st,ctx,c,crusher,rocket=fixture()
  with scoped({'crab_facing_after_kill':False}):a=combat.evaluate([c],ctx)
  with scoped({'crab_facing_after_kill':True}):b=combat.evaluate([c],ctx)
  self.assertAlmostEqual(b-a,19*P['crab_facing_w']*P['block_mult'])
 def test_nonlethal_score_exact(self):
  st,ctx,c,crusher,rocket=fixture();crusher['hp']=189
  with scoped({'crab_facing_after_kill':False}):a=combat.evaluate([c],ctx)
  with scoped({'crab_facing_after_kill':True}):b=combat.evaluate([c],ctx)
  self.assertEqual(a,b)
 def test_public_input_unchanged(self):
  st,ctx,c,crusher,rocket=fixture();before=deepcopy(st)
  with scoped({'crab_facing_after_kill':True}):combat.evaluate([c],ctx)
  self.assertEqual(st,before)

if __name__=='__main__':unittest.main(verbosity=2)
