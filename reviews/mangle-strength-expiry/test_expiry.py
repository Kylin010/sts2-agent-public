from pathlib import Path
import sys,unittest,subprocess,json
from copy import deepcopy
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def forbidden(*a,**kw):raise AssertionError('No native/process starts in pure checks')
subprocess.Popen=forbidden
from params import P,scoped
from policy import foresight as F

def enemy(amount=15,strength=-15):
 return {'name':'Knowledge Demon','powers':[{'id':'STRENGTH_POWER','name':'Strength','amount':strength},
         {'id':'MANGLE_POWER','name':'Mangle','amount':amount}]}

class Checks(unittest.TestCase):
 def test_next_multihit_returns_current_loss(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(F.future(enemy(),'SLAP_MOVE',1),[27.0])
 def test_next_ponder_strength_restored(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(F.future(enemy(),'KNOWLEDGE_OVERWHELMING_MOVE',1),[13.0])
 def test_existing_permanent_strength_kept(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(F.future(enemy(strength=-9),'SLAP_MOVE',1),[45.0])
 def test_original_enemy_power_not_mutated(self):
  e=enemy();old=deepcopy(e)
  with scoped({'foresight_public_mangle_expiry':True}):F.future(e,'SLAP_MOVE',3)
  self.assertEqual(e,old)
 def test_no_mangle_exact_legacy(self):
  e={'name':'Knowledge Demon','powers':[{'name':'Strength','amount':3}]}
  with scoped({'foresight_public_mangle_expiry':False}):a=F.future(e,'SLAP_MOVE',5)
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(a,F.future(e,'SLAP_MOVE',5))
 def test_unknown_temporary_power_not_assumed_mangle(self):
  e=enemy();e['powers'][1]['id']='UNKNOWN_TEMP'
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(F.future(e,'SLAP_MOVE',1),[0.0])
 def test_bad_visible_amount_defer(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertIsNone(F.future(enemy(amount=None),'SLAP_MOVE',1))
 def test_negative_mangle_amount_defer(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertIsNone(F.future(enemy(amount=-15),'SLAP_MOVE',1))
 def test_boolean_amount_defer(self):
  with scoped({'foresight_public_mangle_expiry':True}):self.assertIsNone(F.future(enemy(amount=True),'SLAP_MOVE',1))
 def test_default_off_original_result(self):
  self.assertFalse(P['foresight_public_mangle_expiry']);self.assertEqual(F.future(enemy(),'SLAP_MOVE',1),[0.0])
 def test_completed_actual_next_intents(self):
  data=json.loads((Path(__file__).parent/'completed-actual-witnesses.json').read_text())
  for case in data['cases']:
   shown=case['current_public'];powers=shown['fpow'][0]
   e=enemy(amount=powers['MANGLE_POWER.title'],strength=powers['Strength'])
   e['intents']=[{'type':'Attack','damage':shown['foes'][0][3],'hits':1}]
   with scoped({'foresight_public_mangle_expiry':True}):
    self.assertEqual(F.future(e,F.identify(e),1),[case['observed_next_damage']])
 def test_private_future_fields_ignored(self):
  e=enemy();a=deepcopy(e);a.update(private_next_move=object(),rng_counters=object())
  with scoped({'foresight_public_mangle_expiry':True}):self.assertEqual(F.future(a,'SLAP_MOVE',3),F.future(e,'SLAP_MOVE',3))

if __name__=='__main__':unittest.main(verbosity=2)
