"""单场战斗对比：同一批单场案例（默认 data/bench_a2ours.json），几种打法各打一遍，一次分发跑完，同案例配对比较。

用法：python3 tools/fight_lab.py --enc KAISER_CRAB_BOSS,KNOWLEDGE_DEMON_BOSS --tag flab1 \
        --cand '{"推演加倍": {"search_k": 8, "search_samples": 3, "search_refine_samples": 6}, "格挡更重": {"block_mult": 1.3}}' [--reps 1]
对照（不改参数）自动加上。只出报告：python3 tools/fight_lab.py --report flab1
"""
import argparse, collections, json, math, os, statistics as S, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sign_p(b, w):
    n = b + w
    return 1.0 if n == 0 else sum(math.comb(n, i) for i in range(b, n + 1)) / 2 ** n


def report(tag):
    sp = json.load(open(f'{HERE}/lab/fightlab/spec-{tag}.json'))
    cases = json.load(open(f'{HERE}/data/{sp["bench"]}'))
    zh = {k: v.get('zh', k) for k, v in json.load(open(f'{HERE}/data/baselines.json')).items()}
    rows = [json.loads(l) for l in open(f'{HERE}/results/{tag}.jsonl')]
    by = collections.defaultdict(dict)                 # (候选, 遭遇) → {(案例, rep): 结果}
    for r in rows:
        if 'crash' in r or not isinstance(r.get('task'), int): continue
        t = sp['tasks'][r['task']]
        by[(t['cand'], cases[t['case']]['encounter'])][(t['case'], t['rep'])] = r
    encs = sorted({e for _, e in by})
    for e in encs:
        print(f'\n{zh.get(e, e)}：')
        ctrl = by.get(('对照', e), {})
        for cand in sp['candidates']:
            g = by.get((cand, e), {})
            if not g: continue
            surv = sum(1 for r in g.values() if r.get('survived')); dmg = S.mean(r.get('dmg') or 0 for r in g.values())
            line = f'  {cand}：{len(g)} 场，撑过 {surv}（{surv / len(g):.0%}），平均掉血 {dmg:.1f}，回合 {S.mean(r.get("rounds") or 0 for r in g.values()):.1f}'
            if cand != '对照':
                com = [k for k in g if k in ctrl]
                sc = lambda r: (1000 if r.get('survived') else 0) - (r.get('dmg') or 0)
                b = sum(1 for k in com if sc(g[k]) > sc(ctrl[k])); w = sum(1 for k in com if sc(g[k]) < sc(ctrl[k]))
                line += f'｜同案例比对照 更好 {b} 更差 {w}（运气概率 {sign_p(b, w):.2f}）'
            print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--enc', default=''); ap.add_argument('--tag', default='flab'); ap.add_argument('--cand', default='{}')
    ap.add_argument('--reps', type=int, default=1); ap.add_argument('--bench', default='bench_a2ours.json'); ap.add_argument('--report', default=None)
    a = ap.parse_args()
    if a.report: return report(a.report)
    cases = json.load(open(f'{HERE}/data/{a.bench}'))
    encs = set(a.enc.split(',')) if a.enc else None
    cands = {'对照': {}, **json.loads(a.cand)}
    tasks = [{'bench': a.bench, 'case': i, 'rep': r, 'cand': name}
             for i, c in enumerate(cases) if not encs or c['encounter'] in encs for r in range(a.reps) for name in cands]
    import random
    random.Random(len(tasks)).shuffle(tasks)
    os.makedirs(f'{HERE}/lab/fightlab', exist_ok=True)
    spec = f'lab/fightlab/spec-{a.tag}.json'
    json.dump({'candidates': cands, 'tasks': tasks, 'bench': a.bench}, open(f'{HERE}/{spec}', 'w'), ensure_ascii=False)
    print(f'{len(cands)} 种打法 × {len(tasks) // len(cands)} 场 = {len(tasks)} 场', flush=True)
    subprocess.run([sys.executable, 'dist.py', '0', '--lab', spec, '--tag', a.tag, '--set', 'search_on=true'], cwd=HERE)
    report(a.tag)


if __name__ == '__main__':
    main()
