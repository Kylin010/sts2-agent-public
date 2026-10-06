"""用遭遇实验室第一轮的结果估「离理论最优还差多少」：
  默认     = 当前默认参数的平均掉血
  最好一组 = 平均下来最好的那组参数（不作弊，正式对局能用）
  事后最优 = 每个（案例, 种子）在所有组里取掉血最少的那次再平均（事后挑结果，等于偷看了牌序；只当下限参考）
用法：python3 tools/lab_gap.py results/lab-a1-r1.jsonl lab/spec_lab-a1_r1.json
"""
import collections, json, sys
rs = [json.loads(l) for l in open(sys.argv[1])]
spec = json.load(open(sys.argv[2])); tasks = spec['tasks']
by = collections.defaultdict(lambda: collections.defaultdict(dict))     # enc → ci → (case, rep) → score
for r in rs:
    j = r.get('task')
    if not isinstance(j, int): continue
    t = tasks[j]
    sc = 90 if 'crash' in r else (r.get('dmg') or 0) + (0 if r.get('survived') else 30)
    by[t['enc']][t['ci']][(t['bench'], t['case'], t['rep'])] = sc
rows = []
for e, cs in by.items():
    keys = set.intersection(*[set(v) for v in cs.values()]) if cs else set()
    if not keys or 0 not in cs: continue
    mean = lambda ci: sum(cs[ci][k] for k in keys) / len(keys)
    d = mean(0); b = min(mean(ci) for ci in cs)
    h = sum(min(cs[ci][k] for ci in cs) for k in keys) / len(keys)
    rows.append((e, d, b, h, len(keys)))
rows.sort(key=lambda x: -(x[1] - x[3]))
print('| 遭遇 | 默认 | 最好一组 | 事后最优 | 默认离事后最优 | 样本 |\n|---|---|---|---|---|---|')
for e, d, b, h, n in rows: print(f'| {e} | {d:.1f} | {b:.1f} | {h:.1f} | {d - h:.1f} | {n} |')
D = sum(x[1] for x in rows) / len(rows); B = sum(x[2] for x in rows) / len(rows); H = sum(x[3] for x in rows) / len(rows)
print(f'\n平均：默认 {D:.1f}，最好一组 {B:.1f}，事后最优 {H:.1f}')
