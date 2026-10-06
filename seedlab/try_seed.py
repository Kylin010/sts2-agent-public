"""研究一个种子：用每种流派（seedlab/archetypes.json）各打一局，看哪种能赢、死在哪。
用法（在 agent/ 目录）：python3 seedlab/try_seed.py 种子 [种子 ...] [--hp 80]
结果追加到 seedlab/results.jsonl，并打印表格。
"""
import json, os, sys, time
from multiprocessing import Pool
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
import params, run
ARCH = {k: v for k, v in json.load(open(f'{HERE}/seedlab/archetypes.json')).items() if not k.startswith('_')}


def job(args):
    seed, arch, hp = args
    params.P['force_archetype'] = arch
    t = time.time()
    try:
        r = run.play_one(seed, god=hp if hp != 80 else 0)
    except Exception as e:
        r = {'win': False, 'crash': str(e)[:150]}
    return {'seed': seed, 'archetype': arch, 'hp': hp, 'win': r.get('win'), 'act': r.get('act'), 'floor': r.get('floor'),
            'enemies': r.get('enemies'), 'deck': r.get('deck'), 'crash': r.get('crash'), 'sec': round(time.time() - t, 1)}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    hp = int(sys.argv[sys.argv.index('--hp') + 1]) if '--hp' in sys.argv else 80
    seeds = [a for a in args if not a.isdigit()]
    jobs = [(s, a, hp) for s in seeds for a in ARCH]
    with Pool(8) as p: rs = p.map(job, jobs)
    with open(f'{HERE}/seedlab/results.jsonl', 'a') as f:
        for r in rs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    for s in seeds:
        print(f'\n种子 {s}（血量 {hp}）')
        for r in rs:
            if r['seed'] == s:
                print(f"  {r['archetype']:<11} {'赢' if r['win'] else '输'}  第{r['act']}幕第{r['floor']}层  {r.get('enemies') or ''} {r.get('crash') or ''}")
