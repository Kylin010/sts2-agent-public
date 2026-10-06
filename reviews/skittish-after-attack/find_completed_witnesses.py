from pathlib import Path
import gzip,json,hashlib
ROOT=Path(__file__).resolve().parent
SRC=Path('/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10')
examples=[];read=0
for path in sorted(SRC.glob('*.ndjson.gz')):
 with gzip.open(path,'rt')as f:events=[json.loads(l)for l in f]
 read+=1;head=events[0]
 if head.get('build_id')!='v0.111.0'or head.get('character')!='IRONCLAD'or head.get('ascension')!=10 or head.get('player_count')!=1:continue
 current=None
 for i,x in enumerate(events):
  if x.get('t')=='combat_start':current=x.get('encounter')
  if current!='PHANTASMAL_GARDENERS_ELITE' or x.get('t')!='play'or x.get('id')!='TWIN_STRIKE':continue
  segment=[]
  for y in events[i+1:i+35]:
   if y.get('t')in('play','end_turn','combat_end','end'):break
   if y.get('t')in('hit','block','power','death','killed'):segment.append(y)
  hits=[y for y in segment if y.get('t')=='hit'and 'PHANTASMAL_GARDENER'in str(y.get('dst',''))]
  blocks=[y for y in segment if y.get('t')=='block'and 'PHANTASMAL_GARDENER'in str(y.get('src',''))]
  if len(hits)>=2 and blocks:
   examples.append({'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'header':{k:head.get(k)for k in ['seed','build_id','replay_version','ascension','reloads']},'completed_play':x,'events':segment})
 if len(examples)>=3:break
(ROOT/'completed-card-witnesses.json').write_text(json.dumps({'scope':'Historical completed replay events, source and attack result sequence only. Not game outcome improvement or No-SL certification. No future event feeds a decision.','files_read':read,'examples':examples[:3]},ensure_ascii=False,indent=2)+'\n')
print('files',read,'found',len(examples))
for e in examples[:3]:print(json.dumps(e['events'],ensure_ascii=False)[:1300])
