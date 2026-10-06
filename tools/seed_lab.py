"""逐种子攻克：一个种子在 80 血下打不过，就研究、改到能打过，再换下一个。

  python3 tools/seed_lab.py run SEED [--tag 说明]   80 血打一整局（开引擎推演），每层出发前存档到 lab/seeds/SEED/saves/，
                                                   记下每个决定和每场战斗，写进 lab/seeds/SEED/runs.jsonl，打印时间线
  python3 tools/seed_lab.py regress                 回归：lab/seeds/ledger.json 里所有「已打过」的种子重打一遍，必须都还能赢
  python3 tools/seed_lab.py next                    账本里第一个还没打过的种子（按 data/dev_seeds.txt 的顺序）

改动必须是通用规则（不能针对某个种子写特判）；每次改完先打当前种子，再跑回归。
同一份代码打同一个种子结果完全一样（推演的随机数按种子和位置固定），所以「打过了」不是碰运气。
"""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
params.P['search_on'] = True
import run
from sim import acquire, release

LAB = f'{HERE}/lab/seeds'
LEDGER = f'{LAB}/ledger.json'


def ledger():
    return json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}


def save_ledger(d):
    os.makedirs(LAB, exist_ok=True)
    json.dump(d, open(LEDGER, 'w'), ensure_ascii=False, indent=1)


def git_rev():
    try:
        import subprocess
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=HERE, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ''


def play(seed, verbose=False):
    d = f'{LAB}/{seed}/saves'; os.makedirs(d, exist_ok=True)
    sim = acquire(); t = time.time()
    try:
        st = sim.start(seed, ascension=10)
        mem = {'save_dir': d, 'trace': []}
        r = run.drive(sim, st, mem, verbose=verbose)
        r['trace'] = mem['trace']
    except Exception as e:
        r = {'win': False, 'crash': str(e)[:400], 'trace': []}
    finally:
        release(sim, ok=sys.exc_info()[0] is None)
    r['seed'] = seed; r['sec'] = round(time.time() - t)
    return r


def timeline(r):
    """按层列出：房间、进出血量、做了什么"""
    out = []
    cb = {(c['act'], c['floor']): c for c in r.get('combats') or []}
    for it in r.get('trace') or []:
        k = (it['act'], it['floor'])
        if it['d'] == 'map_select':
            out.append(f"{it['act']}-{it['floor']:02d} 血{it['hp']}/{it['max_hp']} 金{it['gold']} 选路 {it['args']} 可选 {it.get('opts')}")
        elif it['d'] in ('card_reward', 'card_select', 'event_choice', 'rest_site', 'shop'):
            out.append(f"{it['act']}-{it['floor']:02d} 血{it['hp']} {it['d']} → {it['a']} {it['args']} | {it.get('event') or ''} {it.get('opts')}")
    for k, c in sorted(cb.items()):
        out.append(f"{k[0]}-{k[1]:02d} 战斗 {c['room']} {c['enemies']} 掉血 {c['dmg']} 回合 {c['rounds']} 药 {c.get('potions', 0)} 推演 {c.get('search')}")
    return sorted(out)


def cmd_run(seed, tag, verbose):
    r = play(seed, verbose)
    os.makedirs(f'{LAB}/{seed}', exist_ok=True)
    with open(f'{LAB}/{seed}/runs.jsonl', 'a') as f:
        f.write(json.dumps({**r, 'tag': tag, 'rev': git_rev(), 'time': time.strftime('%m-%d %H:%M')}, ensure_ascii=False) + '\n')
    for line in timeline(r): print(line)
    res = '赢了' if r.get('win') else f"输在 {r.get('act')}-{r.get('floor')} {r.get('room')} {r.get('enemies')}" + (f"（崩溃：{r['crash']}）" if r.get('crash') else '')
    print(f'\n种子 {seed}：{res}，用时 {r["sec"]} 秒')
    L = ledger(); e = L.setdefault(seed, {'tries': 0, 'won': False})
    e['tries'] += 1; e['last'] = res; e['last_tag'] = tag
    if r.get('win') and not e['won']: e['won'] = True; e['won_at'] = time.strftime('%m-%d %H:%M'); e['won_tag'] = tag
    save_ledger(L)
    return r


def cmd_regress():
    from multiprocessing import Pool
    seeds = [s for s, e in ledger().items() if e.get('won')]
    if not seeds: print('还没有打过的种子'); return True
    with Pool(min(8, len(seeds))) as p:
        rs = p.map(play, seeds)
    bad = [r['seed'] for r in rs if not r.get('win')]
    print(f'回归：{len(seeds)} 个已打过的种子，{len(seeds) - len(bad)} 个仍然赢；退步的：{bad}')
    return not bad


def cmd_next():
    L = ledger()
    for s in open(f'{HERE}/data/dev_seeds.txt').read().split():
        if not L.get(s, {}).get('won'): return s


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('seed', nargs='?'); ap.add_argument('--tag', default='')
    ap.add_argument('--verbose', action='store_true'); ap.add_argument('--set', action='append', default=[])
    a = ap.parse_args()
    params.override(a.set)
    if a.cmd == 'run': cmd_run(a.seed or cmd_next(), a.tag, a.verbose)
    elif a.cmd == 'regress': sys.exit(0 if cmd_regress() else 1)
    elif a.cmd == 'next': print(cmd_next())
