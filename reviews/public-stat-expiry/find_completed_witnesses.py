from pathlib import Path
import gzip,json,hashlib
ROOT=Path(__file__).resolve().parent;SRC=Path('/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10');rows=[];read=0
index={r['run_hash']:r for l in (SRC/'index.jsonl').open() if (r:=json.loads(l)).get('run_hash')}
for path in sorted(SRC.glob('*.ndjson.gz')):
 with gzip.open(path,'rt') as f:es=[json.loads(l) for l in f]
 read+=1;head=es[0];label=index.get(path.name.split('.')[0])
 if not label or label.get('was_abandoned') or head.get('build_id')!='v0.111.0' or head.get('ascension')!=10 or head.get('character')!='IRONCLAD' or head.get('player_count')!=1 or head.get('game_mode')!='standard' or head.get('modifiers'):continue
 if (head.get('reloads') or 0)>0 or any(y.get('t')=='resume' or (y.get('attempt_id') or 0)>0 for y in es):continue
 for i,x in enumerate(es):
  if x.get('t')!='power' or x.get('id')!='SHACKLING_POTION_POWER' or (x.get('amount') or 0)<=0:continue
  target=x.get('tgt');cid=x.get('tgt_cid');s=[];seen_end=False;restore=None
  for j in range(i+1,len(es)):
   y=es[j]
   if y.get('t') in ('combat_start','combat_end','end'):break
   if y.get('t')=='end_turn' and y.get('side')=='enemy':seen_end=True
   if seen_end and y.get('t')=='power' and y.get('id')=='STRENGTH_POWER' and y.get('tgt_cid')==cid and y.get('n')==x['amount']:
    restore=j;break
  if restore is None:continue
  # Export only completed public events, no native RNG/state fields.
  for y in es[max(0,i-5):min(restore+9,len(es))]:
   if y.get('t') in ('power','power_removed','power_remove','end_turn','intent','move','hit','use_potion'):
    if len(s)<45:s.append(y)
  rows.append({'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'header':{k:head.get(k) for k in ['seed','build_id','reloads','ascension']},'run_win':bool(label['win']),'temporary_applied':x,'matched_restore':es[restore],'events':s})
result={'scope':'Strict no-recorded-restart historical completed sequence. Matching same creature cid, temporary amount, enemy end-turn then positive Strength restoration; source explains cause. Not own normal qualification, actual full outcome improvement or future data used for decisions.','files_read':read,'matches':len(rows),'examples':rows[:8]}
(ROOT/'completed-shackling-witnesses.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('files',read,'matches',len(rows))
for r in rows[:8]:print(r['header']['seed'],r['temporary_applied']['tgt'],r['temporary_applied']['amount'],r['matched_restore']['n'],r['run_win'])
