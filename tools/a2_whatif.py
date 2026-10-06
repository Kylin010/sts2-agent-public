"""第二幕 Boss「如果牌组这样改会怎样」（10/3：找出提高第二幕通过率最值钱的方向——升级、产能牌、还是遗物）。

从 data/bench_a2ours.json 取帝皇蟹、知识恶魔、无厌沙虫的「我们的遗物档」案例（我们程序自己的牌组 + 10 个遗物），每个做 4 个版本：
  原样 / +3 升级（随机升级 3 张没升级的非基础牌） / +产能牌（加耸肩无视 + 战斗专注） / +5 遗物（到人类水平）
输出 data/bench_a2whatif.json（每条带 variant 字段），用 STS2_BENCH=bench_a2whatif.json dist.py 0 --bench 跑，再 python3 tools/a2_whatif.py --report 结果文件
"""
import collections, json, os, random, statistics as S, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOSSES = ('KAISER_CRAB_BOSS', 'KNOWLEDGE_DEMON_BOSS', 'THE_INSATIABLE_BOSS')
BASIC = {'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'ASCENDERS_BANE'}


def make(seed=11):
    rng = random.Random(seed)
    src = json.load(open(f'{HERE}/data/bench_a2ours.json'))
    pool = collections.Counter(r for c in src if c['relic_level'] == '人类' for r in c['relics'] if r != 'BURNING_BLOOD')
    out = []
    for c in src:
        if c['encounter'] not in BOSSES or c['relic_level'] != '我们': continue
        base = dict(c, variant='原样'); out.append(base)
        d = list(c['deck']); cand = [i for i, x in enumerate(d) if not x.endswith('+') and x.rstrip('+') not in BASIC]
        for i in rng.sample(cand, min(3, len(cand))): d[i] = d[i] + '+'
        out.append(dict(c, deck=d, variant='+3升级'))
        out.append(dict(c, deck=list(c['deck']) + ['SHRUG_IT_OFF', 'BATTLE_TRANCE'], variant='+产能牌'))
        rs = set(c['relics'])
        extra = [r for r, _ in pool.most_common() if r not in rs]
        while len(rs) < len(c['relics']) + 5 and extra: rs.add(extra.pop(rng.randrange(min(len(extra), 30))))
        out.append(dict(c, relics=sorted(rs), variant='+5遗物'))
    json.dump(out, open(f'{HERE}/data/bench_a2whatif.json', 'w'), ensure_ascii=False)
    print('案例', len(out))


def report(path):
    cases = json.load(open(f'{HERE}/data/bench_a2whatif.json'))
    rows = [json.loads(l) for l in open(path)]
    zh = {k: v.get('zh', k) for k, v in json.load(open(f'{HERE}/data/baselines.json')).items()}
    g = collections.defaultdict(list)
    for r in rows:
        if 'crash' in r or not isinstance(r.get('case'), int): continue
        c = cases[r['case']]; g[(c['encounter'], c['variant'])].append(r)
    for e in BOSSES:
        print(f'\n{zh.get(e, e)}：')
        for v in ('原样', '+3升级', '+产能牌', '+5遗物'):
            xs = g.get((e, v)) or []
            if xs: print(f'  {v}：{len(xs)} 场，撑过 {sum(1 for r in xs if r.get("survived")) / len(xs):.0%}，平均掉血 {S.mean(r.get("dmg") or 0 for r in xs):.1f}')


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--report': report(sys.argv[2])
    else: make()
