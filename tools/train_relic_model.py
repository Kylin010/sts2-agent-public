"""从社区商店记录学「在这个牌组下，这件遗物值不值得买」（遗物估值模型）。

每次进商店上架 3 件遗物，记录了买没买。对每件上架的遗物：
  P(买) = sigmoid( a[遗物] + w[遗物] · m(牌组) + g × 进店金币/200 + c[幕] )
  m(牌组) 用选牌模型（data/pick_model.json）学好的牌向量 v 求平均，保持不变——这样遗物和牌组的配合用的是同一套「牌组画像」。
运行时遗物价值 = a[遗物] + w[遗物] · m(牌组)（去掉金币和幕的项，那两项只是为了把「买不起 / 不同阶段」的影响剥离出去）。
赢家权重 1，输家 0.4。数据：sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz
输出：data/relic_model.json
用法：python3 tools/train_relic_model.py
"""
import collections, gzip, json, os, random
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']
import sys
PICK = sys.argv[sys.argv.index('--pick') + 1] if '--pick' in sys.argv else 'data/pick_model.json'
OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'data/relic_model.json'
PM = json.load(open(f'{HERE}/{PICK}'))
V = np.array(PM['v']); DIDX = {c: i for i, c in enumerate(PM['deck_vocab'])}; K = V.shape[1]
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
rid = lambda x: str(x).replace('RELIC.', '')
random.seed(3); np.random.seed(3)

rows = []          # (relic, m, gold, act, bought, weight, run)
for ri, line in enumerate(gzip.open(SRC, 'rt')):
    d = json.loads(line)
    if d.get('was_abandoned') or d.get('modifiers') or 'BaseLib' in line: continue
    win = bool(d.get('win')); deck = collections.Counter(START)
    for ai, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            ps = (p.get('player_stats') or [{}])[0]
            rc = ps.get('relic_choices') or []
            if p.get('map_point_type') == 'shop' and len(rc) == 3:
                m = np.zeros(K); n = 0
                for c, k in deck.items():
                    if not c.startswith('R:'): n += k
                    if c in DIDX: m += k * V[DIDX[c]]
                m /= (max(n, 1) if PM.get('pool', 'mean') == 'mean' else 10.0)
                gold = (ps.get('current_gold') or 0) + (ps.get('gold_spent') or 0)
                for r in rc:
                    rows.append((rid(r.get('choice')), m, gold / 200.0, min(ai + 1, 3), 1.0 if r.get('was_picked') else 0.0, 1.0 if win else 0.4, ri))
            for r in ps.get('relic_choices') or []:                 # 已有的遗物也进牌组画像（和选牌模型一致）
                if r.get('was_picked'): deck['R:' + rid(r.get('choice'))] = 1
            for c in ps.get('cards_gained') or []: deck[cid(c)] += 1
            for c in ps.get('cards_removed') or []:
                if deck[cid(c)] > 0: deck[cid(c)] -= 1
cnt = collections.Counter(r[0] for r in rows)
vocab = sorted(k for k, n in cnt.items() if n >= 15); idx = {k: i for i, k in enumerate(vocab)}
rows = [r for r in rows if r[0] in idx]
runs = sorted({r[6] for r in rows}); random.shuffle(runs); test = set(runs[:len(runs) // 5])
tr = [r for r in rows if r[6] not in test]; te = [r for r in rows if r[6] in test]
print(f'{len(rows)} 条（{len(vocab)} 件遗物），训练 {len(tr)} / 检验 {len(te)}')

R = len(vocab)
a = np.zeros(R); W = np.zeros((R, K)); g = np.zeros(1); c = np.zeros(3); bias = np.zeros(1)
Ga = np.zeros(R); GW = np.zeros((R, K)); Gg = np.zeros(1); Gc = np.zeros(3); Gb = np.zeros(1)
lr, l2 = 0.05, 1e-3


def logit(r):
    i = idx[r[0]]
    return bias[0] + a[i] + W[i] @ r[1] + g[0] * r[2] + c[r[3] - 1], i


def ev(xs):
    ll = 0; ok = 0; wsum = 0
    for r in xs:
        z, _ = logit(r); p = 1 / (1 + np.exp(-z))
        ll += -(r[4] * np.log(p + 1e-9) + (1 - r[4]) * np.log(1 - p + 1e-9)); ok += (p > 0.5) == (r[4] > 0.5)
    return ll / len(xs), ok / len(xs)


base_rate = sum(r[4] for r in te) / len(te)
print(f'检验集购买率 {base_rate:.1%}（全猜不买的准确率 {1 - base_rate:.1%}）')
for ep in range(25):
    random.shuffle(tr)
    for r in tr:
        z, i = logit(r); p = 1 / (1 + np.exp(-z)); e = (p - r[4]) * r[5]
        for arr, G, key, gr in ((a, Ga, i, e + l2 * a[i]), (bias, Gb, 0, e), (g, Gg, 0, e * r[2]), (c, Gc, r[3] - 1, e)):
            G[key] += gr * gr; arr[key] -= lr * gr / (np.sqrt(G[key]) + 1e-8)
        gw = e * r[1] + l2 * W[i]; GW[i] += gw * gw; W[i] -= lr * gw / (np.sqrt(GW[i]) + 1e-8)
    if ep % 5 == 4: print(f'第 {ep + 1} 轮：检验对数损失 {ev(te)[0]:.4f}，准确率 {ev(te)[1]:.1%}', flush=True)
json.dump({'vocab': vocab, 'a': a.tolist(), 'W': W.tolist(), 'g': g.tolist(), 'c': c.tolist(), 'bias': bias.tolist(),
           'meta': {'rows': len(rows), 'test_logloss': ev(te)[0], 'test_acc': ev(te)[1], 'base_rate': base_rate}},
          open(f'{HERE}/{OUT}', 'w'))
top = sorted(range(R), key=lambda i: -a[i])
print('基础价值最高：', [(vocab[i], round(a[i], 2)) for i in top[:12]])
print('基础价值最低：', [(vocab[i], round(a[i], 2)) for i in top[-6:]])
