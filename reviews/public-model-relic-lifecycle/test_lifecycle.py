from pathlib import Path
from copy import deepcopy
import sys,subprocess,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No process starts'))
from policy.public_relic_lifecycle import model_flags
from policy import search
from params import scoped
def relic(key='PEN_NIB',wax=True,melted=True,status='Disabled'):
 return dict(id=key,is_wax=wax,is_melted=melted,status=status,counter=9)
def state(rows):
 return dict(context=dict(encounter='BYGONE_EFFIGY_ELITE',act=1,floor=10),round=3,energy=3,hand=[],draw_pile=[],discard_pile=[],exhaust_pile=[],player=dict(hp=50,max_hp=80,block=0,relics=rows,deck=[],potions=[]),player_powers=[],enemies=[])
class Model:
 def __init__(self,st,restore=True):self.st=st;self.restore=restore;self.commands=[]
 def send(self,cmd):
  self.commands.append(deepcopy(cmd))
  if cmd['cmd']=='set_combat':
   st=deepcopy(self.st);st['decision']='combat_play'
   if not self.restore:
    for r in st['player']['relics']:r.pop('is_wax',None);r.pop('is_melted',None)
   return st
  return dict(type='ok')
class Checks(unittest.TestCase):
 def test_explicit_melted_wax_flags(self):self.assertEqual(model_flags([relic()]),{'PEN_NIB':dict(is_wax=True,is_melted=True)})
 def test_disabled_can_be_used_up_bone_tea(self):
  self.assertIsNone(model_flags([relic('BONE_TEA',False,False)]))
 def test_missing_flags_defer_instead_of_status_guess(self):
  self.assertIsNone(model_flags([dict(id='PEN_NIB',status='Disabled',counter=9)]))
 def test_missing_flags_normal_status_also_unknown(self):
  self.assertIsNone(model_flags([dict(id='PEN_NIB',status='Normal',counter=9)]))
 def test_toybox_lifetime_not_guessed(self):
  for status in ['Normal','Active','Disabled']:
   self.assertIsNone(model_flags([relic('TOY_BOX',False,False,status)]))
 def test_invalid_bool_and_impossible_flags_defer(self):
  self.assertIsNone(model_flags([relic(wax=1)]));self.assertIsNone(model_flags([relic(wax=False,melted=True)]))
 def test_duplicate_relic_unknown_instance_state_defer(self):self.assertIsNone(model_flags([relic(),relic()]))
 def test_namespace_relic_id(self):self.assertIn('PEN_NIB',model_flags([relic('RELIC.PEN_NIB')]))
 def test_model_receives_flags_separately_from_status(self):
  st=state([relic()]);model=Model(st)
  with scoped(dict(search_public_fast=False)):self.assertIsNotNone(search.build_public(model,st,7))
  cmd=next(c for c in model.commands if c['cmd']=='set_combat');self.assertEqual(cmd['relic_lifecycle']['PEN_NIB'],dict(is_wax=True,is_melted=True));self.assertEqual(cmd['relic_status']['PEN_NIB'],'Disabled')
 def test_missing_ui_flags_stop_before_any_model_command(self):
  st=state([dict(id='PEN_NIB',status='Disabled')]);model=Model(st)
  self.assertIsNone(search.build_public(model,st,7));self.assertEqual(model.commands,[])
 def test_old_model_ignoring_lifecycle_not_accepted(self):
  st=state([relic()]);model=Model(st,restore=False)
  with scoped(dict(search_public_fast=False)):self.assertIsNone(search.build_public(model,st,7))
 def test_input_preserved(self):
  rows=[relic()];old=deepcopy(rows);model_flags(rows);self.assertEqual(rows,old)
if __name__=='__main__':unittest.main(verbosity=2)
