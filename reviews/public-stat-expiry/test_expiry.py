from pathlib import Path
from copy import deepcopy
import sys,unittest,subprocess,json
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No process starts'))
from params import P,scoped
from policy.public_stat_expiry import RULES,resolve_subphase,negative_strength_return
from policy import foresight,combatvalue,mentalmodel
FLAG={'foresight_public_stat_expiry':True}
def power(key,n):return {'id':key,'amount':n}
def base(s=0,d=0,a=0):return [power('STRENGTH_POWER',s),power('DEXTERITY_POWER',d),power('ARTIFACT_POWER',a)]
def kd(n=7,key='SHACKLING_POTION_POWER'):
 return {'name':'Knowledge Demon','index':0,'hp':200,'max_hp':399,'block':0,'powers':[{'id':'STRENGTH_POWER','name':'Strength','amount':-n},power(key,n)],'intents':[{'type':'Attack','damage':18-n,'hits':1}]}
class Checks(unittest.TestCase):
 def test_all_subclasses_source_match(self):
  rows=json.loads((Path(__file__).parent/'subclasses-source.json').read_text());self.assertEqual(RULES,{r['id']:(r['stat'],r['sign']) for r in rows})
 def test_flex_expires(self):self.assertEqual(resolve_subphase(base(s=7)+[power('FLEX_POTION_POWER',5)])['after']['str'],2)
 def test_flex_artifact_keeps_boost(self):
  x=resolve_subphase(base(s=7,a=1)+[power('FLEX_POTION_POWER',5)]);self.assertEqual((x['after']['str'],x['after']['artifact']),(7,0))
 def test_speed_expires(self):self.assertEqual(resolve_subphase(base(d=7)+[power('SPEED_POTION_POWER',5)])['after']['dex'],2)
 def test_speed_artifact_keeps_boost(self):self.assertEqual(resolve_subphase(base(d=7,a=1)+[power('SPEED_POTION_POWER',5)])['after']['dex'],7)
 def test_public_order_changes_retained_stat(self):
  xs=[power('FLEX_POTION_POWER',5),power('SPEED_POTION_POWER',5)]
  a=resolve_subphase(base(s=5,d=5,a=1)+xs,order_is_public=True);b=resolve_subphase(base(s=5,d=5,a=1)+list(reversed(xs)),order_is_public=True)
  self.assertEqual((a['after']['str'],a['after']['dex']),(5,0));self.assertEqual((b['after']['str'],b['after']['dex']),(0,5))
 def test_missing_public_order_defer(self):self.assertIsNone(resolve_subphase(base()+[power('FLEX_POTION_POWER',5),power('SPEED_POTION_POWER',5)]))
 def test_two_artifact_keep_both(self):
  x=resolve_subphase(base(s=5,d=5,a=2)+[power('FLEX_POTION_POWER',5),power('SPEED_POTION_POWER',5)],order_is_public=True);self.assertEqual(x['after'],{'str':5,'dex':5,'artifact':0})
 def test_negative_strength_restore_ignores_artifact(self):
  x=resolve_subphase(base(s=-7,a=1)+[power('SHACKLING_POTION_POWER',7)]);self.assertEqual(x['after'],{'str':0,'dex':0,'artifact':1})
 def test_restore_positive_with_helmet_unused(self):self.assertEqual(resolve_subphase(base(s=-7)+[power('SHACKLING_POTION_POWER',7)],helmet='unused')['after']['str'],7)
 def test_restore_positive_with_helmet_used(self):self.assertEqual(resolve_subphase(base(s=-7)+[power('SHACKLING_POTION_POWER',7)],helmet='used')['after']['str'],0)
 def test_helmet_unknown_defer_restore(self):self.assertIsNone(resolve_subphase(base()+[power('MANGLE_POWER',3)],helmet='unknown'))
 def test_helmet_unknown_negative_change_safe(self):self.assertEqual(resolve_subphase(base(s=5)+[power('FLEX_POTION_POWER',5)],helmet='unknown')['after']['str'],0)
 def test_invalid_counters_defer(self):
  for n in [None,0,-1,True,1.5,'7']:self.assertIsNone(negative_strength_return([power('SHACKLING_POTION_POWER',n)]))
 def test_duplicate_counters_defer(self):self.assertIsNone(negative_strength_return([power('MANGLE_POWER',3)]*2))
 def test_all_negative_strength_classes_sum(self):self.assertEqual(negative_strength_return([power(k,1) for k,r in RULES.items() if r==('str',-1)]),8)
 def test_positive_strength_defer_forecast(self):self.assertIsNone(negative_strength_return([power('FLEX_POTION_POWER',5)]))
 def test_namespace_id(self):self.assertEqual(negative_strength_return([power('POWER.SHACKLING_POTION_POWER',7)]),7)
 def test_name_only_unknown_badge_defer(self):self.assertIsNone(negative_strength_return([{'name':'Shackling Potion','amount':7}]))
 def test_unrelated_listener_not_certified(self):self.assertEqual(resolve_subphase(base()+[power('UNREVIEWED_POWER',2)])['unhandled_power_ids'],['UNREVIEWED_POWER'])
 def test_input_preserved(self):
  x=base(s=-7)+[power('SHACKLING_POTION_POWER',7)];y=deepcopy(x);resolve_subphase(x);self.assertEqual(x,y)
 def test_shackling_kd_future_restored(self):
  with scoped(FLAG):self.assertEqual(foresight.future(kd(),'SLAP_MOVE',3),[27,13,10.5])
 def test_legacy_kd_future_too_low(self):
  with scoped({'foresight_public_stat_expiry':False,'foresight_public_mangle_expiry':False}):self.assertEqual(foresight.future(kd(),'SLAP_MOVE',3),[6,6,7])
 def test_mangle_flags_do_not_double_restore(self):
  with scoped(dict(FLAG,foresight_public_mangle_expiry=True)):self.assertEqual(foresight.future(kd(key='MANGLE_POWER'),'SLAP_MOVE',3),[27,13,10.5])
 def test_multiple_temporary_losses_restore(self):
  e=kd(n=10);e['powers'][-1]['amount']=7;e['powers'].append(power('MANGLE_POWER',3))
  with scoped(FLAG):self.assertEqual(foresight.future(e,'SLAP_MOVE',3),[27,13,10.5])
 def test_visible_positive_temp_returns_unknown(self):
  e=kd();e['powers'].append(power('FLEX_POTION_POWER',5))
  with scoped(FLAG):self.assertIsNone(foresight.future(e,'SLAP_MOVE',3));self.assertIsNone(mentalmodel.schedule([e],3,{}))
 def test_cv_root_receives_correct_future(self):
  with scoped(FLAG):s=combatvalue.situation_from_state({'player':{'hp':50},'enemies':[kd()]})
  self.assertEqual(s['enemies'][0]['fut'],50.5/3)
 def test_with_public_final_curse_loop(self):
  with scoped(dict(FLAG,foresight_public_kd_loop=True)):
   self.assertEqual(foresight.future(kd(),'SLAP_MOVE',3,public_player_powers=[{'id':'WASTE_AWAY_POWER','amount':1}]),[27,13,21])
 def test_default_false(self):self.assertFalse(P['foresight_public_stat_expiry'])
if __name__=='__main__':unittest.main(verbosity=2)
