"""输出核心研究 · 按阶段细分「见到这张牌时拿了 vs 没拿」：第一幕前半（第 1~9 层）/ 第一幕后半（第 10~17 层，含第一幕 Boss 奖励）/ 第二幕前半 / 第二幕后半。
同时按「这时牌组里有没有消耗或格挡核心」分开。用来定「第几层前 / 后」「有 / 没有核心」时规则的加分。
分层加权同 core_timing.py 第 3 节（层内再按进节点血量三档分层）。结果：过本幕 / 过第二幕 / 最终通关的差（百分点），正数 = 拿了更好。
用法：CORE_CACHE=缓存路径 python3 core_phase.py
"""
import sys, os, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts, BASIC
from core_timing import decisions, KEYCARDS
from cores import CORES

GOODF = lambda k: bool(CORES['消耗引擎'][0](k) or CORES['格挡转伤害'][0](k))
PHASES = [('第一幕前半', 1, False), ('第一幕后半', 1, True), ('第二幕前半', 2, False), ('第二幕后半', 2, True)]


def main():
    runs = load_all()
    out = collections.defaultdict(lambda: collections.defaultdict(lambda: [[], []]))
    for r, p, off, pk in decisions(runs):
        if p['act'] > 2: continue
        mx = p['maxhp'] or 80; hp = (p['hp_in'] if p['hp_in'] is not None else mx) / mx
        hb = 0 if hp < 0.5 else 1 if hp < 0.8 else 2
        core = GOODF(counts(p['deck']))
        late = p['i'] >= 9
        y = (r['acts'] >= p['act'] + 1, r['acts'] >= 3, r['win'])
        for c in set(off):
            if c in BASIC: continue
            out[(c, p['act'], late, core)][hb][0 if pk == c else 1].append(y)

    def mh(strata, j):
        num = den = 0.0
        for a, b in strata.values():
            if not a or not b: continue
            w = len(a) * len(b) / (len(a) + len(b))
            num += w * (np.mean([x[j] for x in a]) - np.mean([x[j] for x in b])); den += w
        return num / den * 100 if den else float('nan')

    for core in (False, True):
        print(f'# 牌组里{"已有" if core else "还没有"}消耗或格挡核心时\n')
        print('每格：过本幕 / 过第二幕 / 最终通关（拿了的次数）。拿了 / 没拿都要 ≥30 次才列。\n')
        print('| 牌 | ' + ' | '.join(p[0] for p in PHASES) + ' |\n|---|' + '---|' * len(PHASES))
        for c in KEYCARDS:
            cells = []; ok = False
            for lab, act, late in PHASES:
                s = out.get((c, act, late, core))
                if not s: cells.append('—'); continue
                a = sum(len(x) for x, _ in s.values()); b = sum(len(y) for _, y in s.values())
                if a < 30 or b < 30: cells.append('—'); continue
                ok = True
                v = [mh(s, j) for j in range(3)]
                cells.append(f'{v[0]:+.0f} / {v[1]:+.0f} / {v[2]:+.0f}（{a}）')
            if ok: print(f'| {name(c)} | ' + ' | '.join(cells) + ' |')
        print()


if __name__ == '__main__':
    main()
