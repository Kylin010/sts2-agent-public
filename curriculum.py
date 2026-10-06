"""逐级降血：先在高血量把整局跑通，胜率稳定了再一档档往下降，直到正常的 80 血。

每一档跑一批（dist.py 四台机器），整局胜率达到 --target 就降到下一档，没达到就停在这一档（交给人改代码再跑）。
血量档：999 → 500 → 300 → 200 → 150 → 120 → 100 → 80（80 = 正常开局，不再加 --god）
结果记到 curriculum.md（每档：胜率、死在哪、每幕每类房间平均掉血）。
用法：python3 curriculum.py [--n 400] [--target 0.7] [--start 999] [--tag v8]
"""
import argparse, collections, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS = [999, 500, 300, 200, 150, 120, 100, 80]
ap = argparse.ArgumentParser()
ap.add_argument('--n', type=int, default=400); ap.add_argument('--target', type=float, default=0.7)
ap.add_argument('--start', type=int, default=999); ap.add_argument('--tag', default=time.strftime('cur-%m%d-%H%M'))
ap.add_argument('--once', action='store_true', help='只跑起始这一档')
a = ap.parse_args()


def run_level(hp):
    tag = f'{a.tag}-hp{hp}'
    cmd = [sys.executable, f'{HERE}/dist.py', str(a.n), '--tag', tag] + (['--god', str(hp)] if hp != 80 else [])
    t = time.time(); subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    rs = [json.loads(l) for l in open(f'{HERE}/results/{tag}.jsonl')]
    ok = [r for r in rs if 'crash' not in r]
    win = sum(bool(r.get('win')) for r in ok) / max(len(ok), 1)
    died = collections.Counter(f"{r.get('act')}-{r.get('room')}" for r in ok if not r.get('win'))
    who = collections.Counter(' + '.join(r.get('enemies') or []) or '?' for r in ok if not r.get('win'))
    dm = collections.defaultdict(list)
    for r in ok:
        for c in r.get('combats') or []: dm[(c['act'], c['room'])].append(c['dmg'])
    line = (f"| {time.strftime('%m-%d %H:%M')} | {tag} | {hp} | {len(ok)}（崩溃 {len(rs) - len(ok)}） | **{win:.1%}** | "
            f"{dict(died.most_common(4))} | {dict(who.most_common(3))} | "
            + ' '.join(f"{k[0]}{k[1][0]}:{sum(v) / len(v):.0f}" for k, v in sorted(dm.items())) + f" | {time.time() - t:.0f}s |")
    path = f'{HERE}/curriculum.md'
    if not os.path.exists(path):
        open(path, 'w').write('# 逐级降血记录\n\n先高血量跑通整局，胜率到门槛再降一档。每幕每类房间平均掉血：1M = 第一幕普通战，1E = 精英，1B = Boss。\n\n'
                              '| 时间 | 标签 | 血量 | 有效局数 | 整局胜率 | 死在哪 | 死在谁手里 | 平均掉血 | 用时 |\n|---|---|---|---|---|---|---|---|---|\n')
    open(path, 'a').write(line + '\n')
    print(line, flush=True)
    return win


lv = [x for x in LEVELS if x <= a.start]
for hp in lv:
    w = run_level(hp)
    if a.once or w < a.target:
        print(f'血量 {hp} 胜率 {w:.1%}，没到 {a.target:.0%}，停在这一档' if w < a.target else '只跑这一档', flush=True)
        break
