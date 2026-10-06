"""输出核心研究 · 「这张牌能凑齐核心」时，人类拿不拿、拿了之后怎样。用来定「凑齐核心」这条规则的加分。

对每次卡牌奖励里的每张牌：标记 completes = 牌组现在没有消耗/格挡核心，加上这张牌就有了。
1. 拿取率：同一张牌，能凑齐时 vs 不能凑齐时（牌组也没有核心），赢家 / 全部；按牌加权合并成一个 logit 差。
2. 后果：能凑齐时拿了 vs 没拿，之后过第二幕 / 最终通关（按牌 × 幕 × 进节点血量分层加权）。
用法：CORE_CACHE=缓存路径 python3 core_complete.py
"""
import sys, os, math, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts, BASIC
from core_timing import decisions
from cores import CORES

GOODF = lambda k: bool(CORES['消耗引擎'][0](k) or CORES['格挡转伤害'][0](k))


def lg(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def main():
    runs = load_all()
    for who, grp in (('赢家', [r for r in runs if r['win']]), ('全部', runs)):
        st = collections.defaultdict(lambda: [0, 0, 0, 0])     # card → 见到(能凑齐) 拿 见到(不能) 拿
        for r, p, off, pk in decisions(grp):
            if p['act'] > 2: continue
            k = counts(p['deck'])
            if GOODF(k): continue
            for c in set(off):
                if c in BASIC: continue
                k2 = k.copy(); k2[c] += 1
                s = st[c]
                if GOODF(k2): s[0] += 1; s[1] += (pk == c)
                else: s[2] += 1; s[3] += (pk == c)
        rows = [(c, v) for c, v in st.items() if v[0] >= 15 and v[2] >= 30]
        num = den = 0.0
        print(f'## {who}：能凑齐核心时的拿取率 vs 同一张牌不能凑齐时（第一、二幕，牌组还没有核心）\n')
        print('| 牌 | 能凑齐 | 不能凑齐 | Δlogit |\n|---|---|---|---|')
        for c, (a, b, cc, d) in sorted(rows, key=lambda x: -x[1][0]):
            pa, pb = b / a, d / cc
            w = a * cc / (a + cc)
            num += w * (lg(pa) - lg(pb)); den += w
            print(f'| {name(c)} | {pa:.0%}（{a}） | {pb:.0%}（{cc}） | {lg(pa) - lg(pb):+.2f} |')
        print(f'\n加权平均 Δlogit = {num / den:+.2f}\n')

    # 后果
    out = collections.defaultdict(lambda: [[], []])
    for r, p, off, pk in decisions(runs):
        if p['act'] > 2: continue
        k = counts(p['deck'])
        if GOODF(k): continue
        mx = p['maxhp'] or 80; hp = (p['hp_in'] if p['hp_in'] is not None else mx) / mx
        hb = 0 if hp < 0.5 else 1 if hp < 0.8 else 2
        comp = [c for c in set(off) if c not in BASIC and GOODF(k + collections.Counter({c: 1}))]
        if not comp: continue
        took = pk in comp
        out[(p['act'], p['i'] >= 9, hb)][0 if took else 1].append((r['acts'] >= 3, r['win']))
    print('## 奖励里有能凑齐核心的牌时：拿了（任意一张能凑齐的）vs 没拿\n')
    print('| 阶段 | 拿了（次） | 没拿（次） | 过第二幕 拿/没拿 | 最终通关 拿/没拿 |\n|---|---|---|---|---|')
    agg = {0: [0, 0], 1: [0, 0]}
    for key in sorted(out):
        a, b = out[key]
        if len(a) < 20 or len(b) < 20: continue
        act, late, hb = key
        lab = f'第{act}幕{"后半" if late else "前半"}·血{["<50%", "50~80%", "≥80%"][hb]}'
        pa = [np.mean([x[j] for x in a]) for j in range(2)]; pb = [np.mean([x[j] for x in b]) for j in range(2)]
        w = len(a) * len(b) / (len(a) + len(b))
        for j in range(2): agg[j][0] += w * (pa[j] - pb[j]); agg[j][1] += w
        print(f'| {lab} | {len(a)} | {len(b)} | {pa[0]:.0%} / {pb[0]:.0%} | {pa[1]:.0%} / {pb[1]:.0%} |')
    print(f'\n分层加权差：过第二幕 {agg[0][0] / agg[0][1] * 100:+.1f}，最终通关 {agg[1][0] / agg[1][1] * 100:+.1f} 个百分点\n')


if __name__ == '__main__':
    main()
