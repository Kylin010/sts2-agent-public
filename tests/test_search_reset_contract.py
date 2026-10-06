"""Public-model search boundary: no real save/replay; no native processes."""
from copy import deepcopy
from pathlib import Path
import sys, unittest, subprocess
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb;require_kb(__name__)
subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No process starts'))
import params,sim
from policy import search
class ModelDouble:
 broken=False
 rec=None
 def send(self,cmd):raise AssertionError('No direct real/reset command expected')
class ResetContract(unittest.TestCase):
 def search(self, *, build_ok=True, draw_count=5, original_seed=None):
  state=dict(decision='combat_play',context=dict(act=1,floor=12,room_type='Elite',seed=original_seed),round=2,energy=3,player=dict(hp=50,block=0),hand=[],enemies=[dict(index=0,name='Visible enemy',hp=30,block=0)],draw_pile_count=draw_count)
  played=[];model_seeds=[]
  def build(model,visible,seed,**kw):
   model_seeds.append(seed);return deepcopy(state) if build_ok else None
  def play(*a):played.append(True);return deepcopy(state)
  with params.scoped(dict(search_on=True,search_public=True,search_public_fast=False,search_public_verify=False,search_potions=False,search_samples=1,search_refine_samples=0,search_time_cap=30)),patch.object(search.combat,'plan',return_value=[(1,[]),(0,[])]),patch.object(search,'build_public',side_effect=build),patch.object(search,'_reset',side_effect=AssertionError('No real-save replay')),patch.object(search,'_play_turn',side_effect=play),patch.object(search,'_value',return_value=10),patch.object(sim,'aux',return_value=ModelDouble()):
   result=search.search_turn(state,{})
  return result,played,model_seeds
 def test_failed_public_build_never_scores(self):
  result,played,seeds=self.search(build_ok=False);self.assertIsNone(result);self.assertEqual(played,[])
 def test_successful_public_build_scores_candidates(self):
  result,played,seeds=self.search();self.assertIsNotNone(result);self.assertEqual(len(played),2)
 def test_empty_draw_pile_is_a_valid_public_state(self):
  result,played,seeds=self.search(draw_count=0);self.assertIsNotNone(result);self.assertEqual(len(played),2)
 def test_candidates_share_same_independent_seed(self):
  _,_,seeds=self.search();self.assertEqual(seeds[0],seeds[1])
 def test_real_seed_does_not_choose_model_random_stream(self):
  self.assertEqual(self.search(original_seed='REAL_A')[2],self.search(original_seed='REAL_B')[2])
 def test_legacy_recipe_cannot_enable_real_replay(self):
  with params.scoped(dict(search_on=True,search_public=False)):
   self.assertFalse(search.enabled(dict(context=dict(room_type='Boss')),dict(recipe={'path':'old-real-save'})))
   with self.assertRaises(sim.SimError):search.search_turn({},dict(recipe={'path':'old-real-save'}))
 def test_unseen_reward_hp_cannot_change_current_score(self):
  def no_reward(*a):raise AssertionError('Reward continuation must not execute')
  scores=[search._value(50,dict(decision='card_reward',player=dict(hp=hp)),{'_ehp0':40},no_reward,None)for hp in [53,63,999]]
  self.assertEqual(scores,[scores[0]]*3)
if __name__=='__main__':unittest.main(verbosity=2)
