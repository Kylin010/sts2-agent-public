"""从社区对局学「高手在这个牌组下会拿哪张牌」（选牌模型，行为克隆）。

每次战后选牌 = 一个决定：提供 2~4 张牌 + 跳过。模型给每个选项一个效用 U，按 softmax 算选中概率：
  U(牌 c) = a[c] + b[c, 幕] + dup[c] × 牌组里已有几张 c + u[c] · m(牌组) + size_w[类型] × 牌组大小
  U(跳过) = skip0[幕] + skip1 × 牌组大小
  m(牌组) = 牌组里每张牌的 v 向量的平均（这副牌「提供了什么」）；u[c] 是这张牌「需要什么」。内积就是联动分。
训练目标：让赢家实际选的那个选项概率最大（输家的选择权重低一些）。L2 正则防止样本少的牌过拟合。

数据：sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz（A10 铁甲战士、测试版 v0.111.0）。
输出：data/pick_model.json（运行时 policy/pickmodel.py 读取）
用法：python3 tools/train_pick_model.py [--dim 8] [--epochs 60] [--loser-weight 0.3]
"""
import argparse, collections, gzip, json, os, random, time
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']

ap = argparse.ArgumentParser()
ap.add_argument('--dim', type=int, default=8); ap.add_argument('--epochs', type=int, default=60)
ap.add_argument('--loser-weight', type=float, default=0.3); ap.add_argument('--l2', type=float, default=2e-4)
ap.add_argument('--lr', type=float, default=0.05); ap.add_argument('--seed', type=int, default=1)
ap.add_argument('--out', default='data/pick_model.json'); ap.add_argument('--no-relics', action='store_true'); ap.add_argument('--no-boss', action='store_true'); ap.add_argument('--pool', default='mean', help='mean = 牌组向量取平均；sum = 求和（核心牌的联动信号不被开局牌冲淡）')
a = ap.parse_args()
random.seed(a.seed); np.random.seed(a.seed)
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')

# ---------- 1. 读对局，还原每次选牌时的牌组 ----------
t0 = time.time()
decisions = []   # (offered[list], chosen_index or -1 for skip, deck Counter, act, win, run_id)
ctype = {}
cards_kb = json.load(open(f'{HERE}/kb/cards.json'))
for k, v in cards_kb.items(): ctype[k] = v.get('type')
for ri, line in enumerate(gzip.open(SRC, 'rt')):
    d = json.loads(line)
    if d.get('was_abandoned') or d.get('modifiers') or len(d.get('players') or []) != 1: continue
    if 'BaseLib' in line: continue                                    # 装了模组的对局（可能有原版没有的牌）
    win = bool(d.get('win')); deck = collections.Counter(START)
    bosses = {}                                                    # 每一幕的 Boss（本幕开始就看得到）；没打到 Boss 的局不知道
    for ai, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            for r in p.get('rooms') or []:
                if r.get('room_type') == 'boss' and ai not in bosses: bosses[ai] = 'B:' + str(r.get('model_id')).replace('ENCOUNTER.', '')
    for ai, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            ps = (p.get('player_stats') or [{}])[0]
            if not a.no_relics:                                    # 遗物也放进「牌组画像」（R: 前缀），学遗物和牌的配合
                for r in ps.get('relic_choices') or []:
                    if r.get('was_picked'): deck['R:' + str(r.get('choice')).replace('RELIC.', '')] = 1
                for r in ps.get('bought_relics') or []: deck['R:' + str(r).replace('RELIC.', '')] = 1
            ch = ps.get('card_choices') or []
            if ch and p.get('map_point_type') in ('monster', 'elite', 'boss', 'unknown', 'treasure', 'event'):
                offered = [cid(x.get('card')) for x in ch]
                picked = [i for i, x in enumerate(ch) if x.get('was_picked')]
                if 2 <= len(offered) <= 5 and len(picked) <= 1:
                    dk = collections.Counter(deck)
                    if ai in bosses and not a.no_boss: dk[bosses[ai]] = 1          # 本幕 Boss 也进牌组画像：学「对这个 Boss 该拿什么」
                    decisions.append((offered, picked[0] if picked else -1, dk, min(ai + 1, 3), win, ri))
            for c in ps.get('cards_gained') or []: deck[cid(c)] += 1
            for c in ps.get('cards_removed') or []:
                k = cid(c)
                if deck[k] > 0: deck[k] -= 1
            deck += collections.Counter()   # 去掉 0
print(f'读入 {len(decisions)} 个选牌决定（{time.time() - t0:.0f} 秒）')

# ---------- 2. 编号 ----------
cnt = collections.Counter(c for o, *_ in decisions for c in o)
vocab = sorted(c for c, n in cnt.items() if n >= 15)
idx = {c: i for i, c in enumerate(vocab)}; N = len(vocab); K = a.dim
decks_vocab = collections.Counter(c for x in decisions for c in x[2])
deck_vocab = sorted(set(vocab) | {c for c, n in decks_vocab.items() if n >= 30})
didx = {c: i for i, c in enumerate(deck_vocab)}; M = len(deck_vocab)
TYPES = ['Attack', 'Skill', 'Power', 'Other']
tix = lambda c: TYPES.index(ctype.get(c)) if ctype.get(c) in TYPES else 3
data = []
for offered, ch, deck, act, win, rid in decisions:
    if any(c not in idx for c in offered): continue
    dv = np.zeros(M, np.float32); size = 0
    for c, n in deck.items():
        if not c.startswith(('R:', 'B:')): size += n     # 牌组大小只算牌，不算遗物和 Boss
        if c in didx: dv[didx[c]] = n
    data.append(dict(off=[idx[c] for c in offered], ch=ch, dv=dv, size=size, act=act, w=1.0 if win else a.loser_weight, win=win, rid=rid,
                     same=[deck.get(c, 0) for c in offered], typ=[tix(c) for c in offered]))
runs = sorted({x['rid'] for x in data}); random.shuffle(runs)
test_runs = set(runs[:len(runs) // 5])
train = [x for x in data if x['rid'] not in test_runs]; test = [x for x in data if x['rid'] in test_runs]
print(f'牌 {N} 种（牌组里 {M} 种），训练 {len(train)} / 检验 {len(test)} 个决定')

# ---------- 3. 参数 ----------
P = {'a': np.zeros(N), 'b': np.zeros((N, 3)), 'dup': np.zeros(N), 'u': np.random.randn(N, K) * 0.01, 'v': np.random.randn(M, K) * 0.01,
     'size_w': np.zeros(4), 'skip0': np.zeros(3), 'skip1': np.zeros(1)}
G = {k: np.zeros_like(v) for k, v in P.items()}   # Adagrad 累积


def forward(x):
    m = (x['dv'] @ P['v']) / (max(x['size'], 1) if a.pool == 'mean' else 10.0)
    s = x['size'] / 25.0
    U = [P['a'][c] + P['b'][c, x['act'] - 1] + P['dup'][c] * x['same'][j] + P['u'][c] @ m + P['size_w'][x['typ'][j]] * s
         for j, c in enumerate(x['off'])]
    U.append(P['skip0'][x['act'] - 1] + P['skip1'][0] * s)
    U = np.array(U); e = np.exp(U - U.max()); p = e / e.sum()
    return U, p, m, s


def evaluate(xs, only_win=True):
    xs = [x for x in xs if x['win'] or not only_win]
    ok = 0; ll = 0
    for x in xs:
        U, p, *_ = forward(x)
        tgt = x['ch'] if x['ch'] >= 0 else len(x['off'])
        ok += int(np.argmax(p) == tgt); ll += -np.log(p[tgt] + 1e-12)
    return ok / max(len(xs), 1), ll / max(len(xs), 1)


base = sum(1 for x in test if x['win'] and x['ch'] >= 0 and x['ch'] == max(range(len(x['off'])), key=lambda j: cnt[vocab[x['off'][j]]])) / max(1, sum(1 for x in test if x['win']))
print(f'参照：总拿「出现最多的那张」的准确率 {base:.1%}')
for ep in range(a.epochs):
    random.shuffle(train); t1 = time.time()
    for x in train:
        U, p, m, s = forward(x)
        tgt = x['ch'] if x['ch'] >= 0 else len(x['off'])
        g = p.copy(); g[tgt] -= 1; g *= x['w']
        gv = np.zeros(K)
        for j, c in enumerate(x['off']):
            gj = g[j]
            if gj == 0: continue
            # 稀疏 Adagrad 更新
            for name, key, gr in (('a', c, gj), ('b', (c, x['act'] - 1), gj), ('dup', c, gj * x['same'][j])):
                gr = gr + a.l2 * P[name][key]
                G[name][key] += gr * gr; P[name][key] -= a.lr * gr / (np.sqrt(G[name][key]) + 1e-8)
            gu = gj * m + a.l2 * P['u'][c]
            G['u'][c] += gu * gu; P['u'][c] -= a.lr * gu / (np.sqrt(G['u'][c]) + 1e-8)
            gv += gj * P['u'][c]
            t = x['typ'][j]; gs = gj * s
            G['size_w'][t] += gs * gs; P['size_w'][t] -= a.lr * gs / (np.sqrt(G['size_w'][t]) + 1e-8)
        gk = g[-1]
        for name, key, gr in (('skip0', x['act'] - 1, gk), ('skip1', 0, gk * s)):
            G[name][key] += gr * gr; P[name][key] -= a.lr * gr / (np.sqrt(G[name][key]) + 1e-8)
        # v：牌组里每张牌按数量分到梯度
        nz = np.nonzero(x['dv'])[0]
        if len(nz):
            w = x['dv'][nz] / (max(x['size'], 1) if a.pool == 'mean' else 10.0)
            gvv = np.outer(w, gv) + a.l2 * P['v'][nz]
            G['v'][nz] += gvv * gvv; P['v'][nz] -= a.lr * gvv / (np.sqrt(G['v'][nz]) + 1e-8)
    if ep % 5 == 4 or ep == a.epochs - 1:
        tr = evaluate(train[:5000]); te = evaluate(test)
        print(f'第 {ep + 1} 轮（{time.time() - t1:.0f} 秒/轮）训练准确率 {tr[0]:.1%}，检验准确率 {te[0]:.1%}，检验对数损失 {te[1]:.3f}', flush=True)

out = {'vocab': vocab, 'deck_vocab': deck_vocab, 'types': TYPES, 'dim': K, 'pool': a.pool,
       **{k: v.tolist() for k, v in P.items()},
       'meta': {'decisions_train': len(train), 'decisions_test': len(test), 'test_acc_winners': evaluate(test)[0],
                'baseline_most_common': base, 'trained': time.strftime('%Y-%m-%d %H:%M'), 'args': vars(a)}}
json.dump(out, open(f'{HERE}/{a.out}', 'w'))
print('写入', a.out)
