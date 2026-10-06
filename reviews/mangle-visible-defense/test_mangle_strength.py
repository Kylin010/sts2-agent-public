from pathlib import Path
import sys,unittest
from copy import deepcopy
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
from policy.public_strength_loss import mangle_incoming_bound

def fixture(damage=11,hits=3,loss=15):
    c=dict(id='CARD.MANGLE',type='Attack',stats={'strengthloss':loss});e=dict(index=0,powers=[],intents=[dict(type='Attack',damage=damage,hits=hits)])
    return c,e,dict(player_powers=[],relics=[]),{id(c):e}

class Checks(unittest.TestCase):
    def test_multihit33_to0(self):c,e,x,t=fixture();v=mangle_incoming_bound([c],e,x,t);self.assertEqual((v['shown_before'],v['after_upper']),(33,0))
    def test_pounce45_to30(self):c,e,x,t=fixture(45,1,15);self.assertEqual(mangle_incoming_bound([c],e,x,t)['after_upper'],30)
    def test_existing_weak_floor_bounds(self):
        c,e,x,t=fixture(15,1,15);e['powers']=[dict(id='WEAK_POWER',amount=1)];v=mangle_incoming_bound([c],e,x,t);self.assertEqual((v['hits'][0]['after_lower'],v['after_upper']),(3,4))
    def test_hero_vulnerable_factor(self):c,e,x,t=fixture(16,1,10);x['player_powers']=[dict(id='VULNERABLE_POWER',amount=1)];self.assertEqual(mangle_incoming_bound([c],e,x,t)['after_upper'],1)
    def test_nonattack_unchanged0(self):c,e,x,t=fixture();e['intents']=[dict(type='Buff')];self.assertEqual(mangle_incoming_bound([c],e,x,t)['after_upper'],0)
    def test_unknown_modifier_defer(self):c,e,x,t=fixture();e['powers']=[dict(id='UNKNOWN_DAMAGE',amount=1)];self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_unknown_relic_defer(self):c,e,x,t=fixture();x['relics']={'UNKNOWN_RELIC'};self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_artifact_id_without_name_defer(self):c,e,x,t=fixture();e['powers']=[dict(id='ARTIFACT_POWER',amount=1)];self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_zero_loss_defer(self):c,e,x,t=fixture(loss=0);self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_missing_hud_defer(self):c,e,x,t=fixture();e['intents'][0].pop('damage');self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_target_difference_defer(self):c,e,x,t=fixture();t[id(c)]=deepcopy(e);self.assertIsNone(mangle_incoming_bound([c],e,x,t))
    def test_enemy_intangible_does_not_stop_debuff(self):c,e,x,t=fixture();e['powers']=[dict(id='INTANGIBLE_POWER',amount=1)];self.assertEqual(mangle_incoming_bound([c],e,x,t)['after_upper'],0)
    def test_enrage_skill_combo_unknown(self):c,e,x,t=fixture();e['powers']=[dict(id='ENRAGE_POWER',amount=3)];self.assertIsNone(mangle_incoming_bound([c,dict(type='Skill')],e,x,t))
    def test_combo_enemy_strength_gain_unknown(self):c,e,x,t=fixture();self.assertIsNone(mangle_incoming_bound([c,dict(stats={'enemystrength':1})],e,x,t))
    def test_private_rng_not_used(self):
        c,e,x,t=fixture();a=mangle_incoming_bound([c],e,x,t);e.update(rng_counters=object(),private_phase=object(),move_id=object());self.assertEqual(a,mangle_incoming_bound([c],e,x,t))

if __name__=='__main__':unittest.main(verbosity=2)
