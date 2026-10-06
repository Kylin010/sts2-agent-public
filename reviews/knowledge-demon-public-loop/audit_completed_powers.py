from pathlib import Path
import sys,json,collections,hashlib,subprocess
W=Path(__file__).resolve().parents[2];sys.path.insert(0,str(W))
def forbidden(*a,**kw):raise AssertionError('No process/native starts in historical audit')
subprocess.Popen=forbidden
from policy.public_knowledge_demon import possible_curse_stages
MAP={'Disintegration':'DISINTEGRATION_POWER','Mind Rot':'MIND_ROT_POWER','Sloth':'SLOTH_POWER','Waste Away':'WASTE_AWAY_POWER'}
counts=collections.Counter();cases=[];pins={};seedsets=collections.defaultdict(set)
for name in ['it-iter-pub-1005-0032.jsonl','it-iter-pub-dev-1005-0034.jsonl']:
 p=Path('/opt/slay-the-spire-2/agent/results')/name;pins[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
 for line in p.open():
  r=json.loads(line)
  for ix,t in enumerate(r.get('trace',[])):
   if t.get('a')!='end_turn'or not any(e[0]=='Knowledge Demon'for e in t.get('foes',[])):continue
   raw=t.get('ppow')or{};pw=[{'id':MAP[k],'amount':v}for k,v in raw.items()if k in MAP]
   stage=possible_curse_stages(pw);key='proved_three'if stage==(3,)else('ambiguous'if stage else 'invalid_or_missing')
   counts[key]+=1;seedsets[key].add(r['seed'])
   if stage==(3,):cases.append({'source':name,'seed':r['seed'],'step':ix,'current_public':t,'derived_public_curses':pw,'possible_completed_stages':stage})
result={'scope':'Current fields of completed normal mainline historical END observations only; no later observation or private counter needed for the inference','counts':dict(counts),'distinct_games':{k:len(v)for k,v in seedsets.items()},'source_sha256':pins,'proved_cases':cases}
(Path(__file__).parent/'completed-public-curses.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k]for k in ['counts','distinct_games']}))
