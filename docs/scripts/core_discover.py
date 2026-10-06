"""输出核心研究 · 第一步：不预设流派，从数据里找「哪些牌会一起出现、哪些牌单独就和胜率挂钩」。

对象：打到第二幕 Boss 的局（牌组取进第二幕 Boss 之前那一刻，c2），结果看「过第二幕 Boss」和「最终通关」。
1. 单牌：有它 vs 没有它的过第二幕 Boss 率、最终胜率；再用逻辑回归控制「第一、二幕打了几个精英、遗物数、升级数、牌组张数、进 Boss 血量比例、第二幕 Boss 是谁」，
   给出调整后的效应（百分点，按样本平均处的斜率换算）。
2. 共现聚类：出现率 ≥2% 的非基础牌，算两两 phi 相关系数，平均连接层次聚类，打印相关 ≥ 阈值合并出来的簇。
用法：CORE_CACHE=缓存路径 python3 core_discover.py [c1]
  加 c1：改用「第一幕结束时」的牌组（所有进了第二幕的局，结果看过第二幕 Boss / 最终通关；控制变量不含第二幕精英和 Boss）。
"""
import sys, os, collections, math
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, ids, counts, BASIC


def logit_fit(X, y, l2=1e-3, iters=50):
    """IRLS 逻辑回归（带很小的 L2，防止完全分离时发散）。返回系数和标准误"""
    n, k = X.shape
    b = np.zeros(k)
    for _ in range(iters):
        z = X @ b; p = 1 / (1 + np.exp(-z))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + l2 * np.eye(k)
        g = X.T @ (y - p) - l2 * b
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-7: break
    cov = np.linalg.inv(H)
    return b, np.sqrt(np.diag(cov))


CP = 'c1' if len(sys.argv) > 1 and sys.argv[1] == 'c1' else 'c2'


def controls_c2(r):
    """检查点的控制变量（c2：第二幕 Boss 前；c1：第一幕结束）"""
    p = r['points'][r[CP + '_idx']]
    hp_in = p['hp_in'] or 0; mx = p['maxhp'] or 80
    if CP == 'c1': return [r['elites_a1'], p['relics'], p['ups'], len(p['deck']), hp_in / mx]
    return [r['elites_a1'], r['elites_a2'], p['relics'], p['ups'], len(p['deck']), hp_in / mx]


def boss_of(r):
    return r['points'][r['c2_idx']]['enc'] if CP == 'c2' else 'x'


def main():
    runs = [r for r in load_all() if r[CP] is not None]
    N = len(runs)
    y_pass = np.array([1.0 if r['acts'] >= 3 else 0.0 for r in runs])
    y_win = np.array([1.0 if r['win'] else 0.0 for r in runs])
    print(f'{"打到第二幕 Boss 的局（牌组取进 Boss 前）" if CP == "c2" else "进了第二幕的局（牌组取第一幕结束时）"}：{N}；过第二幕 Boss {y_pass.mean():.1%}，最终通关 {y_win.mean():.1%}\n')
    bosses = sorted({boss_of(r) for r in runs})
    C = np.array([controls_c2(r) for r in runs], dtype=float)
    Cm, Cs = C.mean(0), C.std(0) + 1e-9
    Cz = (C - Cm) / Cs
    B = np.array([[1.0 if boss_of(r) == b else 0.0 for b in bosses[1:]] for r in runs]).reshape(N, -1)
    sets = [ids(r[CP]) - BASIC for r in runs]
    pres = collections.Counter(c for s in sets for c in s)
    cards = [c for c, n in pres.most_common() if n >= 60]

    # 单牌
    rows = []
    for c in cards:
        x = np.array([1.0 if c in s else 0.0 for s in sets])
        X = np.column_stack([np.ones(N), x, Cz, B])
        out = []
        for y in (y_pass, y_win):
            b, se = logit_fit(X, y)
            p0 = y.mean()
            out.append((b[1] * p0 * (1 - p0) * 100, b[1] / se[1]))
        a = x == 1
        rows.append((c, int(a.sum()), y_pass[a].mean(), y_pass[~a].mean(), y_win[a].mean(), y_win[~a].mean(), out[0], out[1]))
    rows.sort(key=lambda r: -r[7][0])
    print(f'## 单牌（{"进第二幕 Boss 时" if CP == "c2" else "第一幕结束时"}牌组里有它；调整 = 控制精英数、遗物、升级、张数、进场血量、Boss 后的效应，百分点）\n')
    print('| 牌 | 局数 | 过二幕Boss 有/无 | 调整 | 最终胜率 有/无 | 调整（z） |\n|---|---|---|---|---|---|')
    for c, n, pa, pb, wa, wb, (dp, zp), (dw, zw) in rows:
        print(f'| {name(c)} | {n} | {pa:.0%} / {pb:.0%} | {dp:+.1f} | {wa:.0%} / {wb:.0%} | {dw:+.1f}（{zw:+.1f}） |')

    # 共现聚类
    top = [c for c, n in pres.most_common() if n >= 0.02 * N]
    M = np.array([[1.0 if c in s else 0.0 for c in top] for s in sets])
    R = np.corrcoef(M.T)
    np.fill_diagonal(R, 1.0)
    clusters = [[i] for i in range(len(top))]

    def link(a, b):
        return np.mean([R[i, j] for i in a for j in b])
    TH = 0.06
    while True:
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                v = link(clusters[i], clusters[j])
                if best is None or v > best[0]: best = (v, i, j)
        if best is None or best[0] < TH: break
        _, i, j = best
        clusters[i] = clusters[i] + clusters[j]; del clusters[j]
    print(f'\n## 共现聚类（出现率 ≥2% 的 {len(top)} 张牌，平均 phi ≥ {TH} 合并）\n')
    for cl in sorted(clusters, key=lambda c: -len(c)):
        if len(cl) < 2: continue
        win_rate = np.mean([y_win[k] for k in range(N) if sum(M[k, i] for i in cl) >= 2])
        n2 = sum(1 for k in range(N) if sum(M[k, i] for i in cl) >= 2)
        print(f'- （{len(cl)} 张；牌组里有其中 ≥2 张的 {n2} 局，最终胜率 {win_rate:.0%}）' + '、'.join(name(top[i]) for i in sorted(cl, key=lambda i: -M[:, i].sum())))
    print('\n单独成簇：' + '、'.join(name(top[cl[0]]) for cl in clusters if len(cl) == 1))

    # 每张牌最强的伙伴（phi）
    print('\n## 每张牌相关最强的 5 个伙伴（phi）\n')
    for i, c in enumerate(top):
        order = np.argsort(-R[i]); partners = [(top[j], R[i, j]) for j in order if j != i][:5]
        print(f'- {name(c)}（{int(M[:, i].sum())}）：' + '，'.join(f'{name(p)} {v:.2f}' for p, v in partners))


if __name__ == '__main__':
    main()
