"""输出核心研究 · 第二步：每种核心有多少用（尽量排除幸存者偏差）。

A. 检查点比较：第一幕结束（c1，所有进了第二幕的局）和第二幕 Boss 前（c2）。
   c1 的结果用「过第二幕 Boss」（acts ≥ 3）——所有 c1 的局都进了第二幕，起点一致；c2 的结果用「过这场 Boss」和「最终通关」。
   调整 = 逻辑回归控制 精英数、遗物数、升级数、牌组张数、血量比例（c2 再加 Boss 是谁），按样本均值处换算成百分点。
B. 第二幕每场战斗掉血（主要症状）：取进这场战斗时的牌组，线性回归，控制遭遇是谁（固定效应）、第几层、遗物、升级、张数、最大生命。
C. 剂量：消耗零件张数（种类）→ 过第二幕率、第二幕普通战掉血。
D. 兑现牌有 / 没有引擎时的价值。
E. 高手（5 人 193 局，胜率 76%）的核心占比，对照普通玩家。
用法：CORE_CACHE=缓存路径 python3 core_effects.py
"""
import sys, os, gzip, json, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, parse, name, ename, counts, ROOT, BASIC
from core_discover import logit_fit
from cores import CORES, which, has_good_core, EXH_ENGINE, EXH_SRC, EXH_PAY, kinds

GOOD = ('消耗引擎', '格挡转伤害')


def ctrl(r, idx, with_boss=False):
    p = r['points'][idx]
    mx = p['maxhp'] or 80
    hp = (p['hp_in'] if p['hp_in'] is not None else mx) / mx
    return [r['elites_a1'] + (r['elites_a2'] if with_boss else 0), p['relics'], p['ups'], len(p['deck']), hp]


def adj_effect(x, y, C, extra=None):
    Cz = (C - C.mean(0)) / (C.std(0) + 1e-9)
    cols = [np.ones(len(y)), x, Cz] + ([extra] if extra is not None else [])
    X = np.column_stack(cols)
    b, se = logit_fit(X, y)
    p0 = y.mean()
    return b[1] * p0 * (1 - p0) * 100, b[1] / se[1]


def section_a(runs, experts):
    print('# A. 检查点：有没有核心\n')
    for cp, lab in (('c1', '第一幕结束（进第二幕第一个节点时）'), ('c2', '第二幕 Boss 前')):
        rs = [r for r in runs if r[cp] is not None]
        idx = cp + '_idx'
        y_pass = np.array([1.0 if r['acts'] >= 3 else 0.0 for r in rs])
        y_win = np.array([1.0 if r['win'] else 0.0 for r in rs])
        C = np.array([ctrl(r, r[idx], cp == 'c2') for r in rs], float)
        extra = None
        if cp == 'c2':
            bosses = sorted({r['points'][r[idx]]['enc'] for r in rs})
            extra = np.array([[1.0 if r['points'][r[idx]]['enc'] == b else 0.0 for b in bosses[1:]] for r in rs])
        K = [counts(r[cp]) for r in rs]
        cores = [set(which(k)) for k in K]
        wins = [r['win'] for r in rs]
        ex_c = [set(which(counts(r[cp]))) for r in experts if r[cp] is not None]
        print(f'## {lab}：{len(rs)} 局（过第二幕 {y_pass.mean():.0%}，最终通关 {y_win.mean():.0%}）；高手 {len(ex_c)} 局\n')
        print('| 核心 | 局数 | 占比 赢家 / 输家 / 高手 | 过第二幕 有 / 无 | 调整（z） | 最终通关 有 / 无 | 调整（z） |\n|---|---|---|---|---|---|---|')
        groups = list(CORES) + ['消耗引擎或格挡转伤害', '只有其他核心（无前两种）', '没有任何核心']
        for g in groups:
            if g in CORES: f = lambda s: g in s
            elif g == '消耗引擎或格挡转伤害': f = lambda s: bool(s & set(GOOD))
            elif g.startswith('只有其他'): f = lambda s: bool(s) and not (s & set(GOOD))
            else: f = lambda s: not s
            x = np.array([1.0 if f(s) else 0.0 for s in cores])
            a = x == 1
            pw = np.mean([f(s) for s, w in zip(cores, wins) if w]); pl = np.mean([f(s) for s, w in zip(cores, wins) if not w])
            pe = np.mean([f(s) for s in ex_c]) if ex_c else float('nan')
            dp, zp = adj_effect(x, y_pass, C, extra)
            dw, zw = adj_effect(x, y_win, C, extra)
            print(f'| {g} | {int(a.sum())} | {pw:.0%} / {pl:.0%} / {pe:.0%} | {y_pass[a].mean():.0%} / {y_pass[~a].mean():.0%} | {dp:+.1f}（{zp:+.1f}） '
                  f'| {y_win[a].mean():.0%} / {y_win[~a].mean():.0%} | {dw:+.1f}（{zw:+.1f}） |')
        print()


def fights(runs, act, rtype):
    """(run, point) 列表：第 act 幕某类房间的战斗"""
    out = []
    for r in runs:
        for p in r['points']:
            if p['act'] == act and p['type'] == rtype and p['enc'] and not p['enc'].startswith('EVENT'):
                out.append((r, p))
    return out


def ols(y, X):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b
    s2 = res @ res / (len(y) - X.shape[1])
    cov = s2 * np.linalg.pinv(X.T @ X)
    return b, np.sqrt(np.diag(cov))


def section_b(runs):
    print('# B. 第二幕每场战斗掉血 vs 进这场战斗时的牌组有没有核心\n')
    print('回归：掉血 ~ 各核心（同时放进去）+ 遭遇固定效应 + 本幕第几个节点 + 遗物数 + 升级数 + 张数 + 最大生命。系数 = 有这个核心时每场多掉 / 少掉几血。\n')
    for act in (1, 2, 3):
        for rtype in ('monster', 'elite', 'boss'):
            fs = fights(runs, act, rtype)
            if len(fs) < 300: continue
            encs = sorted({p['enc'] for _, p in fs})
            y = np.array([float(p['dmg']) for _, p in fs])
            K = [counts(p['deck']) for _, p in fs]
            names = list(CORES)
            D = np.array([[1.0 if CORES[n][0](k) else 0.0 for n in names] for k in K])
            ctl = np.array([[p['i'], p['relics'], p['ups'], len(p['deck']), p['maxhp'] or 80] for _, p in fs], float)
            E = np.array([[1.0 if p['enc'] == e else 0.0 for e in encs[1:]] for _, p in fs])
            X = np.column_stack([np.ones(len(y)), D, ctl, E])
            b, se = ols(y, X)
            won = np.array([bool(r['win']) for r, _ in fs])
            good = np.array([bool(has_good_core(k)) for k in K])
            anyc = D.sum(1) > 0
            X2 = np.column_stack([np.ones(len(y)), good.astype(float), ctl, E])
            b2, se2 = ols(y, X2)
            lab = f'第{act}幕 {dict(monster="普通战", elite="精英", boss="Boss")[rtype]}'
            print(f'## {lab}：{len(fs)} 场，平均掉血 {y.mean():.1f}（最终赢家 {y[won].mean():.1f} / 输家 {y[~won].mean():.1f}）')
            print(f'- 原始均值：有消耗或格挡核心 {y[good].mean():.1f}（{good.sum()} 场）/ 没有 {y[~good].mean():.1f}；有任何核心 {y[anyc].mean():.1f} / 没有任何核心 {y[~anyc].mean():.1f}（{(~anyc).sum()} 场）')
            print(f'- 调整后：有消耗或格挡核心 {b2[1]:+.1f} 血/场（±{1.96 * se2[1]:.1f}）')
            print('- 各核心（调整后，血/场）：' + '，'.join(f'{n} {b[1 + i]:+.1f}（±{1.96 * se[1 + i]:.1f}，{int(D[:, i].sum())} 场）' for i, n in enumerate(names)))
            print()


def section_c(runs):
    print('# C. 剂量：消耗零件种类数（引擎 + 主动消耗 + 兑现，去重）\n')
    parts = EXH_ENGINE | EXH_SRC | EXH_PAY | {'BODY_SLAM', 'JUGGERNAUT', 'BARRICADE', 'UNMOVABLE'}
    rs = [r for r in runs if r['c1'] is not None]
    g = collections.defaultdict(list)
    for r in rs:
        g[min(kinds(counts(r['c1']), parts), 5)].append(r['acts'] >= 3)
    print('第一幕结束时 → 过第二幕率：' + '，'.join(f'{k}{"+" if k == 5 else ""} 种 {np.mean(v):.0%}（{len(v)}）' for k, v in sorted(g.items())))
    g2 = collections.defaultdict(list)
    for r, p in fights(runs, 2, 'monster'):
        g2[min(kinds(counts(p['deck']), parts), 6)].append(p['dmg'])
    print('第二幕普通战（进场牌组）→ 每场掉血：' + '，'.join(f'{k}{"+" if k == 6 else ""} 种 {np.mean(v):.1f}（{len(v)}）' for k, v in sorted(g2.items())))
    rs2 = [r for r in runs if r['c2'] is not None]
    g3 = collections.defaultdict(list)
    for r in rs2:
        g3[min(kinds(counts(r['c2']), parts), 6)].append(r['win'])
    print('第二幕 Boss 前 → 最终通关：' + '，'.join(f'{k}{"+" if k == 6 else ""} 种 {np.mean(v):.0%}（{len(v)}）' for k, v in sorted(g3.items())))
    print()


def section_d(runs):
    print('# D. 兑现牌：有引擎 vs 没引擎（第二幕 Boss 前的牌组，最终通关；括号是局数）\n')
    rs = [r for r in runs if r['c2'] is not None]
    K = [(counts(r['c2']), r['win']) for r in rs]
    base = np.mean([w for _, w in K])
    tests = [
        ('ASHEN_STRIKE', '消耗引擎', lambda k: CORES['消耗引擎'][0](k)),
        ('PACTS_END', '消耗引擎', lambda k: CORES['消耗引擎'][0](k)),
        ('HOWL_FROM_BEYOND', '主动消耗 ≥2 种', lambda k: kinds(k, EXH_SRC) >= 2),
        ('FIEND_FIRE', '无惧疼痛/黑暗之拥', lambda k: kinds(k, EXH_ENGINE) >= 1),
        ('EVIL_EYE', '主动消耗 ≥2 种', lambda k: kinds(k, EXH_SRC) >= 2),
        ('BODY_SLAM', '壁垒/坚定不移/势不可当/无惧疼痛', lambda k: kinds(k, {'BARRICADE', 'UNMOVABLE', 'JUGGERNAUT', 'FEEL_NO_PAIN'}) >= 1),
        ('JUGGERNAUT', '无惧疼痛/壁垒/坚定不移/岩石铠甲/狂怒/绯红披风', lambda k: kinds(k, {'FEEL_NO_PAIN', 'BARRICADE', 'UNMOVABLE', 'STONE_ARMOR', 'RAGE', 'CRIMSON_MANTLE'}) >= 1),
        ('BARRICADE', '全身撞击', lambda k: k.get('BODY_SLAM', 0) > 0),
        ('PERFECTED_STRIKE', '打击标签 ≥7 张', lambda k: sum(k.get(c, 0) for c in ('STRIKE_IRONCLAD', 'POMMEL_STRIKE', 'TWIN_STRIKE', 'SETUP_STRIKE', 'ASHEN_STRIKE', 'PERFECTED_STRIKE')) >= 7),
        ('HELLRAISER', '剑柄打击', lambda k: k.get('POMMEL_STRIKE', 0) > 0),
        ('RUPTURE', '自伤牌 ≥2 种', lambda k: kinds(k, {'BLOODLETTING', 'CRIMSON_MANTLE', 'OFFERING', 'HEMOKINESIS', 'BREAKTHROUGH', 'BLOOD_WALL', 'BRAND'}) >= 2),
        ('INFERNO', '自伤牌 ≥2 种', lambda k: kinds(k, {'BLOODLETTING', 'CRIMSON_MANTLE', 'OFFERING', 'HEMOKINESIS', 'BREAKTHROUGH', 'BLOOD_WALL', 'BRAND'}) >= 2),
        ('WHIRLWIND', '力量来源', lambda k: kinds(k, {'DEMON_FORM', 'INFLAME', 'FIGHT_ME', 'BRAND', 'DOMINATE'}) >= 1),
        ('CONFLAGRATION', '力量来源', lambda k: kinds(k, {'DEMON_FORM', 'INFLAME', 'FIGHT_ME', 'BRAND', 'DOMINATE'}) >= 1),
        ('DEMON_FORM', '多段 ≥2 种', lambda k: kinds(k, {'WHIRLWIND', 'CONFLAGRATION', 'SWORD_BOOMERANG', 'TWIN_STRIKE', 'FIGHT_ME', 'THRASH', 'TEAR_ASUNDER'}) >= 2),
        ('INFLAME', '多段 ≥2 种', lambda k: kinds(k, {'WHIRLWIND', 'CONFLAGRATION', 'SWORD_BOOMERANG', 'TWIN_STRIKE', 'FIGHT_ME', 'THRASH', 'TEAR_ASUNDER'}) >= 2),
        ('CRUELTY', '易伤来源 ≥2 种（不算痛击）', lambda k: kinds(k, {'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}) >= 2),
        ('VICIOUS', '易伤来源 ≥2 种（不算痛击）', lambda k: kinds(k, {'TREMBLE', 'UPPERCUT', 'TAUNT', 'THUNDERCLAP', 'SHOCKWAVE'}) >= 2),
        ('THRASH', '无惧疼痛/黑暗之拥', lambda k: kinds(k, EXH_ENGINE) >= 1),
    ]
    print(f'（基线最终通关 {base:.0%}）\n')
    print('| 牌 | 条件 | 有牌+有条件 | 有牌+无条件 | 无牌+有条件 | 都没有 | 交互（百分点） |\n|---|---|---|---|---|---|---|')
    for c, lab, f in tests:
        cell = {(a, b): [] for a in (0, 1) for b in (0, 1)}
        for k, w in K:
            cell[(int(k.get(c, 0) > 0), int(bool(f(k))))].append(w)
        p = {kk: (np.mean(v) if v else float('nan')) for kk, v in cell.items()}
        inter = p[(1, 1)] - p[(1, 0)] - p[(0, 1)] + p[(0, 0)]
        fm = lambda kk: f'{p[kk]:.0%}（{len(cell[kk])}）' if cell[kk] else '—'
        print(f'| {name(c)} | {lab} | {fm((1, 1))} | {fm((1, 0))} | {fm((0, 1))} | {fm((0, 0))} | {inter * 100:+.0f} |')
    print()


def section_e(runs):
    print('# E. 单张牌 → 第二幕每场掉血（进场牌组里有这张牌；岭回归，同时放入所有牌 + 打击/防御张数 + 遭遇固定效应 + 层数、遗物、升级、张数、最大生命）\n')
    print('负数 = 有这张牌时每场少掉的血。只列出现 ≥300 场的牌。\n')
    for act, rtype in ((2, 'monster'), (2, 'elite'), (2, 'boss')):
        fs = fights(runs, act, rtype)
        K = [counts(p['deck']) for _, p in fs]
        pres = collections.Counter(c for k in K for c in k if c not in BASIC)
        cards = [c for c, n in pres.items() if n >= (300 if rtype != 'boss' else 150)]
        encs = sorted({p['enc'] for _, p in fs})
        y = np.array([float(p['dmg']) for _, p in fs])
        D = np.array([[1.0 if k.get(c, 0) else 0.0 for c in cards] for k in K])
        ctl = np.array([[k.get('STRIKE_IRONCLAD', 0), k.get('DEFEND_IRONCLAD', 0), p['i'], p['relics'], p['ups'], len(p['deck']), p['maxhp'] or 80]
                        for k, (_, p) in zip(K, fs)], float)
        E = np.array([[1.0 if p['enc'] == e else 0.0 for e in encs[1:]] for _, p in fs])
        X = np.column_stack([np.ones(len(y)), D, ctl, E])
        lam = 5.0
        R = lam * np.eye(X.shape[1]); R[0, 0] = 0
        b = np.linalg.solve(X.T @ X + R, X.T @ y)
        res = y - X @ b; s2 = res @ res / (len(y) - X.shape[1])
        se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X + R)))
        nc = len(cards)
        rows = sorted([(cards[i], b[1 + i], se[1 + i], int(D[:, i].sum())) for i in range(nc)], key=lambda r: r[1])
        lab = f'第{act}幕 {dict(monster="普通战", elite="精英", boss="Boss")[rtype]}（{len(fs)} 场，平均 {y.mean():.1f}）'
        print(f'## {lab}')
        print(f'- 每多 1 张基础打击 {b[1 + nc]:+.2f}，每多 1 张基础防御 {b[2 + nc]:+.2f}，每多 1 个遗物 {b[4 + nc]:+.2f}，每多 1 次升级 {b[5 + nc]:+.2f}')
        print('- 少掉血最多：' + '，'.join(f'{name(c)} {v:+.1f}（±{1.96 * e:.1f}，{n}）' for c, v, e, n in rows[:25]))
        print('- 多掉血最多：' + '，'.join(f'{name(c)} {v:+.1f}（±{1.96 * e:.1f}，{n}）' for c, v, e, n in rows[::-1][:20]))
        print()


def load_experts():
    path = f'{ROOT}/sources/community-runs/elite-ironclad-a10-v0.111.0.jsonl.gz'
    out = []
    for line in gzip.open(path, 'rt'):
        d = json.loads(line)
        if d.get('was_abandoned'): continue
        out.append(parse(d))
    return out


def main():
    runs = load_all()
    experts = load_experts()
    print(f'社区对局 {len(runs)} 局；高手 {len(experts)} 局（赢 {sum(r["win"] for r in experts)}）\n')
    for n, (f, desc) in CORES.items():
        print(f'- **{n}**：{desc}')
    print()
    section_a(runs, experts)
    section_b(runs)
    section_c(runs)
    section_d(runs)
    section_e(runs)


if __name__ == '__main__':
    main()
