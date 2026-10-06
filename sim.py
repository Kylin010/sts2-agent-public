"""连接 sts2-cli 的后台游戏引擎（真游戏的规则、随机数，没有画面）。

一个 Sim 对象 = 一个引擎进程，可以连续打多局（每局发一次 start_run）。
引擎用一行 JSON 收指令、一行 JSON 回状态。
"""
import time, json, os, queue, subprocess, threading

CLI_DIR = os.environ.get('STS2_CLI_DIR', '/opt/slay-the-spire-2/sources/github/wuhao21_sts2-cli')
DLL = f'{CLI_DIR}/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll'
DOTNET = os.environ.get('DOTNET', '/opt/dotnet9/dotnet')


class SimError(RuntimeError):
    pass


_SLOW = os.environ.get('STS2_SLOW_LOG'); _SLOW_STAT = {}


class Sim:
    def __init__(self, timeout=120):     # 10/2：机器满载时 30 秒不够（基准里 44 场「引擎超时」），宁可多等
        self.timeout = timeout
        self.rec = None                   # 不是 None 时，act 成功的动作都记进这个列表（战斗推演靠它重放）
        self._spawn()

    def _spawn(self):
        env = dict(os.environ, DOTNET_ROOT=os.path.dirname(DOTNET), DOTNET_CLI_TELEMETRY_OPTOUT='1')
        self.broken = False
        self.p = subprocess.Popen([DOTNET, DLL], cwd=CLI_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=(open(f"{os.environ['STS2_ENGINE_LOG']}.{os.getpid()}", 'a') if os.environ.get('STS2_ENGINE_LOG') else subprocess.DEVNULL),
                                  text=True, bufsize=1, env=env)   # STS2_ENGINE_LOG：引擎日志存文件（排查用）
        self.q = queue.Queue()
        threading.Thread(target=self._pump, args=(self.p, self.q), daemon=True).start()
        ready = self._read()
        if ready.get('type') != 'ready':
            raise SimError(f'引擎没有就绪：{ready}')

    def rss_mb(self):
        """引擎进程当前占的内存（MB）。10/2：影子引擎反复读档重放，内存会慢慢涨到 1 GB 以上"""
        try:
            for line in open(f'/proc/{self.p.pid}/status'):
                if line.startswith('VmRSS:'): return int(line.split()[1]) / 1024
        except Exception:
            pass
        return 0.0

    def restart(self):
        """换一个新的引擎进程（超时之后旧进程的回应会错位，不能再用）"""
        try:
            self.p.kill()
        except Exception:
            pass
        self._spawn()

    @staticmethod
    def _pump(p, q):
        for line in p.stdout:
            q.put(line)
        q.put(None)

    def _read(self):
        while True:
            try:
                line = self.q.get(timeout=self.timeout)
            except queue.Empty:
                # 10/2：机器负载高时偶尔超时。超时之后这条指令的回应可能晚到，之后每次读到的都是上一条的回应（错位）——
                # 推演就是这样「恢复局面失败」的。标记为坏掉，调用方换新进程
                self.broken = True
                raise SimError('引擎超时没有回应') from None
            if line is None:
                self.broken = True
                raise SimError('引擎进程退出了')
            if line.startswith('{'):
                return json.loads(line)

    def send(self, cmd):
        if self.broken: raise SimError('引擎之前超时 / 退出过，回应会错位，需要 restart')
        self.p.stdin.write(json.dumps(cmd) + '\n')
        self.p.stdin.flush()
        _t0 = time.time() if _SLOW else 0
        r = self._read()
        if _SLOW:                                           # 慢调用记录（STS2_SLOW_LOG=文件）：按命令 / 动作统计引擎耗时
            k = str(cmd.get('cmd')) + ':' + str(cmd.get('action') or '')
            d = _SLOW_STAT.setdefault(k, [0, 0.0, 0.0]); dt = time.time() - _t0; d[0] += 1; d[1] += dt; d[2] = max(d[2], dt)
            if d[0] % 50 == 0 or dt > 0.2:
                with open(f'{_SLOW}.{os.getpid()}', 'w') as f: json.dump(_SLOW_STAT, f)
        if r.get('type') == 'error' and str(r.get('message', '')).startswith(('EVENT_FAULT', 'MERCHANT_FAULT', 'ENDTURN_STALE')):
            # Native event/purchase failure may leave partial effects. Stop this run
            # as a technical failure instead of retrying an option or purchase.
            raise SimError(f'后台操作失败（技术故障）：{str(r.get("message"))[:700]}')
        ov = getattr(self, 'ctx_override', None)
        if ov and isinstance(r.get('context'), dict):
            # 10/4 新引擎推演：影子局是另开的一局（永远是第一幕第一层），局面里的幕 / 章节 / Boss / 层数改成真局的，
            # 否则推演里规划器按「第一幕」的规则打第二、三幕的战斗（省药、估值模型的幕特征……）
            r['context'].update(ov)
        return r

    def start(self, seed, ascension=10, character='Ironclad'):
        return self.send({'cmd': 'start_run', 'character': character, 'ascension': ascension, 'seed': seed})

    def act(self, action, **args):
        cmd = {'cmd': 'action', 'action': action}
        if args:
            cmd['args'] = args
        r = self.send(cmd)
        if self.rec is not None and r.get('type') != 'error':
            self.rec.append((action, dict(args)))
        return r

    def get_map(self):
        return self.send({'cmd': 'get_map'})

    def close(self):
        try:
            self.send({'cmd': 'quit'})
        except Exception:
            pass
        self.p.kill()


# ---- 每个进程复用一个引擎（10/2：sts2-cli 开新局前会先清理上一局，同一进程可以连开很多局，省掉每局约 5 秒的初始化）----
_POOL = {'sim': None, 'uses': 0}
MAX_USES = 200                       # 用满这么多局就换一个新进程，防止内存慢慢涨


def acquire():
    s = _POOL['sim']
    if s is None or s.broken or s.p.poll() is not None or _POOL['uses'] >= MAX_USES or os.environ.get('STS2_NO_REUSE') == '1' or s.rss_mb() > 800:
        if s is not None:
            s.close()
        s = Sim(); _POOL['sim'] = s; _POOL['uses'] = 0
    _POOL['uses'] += 1
    s.rec = None
    return s


def release(s, ok=True):
    """一局结束：正常的留着复用；出过错的关掉（下一局重开），避免坏状态传下去"""
    if not ok or os.environ.get('STS2_NO_REUSE') == '1':
        s.close()
        if _POOL['sim'] is s: _POOL['sim'] = None


# ---- 每个进程第二个引擎（10/2）：推演和模拟实打都在它上面做，真实对局的引擎完全不碰 ----
_AUX = {'sim': None, 'uses': 0}


def aux():
    s = _AUX['sim']
    if s is None or s.broken or s.p.poll() is not None or _AUX['uses'] > 3000 or (_AUX['uses'] % 20 == 0 and s.rss_mb() > 600):
        if s is not None:
            s.close()
        s = Sim(timeout=90); _AUX["sim"] = s; _AUX["uses"] = 0
    _AUX['uses'] += 1
    return s
