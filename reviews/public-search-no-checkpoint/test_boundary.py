from pathlib import Path
import sys, unittest, subprocess
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No process starts'))
import params, policy, run
from policy import search
from sim import SimError

class PublicMap:
    def __init__(self):self.sent=[]
    def get_map(self):return {'rows':[[{'col':0,'row':1,'type':'Elite','children':[]}]],'boss':{'col':0,'row':2}}
    def send(self,cmd):self.sent.append(cmd);raise AssertionError('Real command is not a map read')
class Follower:
    def route(self,m,st):return {'col':0,'row':1}
def state():return dict(decision='map_select',context=dict(act=1,floor=1),player=dict(hp=64,max_hp=80),choices=[dict(col=0,row=1)])
class Checks(unittest.TestCase):
    def test_public_search_map_uses_no_real_save(self):
        m=PublicMap();memory={}
        with params.scoped(dict(search_on=True,search_public=True)),patch.object(policy.route,'choose',return_value={'col':0,'row':1}),patch.object(policy.pathing,'choose',return_value={'col':0,'row':1}):
            self.assertEqual(policy.decide(state(),memory,m),('select_map_node',dict(col=0,row=1)))
        self.assertEqual(m.sent,[]);self.assertNotIn('recipe_pending',memory)
    def test_follower_uses_no_real_save(self):
        m=PublicMap();memory={'follow':Follower()}
        with params.scoped(dict(search_on=True,search_public=True)):
            self.assertEqual(policy.decide(state(),memory,m),('select_map_node',dict(col=0,row=1)))
        self.assertEqual(m.sent,[]);self.assertNotIn('recipe_pending',memory)
    def test_legacy_replay_cannot_be_enabled_with_old_recipe(self):
        st=dict(context=dict(room_type='Boss'));memory=dict(recipe={'kind':'node','path':'old-save'})
        with params.scoped(dict(search_on=True,search_public=False)):
            self.assertFalse(search.enabled(st,memory))
            with self.assertRaises(SimError):search.search_turn(st,memory)
    def test_public_model_still_enabled(self):
        with params.scoped(dict(search_on=True,search_public=True)):
            self.assertTrue(search.enabled(dict(context=dict(room_type='Boss')),{}))
    def test_sl_requested_fails_before_native_acquire(self):
        with params.scoped(dict(sl_on=True)),patch.object(run,'acquire',side_effect=AssertionError('No start')):
            with self.assertRaises(SimError):run.play_one('JKAU455ZQY0X')
    def test_hp_override_fails_before_native_acquire(self):
        with params.scoped(dict(sl_on=False)),patch.object(run,'acquire',side_effect=AssertionError('No start')):
            with self.assertRaises(SimError):run.play_one('JKAU455ZQY0X',god=999)
    def test_save_dir_driver_rejected_before_actions(self):
        with params.scoped(dict(sl_on=False)):
            with self.assertRaises(SimError):run.drive(PublicMap(),state(),{'save_dir':'old-lab'})

if __name__=='__main__':unittest.main(verbosity=2)
