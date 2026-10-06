from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import sys,unittest,subprocess,collections
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def forbidden(*a,**kw):raise AssertionError('Native/process starts prohibited')
subprocess.Popen=forbidden
from params import P,scoped
from policy import foresight as F,combatvalue as CV,mentalmodel as MM
from policy.public_knowledge_demon import possible_curse_stages as stages
from tools import replay_situations as replay


def powers(**values):return [{'id':key+'_POWER','amount':val}for key,val in values.items()]
DONE=powers(MIND_ROT=1,SLOTH=3,DISINTEGRATION=8)
def enemy():
 e={'index':0,'name':'Knowledge Demon','hp':200,'max_hp':399,'block':0,
 'powers':[{'id':'STRENGTH_POWER','name':'Strength','amount':6}], 'intents':[]}
 for typ,dmg,hits in F._move_sig(F.BY_NAME[e['name']]['moves']['PONDER_MOVE']):
  e['intents'].append({'type':typ.capitalize(),'damage':dmg+6 if dmg else 0,'hits':hits})
 return e

class Checks(unittest.TestCase):
 def test_waste_away_proves_third_slot(self):self.assertEqual(stages(powers(WASTE_AWAY=1)),(3,))
 def test_dis8_proves_third_with_earlier_blocks(self):self.assertEqual(stages(powers(DISINTEGRATION=8)),(3,))
 def test_dis14_proves_first_and_third(self):self.assertEqual(stages(powers(DISINTEGRATION=14)),(3,))
 def test_dis15_proves_second_and_third(self):self.assertEqual(stages(powers(DISINTEGRATION=15)),(3,))
 def test_dis21_proves_all_three(self):self.assertEqual(stages(powers(DISINTEGRATION=21)),(3,))
 def test_dis13_still_ambiguous_if_third_blocked(self):self.assertEqual(stages(powers(DISINTEGRATION=13)),(2,3))
 def test_no_badges_does_not_prove_zero(self):self.assertEqual(stages([]),(0,1,2,3))
 def test_mind_rot_does_not_prove_first_only(self):self.assertEqual(stages(powers(MIND_ROT=1)),(1,2,3))
 def test_sloth_only_still_ambiguous(self):self.assertEqual(stages(powers(SLOTH=3)),(2,3))
 def test_known_three_choices(self):self.assertEqual(stages(DONE),(3,))
 def test_impossible_combination_rejected(self):self.assertIsNone(stages(powers(MIND_ROT=1,DISINTEGRATION=6)))
 def test_all_dis_plus_sloth_rejected(self):self.assertIsNone(stages(powers(DISINTEGRATION=21,SLOTH=3)))
 def test_bad_amount_rejected(self):self.assertIsNone(stages(powers(DISINTEGRATION=9)))
 def test_bool_amount_rejected(self):self.assertIsNone(stages(powers(WASTE_AWAY=True)))
 def test_duplicate_counters_rejected(self):self.assertIsNone(stages(powers(WASTE_AWAY=1)+powers(WASTE_AWAY=1)))
 def test_missing_public_powers_unknown(self):self.assertIsNone(stages(None))
 def test_ponder_after_third_is_not_curse(self):
  with scoped({'foresight_public_kd_loop':True}):self.assertEqual(F.future(enemy(),'PONDER_MOVE',4,public_player_powers=DONE),[27,54,22,30])
 def test_ambiguous_branch_retains_legacy(self):
  with scoped({'foresight_public_kd_loop':False}):a=F.future(enemy(),'PONDER_MOVE',5,public_player_powers=DONE)
  with scoped({'foresight_public_kd_loop':True}):self.assertEqual(a,F.future(enemy(),'PONDER_MOVE',5,public_player_powers=powers(DISINTEGRATION=13)))
 def test_no_context_retains_legacy(self):
  with scoped({'foresight_public_kd_loop':False}):a=F.future(enemy(),'PONDER_MOVE',5)
  with scoped({'foresight_public_kd_loop':True}):self.assertEqual(a,F.future(enemy(),'PONDER_MOVE',5))
 def test_default_off_exact(self):
  self.assertFalse(P['foresight_public_kd_loop'])
  self.assertEqual(F.future(enemy(),'PONDER_MOVE',4,public_player_powers=DONE),[13.5,40.5,38,18.875])
 def test_non_kd_branch_unchanged(self):
  m=deepcopy(F.BY_NAME['Knowledge Demon']);m['name']='Different Monster'
  with scoped({'foresight_public_kd_loop':True}):self.assertEqual(F.resolve_next(m,'CurseOfKnowledgeBranch',public_player_powers=DONE),{'CURSE_OF_KNOWLEDGE_MOVE':.5,'SLAP_MOVE':.5})
 def test_cv_runtime_gets_public_context(self):
  st={'context':{'act':2,'encounter':'KNOWLEDGE_DEMON_BOSS'},'round':12,'player':{'hp':60,'max_hp':80,'block':10,'deck':[]},'player_powers':DONE,'enemies':[enemy()]}
  with scoped({'foresight_public_kd_loop':True}):self.assertAlmostEqual(CV.situation_from_state(st)['enemies'][0]['fut'],103/3)
 def test_ema_foresight_gets_same_context(self):
  with scoped({'foresight_public_kd_loop':True}):self.assertAlmostEqual(F.expected_incoming([enemy()],{},turns=3,public_player_powers=DONE),103/3)
 def test_mental_schedule_damage_and_heal_consistent(self):
  with scoped({'foresight_public_kd_loop':True}):
   heal,block,sched=MM.schedule([enemy()],3,{},public_player_powers=DONE)
   self.assertEqual([x[0]for x in sched],[27,54,22]);self.assertEqual([x[1]for x in sched],[0,0,30])
 def test_training_future_same_semantics(self):
  with scoped({'foresight_public_kd_loop':True}):self.assertAlmostEqual(replay.fut_of('KNOWLEDGE_DEMON','PONDER_MOVE',6,19,DONE)[0],103/3)
 def test_snapshot_before_later_power_changes(self):
  cb=SimpleNamespace(enemies=[],ppw=collections.Counter({'MIND_ROT_POWER':1,'SLOTH_POWER':3,'DISINTEGRATION_POWER':8}),
   enc='KNOWLEDGE_DEMON_BOSS',act=2,round=12,hp=60,max_hp=80,block=10,deck_n=20,draw_n=10,disc_n=5,my_dpt=30)
  with scoped({'foresight_public_kd_loop':True}):snap=replay.situation(cb)
  cb.ppw.clear()
  self.assertEqual(stages(snap['public_player_powers']),(3,))
 def test_default_off_training_schema_unchanged(self):
  cb=SimpleNamespace(enemies=[],ppw=collections.Counter(),enc='KNOWLEDGE_DEMON_BOSS',act=2,round=12,hp=60,max_hp=80,block=10,deck_n=20,draw_n=10,disc_n=5,my_dpt=30)
  with scoped({'foresight_public_kd_loop':False}):self.assertNotIn('public_player_powers',replay.situation(cb))
 def test_completed_pending_training_uses_snapshot(self):
  snap={'enemies':[{'key':0,'id':'KNOWLEDGE_DEMON','str':6,'intent':0,'fut':0}], 'public_player_powers':DONE}
  cb=SimpleNamespace(pending={'s':snap,'_acc':{0:19},'_moves':{0:'PONDER_MOVE'},'_v7':{}},enemies=[])
  with scoped({'foresight_public_kd_loop':True}):replay.close_pending(cb,collections.Counter())
  self.assertAlmostEqual(snap['enemies'][0]['fut'],34.33)
 def test_public_input_unchanged(self):
  e=enemy();p=deepcopy(DONE);old=deepcopy((e,p))
  with scoped({'foresight_public_kd_loop':True}):F.future(e,'PONDER_MOVE',4,public_player_powers=p)
  self.assertEqual((e,p),old)
 def test_private_counter_and_rng_irrelevant(self):
  e=enemy();e.update(_curseOfKnowledgeCounter=1000,private_next_move=object(),rng_counters=object())
  with scoped({'foresight_public_kd_loop':True}):self.assertEqual(F.future(e,'PONDER_MOVE',4,public_player_powers=DONE),[27,54,22,30])

if __name__=='__main__':unittest.main(verbosity=2)
