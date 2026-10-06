"""一步一步迭代。

固定 100 个种子（lab/iter/seeds.txt）。当前最好配置的对照结果存在 lab/iter/state.json；每次从队列 lab/iter/queue.json 取一个改动，
只跑这一个改动的 100 局（约半小时），和对照逐种子配对：
  采用条件：过第二幕 ≥ 对照、同种子「走得更远」多于「更近」、符号检验运气概率 ≤ ADOPT_P。
  采用 → 改动叠进基准，它这 100 局直接当新的对照（不用重跑）；不采用 → 丢掉，下一个改动还在原基准上测。
队列随时可以往里加（JSON 列表，每项 {"name": 名字, "params": {参数: 值}}；{"control": true} = 用当前基准重跑对照，换引擎 / 改代码后用）。
队列空了每 5 分钟看一次。每次结果写 lab/iter/LOG.md。

加 --stop-act 1（只打到第一幕结束，100 局约 10~15 分钟），
采用标准看「过关数」；报告按第一幕章节分「密林 / 暗港」（lab/iter/seed_acts.json，随机章节 = 补丁 17 / B-018）。
用法：setsid nohup python3 tools/iter_lab.py [--stop-act 1] >> lab/iter/run.out 2>&1 < /dev/null &
"""
import json, math, os, random, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f"{HERE}/{sys.argv[sys.argv.index('--dir') + 1]}" if '--dir' in sys.argv else f'{HERE}/lab/iter'   # 10/4：暗港专项用 --dir lab/iter-ud
STATE, QUEUE, LOG = f'{OUT}/state.json', f'{OUT}/queue.json', f'{OUT}/LOG.md'
ADOPT_P = 0.2
STOP_ACT = int(sys.argv[sys.argv.index('--stop-act') + 1]) if '--stop-act' in sys.argv else 2
ACTS = {}


def w(msg):
    print(msg, flush=True)
    with open(LOG, 'a') as f: f.write(msg + '\n')


def disasters(r):
    """这局「要读档」的次数：诚实打的战斗里，死了 / 掉血 ≥30% 最大血量 / ≥1.5 倍人类赢家同场平均（≥15）。
    和 run.py 读档学习的触发条件一样，只是不真的读档"""
    sys.path.insert(0, HERE)
    import run
    mx = r.get('max_hp') or 80; n = 0
    for c in r.get('combats') or []:
        b = run.BASE.get(run.match_baseline(c)) or {}
        d = c.get('dmg') or 0
        if d >= 0.3 * mx or (b.get('win_avg') and d >= max(15, 1.5 * b['win_avg'])): n += 1
    return n + (0 if (r.get('win') or r.get('cleared')) else 1)


def summ(r):
    """一局的摘要：打到哪、过没过第一 / 二幕、剩血；崩溃（技术故障）单独标"""
    if 'crash' in r: return {'crash': str(r['crash'])[:120]}
    act = r.get('act') or 1; win = bool(r.get('win') or r.get('cleared'))
    # 10/4 整局迭代：--stop-act 3 时 a2 = 到了第三幕，clear = 通关
    a2 = bool(win or act >= 3) if STOP_ACT >= 3 else bool(win and STOP_ACT >= 2)
    return {'act': act, 'floor': r.get('floor') or 0, 'a1': bool(win or act >= 2), 'a2': a2, 'clear': win, 'hp': r.get('hp') or 0,
            'boss3': bool(win or (act >= 3 and r.get('room') == 'Boss')), 'act1': r.get('act1'),
            # 10/4 claude-value（B-009）：第三幕打赢了几个 Boss（双 Boss 补丁 12 部署前，打赢第一个就结束、被记成没通关）
            'b3won': sum(1 for c in r.get('combats') or [] if c.get('act') == 3 and c.get('room') == 'Boss')
                     - (1 if (not win and act >= 3 and r.get('room') == 'Boss' and not r.get('terminal_victory_reported')) else 0),
            'sl': disasters(r)}


def prog(s):
    """走得多远：打完要求的幕 = 100 × 幕数 + 剩血；否则 100 × (幕 − 1) + 层"""
    # 10/4：原来过关的局再比剩余血量，噪声盖过了过关数（暗港「想得更久」过关 67 vs 59、多过 18 / 少过 10，却因血量判成 37 / 34 不采用）→ 过关的局都算一样远
    # 10/4：引擎 p21 起第三幕有第二个 Boss（B-009），之前的对照打赢第一个 Boss 就结束——配对时「打赢第三幕第一个 Boss」和通关算一样远，通关另外单列
    # 10/5：只按「过了几幕」比（主指标），同一幕里死在第几层不算——人类价值网络那次过第一幕 +7、过第二幕 +5，按层比 36 / 30（p=0.27）判不采用，
    # 按幕比 25 / 16（p=0.11）。同一幕里早死晚死几层基本是噪声
    if s.get('clear', s['a2']): return 10 * STOP_ACT + 5
    if STOP_ACT >= 3 and s.get('b3won', 0) >= 1: return 10 * STOP_ACT
    return 10 * (s['act'] - 1)


def sign_p(b, wo):
    n = b + wo
    return 1.0 if n == 0 else sum(math.comb(n, i) for i in range(b, n + 1)) / 2 ** n


def run(name, cfg, seeds, stop_act=None):
    stop_act = stop_act or STOP_ACT
    tag = f"it-{os.path.basename(OUT)}-{time.strftime('%m%d-%H%M')}"     # 10/4：两个循环同一分钟开跑撞了标签，结果文件互相串 → 标签带目录名
    spec = f'{os.path.relpath(OUT, HERE)}/spec-{tag}.json'
    tasks = [{'seed': s, 'cand': name} for s in seeds]
    random.Random(len(tasks)).shuffle(tasks)
    json.dump({'candidates': {name: cfg}, 'tasks': tasks, 'stop_act': stop_act}, open(f'{HERE}/{spec}', 'w'), ensure_ascii=False)
    t0 = time.time()
    with open(f'{OUT}/dist-{tag}.out', 'w') as out:
        subprocess.run([sys.executable, 'dist.py', '0', '--lab', spec, '--tag', tag, '--set', 'search_on=true'], cwd=HERE, stdout=out, stderr=subprocess.STDOUT)
    p = f'{HERE}/results/{tag}.jsonl'
    rows = {}
    for l in (open(p) if os.path.exists(p) else []):
        r = json.loads(l)
        if isinstance(r.get('task'), int): rows[tasks[r['task']]['seed']] = summ(r)
    return tag, rows, time.time() - t0


def describe(rows):
    ok = [s for s in rows.values() if 'crash' not in s]
    a1 = sum(s['a1'] for s in ok); a2 = sum(s['a2'] for s in ok)
    by = ''
    if True:                                   # 章节：种子章节表，没有就用结果里的 act1（10/4）
        parts = []
        for name, zh in (('Overgrowth', '密林'), ('Underdocks', '暗港')):
            xs = [s for seed, s in rows.items() if (ACTS.get(seed) or s.get('act1')) == name and 'crash' not in s]
            if xs:
                n1 = sum(x['a1'] for x in xs); n2 = sum(x['a2'] for x in xs)
                parts.append(f"{zh} 一幕 {n1}/{len(xs)}" + (f"、二幕 {n2}/{n1}（{n2 / max(n1, 1):.0%}）" if STOP_ACT >= 2 else ''))
        by = '（' + '，'.join(parts) + '）' if parts else ''
    sln = sum(s.get('sl', 0) for s in ok) / max(len(ok), 1)
    by += f"，每局要读档 {sln:.2f} 次"
    if STOP_ACT >= 3:
        cl = sum(s['clear'] for s in ok); a3b = sum(1 for s in ok if s.get('boss3'))
        return ok, (f"{len(ok)} 局（技术故障 {len(rows) - len(ok)}）：过第一幕 {a1}（{a1 / max(len(ok), 1):.0%}）、过了第一幕的局里过第二幕 {a2}/{a1}（{a2 / max(a1, 1):.0%}）、"
                    f"打到第三幕 Boss {a3b}、打赢第三幕第一个 Boss {sum(1 for s in ok if s.get('b3won', 0) >= 1)}、**通关 {cl}（{cl / max(len(ok), 1):.0%}）**{by}")
    head = f"**过第一幕 {a1}（{a1 / max(len(ok), 1):.0%}）**{by}" if STOP_ACT == 1 else \
        f"过第一幕 {a1}（{a1 / max(len(ok), 1):.0%}）、**过了第一幕的局里过第二幕 {a2}/{a1}（{a2 / max(a1, 1):.0%}）**{by}"
    return ok, f"{len(ok)} 局（技术故障 {len(rows) - len(ok)}）：{head}"


def main():
    os.makedirs(OUT, exist_ok=True)
    seeds = [l.strip() for l in open(f'{OUT}/seeds.txt') if l.strip()]
    if os.path.exists(f'{OUT}/seed_acts.json'): ACTS.update(json.load(open(f'{OUT}/seed_acts.json')))
    st = json.load(open(STATE)) if os.path.exists(STATE) else None
    if st is None:
        base0 = json.load(open(f'{HERE}/lab/iter/best.json'))['cfg'] if os.path.exists(f'{HERE}/lab/iter/best.json') else json.load(open(f'{HERE}/lab/bundle/best-a2.json'))['cfg']
        st = {'base': base0, 'adopted': [], 'control': None, 'n': 0}       # 新目录从主迭代当前最好的配置起步
        w(f"\n## {time.strftime('%m-%d %H:%M')} 一步一步迭代开始：{len(seeds)} 个种子、打到第 {STOP_ACT} 幕；基准 = 组合迭代的 best-a2（{len(st['base'])} 个参数）")
    while True:
        q = json.load(open(QUEUE)) if os.path.exists(QUEUE) else []
        if st['control'] is None:
            item = {'name': '对照', 'control': True}
        elif q:
            item = q.pop(0); json.dump(q, open(QUEUE, 'w'), ensure_ascii=False, indent=1)
        else:
            time.sleep(300); continue
        st['n'] += 1
        cfg = dict(st['base'], **(item.get('params') or {}))
        if item.get('checkpoint'):
            # 整局检查：当前最好配置在同一批种子上打到第 stop_act 幕，只报数、不改基准
            ca = item.get('stop_act', 2)
            tag, rows, sec = run(item['name'], cfg, seeds, stop_act=ca)
            ok = [r for r in rows.values() if 'crash' not in r]
            a1 = sum(r['a1'] for r in ok); a2 = sum(1 for r in ok if r['act'] >= 3 or (r.get('clear') and ca >= 2))
            by = ''
            if ACTS:
                parts = []
                for nm, zh in (('Overgrowth', '密林'), ('Underdocks', '暗港')):
                    xs = [r for sd, r in rows.items() if ACTS.get(sd) == nm and 'crash' not in r]
                    if xs: parts.append(f"{zh} 一幕 {sum(x['a1'] for x in xs)}/{len(xs)}、二幕 {sum(1 for x in xs if x['act'] >= 3 or (x.get('clear') and ca >= 2))}")
                by = '（' + '，'.join(parts) + '）'
            w(f"- 第 {st['n']} 次（{time.strftime('%m-%d %H:%M')}，{sec / 60:.0f} 分钟）**整局检查（打到第 {ca} 幕）**（基准 + 已采用 {len(st['adopted'])} 项）："
              f"{len(ok)} 局（技术故障 {len(rows) - len(ok)}）：过第一幕 {a1}（{a1 / max(len(ok), 1):.0%}）、**过第二幕 {a2}（{a2 / max(len(ok), 1):.0%}）**{by}")
            json.dump(st, open(STATE, 'w'), ensure_ascii=False)
            continue
        tag, rows, sec = run(item['name'], cfg, seeds)
        ok, desc = describe(rows)
        if item.get('control'):
            st['control'] = {'tag': tag, 'rows': rows}
            w(f"- 第 {st['n']} 次（{time.strftime('%m-%d %H:%M')}，{sec / 60:.0f} 分钟）**对照**（基准 + 已采用 {len(st['adopted'])} 项）：{desc}")
        else:
            ctrl = st['control']['rows']
            com = [s for s in seeds if s in rows and s in ctrl and 'crash' not in rows[s] and 'crash' not in ctrl[s]]
            b = sum(prog(rows[s]) > prog(ctrl[s]) for s in com); wo = sum(prog(rows[s]) < prog(ctrl[s]) for s in com)
            d1 = sum(rows[s]['a1'] for s in com) - sum(ctrl[s]['a1'] for s in com)
            d2 = sum(rows[s]['a2'] for s in com) - sum(ctrl[s]['a2'] for s in com)
            dc = sum(rows[s].get('clear', rows[s]['a2']) for s in com) - sum(ctrl[s].get('clear', ctrl[s]['a2']) for s in com)
            p = sign_p(b, wo)
            adopt = (d2 if STOP_ACT >= 2 else d1) >= 0 and b > wo and p <= ADOPT_P     # 10/5：通关数每次只有 0~1 局，噪声；改看过第二幕不少（主指标）
            w(f"- 第 {st['n']} 次（{time.strftime('%m-%d %H:%M')}，{sec / 60:.0f} 分钟）{item['name']} {item.get('params')}：{desc}｜"
              f"和对照同 {len(com)} 个种子：过第一幕 {d1:+d}、过第二幕 {d2:+d}" + (f"、通关 {dc:+d}" if STOP_ACT >= 3 else '') + f"，走得更远 {b} / 更近 {wo}（运气概率 {p:.2f}）→ {'**采用**' if adopt else '不采用'}")
            if adopt:
                st['base'] = cfg; st['adopted'].append({'name': item['name'], 'params': item.get('params'), 'tag': tag})
                st['control'] = {'tag': tag, 'rows': rows}
                json.dump({'cfg': cfg, 'adopted': st['adopted'], 'time': time.strftime('%m-%d %H:%M')}, open(f'{OUT}/best.json', 'w'), ensure_ascii=False, indent=1)
        json.dump(st, open(STATE, 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
