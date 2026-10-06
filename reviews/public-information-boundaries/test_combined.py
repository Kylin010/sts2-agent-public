import copy,importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
H=load('history_fixture','reviews/public-model-no-hidden-followup/test_history.py')
M=load('move_fixture','tests/test_public_move_beliefs.py')
from params import scoped
from policy import search,public_stun_history as S,public_move_beliefs as B
import run

def relic():return dict(id='PEN_NIB',is_wax=True,is_melted=True,status='Disabled',counter=9)
def proved_stun():
 a,b,mem=H.state(),H.state(hp=70,stun=True),{}
 a['player']['relics']=[relic()];b['player']['relics']=[relic()]
 S.observe_completed(a,'play_card',{'card_index':0},b,mem)
 return a,b,mem
class Combined(unittest.TestCase):
 def test_public_stun_and_melted_relic_both_restored(self):
  a,b,mem=proved_stun();model=H.ModelDouble(b)
  with scoped({'search_public_fast':False}):self.assertIsNotNone(search.build_public(model,b,2,public_history=mem))
  p=next(c for c in model.commands if c['cmd']=='set_combat')
  self.assertEqual(p['enemies'][0]['move'],'STUNNED');self.assertEqual(p['enemies'][0]['move_next'],'TERROR_MOVE')
  self.assertTrue(p['relic_lifecycle']['PEN_NIB']['is_melted'])
 def test_valid_stun_cannot_bypass_missing_relic_flags(self):
  a,b,mem=proved_stun();b['player']['relics'][0].pop('is_melted');model=H.ModelDouble(b)
  self.assertIsNone(search.build_public(model,b,2,public_history=mem));self.assertEqual(model.commands,[])
 def test_valid_relic_flags_cannot_bypass_cold_stun(self):
  a,b,mem=proved_stun();model=H.ModelDouble(b)
  self.assertIsNone(search.build_public(model,b,2));self.assertEqual(model.commands,[])
 def test_valid_move_history_and_melted_relic_both_restored(self):
  a,b,mem=M.state(M.enemy(kind='Buff'),4),M.state(rnd=5),{}
  B.observe_completed(a,'end_turn',{},b,mem);b['player']['relics']=[relic()];model=H.ModelDouble(b)
  with scoped({'search_public_fast':False}):self.assertIsNotNone(search.build_public(model,b,2,public_history=mem))
  p=next(c for c in model.commands if c['cmd']=='set_combat')
  self.assertEqual(p['enemies'][0]['move'],'THRASH_MOVE_2');self.assertIsNone(p['enemies'][0]['move_next']);self.assertTrue(p['relic_lifecycle']['PEN_NIB']['is_melted'])
 def test_actual_driver_calls_both_observers_after_return(self):
  before=H.state();after={'decision':'card_reward','context':before['context'],'player':before['player']};events=[]
  class Transport:
   def act(self,a,**args):events.append('returned');return after
  def mark(*args):
   self.assertEqual(events[0],'returned');self.assertIs(args[0],before);self.assertIs(args[3],after);events.append('observed')
  with scoped({'sl_on':False,'search_on':False,'simeval_pick':False,'simeval_route':False}),patch('policy.decide',return_value=('play_card',{'card_index':0})),patch.object(B,'observe_completed',side_effect=mark),patch.object(S,'observe_completed',side_effect=mark):
   run.drive(Transport(),before,{},combat_only=True)
  self.assertEqual(events,['returned','observed','observed'])
if __name__=='__main__':unittest.main(verbosity=2)
