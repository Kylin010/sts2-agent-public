"""输出核心研究 · 第四步：我们第二幕多掉的血，有多少能用「牌组本身」解释。

做法：用人类第二幕的战斗（进场牌组 → 这场掉血）拟合一个线性模型（每张牌是否在牌组 + 打击/防御张数 + 遗物数 + 升级数 + 张数 + 最大生命 + 遭遇固定效应），
然后把「我们死在第二幕时的牌组」和「人类赢家第二幕 Boss 前的牌组」分别代进去，遭遇按同一个平均来算，看预测掉血差多少。
预测差 = 牌组（含遗物、升级数量）能解释的部分；实际差 − 预测差 = 牌组以外（出牌、路线、药水、具体遗物……）的部分。
我们的牌组只有死时的最终牌组，用它近似第二幕后段的牌组。
用法：CORE_CACHE=缓存路径 python3 gap_decomp.py
"""
import sys, os, json, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts, BASIC
from core_effects import fights
from our_decks import ours


def fit(fs, cards, encs, lam=5.0):
    K = [counts(p['deck']) for _, p in fs]
    y = np.array([float(p['dmg']) for _, p in fs])
    X = np.array([feat(k, p['relics'], p['ups'], p['maxhp'] or 80, cards) + [1.0 if p['enc'] == e else 0.0 for e in encs[1:]] for k, (_, p) in zip(K, fs)])
    R = lam * np.eye(X.shape[1]); R[0, 0] = 0
    b = np.linalg.solve(X.T @ X + R, X.T @ y)
    return b, X, y


def feat(k, relics, ups, maxhp, cards):
    return [1.0] + [1.0 if k.get(c, 0) else 0.0 for c in cards] + [k.get('STRIKE_IRONCLAD', 0), k.get('DEFEND_IRONCLAD', 0), relics, ups, sum(k.values()), maxhp]


def main():
    H = load_all()
    O = [o for o in ours() if o['act'] == 2 and not o['win']]
    hw = [r for r in H if r['win'] and r['c2'] is not None]
    for rtype, lab in (('monster', '普通战'), ('elite', '精英'), ('boss', 'Boss')):
        fs = fights(H, 2, rtype)
        pres = collections.Counter(c for _, p in fs for c in counts(p['deck']) if c not in BASIC)
        cards = [c for c, n in pres.items() if n >= 100]
        encs = sorted({p['enc'] for _, p in fs})
        b, X, y = fit(fs, cards, encs)
        nb = 1 + len(cards) + 6
        enc_mean = X[:, nb:].mean(0)                      # 人类第二幕遭遇分布
        def pred(k, relics, ups, maxhp):
            return float(np.dot(b[:nb], feat(k, relics, ups, maxhp, cards)) + np.dot(b[nb:], enc_mean))
        po = [pred(o['k'], o['relics'], o['ups'], 80 + 0) for o in O]
        ph = [pred(counts(r['c2']), r['points'][r['c2_idx']]['relics'], r['points'][r['c2_idx']]['ups'], r['points'][r['c2_idx']]['maxhp'] or 80) for r in hw]
        # 拆开：只换牌（遗物、升级、最大生命用人类赢家的平均）
        mr = np.mean([r['points'][r['c2_idx']]['relics'] for r in hw]); mu = np.mean([r['points'][r['c2_idx']]['ups'] for r in hw])
        mm = np.mean([r['points'][r['c2_idx']]['maxhp'] or 80 for r in hw])
        po_cards = [pred(o['k'], mr, mu, mm) for o in O]
        won = np.array([bool(r['win']) for r, _ in fs])
        actual_o = [c.get('dmg') or 0 for o in ours() for c in o['combats'] if c.get('act') == 2 and c.get('room', '').lower() == rtype]
        print(f'## 第二幕{lab}（人类 {len(fs)} 场拟合）')
        print(f'- 实际：人类赢家 {y[won].mean():.1f}，人类全部 {y.mean():.1f}，我们 {np.mean(actual_o):.1f}（{len(actual_o)} 场）')
        print(f'- 模型预测（同样的遭遇分布）：人类赢家第二幕 Boss 前的牌组 {np.mean(ph):.1f}；我们死在第二幕的牌组 {np.mean(po):.1f}'
              f'（只换牌、遗物升级按人类赢家算：{np.mean(po_cards):.1f}）')
        print(f'- 牌组（含遗物、升级）能解释的差：{np.mean(po) - np.mean(ph):+.1f}，其中牌本身 {np.mean(po_cards) - np.mean(ph):+.1f}；'
              f'实际差 {np.mean(actual_o) - y[won].mean():+.1f}\n')


if __name__ == '__main__':
    main()
