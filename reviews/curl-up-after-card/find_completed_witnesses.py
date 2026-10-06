from pathlib import Path
import gzip,json,hashlib
ROOT=Path(__file__).resolve().parent;SRC=Path('/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10');found=[];read=0
for path in sorted(SRC.glob('*.ndjson.gz')):
 with gzip.open(path,'rt')as f:events=[json.loads(l)for l in f]
 read+=1;header=events[0]
 if header.get('build_id')!='v0.111.0'or header.get('character')!='IRONCLAD'or header.get('ascension')!=10 or header.get('player_count')!=1:continue
 enc=None
 for i,x in enumerate(events):
  if x.get('t')=='combat_start':enc=x.get('encounter')
  if enc!='LOUSE_PROGENITOR_NORMAL' or x.get('t')!='play':continue
  seg=[]
  for y in events[i+1:i+45]:
   if y.get('t')in('play','end_turn','combat_end','end'):break
   if y.get('t')in('hit','block','power','power_lost','death'):seg.append(y)
  hits=[y for y in seg if y.get('t')=='hit'and y.get('dst')=='LOUSE_PROGENITOR']
  blocks=[y for y in seg if y.get('t')=='block'and y.get('src')=='LOUSE_PROGENITOR'and y.get('n')==18]
  if blocks and ((x.get('id')=='TWIN_STRIKE'and len(hits)>=2)or(hits and all(y.get('dmg')==0 for y in hits))):
   found.append({'source':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'header':{k:header.get(k)for k in ['seed','build_id','replay_version','ascension','reloads']},'play':x,'events':seg})
 if len(found)>=4:break
(ROOT/'completed-curl-witnesses.json').write_text(json.dumps({'scope':'Completed historical replay actions; validation only, not normal No-SL qualification or candidate win-rate','files_read':read,'examples':found[:4]},ensure_ascii=False,indent=2)+'\n')
print('read',read,'found',len(found))
for r in found[:4]:print(r['play']['id'],json.dumps(r['events'],ensure_ascii=False)[:1500])
