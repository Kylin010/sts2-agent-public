"""Pure planner reproduction; launching any child process is forbidden."""
from pathlib import Path
import json,sys,subprocess
W=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(W))
def forbidden(*a,**kw):raise AssertionError('native/process execution forbidden in pure reproduction')
subprocess.Popen=forbidden
from params import P
from policy import combat
st=json.loads((Path(__file__).parent/'own-public-root.json').read_text())
P['public_mangle_strength_score']=False
base=combat.plan(st,{},set(),topk=5)
P['public_mangle_strength_score']=True
candidate=combat.plan(st,{},set(),topk=5)
P['public_mangle_strength_score']=False
restored=combat.plan(st,{},set(),topk=5)
assert restored==base,'default-off behavior changed after pure comparison'
assert candidate[0][1][0][0]['id']=='CARD.MANGLE'
assert all(c['id']!='CARD.MANGLE'for c,t in base[0][1])
result=dict(base_commit='c0e6d01ba10361f5684e1b94fed28fab9123ad4c',baseline=base,candidate=candidate,
            root_origin='Independent PUB6447 completed hypothetical public interface, not actual game',native_calls=0,
            default_off_restored_exact=True)
(Path(__file__).parent/'latest-master-pure-plans.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:[{'score':round(score,4),'cards':[c['id']for c,target in plan]}for score,plan in result[k][:1]]for k in ('baseline','candidate')}))
