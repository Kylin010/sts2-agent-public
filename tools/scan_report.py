"""新引擎推演体检报告：每种遭遇几个人类牌组案例，开 search_public + search_public_why 打完后汇总——
摆不出来的原因（结果里的 search_x.pub_fail_why）、引擎日志里的报错 / 卡死 / 兜底（STS2_ENGINE_LOG 存下的文件）、慢调用（STS2_SLOW_LOG）。
用法：python3 tools/scan_report.py 结果.jsonl [引擎日志前缀] [慢调用前缀]
"""
import collections, glob, json, re, sys
res = sys.argv[1]; elog = sys.argv[2] if len(sys.argv) > 2 else None; slog = sys.argv[3] if len(sys.argv) > 3 else None
by = collections.defaultdict(lambda: dict(n=0, surv=0, roll=0, fail=0, why=collections.Counter(), turns=0, sec=0.0))
for l in open(res):
    try: r = json.loads(l)
    except Exception: continue
    if 'survived' not in r and 'crash' not in r: continue
    d = by[r.get('encounter')]; d['n'] += 1; d['surv'] += bool(r.get('survived'))
    x = r.get('search_x') or {}; s = r.get('search') or {}
    d['roll'] += x.get('pub_rollouts', 0); d['fail'] += x.get('public_build_fail', 0); d['turns'] += s.get('turns', 0); d['sec'] += s.get('sec', 0.0)
    for k, v in (x.get('pub_fail_why') or {}).items(): d['why'][re.sub(r'\d+', 'N', k)] += v
    if r.get('crash'): d['why']['崩溃：' + str(r['crash'])[:60]] += 1
print(f'{"遭遇":32s} {"场":>3s} {"活":>3s} {"推演":>5s} {"秒/次":>6s} {"模拟":>6s} {"失败":>5s}  主要失败原因')
for e, d in sorted(by.items(), key=lambda kv: -(kv[1]['fail'] / max(kv[1]['roll'], 1))):
    w = '; '.join(f'{k[:70]} ×{v}' for k, v in d['why'].most_common(2))
    print(f'{str(e)[:32]:32s} {d["n"]:3d} {d["surv"]:3d} {d["turns"]:5d} {d["sec"] / max(d["turns"], 1):6.1f} {d["roll"]:6d} {d["fail"] / max(d["roll"], 1):5.0%}  {w}')
if elog:
    c = collections.Counter()
    for f in glob.glob(elog + '.*'):
        for line in open(f, errors='replace'):
            if re.search(r'turn loop died|stuck|Nuclear|STALE|Exception:|\[ERROR\]', line) and not line.startswith('   at '):
                c[re.sub(r'\d+', 'N', line.strip())[:150]] += 1
    print('\n引擎日志里的报错 / 卡死（前 15 种）：')
    for k, v in c.most_common(15): print(f'  {v:5d}  {k}')
if slog:
    agg = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for f in glob.glob(slog + '.*'):
        for k, (n, tot, mx) in json.load(open(f)).items():
            a = agg[k]; a[0] += n; a[1] += tot; a[2] = max(a[2], mx)
    print('\n引擎调用耗时：')
    for k, (n, tot, mx) in sorted(agg.items(), key=lambda kv: -kv[1][1])[:6]:
        print(f'  {k:28s} 次数 {n:7d}  平均 {tot / n * 1000:7.1f} ms  最长 {mx:5.2f} 秒')
