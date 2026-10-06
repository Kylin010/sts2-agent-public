"""第二幕单场案例的结果（tools/make_a2_cases.py 生成的 data/bench_a2ours.json）：按战斗 × 遗物档看撑过率和掉血，
再看什么样的牌组打得过（有没有核心、联动分、升级数、牌数、伤害 / 格挡估计），给选牌找方向。

用法：python3 tools/a2lab_report.py results/a2lab-base.jsonl [results/另一组.jsonl ...]
"""
import collections, json, os, statistics as S, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, f'{HERE}/tools')
import zh
from policy import corerules, combos, deckeval
CASES = json.load(open(f'{HERE}/data/bench_a2ours.json'))
ZH = {k: v.get('zh', k) for k, v in json.load(open(f'{HERE}/data/baselines.json')).items()}


def deck_feats(case):
    d = [c.rstrip('+') for c in case['deck']]
    st = {'player': {'deck': [{'id': 'CARD.' + c.rstrip('+'), 'upgraded': c.endswith('+')} for c in case['deck']],
                     'relics': [{'id': r} for r in case['relics']], 'potions': []}}
    ev = deckeval.evaluate(st['player']['deck'])
    return {'核心': corerules.has_core(d), '联动分': combos.score(st)[0], '升级': sum(1 for c in case['deck'] if c.endswith('+')),
            '牌数': len(d), '每回合伤害': ev['dmg_per_turn'], '每回合格挡': ev['block_per_turn']}


def report(path):
    rs = [json.loads(l) for l in open(path)]
    print(f'\n== {os.path.basename(path)}：{len(rs)} 场（崩溃 {sum("crash" in r for r in rs)}）')
    g = collections.defaultdict(list)
    for r in rs:
        if 'crash' in r or not isinstance(r.get('case'), int): continue
        c = CASES[r['case']]
        g[(c['encounter'], c['relic_level'])].append((r, c))
    print('战斗 | 遗物档 | 场数 | 撑过 | 平均掉血（人类赢家） | 回合')
    for (enc, lv), xs in sorted(g.items()):
        surv = sum(1 for r, _ in xs if r.get('survived'))
        print(f"{ZH.get(enc, enc)} | {lv} | {len(xs)} | {surv}（{surv / len(xs):.0%}） | "
              f"{S.mean(r.get('dmg') or 0 for r, _ in xs):.0f}（{xs[0][1]['human_dmg']}） | {S.mean(r.get('rounds') or 0 for r, _ in xs):.1f}")
    tot = [x for xs in g.values() for x in xs]
    for lv in ('我们', '人类'):
        sub = [x for x in tot if x[1]['relic_level'] == lv]
        if sub: print(f'遗物 {lv} 档合计：撑过 {sum(1 for r, _ in sub if r.get("survived")) / len(sub):.0%}，平均掉血 {S.mean(r.get("dmg") or 0 for r, _ in sub):.1f}')
    # 什么样的牌组打得过（按牌组特征分组）
    win = [deck_feats(c) for r, c in tot if r.get('survived')]; lose = [deck_feats(c) for r, c in tot if not r.get('survived')]
    if win and lose:
        print('牌组特征（撑过的 vs 没撑过的）：')
        for k in win[0]:
            a = S.mean(float(x[k]) for x in win); b = S.mean(float(x[k]) for x in lose)
            print(f'  {k}：{a:.2f} vs {b:.2f}')
    return g


if __name__ == '__main__':
    for p in sys.argv[1:]: report(p)
