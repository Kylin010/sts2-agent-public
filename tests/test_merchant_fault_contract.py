"""Driver stops native merchant/event faults without starting an engine."""
import io
from pathlib import Path
import sys
import types
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim import Sim,SimError
class MerchantFaultContract(unittest.TestCase):
 def make(self,response):
  sim=Sim.__new__(Sim);sim.broken=False;sim.p=types.SimpleNamespace(stdin=io.StringIO());sim._read=lambda:response
  return sim
 def test_event_fault_is_technical(self):
  sim=self.make(dict(type='error',message='EVENT_FAULT: real failure'))
  with self.assertRaisesRegex(SimError,'EVENT_FAULT'):sim.send(dict(cmd='action',action='choose_option'))
 def test_merchant_fault_is_technical(self):
  sim=self.make(dict(type='error',message='MERCHANT_FAULT: partial purchase'))
  with self.assertRaisesRegex(SimError,'MERCHANT_FAULT'):sim.send(dict(cmd='action',action='buy_relic'))
 def test_ordinary_error_contract_is_preserved(self):
  response=dict(type='error',message='Invalid input');sim=self.make(response)
  self.assertIs(sim.send(dict(cmd='action',action='buy_relic')),response)
if __name__=='__main__':unittest.main()
