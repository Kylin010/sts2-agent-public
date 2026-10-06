"""组合迭代跑到一半时看各组成绩（已经传回本机的小份结果）：局数、过第一 / 二幕、精英数，以及和对照在「同一批种子」上的比较。

用法：python3 tools/bundle_progress.py [spec 文件，默认最新的 lab/bundle/spec-*.json] [另一份 spec ...]
后面加的 spec（比如别的代码分支用对照参数跑的同一批种子）各组也并进来，和第一份 spec 的对照按同种子比较。
结果文件在 spec 所在项目的 results/ 下（spec 路径 X/lab/bundle/spec-T.json → X/results/T*.jsonl）。
"""
import collections, glob, json, math, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
specs = sys.argv[1:] or [max(glob.glob(f'{HERE}/lab/bundle/spec-*.json'), key=os.path.getmtime)]
by = collections.defaultdict(dict); cands = []; nrows = ntasks = 0
for spec in specs:
    sp = json.load(open(spec)); tag = os.path.basename(spec)[5:-5]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(spec))))
    rows = [json.loads(l) for f in glob.glob(f'{root}/results/{tag}-p*.jsonl') + glob.glob(f'{root}/results/{tag}.jsonl') for l in open(f)]
    nrows += len(rows); ntasks += len(sp['tasks']); cands += [c for c in sp['candidates'] if c not in cands]
    for r in rows:
        t = sp['tasks'][r['task']] if isinstance(r.get('task'), int) else None
        if t and 'crash' not in r: by[t['cand']][t['seed']] = r
spec = specs[0]; sp = {'candidates': cands, 'tasks': [None] * ntasks}; rows = [None] * nrows
a1 = lambda r: bool(r.get('win') or (r.get('act') or 1) >= 2)
a2 = lambda r: bool(r.get('win'))
prog = lambda r: 100 * ((r.get('act') or 1) - 1) + (r.get('floor') or 0) + (200 if r.get('win') else 0)
ctrl = by.get('对照', {})
print(f'{os.path.basename(spec)}：已传回 {len(rows)} / {len(sp["tasks"])} 局')
for name in sp['candidates']:
    g = by.get(name, {})
    if not g: print(f'  {name}：还没有结果'); continue
    el = sum(1 for r in g.values() for c in r.get('combats') or [] if c['room'] == 'Elite') / len(g)
    com = [s for s in g if s in ctrl]
    cmp_ = ''
    if name != '对照' and com:
        d1 = sum(a1(g[s]) for s in com) - sum(a1(ctrl[s]) for s in com); d2 = sum(a2(g[s]) for s in com) - sum(a2(ctrl[s]) for s in com)
        fw = sum(1 for s in com if prog(g[s]) > prog(ctrl[s])); bw = sum(1 for s in com if prog(g[s]) < prog(ctrl[s]))
        cmp_ = f'｜和对照同 {len(com)} 个种子：过第一幕 {d1:+d}、过第二幕 {d2:+d}，走得更远 {fw} / 更近 {bw}（运气概率 {sum(math.comb(fw + bw, i) for i in range(fw, fw + bw + 1)) / 2 ** (fw + bw) if fw + bw else 1:.2f}）'
    print(f'  {name}：{len(g)} 局，过第一幕 {sum(map(a1, g.values()))}（{sum(map(a1, g.values())) / len(g):.0%}），'
          f'过第二幕 {sum(map(a2, g.values()))}（{sum(map(a2, g.values())) / len(g):.0%}），精英 {el:.2f}/局{cmp_}')
