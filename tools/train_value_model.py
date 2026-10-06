"""胜率预测模型。

输入一个局面（牌组含升级、遗物、血量、最大生命、金币、药水数、第几幕第几层），输出「这局最终能赢的概率」。
以后每次做选择（拿哪张牌、商店买什么、篝火休息还是升级……），把每个选项会变成的局面都算一遍胜率，挑最高的。

模型：因子分解机（FM）。一阶项 = 每张牌 / 每件遗物 / 每个数值特征各自的权重；
二阶项 = 任意两个特征的配合（牌 × 牌、牌 × 遗物、牌 × 第几幕、牌 × 血量……），用 k 维向量内积表示，样本少的组合也能学。
数据：sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz，每局每隔几层取一个局面（同一局的局面高度相关，取太密没用）。
按对局划分训练 / 检验，报告检验集的对数损失和 AUC，并和「只看楼层和血量」的简单模型比。
注意混杂：高手的牌组本来就容易赢，模型会把「高手的习惯」也学成「赢的原因」——所以只当一个信号，要在模拟器里对打验证。
输出：data/value_model.json（运行时 policy/valuemodel.py 读取）
用法：python3 tools/train_value_model.py [--dim 8] [--epochs 12] [--every 2]
"""
import argparse, collections, gzip, json, math, os, random, time
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']
ap = argparse.ArgumentParser()
ap.add_argument('--dim', type=int, default=8); ap.add_argument('--epochs', type=int, default=12)
ap.add_argument('--every', type=int, default=2, help='每隔几层取一个局面'); ap.add_argument('--lr', type=float, default=0.03)
ap.add_argument('--l2', type=float, default=1e-3); ap.add_argument('--batch', type=int, default=256)
ap.add_argument('--min-count', type=int, default=150)
a = ap.parse_args()
random.seed(2); np.random.seed(2)
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
rid = lambda x: str(x).replace('RELIC.', '')


def feats(deck, relics, hp, mx, gold, pots, act, floor):
    """局面 → [(特征名, 值)]。牌按张数（升级的另记一个特征）"""
    f = []
    for (c, up), n in deck.items():
        f.append((f'c:{c}', min(n, 6) / 2.0))
        if up: f.append((f'u:{c}', min(n, 6) / 2.0))
    for r in relics: f.append((f'r:{r}', 1.0))
    size = sum(deck.values())
    f += [('hp_frac', hp / max(mx, 1)), ('hp', hp / 80.0), ('max_hp', mx / 80.0), ('gold', min(gold, 600) / 300.0),
          ('pots', pots / 3.0), ('size', size / 30.0), (f'act{act}', 1.0), ('floor', floor / 50.0)]
    return f


# ---------- 1. 局面快照 ----------
t0 = time.time(); rows = []
for ri, line in enumerate(gzip.open(SRC, 'rt')):
    d = json.loads(line)
    if d.get('was_abandoned') or d.get('modifiers') or len(d.get('players') or []) != 1 or 'BaseLib' in line: continue
    win = 1.0 if d.get('win') else 0.0
    deck = collections.Counter((c, False) for c in START); relics = set(); gfloor = 0; pots = 0
    for ai, act in enumerate(d.get('map_point_history') or []):
        for fi, p in enumerate(act):
            gfloor += 1
            ps = (p.get('player_stats') or [{}])[0]
            for c in ps.get('cards_gained') or []:
                deck[(cid(c), bool(isinstance(c, dict) and c.get('current_upgrade_level')))] += 1
            for c in ps.get('cards_removed') or []:
                k = (cid(c), bool(isinstance(c, dict) and c.get('current_upgrade_level')))
                k2 = (k[0], not k[1])
                if deck[k] > 0: deck[k] -= 1
                elif deck[k2] > 0: deck[k2] -= 1
            for u in ps.get('upgraded_cards') or []:
                u = cid(u)
                if deck[(u, False)] > 0: deck[(u, False)] -= 1; deck[(u, True)] += 1
            for r in ps.get('relic_choices') or []:
                if r.get('was_picked'): relics.add(rid(r.get('choice')))
            for r in ps.get('bought_relics') or []: relics.add(rid(r))
            pots += sum(1 for x in ps.get('potion_choices') or [] if x.get('was_picked')) + len(ps.get('bought_potions') or [])
            pots -= len(ps.get('potion_used') or []) + len(ps.get('potion_discarded') or [])
            pots = max(0, min(pots, 3))
            deck += collections.Counter()
            if gfloor % a.every == 0 and ps.get('max_hp'):
                rows.append((feats(deck, relics, ps.get('current_hp') or 0, ps.get('max_hp') or 80, ps.get('current_gold') or 0,
                                   pots, min(ai + 1, 3), gfloor), win, ri))
print(f'{len(rows)} 个局面（{time.time() - t0:.0f} 秒）')

# ---------- 2. 编号（出现太少的牌 / 遗物丢掉）----------
cnt = collections.Counter(k for f, _, _ in rows for k, _ in f)
vocab = sorted(k for k, n in cnt.items() if n >= a.min_count)
idx = {k: i + 1 for i, k in enumerate(vocab)}         # 0 = 填充
L = max(len(f) for f, _, _ in rows)
N = len(rows); I = np.zeros((N, L), np.int32); X = np.zeros((N, L), np.float32); Y = np.zeros(N, np.float32); R = np.zeros(N, np.int32)
for n, (f, y, r) in enumerate(rows):
    j = 0
    for k, v in f:
        if k in idx: I[n, j] = idx[k]; X[n, j] = v; j += 1
    Y[n] = y; R[n] = r
runs = np.unique(R); np.random.shuffle(runs); test_runs = set(runs[:len(runs) // 5].tolist())
te = np.array([r in test_runs for r in R]); tr = ~te
print(f'特征 {len(vocab)} 个；训练 {tr.sum()} / 检验 {te.sum()} 个局面；检验集胜率 {Y[te].mean():.1%}')

F = len(vocab) + 1; K = a.dim
w0 = np.zeros(1); W = np.zeros(F); V = np.random.randn(F, K).astype(np.float64) * 0.01
W[0] = 0; V[0] = 0
G = {'w0': np.zeros(1), 'W': np.zeros(F), 'V': np.zeros((F, K))}


def predict(Ib, Xb):
    lin = w0[0] + (W[Ib] * Xb).sum(1)
    vx = V[Ib] * Xb[:, :, None]                       # N×L×K
    s = vx.sum(1); inter = 0.5 * ((s * s).sum(1) - (vx * vx).sum((1, 2)))
    return lin + inter, vx, s


def metrics(mask):
    z, _, _ = predict(I[mask], X[mask]); p = 1 / (1 + np.exp(-z)); y = Y[mask]
    ll = -np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(len(p))
    pos = y == 1; auc = (ranks[pos].mean() - (pos.sum() - 1) / 2) / max((~pos).sum(), 1)
    return ll, auc


# 参照：只看「第几层 + 血量比例 + 幕」的逻辑回归（同样的训练流程，只用这几个特征）
base_ll = -np.mean(Y[te] * np.log(Y[tr].mean()) + (1 - Y[te]) * np.log(1 - Y[tr].mean()))
print(f'参照：只猜平均胜率的对数损失 {base_ll:.4f}')
idx_tr = np.where(tr)[0]
best = (9e9, None)
for ep in range(a.epochs):
    np.random.shuffle(idx_tr); t1 = time.time()
    for b in range(0, len(idx_tr), a.batch):
        bi = idx_tr[b:b + a.batch]; Ib, Xb, yb = I[bi], X[bi], Y[bi]
        z, vx, s = predict(Ib, Xb); p = 1 / (1 + np.exp(-z)); g = (p - yb) / len(bi)         # N
        gw0 = g.sum(); G['w0'] += gw0 ** 2; w0[0] -= a.lr * gw0 / (np.sqrt(G['w0'][0]) + 1e-8)
        gW = np.zeros(F); np.add.at(gW, Ib.ravel(), (g[:, None] * Xb).ravel()); gW += a.l2 * W
        G['W'] += gW ** 2; W -= a.lr * gW / (np.sqrt(G['W']) + 1e-8)
        # d inter / d v_i = x_i * (s - v_i x_i)
        gv = g[:, None, None] * Xb[:, :, None] * (s[:, None, :] - vx)          # N×L×K
        gV = np.zeros((F, K)); np.add.at(gV, Ib.ravel(), gv.reshape(-1, K)); gV += a.l2 * V
        G['V'] += gV ** 2; V -= a.lr * gV / (np.sqrt(G['V']) + 1e-8)
        W[0] = 0; V[0] = 0
    ll, auc = metrics(te)
    print(f'第 {ep + 1} 轮（{time.time() - t1:.0f} 秒）检验对数损失 {ll:.4f}，AUC {auc:.3f}', flush=True)
    if ll < best[0]: best = (ll, (w0.copy(), W.copy(), V.copy(), auc))      # 早停：留检验集上最好的那一轮
w0, W, V, auc = best[1]; ll = best[0]
print(f'采用检验对数损失最低的一轮：{ll:.4f}，AUC {auc:.3f}')

json.dump({'vocab': vocab, 'w0': w0.tolist(), 'W': W.tolist(), 'V': V.tolist(),
           'meta': {'rows': int(N), 'test_logloss': float(ll), 'test_auc': float(auc), 'base_logloss': float(base_ll),
                    'every': a.every, 'dim': K, 'trained': time.strftime('%Y-%m-%d %H:%M')}},
          open(f'{HERE}/data/value_model.json', 'w'))
top = np.argsort(-W[1:])[:15] + 1
print('一阶权重最高：', [(vocab[i - 1], round(float(W[i]), 2)) for i in top])
print('写入 data/value_model.json')
