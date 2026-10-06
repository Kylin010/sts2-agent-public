"""只当老师（search_teach_only）记录的诊断：规划器实际那手在老师眼里亏多少，按房间 / 遭遇汇总；喝药候选比不喝好多少。
遗憾 = 老师打满遍数的候选里最好的 v − 规划器首选（候选里规划器分最高的那组）的 v。v 的单位约等于「到战斗结束剩的血」。
用法：python3 tools/dagger_report.py 记录...
"""
import collections, json, sys
by = collections.defaultdict(lambda: collections.defaultdict(float))
for p in sys.argv[1:]:
    for line in open(p):
        r = json.loads(line); al = r.get('all')
        if not al: continue
        cards = [a for a in al if not a.get('potion')]; pots = [a for a in al if a.get('potion')]
        if len(cards) < 2: continue
        plan = max(cards, key=lambda a: a['sc'])
        full = [a for a in cards if a['n'] >= max(x['n'] for x in cards)]
        best = max(a['v'] for a in full + [plan])
        for k in (r.get('room') or '?', f"{r.get('room')}|{r.get('enc')}"):
            d = by[k]; d['n'] += 1; d['reg'] += max(0.0, best - plan['v']); d['top'] += plan['v'] >= best - 1e-6
            d['big'] += (best - plan['v']) > 5
            if pots:
                g = max(a['v'] for a in pots) - max(a['v'] for a in cards)
                d['pn'] += 1; d['pg'] += max(0.0, g); d['pbig'] += g > 5
rows = sorted(by.items(), key=lambda kv: -kv[1]['reg'])
print(f'{"房间 / 遭遇":44s} {"局面":>5s} {"总遗憾":>7s} {"每回合":>6s} {"首选最好":>7s} {">5":>5s} | {"有药":>4s} {"喝药更好>5":>9s} {"喝药平均收益":>8s}')
for k, d in rows:
    if '|' in k and d['n'] < 15: continue
    print(f'{k[:44]:44s} {int(d["n"]):5d} {d["reg"]:7.0f} {d["reg"] / d["n"]:6.2f} {d["top"] / d["n"]:7.0%} {int(d["big"]):5d} | {int(d["pn"]):4d} {int(d["pbig"]):9d} {d["pg"] / max(d["pn"], 1):8.2f}')
