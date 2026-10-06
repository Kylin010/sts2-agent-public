from pathlib import Path
from collections import Counter
import gzip,json,hashlib
ROOT=Path(__file__).resolve().parent
SRC=Path('/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10')
rows=[];examples={};read=0; excluded=Counter()
index={r['run_hash']:r for l in (SRC/'index.jsonl').open() if (r:=json.loads(l)).get('run_hash')}
for path in sorted(SRC.glob('*.ndjson.gz')):
 with gzip.open(path,'rt') as f:es=[json.loads(l) for l in f]
 read+=1;h=es[0]
 label=index.get(path.name.split('.')[0])
 if not label or label.get('was_abandoned'):continue
 if h.get('build_id')!='v0.111.0' or h.get('character')!='IRONCLAD' or h.get('ascension')!=10 or h.get('player_count')!=1 or h.get('game_mode')!='standard' or h.get('modifiers'):continue
 if (h.get('reloads') or 0)>0 or any(x.get('t')=='resume' or (x.get('attempt_id') or 0)>0 for x in es):excluded['recorded_restart']+=1;continue
 end=next((x for x in reversed(es) if x.get('t')=='end'),{})
 for begin,x in enumerate(es):
  if x.get('t')!='combat_start' or x.get('encounter')!='LAGAVULIN_MATRIARCH_BOSS' or (x.get('attempt_id') or 0)!=0:continue
  stop=next((j for j in range(begin+1,len(es)) if es[j].get('t') in ['combat_start','combat_end','end']),len(es))
  seg=es[begin+1:stop];finish=es[stop] if stop<len(es) else {};round_=1;wake=None;first_attack=None;sequence=[];public=[]
  if not (finish.get('t')=='combat_end' or (finish.get('t')=='end' and finish.get('terminal_reason')=='death')):excluded['truncated_or_nondeath_exit']+=1;continue
  for y in seg:
   if y.get('t')=='turn' and y.get('side')=='player':round_=y.get('n',round_)
   if y.get('t')=='power' and y.get('id')=='ASLEEP_POWER':public.append({'round':round_,'event':y})
   if y.get('t')=='intent' and y.get('src')=='LAGAVULIN_MATRIARCH':
    if y.get('id')=='STUNNED' and wake is None:wake=round_
    if y.get('id')=='SLASH_MOVE' and first_attack is None:first_attack=round_
    public.append({'turn':round_,'event':y})
   if y.get('t')=='move' and y.get('src')=='LAGAVULIN_MATRIARCH':sequence.append(y.get('id'));public.append({'round':round_,'event':y})
  outcome=end.get('terminal_reason','missing')
  row={'source':str(path),'seed':h.get('seed'),'run_terminal_reason':outcome,'run_win':bool(label['win']),'boss_win':finish.get('result')=='victory','combat_finish':finish.get('t'),'wake_turn':wake,'first_attack_turn':first_attack,'moves':sequence}
  rows.append(row)
  kind='natural' if sequence[:3]==['SLEEP_MOVE']*3 else 'stunned' if 'STUNNED' in sequence[:3] else 'other'
  if kind not in examples and kind in ('natural','stunned'):
   examples[kind]={'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'header':{k:h.get(k) for k in ['seed','build_id','reloads','player_count','ascension']},'public_events':public[:30],'sequence':sequence,'terminal':{k:end.get(k) for k in ['terminal_reason','floor','act']}}
counts=Counter((r['run_terminal_reason'],tuple(r['moves'][:3])) for r in rows)
result={'scope':'Historical completed public intent/power/move order. Fixed-source timing validation only; not own No-SL qualification, causal wake strategy comparison or win-rate uplift. No RNG/save/private phase fields used by the decision function or exported here.','files_read':read,'eligible_combats':len(rows),'excluded':dict(excluded),'good_bad':{k:{'count':len(rs),'wake_turns':dict(Counter(str(r['wake_turn']) for r in rs)), 'first_attack_turns':dict(Counter(str(r['first_attack_turn']) for r in rs))} for k,rs in [('run_winners',[r for r in rows if r['run_win']]),('run_losers',[r for r in rows if not r['run_win']]),('boss_deaths',[r for r in rows if not r['boss_win']])]},'prefix_counts':[{'terminal':k[0],'first_three_moves':k[1],'count':v} for k,v in sorted(counts.items())],'examples':examples,'rows':rows}
(ROOT/'completed-sleep-witnesses.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('files',read,'eligible',len(rows),'examples',list(examples),'excluded',dict(excluded));print(json.dumps(result['good_bad'],ensure_ascii=False))
for x in result['prefix_counts']:print(json.dumps(x,ensure_ascii=False))
