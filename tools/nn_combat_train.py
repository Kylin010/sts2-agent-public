"""大版战斗价值网络训练（policy/cvnet.py 的模型）。
数据：推演模拟记录（四台机器 /opt/sts2/teach/rollout.<pid> 拉到本机，search._compact 格式），每次模拟记了每个回合开始的局面 + 这次模拟的结局。
标签：从这个局面到战斗结束还掉多少血；死了 = 当时血量 + 30（和 combat_value_human 一样）。
划分：按「哪次模拟」整组划分（同一次模拟的几个局面不会一半训练一半检验），80 / 10 / 10。
模型：输入约 1500 维（逐张牌 / 怪 / 能力 / 遗物 / 药水），两层 ReLU 隐藏层，Huber 损失，Adam，按验证集早停。numpy 实现，本机 CPU 可训；装好 GPU 后换 torch 训更大的。
用法：python3 tools/nn_combat_train.py [--data '/opt/slay-the-spire-2/data-nn/rollout/*/rollout.*'] [--max 2000000] [--hidden 256,128] [--epochs 12] [--out cvnet.npz]
"""
import argparse, glob, hashlib, json, os, sys, time
import numpy as np
import scipy.sparse as sp
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy import cvnet

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='/opt/slay-the-spire-2/data-nn/rollout/*/rollout.*')
ap.add_argument('--max', type=int, default=2000000, help='最多用多少个局面')
ap.add_argument('--hidden', default='256,128'); ap.add_argument('--epochs', type=int, default=12)
ap.add_argument('--lr', type=float, default=1e-3); ap.add_argument('--batch', type=int, default=512)
ap.add_argument('--death', type=float, default=30); ap.add_argument('--min-count', type=int, default=20, help='出现少于这么多次的牌 / 怪 / 能力不进词表')
ap.add_argument('--out', default='cvnet.npz'); ap.add_argument('--seed', type=int, default=1)
a = ap.parse_args()
t0 = time.time()

# 1. 读数据
snaps, ys, groups, ctxs = [], [], [], []
files = sorted(glob.glob(a.data))
for fi, f in enumerate(files):
    for li, l in enumerate(open(f)):
        try: r = json.loads(l)
        except Exception: continue
        if r.get('end') not in ('win', 'death'): continue
        g = int(hashlib.md5(f'{f}:{li}'.encode()).hexdigest()[:8], 16)
        for s in r['snaps']:
            hp = (s.get('p') or [0])[0] or 0
            y = hp - (r.get('hp_end') or 0) if r['end'] == 'win' else hp + a.death
            snaps.append(s); ys.append(max(0.0, float(y))); groups.append(g); ctxs.append(s.get('c') or [None] * 4)
    if len(snaps) >= a.max: break
snaps, ys, groups = snaps[:a.max], np.array(ys[:a.max], dtype=np.float32), np.array(groups[:a.max])
print(f'{len(files)} 个文件，{len(snaps)} 个局面（{time.time() - t0:.0f} 秒）；标签均值 {ys.mean():.1f}', flush=True)

# 2. 词表（出现太少的去掉）
from collections import Counter
cnt = {k: Counter() for k in ('card', 'mon', 'pw', 'rel', 'pot')}
for s in snaps:
    for k in ('h', 'd', 'x', 'z'):
        for c in s[k]: cnt['card'][cvnet.base(c)[0]] += 1
    for p in s['pp']: cnt['pw'][p[0]] += 1
    for r in s['rl']: cnt['rel'][r[0]] += 1
    for p in s['po']: cnt['pot'][p] += 1
    for e in s['en']:
        cnt['mon'][e[0]] += 1
        for p in e[5]: cnt['pw'][p[0]] += 1
vocab = {k: sorted(x for x, n in c.items() if n >= a.min_count) for k, c in cnt.items()}
idx = cvnet.layout(vocab); D = len(idx)
print('词表', {k: len(v) for k, v in vocab.items()}, '特征维度', D, flush=True)

# 3. 编码成稀疏矩阵
rows, cols, vals = [], [], []
for i, s in enumerate(snaps):
    ix, val = cvnet.encode(s, idx)
    rows += [i] * len(ix); cols += ix; vals += val
X = sp.csr_matrix((np.array(vals, dtype=np.float32), (np.array(rows), np.array(cols))), shape=(len(snaps), D))
del rows, cols, vals
print(f'编码完成（{time.time() - t0:.0f} 秒），平均每个局面 {X.nnz / X.shape[0]:.0f} 个非零', flush=True)

# 4. 划分
h = groups % 10
tr, va, te = np.where(h < 8)[0], np.where(h == 8)[0], np.where(h == 9)[0]
mu = np.asarray(X[tr].mean(axis=0)).ravel().astype(np.float32)
sq = np.asarray(X[tr].multiply(X[tr]).mean(axis=0)).ravel()
sd = np.sqrt(np.maximum(sq - mu.astype(np.float64) ** 2, 1e-6)).astype(np.float32)
ymu, ysd = float(ys[tr].mean()), float(ys[tr].std() + 1e-6)


def dense(ii):
    return (X[ii].toarray() - mu) / sd


# 5. 网络
rng = np.random.default_rng(a.seed)
sizes = [D] + [int(x) for x in a.hidden.split(',')] + [1]
W = [rng.normal(0, np.sqrt(2 / sizes[i]), (sizes[i], sizes[i + 1])).astype(np.float32) for i in range(len(sizes) - 1)]
b = [np.zeros(sizes[i + 1], dtype=np.float32) for i in range(len(sizes) - 1)]
mW = [np.zeros_like(w) for w in W]; vW = [np.zeros_like(w) for w in W]; mb = [np.zeros_like(x) for x in b]; vb = [np.zeros_like(x) for x in b]
step = 0


def forward(x):
    hs = [x]
    for i in range(len(W)):
        z = hs[-1] @ W[i] + b[i]
        hs.append(np.maximum(z, 0) if i < len(W) - 1 else z)
    return hs


def predict(ii):
    out = []
    for k in range(0, len(ii), 4096):
        out.append(forward(dense(ii[k:k + 4096]))[-1][:, 0])
    return np.concatenate(out) * ysd + ymu


def rmse(ii):
    p = predict(ii); return float(np.sqrt(np.mean((p - ys[ii]) ** 2))), p


best = (1e9, None)
print(f'训练 {len(tr)} / 验证 {len(va)} / 检验 {len(te)}；只猜平均 RMSE {np.sqrt(np.mean((ymu - ys[va]) ** 2)):.2f}', flush=True)
for ep in range(a.epochs):
    perm = rng.permutation(tr); lr = a.lr * (0.5 if ep >= a.epochs * 2 // 3 else 1.0)
    for k in range(0, len(perm), a.batch):
        bi = perm[k:k + a.batch]
        hs = forward(dense(bi)); y = (ys[bi] - ymu) / ysd
        err = hs[-1][:, 0] - y
        g = np.clip(err, -1.0, 1.0)[:, None] / len(bi)          # Huber（1 个标准差封顶）
        step += 1
        for i in range(len(W) - 1, -1, -1):
            gW = hs[i].T @ g; gb = g.sum(0)
            if i > 0: g = (g @ W[i].T) * (hs[i] > 0)
            for P_, M_, V_, G_ in ((W[i], mW[i], vW[i], gW), (b[i], mb[i], vb[i], gb)):
                M_ *= 0.9; M_ += 0.1 * G_; V_ *= 0.999; V_ += 0.001 * G_ * G_
                P_ -= lr * (M_ / (1 - 0.9 ** step)) / (np.sqrt(V_ / (1 - 0.999 ** step)) + 1e-8)
    r, _ = rmse(va)
    print(f'第 {ep + 1} 轮：验证 RMSE {r:.2f}（{time.time() - t0:.0f} 秒）', flush=True)
    if r < best[0]: best = (r, ([w.copy() for w in W], [x.copy() for x in b]))
W, b = best[1]
r_te, p_te = rmse(te)
print(f'检验 RMSE {r_te:.2f}（只猜平均 {np.sqrt(np.mean((ymu - ys[te]) ** 2)):.2f}）', flush=True)
# 分组检验：按幕 / 房间，死没死
ctx = [snaps[i].get('c') or [None] * 4 for i in te]
for name, mask in (('第一幕', [c[0] == 1 for c in ctx]), ('第二幕', [c[0] == 2 for c in ctx]), ('第三幕', [c[0] == 3 for c in ctx]),
                   ('Boss', [c[2] == 'Boss' for c in ctx]), ('精英', [c[2] == 'Elite' for c in ctx])):
    m = np.array(mask)
    if m.sum(): print(f'  {name} {m.sum()} 个：RMSE {np.sqrt(np.mean((p_te[m] - ys[te][m]) ** 2)):.2f}，标签均值 {ys[te][m].mean():.1f}')
# 同一次模拟之外：同一场战斗里两个局面谁之后掉血更多（差 ≥5），排对的比例
rng2 = np.random.default_rng(0); pairs = ok = 0
for _ in range(20000):
    i, j = rng2.integers(0, len(te), 2)
    if abs(ys[te][i] - ys[te][j]) < 5: continue
    pairs += 1; ok += (p_te[i] > p_te[j]) == (ys[te][i] > ys[te][j])
print(f'  随机两个局面谁之后掉血更多（差 ≥5）：排对 {ok / max(pairs, 1):.1%}（{pairs} 对）')
names = np.array(sorted(idx, key=idx.get))
np.savez(f'{HERE}/data/{a.out}', names=names, mu=mu, sd=sd, ymu=ymu, ysd=ysd, nlayers=len(W),
         **{f'W{i}': w for i, w in enumerate(W)}, **{f'b{i}': x for i, x in enumerate(b)},
         meta=json.dumps({'n': len(snaps), 'files': len(files), 'test_rmse': r_te, 'val_rmse': best[0], 'hidden': a.hidden, 'death': a.death}))
print('已写', a.out, f'（{time.time() - t0:.0f} 秒）')
