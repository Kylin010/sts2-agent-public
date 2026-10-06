"""完整记录几局（方便逐层查看）：每个非战斗决定（选项 + 选了什么 + 当时血 / 金币）、商店货架和价格、每回合手牌 / 出牌 / 敌人意图。

用法（在 agent/ 目录）：python3 tools/trace_game.py 种子1 种子2 [--stop-act 2] [--set search_on=true ...]
结果：lab/trace/<种子>.json（整局结果 + trace 列表），再用 tools/trace_report.py 做成中文页面。
"""
import argparse, json, os, sys
from multiprocessing import Pool
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); os.chdir(HERE)
import params


def one(job):
    seed, stop_act, sets = job
    params.override(sets)
    import run
    try:
        r = run.play_one(seed, stop_act=stop_act, trace=True)
    except Exception as e:
        r = {'seed': seed, 'crash': str(e)[:500]}
    os.makedirs(f'{HERE}/lab/trace', exist_ok=True)
    json.dump(r, open(f'{HERE}/lab/trace/{seed}.json', 'w'), ensure_ascii=False)
    return seed, r.get('win'), r.get('act'), r.get('floor'), r.get('crash')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('seeds', nargs='+'); ap.add_argument('--stop-act', type=int, default=None)
    ap.add_argument('--set', action='append', default=[]); ap.add_argument('--workers', type=int, default=0)
    a = ap.parse_args()
    with Pool(a.workers or len(a.seeds)) as p:
        for x in p.imap_unordered(one, [(s, a.stop_act, a.set) for s in a.seeds]):
            print(*x, flush=True)
