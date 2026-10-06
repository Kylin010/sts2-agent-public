"""训练战斗局面估值模型（policy/combatvalue.py 用）：回合结束时的局面 → 从现在到战斗结束还要掉多少血（死了 +30）。

数据：STS2_LOG_TURNS=1 跑出来的结果文件（每条结果的 turns 字段），默认读 results/turns-*.jsonl。
模型：一层隐藏层的小神经网络（ReLU），numpy 手写反向传播 + Adam。按战斗划分训练 / 检验，
和「只猜平均」「线性回归」两个对照比检验集误差。
输出：data/combat_value.json
用法：python3 tools/train_combat_value.py [--hidden 32] [--epochs 60] [文件...]
"""
import argparse, glob, json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy.combatvalue import features, unblocked_now

ap = argparse.ArgumentParser()
ap.add_argument('files', nargs='*'); ap.add_argument('--hidden', type=int, default=32); ap.add_argument('--epochs', type=int, default=60)
ap.add_argument('--out', default='combat_value.json'); ap.add_argument('--lr', type=float, default=3e-3); ap.add_argument('--l2', type=float, default=1e-4); ap.add_argument('--death', type=float, default=30)
a = ap.parse_args()
random.seed(4); np.random.seed(4)
files = a.files or sorted(glob.glob(f'{HERE}/results/turns*-*.jsonl'))
rows = []; fight = 0
for fn in files:
    for line in open(fn):
        r = json.loads(line)
        groups = [r.get('turns') or []] + [c.get('turns') or [] for c in r.get('combats') or []]   # 基准结果 / 整局里的每场战斗
        for g in groups:
            if not g: continue
            for t in g:
                unb = min(unblocked_now(t['s']), t['s']['hp'])          # v2：去掉这次敌方回合的伤害，模型只学之后的部分
                rows.append((features(t['s']), max(0, t['future'] - unb) + (a.death if t['died'] else 0), fight))
            fight += 1
print(f'{len(rows)} 个局面，来自 {fight} 场战斗（{len(files)} 个文件）')
names = sorted({k for f, _, _ in rows for k in f})
idx = {k: i for i, k in enumerate(names)}
X = np.zeros((len(rows), len(names)), np.float32); Y = np.zeros(len(rows), np.float32); G = np.zeros(len(rows), np.int32)
for n, (f, y, g) in enumerate(rows):
    for k, v in f.items(): X[n, idx[k]] = v
    Y[n] = y; G[n] = g
fights = np.unique(G); np.random.shuffle(fights); test = set(fights[:len(fights) // 5].tolist())
te = np.array([g in test for g in G]); tr = ~te
scale = float(np.std(Y[tr]) or 1)
print(f'特征 {len(names)} 个；训练 {tr.sum()} / 检验 {te.sum()}；目标均值 {Y.mean():.1f}，标准差 {scale:.1f}')
rmse = lambda p, y: float(np.sqrt(np.mean((p - y) ** 2)))
print(f'对照 1：只猜平均  检验 RMSE {rmse(np.full(te.sum(), Y[tr].mean()), Y[te]):.2f}')
Xa = np.hstack([X, np.ones((len(X), 1))])
w = np.linalg.lstsq(Xa[tr].T @ Xa[tr] + 1.0 * np.eye(Xa.shape[1]), Xa[tr].T @ Y[tr], rcond=None)[0]
print(f'对照 2：线性回归  检验 RMSE {rmse(Xa[te] @ w, Y[te]):.2f}')

# 输入标准化（均值 0、标准差 1），存进模型里，运行时同样变换
mu = X[tr].mean(0); sd = X[tr].std(0); sd[sd < 1e-6] = 1.0
X = (X - mu) / sd
H = a.hidden; F = len(names)
W1 = np.random.randn(H, F) * np.sqrt(2 / F); b1 = np.zeros(H); W2 = np.random.randn(H) * 0.1; b2 = np.array(Y[tr].mean() / scale)
params = [W1, b1, W2, b2]; mom = [np.zeros_like(p) for p in params]; vel = [np.zeros_like(p) for p in params]; step = 0
Yt = Y / scale
best = (9e9, None)
idx_tr = np.where(tr)[0]
for ep in range(a.epochs):
    np.random.shuffle(idx_tr)
    for b in range(0, len(idx_tr), 256):
        bi = idx_tr[b:b + 256]; x = X[bi]; y = Yt[bi]
        z = x @ W1.T + b1; h = np.maximum(z, 0); p = h @ W2 + b2
        g = np.clip(p - y, -1.0, 1.0) / len(bi)            # Huber 损失：误差超过 1 个标准差后梯度封顶，防止个别样本把训练带飞
        gW2 = h.T @ g + a.l2 * W2; gb2 = g.sum()
        gh = np.outer(g, W2) * (z > 0)
        gW1 = gh.T @ x + a.l2 * W1; gb1 = gh.sum(0)
        step += 1
        for i, (pp, gg) in enumerate(zip(params, [gW1, gb1, gW2, gb2])):
            mom[i] = 0.9 * mom[i] + 0.1 * gg; vel[i] = 0.999 * vel[i] + 0.001 * gg * gg
            mh = mom[i] / (1 - 0.9 ** step); vh = vel[i] / (1 - 0.999 ** step)
            pp -= a.lr * mh / (np.sqrt(vh) + 1e-8)
    pred = (np.maximum(X[te] @ W1.T + b1, 0) @ W2 + b2) * scale
    e = rmse(pred, Y[te])
    if e < best[0]: best = (e, [p.copy() for p in params])
    if ep % 10 == 9: print(f'第 {ep + 1} 轮：检验 RMSE {e:.2f}', flush=True)
e, (W1, b1, W2, b2) = best
print(f'采用检验最好的一轮：RMSE {e:.2f}')
json.dump({'features': names, 'idx': idx, 'mu': mu.tolist(), 'sd': sd.tolist(), 'W1': W1.tolist(), 'b1': b1.tolist(), 'W2': W2.tolist(), 'b2': float(b2), 'scale': scale,
           'meta': {'rows': len(rows), 'fights': int(fight), 'test_rmse': e, 'death': a.death, 'hidden': H}},
          open(f'{HERE}/data/{a.out}', 'w'))
print(f'写入 data/{a.out}')
