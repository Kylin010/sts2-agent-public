import json,hashlib
from pathlib import Path
from collections import defaultdict
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from policy import foresight as F
rows=[];identical=[]
for ident,m in F._M.items():
 if not isinstance(m,dict) or m.get('category') in ('test','unused','pet') or ident.startswith('_'):continue
 shape=defaultdict(list);exact=defaultdict(list)
 for mid,mv in m.get('moves',{}).items():
  sig=F._move_sig(mv)
  shape[tuple((t,h if t=='attack' else 1) for t,d,h in sig)].append(mid)
  exact[tuple(sig)].append(mid)
 for k,v in shape.items():
  if len(v)>1:rows.append(dict(id=ident,name=m.get('name'),signature=k,moves=v))
 for k,v in exact.items():
  if len(v)>1:identical.append(dict(id=ident,name=m.get('name'),signature=k,moves=v))
print(json.dumps(dict(note='Static KB collision inventory, not source-complete runtime proof.',shape_collisions=rows,base_damage_identical=identical),indent=2))
