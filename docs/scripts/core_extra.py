"""输出核心研究 · 补充：核心牌从哪来、组合胜率、「到某一层还没核心」之后怎样。

1. 关键牌第一次进牌组的来源（第一幕 Boss 奖励 / 精英 / 普通战 / 商店 / 问号房等），赢家里有核心的局。
2. 组合胜率（第二幕 Boss 前的牌组）：过第二幕 Boss、最终通关，原始值 + 调整值 + 局数。
3. 第一幕结束时有几个核心零件 → 第二幕 Boss 前凑齐核心的概率、过第二幕率、最终通关率。
4. 分第二幕 Boss：哪些牌组特征和过这场 Boss 有关。
用法：CORE_CACHE=缓存路径 python3 core_extra.py
"""
import sys, os, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts
from core_effects import ctrl, adj_effect
from cores import CORES, EXH_ENGINE, EXH_SRC, EXH_PAY, kinds

GOODF = lambda k: bool(CORES['消耗引擎'][0](k) or CORES['格挡转伤害'][0](k))
PARTS = EXH_ENGINE | EXH_SRC | {'BODY_SLAM', 'JUGGERNAUT', 'BARRICADE', 'UNMOVABLE'}


def section1(runs):
    print('# 1. 关键牌第一次进牌组的来源（赢家、第二幕 Boss 前有消耗或格挡核心）\n')
    rs = [r for r in runs if r['win'] and r['c2'] is not None and GOODF(counts(r['c2']))]
    keys = ['FEEL_NO_PAIN', 'DARK_EMBRACE', 'STOKE', 'BURNING_PACT', 'SECOND_WIND', 'TRUE_GRIT', 'FIEND_FIRE', 'HAVOC', 'BODY_SLAM', 'BARRICADE',
            'UNMOVABLE', 'JUGGERNAUT', 'ASHEN_STRIKE', 'OFFERING', 'BATTLE_TRANCE']
    print('| 牌 | 局数 | 第一幕Boss | 第一幕精英 | 第一幕普通/其他 | 第二幕精英 | 第二幕普通/其他 | 商店 |\n|---|---|---|---|---|---|---|---|')
    for c in keys:
        src = collections.Counter(); n = 0
        for r in rs:
            fl = r['first'].get(c)
            if fl is None or fl > r['points'][r['c2_idx']]['floor']: continue
            p = r['points'][fl - 1]
            n += 1
            if p['type'] == 'shop': src['商店'] += 1
            elif p['act'] == 1 and p['type'] == 'boss': src['1boss'] += 1
            elif p['type'] == 'elite': src[f'{p["act"]}elite'] += 1
            else: src[f'{p["act"]}other'] += 1
        if n < 20: continue
        f = lambda k: f'{src[k] / n:.0%}'
        print(f'| {name(c)} | {n} | {f("1boss")} | {f("1elite")} | {f("1other")} | {f("2elite")} | {f("2other")} | {f("商店")} |')
    print()


def section2(runs):
    print('# 2. 组合胜率（第二幕 Boss 前的牌组）\n')
    rs = [r for r in runs if r['c2'] is not None]
    K = [counts(r['c2']) for r in rs]
    y_pass = np.array([1.0 if r['acts'] >= 3 else 0.0 for r in rs]); y_win = np.array([1.0 if r['win'] else 0.0 for r in rs])
    C = np.array([ctrl(r, r['c2_idx'], True) for r in rs], float)
    bosses = sorted({r['points'][r['c2_idx']]['enc'] for r in rs})
    extra = np.array([[1.0 if r['points'][r['c2_idx']]['enc'] == b else 0.0 for b in bosses[1:]] for r in rs])
    has = lambda k, c: k.get(c, 0) > 0
    combos = [
        ('无惧疼痛，没有主动消耗牌', lambda k: has(k, 'FEEL_NO_PAIN') and kinds(k, EXH_SRC) == 0),
        ('无惧疼痛 + 主动消耗 1 种', lambda k: has(k, 'FEEL_NO_PAIN') and kinds(k, EXH_SRC) == 1),
        ('无惧疼痛 + 主动消耗 ≥2 种', lambda k: has(k, 'FEEL_NO_PAIN') and kinds(k, EXH_SRC) >= 2),
        ('无惧疼痛 + 黑暗之拥', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'DARK_EMBRACE')),
        ('黑暗之拥 + 主动消耗 ≥2 种（无无惧疼痛）', lambda k: has(k, 'DARK_EMBRACE') and not has(k, 'FEEL_NO_PAIN') and kinds(k, EXH_SRC) >= 2),
        ('主动消耗 ≥2 种，没有引擎', lambda k: kinds(k, EXH_ENGINE) == 0 and kinds(k, EXH_SRC) >= 2),
        ('无惧疼痛 + 燃烧契约', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'BURNING_PACT')),
        ('无惧疼痛 + 重振精神', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'SECOND_WIND')),
        ('无惧疼痛 + 添柴', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'STOKE')),
        ('无惧疼痛 + 坚毅', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'TRUE_GRIT')),
        ('无惧疼痛 + 势不可当', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'JUGGERNAUT')),
        ('无惧疼痛 + 全身撞击', lambda k: has(k, 'FEEL_NO_PAIN') and has(k, 'BODY_SLAM')),
        ('消耗引擎 + 灰烬打击', lambda k: CORES['消耗引擎'][0](k) and has(k, 'ASHEN_STRIKE')),
        ('消耗引擎 + 恶魔之焰', lambda k: CORES['消耗引擎'][0](k) and has(k, 'FIEND_FIRE')),
        ('全身撞击，无壁垒/坚定不移/势不可当/无惧疼痛', lambda k: has(k, 'BODY_SLAM') and kinds(k, {'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT', 'FEEL_NO_PAIN'}) == 0),
        ('全身撞击 + 壁垒', lambda k: has(k, 'BODY_SLAM') and has(k, 'BARRICADE')),
        ('全身撞击 + 坚定不移', lambda k: has(k, 'BODY_SLAM') and has(k, 'UNMOVABLE')),
        ('势不可当，无格挡引擎', lambda k: has(k, 'JUGGERNAUT') and kinds(k, {'FEEL_NO_PAIN', 'BARRICADE', 'UNMOVABLE', 'STONE_ARMOR', 'RAGE', 'CRIMSON_MANTLE'}) == 0),
        ('坚定不移（任意）', lambda k: has(k, 'UNMOVABLE')),
        ('壁垒，无全身撞击', lambda k: has(k, 'BARRICADE') and not has(k, 'BODY_SLAM')),
        ('凶恶 + 易伤来源 ≥2 种', lambda k: has(k, 'VICIOUS') and kinds(k, {'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}) >= 2),
        ('恶魔形态', lambda k: has(k, 'DEMON_FORM')),
        ('狱火 + 撕裂', lambda k: has(k, 'INFERNO') and has(k, 'RUPTURE')),
        ('完美打击 + 打击标签 ≥7', CORES['打击'][0]),
        ('祭品 / 战斗专注 / 放血 ≥2 种（周转）', lambda k: kinds(k, {'OFFERING', 'BATTLE_TRANCE', 'BLOODLETTING', 'FORGOTTEN_RITUAL', 'PYRE'}) >= 2),
    ]
    print('| 组合 | 局数 | 过第二幕 Boss 有 / 无 | 调整 | 最终通关 有 / 无 | 调整 |\n|---|---|---|---|---|---|')
    for lab, f in combos:
        x = np.array([1.0 if f(k) else 0.0 for k in K]); a = x == 1
        if a.sum() < 30: print(f'| {lab} | {int(a.sum())} | 样本不够 | | | |'); continue
        dp, zp = adj_effect(x, y_pass, C, extra); dw, zw = adj_effect(x, y_win, C, extra)
        print(f'| {lab} | {int(a.sum())} | {y_pass[a].mean():.0%} / {y_pass[~a].mean():.0%} | {dp:+.1f}（z {zp:+.1f}） | {y_win[a].mean():.0%} / {y_win[~a].mean():.0%} | {dw:+.1f}（z {zw:+.1f}） |')
    print()


def section3(runs):
    print('# 3. 第一幕结束时的零件数 → 之后\n')
    print('零件 = 无惧疼痛、黑暗之拥、腐化、主动消耗牌（9 种）、全身撞击、势不可当、壁垒、坚定不移，按种类去重。\n')
    rs = [r for r in runs if r['c1'] is not None]
    g = collections.defaultdict(list)
    for r in rs:
        k1 = counts(r['c1'])
        if GOODF(k1): key = '已有核心'
        else: key = f'{min(kinds(k1, PARTS), 3)}{"+" if kinds(k1, PARTS) >= 3 else ""} 个零件'
        got = r['c2'] is not None and GOODF(counts(r['c2']))
        g[key].append((r['c2'] is not None, got, r['acts'] >= 3, r['win']))
    print('| 第一幕结束时 | 局数 | 打到第二幕 Boss | 打到的局里凑齐核心 | 过第二幕 | 最终通关 |\n|---|---|---|---|---|---|')
    for k in sorted(g):
        v = g[k]; reached = [x for x in v if x[0]]
        print(f'| {k} | {len(v)} | {np.mean([x[0] for x in v]):.0%} | {np.mean([x[1] for x in reached]) if reached else float("nan"):.0%} | {np.mean([x[2] for x in v]):.0%} | {np.mean([x[3] for x in v]):.0%} |')
    print()
    # 第二幕中段（本幕第 9 个节点）还没有核心
    print('## 第二幕第 9 个节点时还没有核心的局：之后还能不能凑齐\n')
    a = collections.Counter(); w = collections.defaultdict(list)
    for r in runs:
        if r['c2'] is None: continue
        mid = [p for p in r['points'] if p['act'] == 2 and p['i'] == 9]
        if not mid: continue
        k = counts(mid[0]['deck'])
        if GOODF(k): continue
        later = GOODF(counts(r['c2']))
        a[later] += 1; w[later].append(r['win'])
    n = sum(a.values())
    print(f'- {n} 局，其中到 Boss 前凑齐的 {a[True] / n:.0%}；凑齐的最终通关 {np.mean(w[True]):.0%}，没凑齐的 {np.mean(w[False]):.0%}\n')


def section4(runs):
    print('# 4. 分 Boss：第二幕 Boss 前的牌组特征 → 过这场 Boss 的概率（原始 有 / 无（局数），调整后百分点）\n')
    feats = [
        ('消耗或格挡核心', GOODF),
        ('消耗引擎', CORES['消耗引擎'][0]),
        ('格挡转伤害', CORES['格挡转伤害'][0]),
        ('无惧疼痛', lambda k: k.get('FEEL_NO_PAIN', 0) > 0),
        ('坚定不移', lambda k: k.get('UNMOVABLE', 0) > 0),
        ('周转 ≥2 种（祭品/战斗专注/放血/被遗忘的仪式/薪火之源）', lambda k: kinds(k, {'OFFERING', 'BATTLE_TRANCE', 'BLOODLETTING', 'FORGOTTEN_RITUAL', 'PYRE'}) >= 2),
        ('凶恶 + 易伤来源 ≥2', lambda k: k.get('VICIOUS', 0) > 0 and kinds(k, {'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}) >= 2),
        ('力量多段', CORES['力量多段'][0]),
        ('自伤', CORES['自伤'][0]),
        ('打击', CORES['打击'][0]),
        ('恶魔形态', lambda k: k.get('DEMON_FORM', 0) > 0),
        ('基础打击 ≥4 张', lambda k: k.get('STRIKE_IRONCLAD', 0) >= 4),
    ]
    rs = [r for r in runs if r['c2'] is not None]
    for boss in sorted({r['points'][r['c2_idx']]['enc'] for r in rs}):
        B = [r for r in rs if r['points'][r['c2_idx']]['enc'] == boss]
        K = [counts(r['c2']) for r in B]
        y = np.array([1.0 if r['acts'] >= 3 else 0.0 for r in B])
        C = np.array([ctrl(r, r['c2_idx'], True) for r in B], float)
        print(f'## {boss}：{len(B)} 局，过关 {y.mean():.0%}\n')
        out = []
        for lab, f in feats:
            x = np.array([1.0 if f(k) else 0.0 for k in K]); a = x == 1
            if a.sum() < 25 or (~a).sum() < 25: continue
            d, z = adj_effect(x, y, C)
            out.append(f'{lab} {y[a].mean():.0%}/{y[~a].mean():.0%}（{int(a.sum())}）{d:+.1f}')
        print('- ' + '；'.join(out) + '\n')


def main():
    runs = load_all()
    section1(runs)
    section2(runs)
    section3(runs)
    section4(runs)


if __name__ == '__main__':
    main()
