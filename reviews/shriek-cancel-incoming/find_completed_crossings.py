from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent;cases=[];counts={'all_crossings':0,'attack_to_zero':0}
for name in ['it-iter-pub-1005-0032.jsonl','it-iter-pub-dev-1005-0034.jsonl']:
 p=Path('/opt/slay-the-spire-2/agent/results')/name;sha=hashlib.sha256(p.read_bytes()).hexdigest()
 for line in p.open():
  r=json.loads(line);trace=r.get('trace',[])
  for ix,t in enumerate(trace[:-1]):
   u=trace[ix+1]
   if t.get('d')!='combat'or u.get('d')!='combat'or t.get('a')!='play_card'or t.get('r')!=u.get('r')or t.get('floor')!=u.get('floor'):continue
   es=[e for e in t.get('foes',[])if e[0]=='Terror Eel'];fs=[e for e in u.get('foes',[])if e[0]=='Terror Eel']
   if len(es)!=1 or len(fs)!=1 or not (es[0][1]>75>=fs[0][1]>0):continue
   counts['all_crossings']+=1
   if es[0][3]>0 and fs[0][3]==0:
    counts['attack_to_zero']+=1
    cases.append({'source':str(p),'sha256':sha,'seed':r['seed'],'step':ix,'before_completed_action':t,'after_completed_action':u})
(ROOT/'completed-threshold-witnesses.json').write_text(json.dumps({'scope':'Historical completed observations only; after rows are validation, not decision input','counts':counts,'cases':cases},ensure_ascii=False,indent=2)+'\n')
print(counts)
for c in cases[:2]:print(c['seed'],c['step'],c['before_completed_action']['foes'],c['after_completed_action']['foes'])
