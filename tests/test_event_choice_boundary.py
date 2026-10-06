"""Actual normal event UIs must produce offered actions or technical failure."""
import copy,json
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._gamedata import require_kb;require_kb(__name__)
import params,policy
from sim import SimError
class NoNative:
 def __getattr__(self,name):raise AssertionError('Native IO requested: '+name)
class EventChoiceBoundary(unittest.TestCase):
 def load(self,name):return json.loads((Path(__file__).parent/'fixtures'/name).read_text())
 def test_actual_unfinished_crystal_cannot_be_escaped(self):
  st=self.load('unfinished-crystal-public-ui.json');old=copy.deepcopy(st);mem={}
  with self.assertRaisesRegex(SimError,'Crystal Sphere'):policy.decide(st,mem,NoNative())
  self.assertEqual(st,old);self.assertEqual(mem['event_unsupported_broken'],1)
  self.assertNotIn('event_left_broken',mem)
 def test_actual_offered_leave_is_selected_by_index(self):
  st=self.load('event-with-leave-public-ui.json')
  leave=next(o for o in st['options']if 'LEAVE'in o.get('text_key','')or 'leave'in o.get('title','').lower())
  # At a repeating event the old strategy explicitly prefers its offered Leave.
  key=f"{st['event_name']}@{st['context']['floor']}";mem={'event_count':{key:params.P['event_max_repeats']}}
  action,args=policy.decide(st,mem,NoNative())
  self.assertEqual((action,args),('choose_option',{'option_index':leave['index']}))
 def test_late_repeat_still_uses_offered_leave(self):
  st=self.load('event-with-leave-public-ui.json');key=f"{st['event_name']}@{st['context']['floor']}"
  mem={'event_count':{key:params.P['event_max_repeats']+7}}
  leave=next(o for o in st['options']if 'LEAVE'in o.get('text_key','')or 'leave'in o.get('title','').lower())
  self.assertEqual(policy.decide(st,mem,NoNative()),('choose_option',{'option_index':leave['index']}))
 def test_stalled_actual_event_without_leave_is_technical(self):
  st=self.load('unfinished-punch-public-ui.json');key=f"{st['event_name']}@{st['context']['floor']}"
  mem={'event_count':{key:params.P['event_max_repeats']+7}}
  with self.assertRaisesRegex(SimError,'unfinished event'):policy.decide(st,mem,NoNative())
if __name__=='__main__':unittest.main()
