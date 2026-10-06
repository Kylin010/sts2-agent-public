"""Public inference contracts; native processes are forbidden in this suite."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb; require_kb(__name__)
from policy import public_move_beliefs as B, search, nnpolicy, combat
from params import scoped

def enemy(name='The Insatiable', kind='Attack', hits=2, damage=9):
    return dict(name=name, index=0, monster_id='THE_INSATIABLE', hp=341,
                max_hp=341, block=0, powers=[], intents=[dict(type=kind, hits=hits, damage=damage)])

def state(e=None, rnd=2):
    return dict(decision='combat_play', round=rnd, energy=3, hand=[],
                context=dict(act=2, floor=17, room_type='Boss', encounter='THE_INSATIABLE_BOSS'),
                player=dict(hp=64, max_hp=80, block=0, relics=[], deck=[], potions=[]),
                enemies=[e or enemy()], draw_pile=[], discard_pile=[], exhaust_pile=[], player_powers=[])

class MoveBeliefs(unittest.TestCase):
    def setUp(self):
        self.no_native = patch('subprocess.Popen', side_effect=AssertionError('native forbidden'))
        self.no_native.start()
    def tearDown(self): self.no_native.stop()
    def test_identical_sandworm_intent_ambiguous(self):
        e=enemy()
        self.assertEqual(B.candidates(e), ('THRASH_MOVE', 'THRASH_MOVE_2'))
        self.assertIsNone(B.unique_move(state(e),e))
    def test_private_id_and_followup_do_not_change_candidates(self):
        for mid in ['THRASH_MOVE','THRASH_MOVE_2','MADE_UP']:
            e=enemy(); e.update(move_id=mid,move_next='SECRET',rng_counters={'enemy':99})
            self.assertEqual(B.candidates(e), ('THRASH_MOVE','THRASH_MOVE_2'))
    def test_damage_not_inverted_under_unknown_modifiers(self):
        for damage in [0,9,99]: self.assertEqual(B.candidates(enemy(damage=damage)), ('THRASH_MOVE','THRASH_MOVE_2'))
    def test_known_single_hit_sandworm_unique(self):
        e=enemy(hits=1,damage=31)
        self.assertEqual(B.unique_move(state(e),e),'LUNGING_BITE_MOVE')
    def test_kin_two_debuff_attacks_ambiguous(self):
        e=enemy('Kin Priest',hits=1);e['intents'].append({'type':'Debuff'})
        self.assertEqual(len(B.candidates(e)),2)
    def test_cubex_two_attack_buff_moves_ambiguous(self):
        e=enemy('Cubex Construct',hits=1);e['intents'].append({'type':'Buff'})
        self.assertEqual(len(B.candidates(e)),2)
    def test_stun_unknown_and_invalid_intents_defer(self):
        for intents in [[{'type':'Stun'}],None,[],['bad'],[{'type':'Attack','hits':True}],[{'type':'Attack','hits':0}]]:
            e=enemy();e['intents']=intents;self.assertIsNone(B.candidates(e))
    def test_unknown_enemy_defer(self): self.assertIsNone(B.candidates(enemy('Unknown')))
    def test_end_turn_liquify_public_history_identifies_first_thrash(self):
        e=enemy(kind='Buff');e['intents'].append({'type':'StatusCard'})
        a,b,mem=state(e,1),state(),{}
        B.observe_completed(a,'end_turn',{},b,mem)
        self.assertEqual(B.unique_move(b,b['enemies'][0],mem),'THRASH_MOVE')
    def test_completed_salivate_identifies_second_thrash(self):
        a,b,mem=state(enemy(kind='Buff'),4),state(rnd=5),{}
        B.observe_completed(a,'end_turn',{},b,mem)
        self.assertEqual(B.unique_move(b,b['enemies'][0],mem),'THRASH_MOVE_2')
    def proof(self):
        a,b,mem=state(enemy(kind='Buff'),4),state(rnd=5),{}
        B.observe_completed(a,'end_turn',{},b,mem)
        return b,mem
    def test_plain_action_preserves_public_proof(self):
        a,mem=self.proof();a['hand']=[{'index':3,'id':'CARD.BASH'}];b=copy.deepcopy(a);b['enemies'][0]['hp']-=8
        B.observe_completed(a,'play_card',{'card_index':3},b,mem)
        self.assertEqual(B.unique_move(b,b['enemies'][0],mem),'THRASH_MOVE_2')
    def test_gap_error_unknown_card_potion_drop_proof(self):
        for case in ['gap','error','card','potion','enchanted','maxhp','floor']:
            a,mem=self.proof();a['hand']=[{'index':3,'id':'CARD.BASH'}];b=copy.deepcopy(a);action='play_card'
            if case=='gap':b['round']+=2;action='end_turn'
            if case=='error':b['type']='error'
            if case=='card':a['hand'][0]['id']='CARD.UNKNOWN'
            if case=='potion':action='use_potion'
            if case=='enchanted':a['hand'][0]['spec']='BASH#UNKNOWN=1'
            if case=='maxhp':b['enemies'][0]['max_hp']+=1
            if case=='floor':b['context']['floor']+=1
            B.observe_completed(a,action,{'card_index':3},b,mem)
            self.assertNotIn('_public_move_belief',mem,case)
    def test_other_monster_history_not_certified(self):
        a=state(enemy('Lagavulin Matriarch',kind='Sleep'),1);b=copy.deepcopy(a);b['round']=2;mem={}
        B.observe_completed(a,'end_turn',{},b,mem);self.assertNotIn('_public_move_belief',mem)
    def test_stale_history_not_consumed(self):
        a,mem=self.proof();a['round']+=1
        self.assertIsNone(B.unique_move(a,a['enemies'][0],mem))
    def test_ambiguous_builder_sends_no_model_commands(self):
        class Reject:
            def send(self,*a): raise AssertionError('no command allowed')
        self.assertIsNone(search.build_public(Reject(),state(),1))
    def test_builder_payload_uses_public_history_only(self):
        st,mem=self.proof();st['enemies'][0]['move_id']='THRASH_MOVE'  # false private value
        class Fake:
            def __init__(self):self.sent=[]
            def send(self,payload):
                self.sent.append(payload)
                return copy.deepcopy(st) if payload['cmd']=='set_combat' else {'type':'ok'}
        fake=Fake()
        with scoped({'search_public_fast':False}):
            self.assertIsNotNone(search.build_public(fake,st,17,public_history=mem))
        payload=next(p for p in fake.sent if p['cmd']=='set_combat')
        self.assertEqual(payload['enemies'][0]['move'],'THRASH_MOVE_2')
        self.assertIsNone(payload['enemies'][0]['move_next'])
    def test_private_changes_cannot_affect_public_fingerprint(self):
        a,b=state(),state();a['enemies'][0]['move_id']='THRASH_MOVE';b['enemies'][0]['move_id']='THRASH_MOVE_2'
        b['enemies'][0]['move_next']='HIDDEN';b['context']['seed']='REAL_SECRET'
        self.assertEqual(search._vis(a),search._vis(b))
    def test_visible_intent_damage_affects_fingerprint(self):
        a,b=state(),state();b['enemies'][0]['intents'][0]['damage']=10
        self.assertNotEqual(search._vis(a),search._vis(b))
    def test_nn_encoding_never_uses_private_id(self):
        a,b=state(),state();a['enemies'][0]['move_id']='THRASH_MOVE';b['enemies'][0]['move_id']='THRASH_MOVE_2'
        self.assertEqual(nnpolicy.encode_state(a),nnpolicy.encode_state(b))
        self.assertEqual(nnpolicy.encode_state(a)['enemies'][0]['mv'],'')
    def test_phase_alpha_ambiguous_does_not_select_hidden_multiplier(self):
        # Real planner path; distinguishable hidden IDs must give identical ctx.
        a,b=state(),state();a['enemies'][0]['move_id']='THRASH_MOVE';b['enemies'][0]['move_id']='THRASH_MOVE_2'
        for st in [a,b]:
            st['hand']=[dict(index=0,id='CARD.STRIKE_IRONCLAD',name='Strike',type='Attack',cost=1,can_play=True,target_type='AnyEnemy',stats={'damage':6},damage_by_target=[{'target_index':0,'damage':6}])]
        with scoped({'cv_weight':0,'imit_w':0}):
            ca=combat.plan(a,{},set(),topk=-1)['ctx'];cb=combat.plan(b,{},set(),topk=-1)['ctx']
        self.assertEqual(ca['alpha'],cb['alpha'])

if __name__=='__main__':unittest.main()
