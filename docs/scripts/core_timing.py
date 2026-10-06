"""输出核心研究 · 第三步：什么时候拿到核心、拿到后补什么、见到核心牌拿不拿的后果。

1. 成型时间：第二幕 Boss 前有「消耗引擎」或「格挡转伤害」的局，核心在第几幕第几层凑齐；每张关键牌第一次进牌组的层数。
2. 拿牌行为（每次卡牌奖励三选一都是一次决策，不受「活得久拿得多」影响）：
   见到某张牌时的拿取率，按「牌组里有没有某个核心 / 引擎」分开，赢家 / 全部 / 高手。差值换成 logit（≈ 程序选牌模型的分数单位）。
3. 拿 vs 不拿的后果：见到这张牌时拿了 vs 没拿（选了别的或跳过），之后过第一幕 / 过第二幕 / 最终通关的差；
   按（幕、本幕前半 / 后半、进节点血量三档、牌组里有没有消耗引擎）分层后加权平均（Mantel-Haenszel 式权重）。
用法：CORE_CACHE=缓存路径 python3 core_timing.py
"""
import sys, os, math, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts, BASIC
from core_effects import load_experts
from cores import CORES, EXH_ENGINE, EXH_SRC, EXH_PAY, kinds

KEYCARDS = ['FEEL_NO_PAIN', 'DARK_EMBRACE', 'BURNING_PACT', 'TRUE_GRIT', 'SECOND_WIND', 'STOKE', 'FIEND_FIRE', 'HAVOC', 'BRAND', 'EVIL_EYE',
            'ASHEN_STRIKE', 'PACTS_END', 'HOWL_FROM_BEYOND', 'DRUM_OF_BATTLE', 'BODY_SLAM', 'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT',
            'BATTLE_TRANCE', 'OFFERING', 'BLOODLETTING', 'FORGOTTEN_RITUAL', 'SHRUG_IT_OFF', 'VICIOUS', 'DOMINATE', 'UPPERCUT', 'COLOSSUS',
            'PYRE', 'IMPERVIOUS', 'FLAME_BARRIER', 'STONE_ARMOR', 'CRIMSON_MANTLE', 'THRASH', 'CINDER', 'TREMBLE', 'TAUNT', 'ARMAMENTS',
            'DEMON_FORM', 'INFLAME', 'FIGHT_ME', 'WHIRLWIND', 'CONFLAGRATION', 'SWORD_BOOMERANG', 'TWIN_STRIKE', 'POMMEL_STRIKE', 'ANGER',
            'BREAKTHROUGH', 'RAMPAGE', 'PERFECTED_STRIKE', 'SETUP_STRIKE', 'HELLRAISER', 'BLUDGEON', 'UNRELENTING', 'STAMPEDE', 'INFERNAL_BLADE',
            'MOLTEN_FIST', 'CRUELTY', 'BULLY', 'DISMANTLE', 'RUPTURE', 'INFERNO', 'HEMOKINESIS', 'SPITE', 'IRON_WAVE', 'HEADBUTT', 'RAGE',
            'TEAR_ASUNDER', 'EXPECT_A_FIGHT', 'BLOOD_WALL', 'THUNDERCLAP', 'MANGLE', 'FEED', 'JUGGLING', 'AGGRESSION', 'PILLAGE', 'PRIMAL_FORCE', 'ONE_TWO_PUNCH', 'STOMP']

GOOD = lambda k: CORES['消耗引擎'][0](k) or CORES['格挡转伤害'][0](k)


def complete_floor(r, f):
    """核心在哪个节点凑齐：返回 (act, 本幕第几个节点, 全局层) 或 None"""
    pts = r['points']
    for j, p in enumerate(pts):
        if f(counts(p['deck'])):
            q = pts[j - 1] if j > 0 else p
            return q['act'], q['i'], q['floor']
    return None


def section1(runs, experts):
    print('# 1. 核心在什么时候凑齐（第二幕 Boss 前已有核心的局）\n')
    for cname in ('消耗引擎', '格挡转伤害'):
        f = CORES[cname][0]
        for lab, grp in (('赢家', [r for r in runs if r['win']]), ('输家', [r for r in runs if not r['win']]), ('高手', experts)):
            rs = [r for r in grp if r['c2'] is not None and f(counts(r['c2']))]
            cf = [complete_floor(r, f) for r in rs]
            cf = [c for c in cf if c]
            if not cf: continue
            b = collections.Counter()
            for a, i, fl in cf:
                b[f'第{a}幕{"前半" if i < 9 else "后半"}'] += 1
            n = len(cf)
            med = np.median([fl for _, _, fl in cf])
            print(f'- {cname}·{lab}（{n} 局，中位全局层 {med:.0f}）：' + '，'.join(f'{k} {v / n:.0%}' for k, v in sorted(b.items())))
        print()
    print('（参考：第一幕是全局第 1~17 层（第 1 层是先古、第 17 层是 Boss），第二幕第 18~33 层（Boss 在 33），第三幕从 34 层起。「前半」= 本幕第 0~8 个节点）\n')

    print('## 关键牌第一次进牌组的全局层（只看第二幕 Boss 前有消耗或格挡核心的赢家；括号是有这张牌的局数）\n')
    rs = [r for r in runs if r['win'] and r['c2'] is not None and GOOD(counts(r['c2']))]
    rows = []
    for c in KEYCARDS[:24]:
        fl = [r['first'][c] for r in rs if c in r['first'] and r['first'][c] <= r['points'][r['c2_idx']]['floor']]
        if len(fl) < 20: continue
        a1 = np.mean([x <= 17 for x in fl])
        rows.append((c, np.median(fl), a1, len(fl)))
    print('| 牌 | 中位层 | 第一幕就拿到的比例 | 局数 |\n|---|---|---|---|')
    for c, m, a1, n in sorted(rows, key=lambda x: x[1]):
        print(f'| {name(c)} | {m:.0f} | {a1:.0%} | {n} |')
    print()


def decisions(runs):
    """每次卡牌奖励三选一：(run, point, offered, picked)"""
    for r in runs:
        for p in r['points']:
            for off, pk in p['picks']:
                yield r, p, off, pk


def logit(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def section2(runs, experts):
    print('# 2. 见到这张牌拿不拿：牌组里有没有核心 / 引擎时的拿取率（赢家的决策；括号是见到的次数）\n')
    print('「Δlogit」= logit(有) − logit(没有)，≈ 程序选牌模型分数要加 / 减多少。只列两边都见过 ≥40 次的。\n')
    conds = [
        ('有消耗引擎（无惧疼痛/黑暗之拥 + 主动消耗 ≥2）', CORES['消耗引擎'][0]),
        ('有无惧疼痛或黑暗之拥', lambda k: kinds(k, EXH_ENGINE) >= 1),
        ('主动消耗牌 ≥2 种', lambda k: kinds(k, EXH_SRC) >= 2),
        ('有格挡转伤害', CORES['格挡转伤害'][0]),
        ('有力量多段', CORES['力量多段'][0]),
        ('有自伤', CORES['自伤'][0]),
        ('有易伤', CORES['易伤'][0]),
    ]
    for who, grp in (('赢家', [r for r in runs if r['win']]), ('全部玩家', runs)):
        D = [(counts(p['deck']), p['act'], off, pk) for r, p, off, pk in decisions(grp)]
        for lab, f in conds:
            st = collections.defaultdict(lambda: [0, 0, 0, 0])      # card → [见到(有), 拿(有), 见到(无), 拿(无)]
            for k, act, off, pk in D:
                if act > 2: continue                                # 第一、二幕的决策
                h = bool(f(k))
                for c in set(off):
                    if c in BASIC: continue
                    s = st[c]
                    if h: s[0] += 1; s[1] += (pk == c)
                    else: s[2] += 1; s[3] += (pk == c)
            rows = []
            for c, (a, b, cc, d) in st.items():
                if a >= 40 and cc >= 40:
                    pa, pb = b / a, d / cc
                    rows.append((c, pa, pb, logit(pa) - logit(pb), a, cc))
            rows.sort(key=lambda x: -x[3])
            print(f'## {who}·{lab}（第一、二幕）')
            print('- 更爱拿：' + '，'.join(f'{name(c)} {pa:.0%}/{pb:.0%}（{dl:+.1f}，{a}/{cc}）' for c, pa, pb, dl, a, cc in rows[:14]))
            print('- 更不爱拿：' + '，'.join(f'{name(c)} {pa:.0%}/{pb:.0%}（{dl:+.1f}，{a}/{cc}）' for c, pa, pb, dl, a, cc in rows[::-1][:12]))
            print()
        if who == '赢家':
            continue

    print('## 拿取率：高手 / 赢家 / 输家（第一幕、第二幕分开；见到 ≥30 次）\n')
    ex = [(p['act'], off, pk) for r, p, off, pk in decisions(experts)]
    wi = [(p['act'], off, pk) for r, p, off, pk in decisions([r for r in runs if r['win']])]
    lo = [(p['act'], off, pk) for r, p, off, pk in decisions([r for r in runs if not r['win']])]

    def rate(D, act):
        st = collections.defaultdict(lambda: [0, 0])
        for a, off, pk in D:
            if a != act: continue
            for c in set(off):
                st[c][0] += 1; st[c][1] += (pk == c)
        return st
    for act in (1, 2):
        E, W, L = rate(ex, act), rate(wi, act), rate(lo, act)
        print(f'### 第{act}幕\n\n| 牌 | 高手 | 赢家 | 输家 | 赢家−输家（logit） |\n|---|---|---|---|---|')
        rows = []
        for c in KEYCARDS:
            w, l = W.get(c, [0, 0]), L.get(c, [0, 0])
            if w[0] < 30 or l[0] < 30: continue
            e = E.get(c, [0, 0])
            pe = f'{e[1] / e[0]:.0%}（{e[0]}）' if e[0] >= 10 else '—'
            rows.append((c, pe, w[1] / w[0], w[0], l[1] / l[0], l[0]))
        for c, pe, pw, nw, pl, nl in sorted(rows, key=lambda x: -(logit(x[2]) - logit(x[4]))):
            print(f'| {name(c)} | {pe} | {pw:.0%}（{nw}） | {pl:.0%}（{nl}） | {logit(pw) - logit(pl):+.2f} |')
        print()


def section3(runs):
    print('# 3. 见到这张牌时拿了 vs 没拿：之后的结果（分层加权差，百分点）\n')
    print('分层：幕 × 本幕前半/后半 × 进节点血量（<50% / 50~80% / ≥80%）× 牌组里有没有消耗引擎。正数 = 拿了更好。是关联，不是严格因果。\n')
    out = collections.defaultdict(lambda: collections.defaultdict(lambda: [[], []]))     # (card, act) → stratum → [picked outcomes, not]
    for r, p, off, pk in decisions(runs):
        if p['act'] > 2: continue
        mx = p['maxhp'] or 80; hp = (p['hp_in'] if p['hp_in'] is not None else mx) / mx
        hb = 0 if hp < 0.5 else 1 if hp < 0.8 else 2
        k = counts(p['deck'])
        stratum = (p['i'] >= 9, hb, bool(CORES['消耗引擎'][0](k)))
        y = (r['acts'] >= 2, r['acts'] >= 3, r['win'])
        for c in set(off):
            if c in BASIC: continue
            out[(c, p['act'])][stratum][0 if pk == c else 1].append(y)

    def mh(strata, j):
        num = den = 0.0; npk = 0
        for a, b in strata.values():
            if not a or not b: continue
            w = len(a) * len(b) / (len(a) + len(b))
            num += w * (np.mean([x[j] for x in a]) - np.mean([x[j] for x in b])); den += w; npk += len(a)
        return (num / den * 100 if den else float('nan')), npk
    for act in (1, 2):
        rows = []
        for c in KEYCARDS:
            s = out.get((c, act))
            if not s: continue
            n_pick = sum(len(a) for a, _ in s.values()); n_no = sum(len(b) for _, b in s.values())
            if n_pick < 40 or n_no < 40: continue
            r = [mh(s, j)[0] for j in range(3)]
            rows.append((c, r, n_pick, n_no))
        hdr = '过第一幕 | 过第二幕 | 最终通关' if act == 1 else '— | 过第二幕 | 最终通关'
        print(f'## 第{act}幕见到时\n\n| 牌 | 拿了 / 没拿（次） | {hdr} |\n|---|---|---|---|---|')
        for c, rr, a, b in sorted(rows, key=lambda x: -x[1][2]):
            f0 = f'{rr[0]:+.1f}' if act == 1 else '—'
            print(f'| {name(c)} | {a} / {b} | {f0} | {rr[1]:+.1f} | {rr[2]:+.1f} |')
        print()


def main():
    runs = load_all()
    experts = load_experts()
    section1(runs, experts)
    section2(runs, experts)
    section3(runs)


if __name__ == '__main__':
    main()
