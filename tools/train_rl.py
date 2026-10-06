"""强化学习训练整局决策（policy/learn.py），逐个种子攻克（80 血）。

每一轮：
  1. 开探索，在 4 台机器上打一批：当前目标种子 × A 局 + 其他种子各 2 局（混进别的种子，防止只学会这一个种子）
  2. 奖励 = 打到的层数（每幕 17 层累计）+ 每过一幕 10 + 赢了 40；同一个种子内比较（减去这个种子这批的平均，再除以标准差）
  3. REINFORCE 更新偏好权重：比平均好的局里做过的选择加分，差的扣分（data/learned_prefs.json，旧版本留在 lab/rl/）
  4. 关掉探索，正式打一次目标种子：赢了 → 回归（已打过的种子必须都还赢）→ 换下一个种子
用法：python3 tools/train_rl.py [--seed 种子] [--iters 20] [--target-runs 64] [--others 32] [--lr 0.2]
记录：lab/rl/LOG.md（每轮的平均奖励、目标种子打到哪、改动最大的偏好）
"""
import argparse, json, os, random, statistics, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy import learn
ap = argparse.ArgumentParser()
ap.add_argument('--seed', default=None); ap.add_argument('--iters', type=int, default=20)
ap.add_argument('--target-runs', type=int, default=64); ap.add_argument('--others', type=int, default=32)
ap.add_argument('--lr', type=float, default=0.2); ap.add_argument('--hosts', default='l,r,h,g')
ap.add_argument('--extra', action='append', default=[], help='额外的 --set 参数')
ap.add_argument('--batch', type=int, default=0, help='固定一批种子死磕：开发种子前 N 个')
ap.add_argument('--attempts', type=int, default=4, help='固定批模式：每个种子每轮打几次（开探索）')
ap.add_argument('--eval-every', type=int, default=2, help='固定批模式：每几轮正式打一次（不探索）')
a = ap.parse_args()
RL = f'{HERE}/lab/rl'; os.makedirs(RL, exist_ok=True)
DEV = open(f'{HERE}/data/dev_seeds.txt').read().split()
LOG = open(f'{RL}/LOG.md', 'a')


def log(s):
    print(s, flush=True); LOG.write(s + '\n'); LOG.flush()


def reward(r):
    act, fl = r.get('act') or 1, r.get('floor') or 0
    return (act - 1) * 17 + fl + 10 * (act - 1) + (40 if r.get('win') else 0)


def dist(tag, seeds, sets):
    path = f'lab/rl/seeds-{tag}.txt'
    open(f'{HERE}/{path}', 'w').write('\n'.join(seeds) + '\n')
    cmd = [sys.executable, 'dist.py', '0', '--seed-list', path, '--tag', tag, '--hosts', a.hosts, '--no-hard-seeds']
    for s in sets: cmd += ['--set', s]
    subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    return [json.loads(l) for l in open(f'{HERE}/results/{tag}.jsonl')]


def greedy(seed):
    """关掉探索正式打一次（seed_lab 会记账、存每层存档）"""
    out = subprocess.run([sys.executable, 'tools/seed_lab.py', 'run', seed, '--tag', 'rl-greedy', '--set', 'learn_on=true'], cwd=HERE, capture_output=True, text=True).stdout
    return out.strip().splitlines()[-1] if out.strip() else '（没有输出）'


def batch_mode():
    """固定一批种子死磕：每轮每个种子打 attempts 次（开探索），按奖励更新偏好；每 eval_every 轮正式打一遍这批种子，记胜率"""
    batch = DEV[:a.batch]
    log(f"\n## {time.strftime('%m-%d %H:%M')} 固定批训练：开发种子前 {a.batch} 个，每个每轮 {a.attempts} 次，学习率 {a.lr}，每 {a.eval_every} 轮正式打一遍")
    best = {}                                  # 每个种子探索中打到最远的
    for it in range(a.iters):
        t = time.time(); tag = f"rl-{time.strftime('%H%M%S')}"
        rs = dist(tag, batch * a.attempts, ['learn_on=true', 'learn_explore=true', 'search_on=true'] + a.extra)
        rs = [r for r in rs if 'crash' not in r and r.get('seed')]
        by = {}
        for r in rs: by.setdefault(r['seed'], []).append(reward(r))
        sd = statistics.pstdev([reward(r) for r in rs]) + 1
        mean = {k: sum(v) / len(v) for k, v in by.items()}
        top = learn.update([((reward(r) - mean[r['seed']]) / sd, r.get('decisions') or [], r['seed']) for r in rs], a.lr, lambda s: 0.0)
        ver = time.strftime('%m%d-%H%M%S')
        learn.save({'version': ver, 'batch': a.batch})
        json.dump({'version': ver, 'w': learn.weights()}, open(f'{RL}/prefs-{ver}.json', 'w'))
        won = sorted({r['seed'] for r in rs if r.get('win')})
        for k, v in by.items(): best[k] = max(best.get(k, 0), max(v))
        line = (f"- 第 {it + 1} 轮（{time.time() - t:.0f} 秒，{len(rs)} 局）：探索平均奖励 {sum(reward(r) for r in rs) / max(1, len(rs)):.1f}，"
                f"探索中赢过的种子 {won}，过第一幕 {sum(1 for r in rs if r.get('win') or (r.get('act') or 1) >= 2)} 局")
        if (it + 1) % a.eval_every == 0:
            g = dist(tag + 'g', batch, ['learn_on=true', 'learn_explore=false', 'search_on=true'] + a.extra)
            g = [r for r in g if 'crash' not in r]
            line += (f"\n  **正式打这批 {len(g)} 个种子：赢 {sum(bool(r.get('win')) for r in g)}，过第一幕 {sum(1 for r in g if r.get('win') or (r.get('act') or 1) >= 2)}，"
                     f"过第二幕 {sum(1 for r in g if r.get('win') or (r.get('act') or 1) >= 3)}，平均奖励 {sum(reward(r) for r in g) / max(1, len(g)):.1f}**；赢的种子 {[r['seed'] for r in g if r.get('win')]}")
        log(line + f"\n  改动最大：{[(k, round(v, 2)) for k, v in top[:6]]}")


if a.batch:
    batch_mode(); sys.exit()

seed = a.seed or subprocess.run([sys.executable, 'tools/seed_lab.py', 'next'], cwd=HERE, capture_output=True, text=True).stdout.strip()
log(f"\n## {time.strftime('%m-%d %H:%M')} 开始训练，目标种子 {seed}，每轮 {a.target_runs} + {a.others}×2 局，学习率 {a.lr}")
for it in range(a.iters):
    t = time.time(); tag = f"rl-{time.strftime('%H%M%S')}"
    others = random.sample([s for s in DEV[:300] if s != seed], a.others)
    rs = dist(tag, [seed] * a.target_runs + others * 2, ['learn_on=true', 'learn_explore=true', 'search_on=true'] + a.extra)
    rs = [r for r in rs if 'crash' not in r and r.get('seed')]
    by = {}
    for r in rs: by.setdefault(r['seed'], []).append(reward(r))
    sd = statistics.pstdev([reward(r) for r in rs]) + 1
    mean = {k: sum(v) / len(v) for k, v in by.items()}
    runs = [((reward(r) - mean[r['seed']]) / sd, r.get('decisions') or [], r['seed']) for r in rs]
    top = learn.update([(R, d, s) for R, d, s in runs], a.lr, lambda s: 0.0)
    ver = time.strftime('%m%d-%H%M%S')
    learn.save({'version': ver, 'target': seed})
    json.dump({'version': ver, 'w': learn.weights()}, open(f'{RL}/prefs-{ver}.json', 'w'))
    tr = by.get(seed, []); wins = sum(1 for r in rs if r['seed'] == seed and r.get('win'))
    g = greedy(seed)
    log(f"- 第 {it + 1} 轮（{time.time() - t:.0f} 秒，{len(rs)} 局）：目标种子平均奖励 {sum(tr) / max(1, len(tr)):.1f}（最好 {max(tr or [0])}，赢 {wins}），"
        f"全体平均 {sum(reward(r) for r in rs) / max(1, len(rs)):.1f}；正式打：{g}\n  改动最大：{[(k, round(v, 2)) for k, v in top[:8]]}")
    if '赢了' in g:
        ok = subprocess.run([sys.executable, 'tools/seed_lab.py', 'regress'], cwd=HERE, capture_output=True, text=True)
        log(f'  回归：{ok.stdout.strip().splitlines()[-1] if ok.stdout.strip() else ok.returncode}')
        if ok.returncode == 0:
            seed = subprocess.run([sys.executable, 'tools/seed_lab.py', 'next'], cwd=HERE, capture_output=True, text=True).stdout.strip()
            log(f'  → 换下一个种子 {seed}')
