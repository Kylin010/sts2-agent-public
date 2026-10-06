"""分布式跑：本机 + 若干台 SSH 工作机一起跑同一批任务，最后合并结果。

机器列表放在 machines.local.json（不进仓库；格式见 machines.example.json，也可以用环境变量 STS2_MACHINES 指定别的文件）。
没有这个文件时只用本机。
用法（在仓库根目录）：参数和 run.py 一样，例如
  python3 dist.py 400 --stop-act 1 --tag a1
  python3 dist.py 0 --bench --reps 3 --tag bench-v5
  python3 dist.py 300 --god 999 --tag g999
可选：--hosts l,a,b 只用其中几台（key 见机器列表）
原理：跑之前先用 rsync 把代码同步到远端；远端用 nice 降优先级。连不上的机器自动跳过；
某台机器中途掉线，它那一份任务改派给别的机器补跑，结果都会传回本机 results/。
"""
import glob, argparse, collections, json, os, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.environ.get('STS2_REMOTE_DIR', '/opt/sts2/agent')   # 调参用独立的远端目录，避免和开发中的代码互相覆盖
# 远端引擎目录：环境变量 > remote_cli.txt（一行路径）> 默认。10/3 换引擎（补丁 13）用新目录，正在跑的实验不受影响（dist 启动时才读）
_rc = f'{HERE}/remote_cli.txt'
RCLI = os.environ.get('STS2_REMOTE_CLI') or (open(_rc).read().strip() if os.path.exists(_rc) else '') or '/opt/sts2/sts2-cli'
RENV = (f'STS2_CLI_DIR={RCLI} DOTNET=/opt/dotnet9/dotnet' + (f' STS2_BENCH={os.environ["STS2_BENCH"]}' if os.environ.get('STS2_BENCH') else '')
        + (' STS2_LOG_TURNS=1' if os.environ.get('STS2_LOG_TURNS') == '1' else '')
        + (' STS2_LOG_PLAYS=1' if os.environ.get('STS2_LOG_PLAYS') == '1' else ''))      # 采集开关也要传给远端
# 机器列表：每台 {key, name, ssh, port, workers, keep_gb, speed}；workers = 最多开几个对局进程，keep_gb = 给机器留的内存，
# speed = 相对速度（收尾时快机器会把慢机器上还在跑的份再跑一遍）。本机不写 ssh，workers 为 0 表示只调度、不跑
_mf = os.environ.get('STS2_MACHINES') or f'{HERE}/machines.local.json'
HOSTS = json.load(open(_mf))['hosts'] if os.path.exists(_mf) else [{'key': 'l', 'name': '本机', 'workers': os.cpu_count() or 4}]
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=4']
ssh_of = lambda h: SSH + ['-p', str(h.get('port', 22))]
if __name__ != '__main__':      # 10/3：下面全是顶层代码，import 一下就会同步代码、往远端派活（真出过事：只想读 HOSTS，结果把代码同步进了在跑实验的远端目录）
    raise ImportError('dist.py 只能当命令行跑；要主机列表请直接看源码里的 HOSTS')

ap = argparse.ArgumentParser(add_help=False)
ap.add_argument('--tag', default='dist'); ap.add_argument('--hosts', default=','.join(h['key'] for h in HOSTS))
a, rest = ap.parse_known_args()
hosts = [h for h in HOSTS if h['key'] in a.hosts.split(',')] or list(HOSTS)   # 一个 key 都对不上（旧脚本写死的 --hosts）：用全部机器
for h in [h for h in hosts if 'ssh' in h]:
    if subprocess.run(['rsync', '-a', '-e', ' '.join(ssh_of(h)), '--exclude', 'results', '--exclude', '__pycache__', '--exclude', '.git',
                       f'{HERE}/', f'{h["ssh"]}:{RDIR}/'], capture_output=True).returncode != 0:
        print(f'{h["ssh"]} 连不上，跳过'); hosts.remove(h); continue
    # 同名实验的旧批次日志先删掉（10/2：重跑 v16c 时旧日志里的看门狗记录让体检误报）
    subprocess.run(ssh_of(h) + [h['ssh'], f'rm -f /tmp/sts2-{a.tag}-p*.log'], capture_output=True)
    # 每个实例按 400 MB 算（10/2 起每个进程两个引擎：对局 + 推演影子），给机器留够内存
    avail_kb = int(subprocess.run(ssh_of(h) + [h['ssh'], "awk '/MemAvailable/{print $2}' /proc/meminfo"], capture_output=True, text=True).stdout.strip() or 0)
    fit = max(0, int((avail_kb / 1024 / 1024 - h['keep_gb']) / 0.4))
    if fit < h['workers']:
        print(f'{h["ssh"]} 可用内存 {avail_kb / 1024 / 1024:.1f} GB，实例数从 {h["workers"]} 降到 {fit}')
        h['workers'] = fit
hosts = [h for h in hosts if h['workers'] > 0]
# 抢活：任务切成 K 小份放进队列，哪台机器空了就领下一份（快的机器自然多干）；某台掉线，它手上那份放回队列
import queue
SLOT_W = 4                                                  # 每个槽位跑一个 4 进程的小批次；一台机器开 workers/4 个槽位
for h in hosts: h['slots'] = max(1, h['workers'] // SLOT_W)
K = max(16, 3 * sum(h['slots'] for h in hosts))
# 份数按任务数封顶，每份尽量凑满一个槽位的 4 局（但至少每个槽位一份）：槽位多、任务少时，
# 每份只剩 1~2 局，4 进程的槽位只开一半，一半以上的核闲着
_n = 0
if '--lab' in rest:
    try:
        _sp = rest[rest.index('--lab') + 1]
        _n = len(json.load(open(_sp if os.path.isabs(_sp) else os.path.join(HERE, _sp)))['tasks'])
    except Exception:
        _n = 0
if _n: K = max(sum(h['slots'] for h in hosts), min(K, -(-_n // SLOT_W)))
todo = queue.Queue()
for i in range(K): todo.put(i)
done_parts = {}; lock = threading.Lock(); dead = set()
# 收尾加速：派完以后，快机器把慢机器上还在跑的份再跑一遍，谁先跑完用谁，慢的那份直接停掉——
# 不然每项最后要干等慢机器上的几局长局
SPEED = {h['key']: h.get('speed', 1) for h in HOSTS}
running = {}; backed = set(); part_file = {}


def run_on(h, part, tag):
    if 'ssh' not in h:
        return subprocess.run([sys.executable, f'{HERE}/run.py', *rest, '--part', part, '--workers', str(SLOT_W), '--tag', tag, '--no-hard-seeds'],
                              capture_output=True, text=True, cwd=HERE).returncode == 0
    import shlex                                  # 10/3：参数原样传到远端要加引号，否则 ["route"] 这种会被远端 shell 吃掉引号
    cmd = f'cd {RDIR} && {RENV} nice -n 10 python3 run.py {" ".join(shlex.quote(x) for x in rest)} --part {part} --workers {SLOT_W} --tag {tag} --no-hard-seeds > /tmp/sts2-{tag}.log 2>&1; echo done'
    ok = 'done' in subprocess.run(ssh_of(h) + [h['ssh'], cmd], capture_output=True, text=True).stdout
    got = subprocess.run(['scp', '-q', '-o', 'ConnectTimeout=8', '-P', str(h.get('port', 22)), f'{h["ssh"]}:{RDIR}/results/{tag}.jsonl', f'{HERE}/results/{tag}.jsonl']).returncode == 0
    return ok and got


def busy(h):
    """派活前看一眼目标机器（几个实验同时开跑时，每个都按「只有自己」估内存，会把机器压垮、交换区用满）。
    可用内存低于保留量 + 2 GB（一个 4 进程批次约 2 GB）→ 'mem'（硬限制）；负载超过核数 × 4（明显叠加失控）→ 'load'。
    负载门槛不能低：机器上有别的常驻任务时，按核数 × 1.5 会一直判成忙、干等 30 分钟；CPU 挤一点只是变慢，内存用光才会出事"""
    if 'ssh' not in h: return False
    # 几个 dist 同时跑时，各自都按「这台归我」派活，会在同一台机器上叠满进程、推演按墙钟截断会少模拟。
    # → 再数一下这台上已经在跑几份（所有 run.py --tag），到了槽位数就等
    out = subprocess.run(ssh_of(h) + [h['ssh'], "nproc; cut -d' ' -f1 /proc/loadavg; awk '/MemAvailable/{print $2}' /proc/meminfo; "
                                                 "ps -eo args | grep '[r]un.py ' | grep -o -- '--tag [^ ]*' | sort -u | wc -l"],
                         capture_output=True, text=True).stdout.split()
    try:
        cores, load, avail = int(out[0]), float(out[1]), int(out[2]) / 1024 / 1024
        used = int(out[3]) if len(out) > 3 else 0
    except Exception:
        return False
    if avail < h.get('keep_gb', 2.0) + 2.0: return 'mem'
    if used >= h.get('slots', 99): return 'full'
    return 'load' if load > cores * 4 else False


def job(h):
    fails = 0
    while True:
        waited = 0
        while True:                                     # 内存不够一直等（硬限制，机器上可能还跑着别的服务）；只是负载高最多等 30 分钟
            b = busy(h)
            if not b or (b == 'load' and waited >= 1800): break
            time.sleep(30); waited += 30
        backup = False
        try:
            i = todo.get_nowait()
        except queue.Empty:
            with lock:                                  # 没有新活了：挑一份在比自己慢的机器上跑、还没备份的，再跑一遍
                cand = [j for j, k2 in running.items() if j not in done_parts and j not in backed and SPEED.get(k2, 1) < SPEED.get(h['key'], 1)]
                if not cand: return
                i = cand[0]; backed.add(i); backup = True
        tag = f'{a.tag}-p{i}' + ('b' if backup else '')
        if h['key'] in dead:
            if not backup: todo.put(i)
            return
        if not backup:
            with lock: running[i] = h['key']
        if run_on(h, f'{i}/{K}', tag):
            with lock:
                first = i not in done_parts
                if first: done_parts[i] = h['key']; part_file[i] = f'{HERE}/results/{tag}.jsonl'
            if first and backup:                         # 备份先跑完：停掉慢机器上那份（它跑完的部分结果不用）
                hs = next((x for x in hosts if x['key'] == running.get(i)), None)
                if hs and 'ssh' in hs:
                    pat = f'{a.tag}-p{i} --no-hard-seed[s]'
                    subprocess.run(ssh_of(hs) + [hs['ssh'], f"pkill -f '{pat}'; true"], capture_output=True)
                print(f'第 {i} 份由 {h["key"]} 备份先跑完', flush=True)
            fails = 0
        elif backup:
            pass                                         # 备份失败不影响原来那份
        else:
            todo.put(i); fails += 1
            if fails >= 2:                                   # 连续失败两次：先停派，每 2 分钟试连一次（网络断几分钟不至于被整项判掉线），30 分钟连不上才算掉线
                print(f'{h.get("ssh", "本机")} 连续失败，暂停派活、每 2 分钟试连', flush=True)
                back = False
                for _ in range(15):
                    time.sleep(120)
                    if len(done_parts) >= K: return
                    try:
                        back = subprocess.run(ssh_of(h) + [h['ssh'], 'true'], capture_output=True, timeout=30).returncode == 0
                    except Exception:
                        back = False
                    if back: break
                if not back:
                    with lock: dead.add(h['key'])
                    print(f'{h.get("ssh", "本机")} 30 分钟连不上，停止派活', flush=True); return
                print(f'{h.get("ssh", "本机")} 恢复，继续派活', flush=True); fails = 0


t = time.time()
for _ in range(3):                                          # 有机器掉线、退回的份没人接时，让活着的机器再来一轮
    th = [threading.Thread(target=job, args=(h,), daemon=True) for h in hosts if h['key'] not in dead for _ in range(h['slots'])]
    for x in th: x.start()
    while any(x.is_alive() for x in th) and len(done_parts) < K: time.sleep(5)   # 全部份都有结果就不再等（被备份顶掉的慢份已停）
    if len(done_parts) >= K: break
    if todo.empty() or not th: break
# 收尾：这个标签还在任何机器上跑的进程（被顶掉的慢份 / 没用上的备份）一律停掉，留下的半截结果文件删掉
for h in hosts:
    if 'ssh' in h and h['key'] not in dead:
        try: subprocess.run(ssh_of(h) + [h['ssh'], f"pkill -f '{a.tag}-p[0-9]+b? --no-hard-seed[s]'; true"], capture_output=True, timeout=60)
        except Exception: pass
status = {h['key']: h['key'] not in dead for h in hosts}
rs = []; counts = collections.Counter()
for i, key in sorted(done_parts.items()):
    p = part_file.get(i) or f'{HERE}/results/{a.tag}-p{i}.jsonl'
    got = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    counts[key] += len(got); rs += got
    os.remove(p)
for f in glob.glob(f'{HERE}/results/{a.tag}-p*.jsonl'):      # 被顶掉的那份留下的半截结果
    os.remove(f)
missing = [i for i in range(K) if i not in done_parts]
if missing: print(f'有 {len(missing)} 份没跑完：{missing}')
with open(f'{HERE}/results/{a.tag}.jsonl', 'w') as f:
    for r in rs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
sys.argv = [sys.argv[0]] + rest
import run
opts = {'stop_act': None, 'scenario': None}
for i, x in enumerate(rest):
    if x == '--stop-act': opts['stop_act'] = int(rest[i + 1])
    if x == '--scenario': opts['scenario'] = rest[i + 1]
names = {h['key']: h.get('name', h['key']) for h in HOSTS}
print(' + '.join(f'{names[k]} {v} 局' for k, v in counts.items()) + f'，用时 {time.time() - t:.0f} 秒' +
      ('' if all(status.values()) else f'（没跑完的：{[names[k] for k, v in status.items() if not v]}）'))
if '--lab' in rest:
    pass                                 # 遭遇实验室：结果由 lab.py 自己读
elif '--bench' in rest:
    run.bench_report(rs)
else:
    run.summarize(rs, opts)
    if not opts['stop_act'] and '--god' not in rest:
        with open(f'{HERE}/seedlab/hard_seeds.jsonl', 'a') as f:
            for r in rs:
                if not r.get('win') and r.get('seed') and 'crash' not in r:
                    f.write(json.dumps({'seed': r['seed'], 'tag': a.tag, 'act': r.get('act'), 'floor': r.get('floor'), 'room': r.get('room'),
                                        'enemies': r.get('enemies'), 'deck': r.get('deck')}, ensure_ascii=False) + '\n')
