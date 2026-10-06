"""出牌偏好校准：让脚本「每张牌在手里时打出的比例」向人类回放靠拢。

人类的比例：data/human_play_rates.json（社区回放 8.2 万个回合，回合开始时在手里 → 当回合打没打出去）。
每轮：用两个战斗基准打一批（STS2_LOG_PLAYS=1 记录每张牌在手里 / 打出的次数），
      偏好分 += 步长 × (人类比例 − 脚本比例)，夹在 ±上限之间，写回 kb/card_play_bias.json。
每轮都记下战斗基准的存活率——最后要看的是「打得更好了没有」，不只是「更像人类」。
用法：python3 tools/calibrate_play_bias.py [--rounds 4] [--step 8] [--cap 6]   记录在 lab/play_bias.log
"""
import argparse, collections, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument('--rounds', type=int, default=4); ap.add_argument('--step', type=float, default=8.0)
ap.add_argument('--cap', type=float, default=6.0); ap.add_argument('--min-n', type=int, default=30)
a = ap.parse_args()
H = json.load(open(f'{HERE}/data/human_play_rates.json'))
path = f'{HERE}/kb/card_play_bias.json'
bias = {k: v for k, v in (json.load(open(path)) if os.path.exists(path) else {}).items() if not k.startswith('_')}
log = open(f'{HERE}/lab/play_bias.log', 'a')


def run_bench(tag, bench, reps):
    env = dict(os.environ, STS2_LOG_PLAYS='1', STS2_BENCH=bench)
    out = subprocess.run([sys.executable, f'{HERE}/dist.py', '0', '--bench', '--reps', str(reps), '--tag', tag], cwd=HERE, env=env,
                         capture_output=True, text=True).stdout
    surv = next((l.strip() for l in out.splitlines() if '撑过去的比例' in l), '')
    boss = next((l.strip() for l in out.splitlines() if l.strip().startswith('boss：')), '')
    rs = [json.loads(l) for l in open(f'{HERE}/results/{tag}.jsonl')]
    return rs, surv, boss


for rd in range(a.rounds):
    t = time.time(); tag = time.strftime('pb-%H%M')
    rs1, surv1, boss1 = run_bench(tag + '-e', 'bench.json', 2)
    rs2, surv2, _ = run_bench(tag + '-n', 'bench_normals.json', 1)
    st = collections.defaultdict(lambda: [0, 0])
    for r in rs1 + rs2:
        for k, (n, p) in (r.get('play_stats') or {}).items():
            st[k][0] += n; st[k][1] += p
    moved = []
    for k, (n, p) in st.items():
        if n < a.min_n or k not in H: continue
        gap = H[k]['rate'] - p / n
        b = max(-a.cap, min(a.cap, bias.get(k, 0.0) + a.step * gap))
        if abs(b - bias.get(k, 0.0)) > 0.3: moved.append((k, round(gap, 2), round(b, 1)))
        bias[k] = round(b, 2)
    json.dump({'_说明': '按牌的出牌偏好分（加在出牌组合的打分上），由 tools/calibrate_play_bias.py 对齐人类回放的打出比例', **bias},
              open(path, 'w'), ensure_ascii=False, indent=1)
    gap_avg = sum(abs(H[k]['rate'] - p / n) for k, (n, p) in st.items() if n >= a.min_n and k in H) / max(1, sum(1 for k, (n, p) in st.items() if n >= a.min_n and k in H))
    line = (f"第 {rd + 1} 轮（{time.strftime('%m-%d %H:%M')}，{time.time() - t:.0f} 秒）：精英 Boss 基准 {surv1} {boss1}；普通战 {surv2}；"
            f"和人类打出比例的平均差 {gap_avg:.3f}；调整最大的 {sorted(moved, key=lambda x: -abs(x[1]))[:8]}")
    print(line, flush=True); log.write(line + '\n'); log.flush()
