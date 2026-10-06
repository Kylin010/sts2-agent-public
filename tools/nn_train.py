"""训练神经网络策略模型（AlphaGo 路线第一步：从推演学打法）。数据见 tools/nn_dataset.py。
模型：局面编码（自己 / 手牌 / 三个牌堆 / 敌人逐个编码后求和 + 取最大 / 能力 / 药水 / 遭遇）+ 候选编码（打哪些牌 + 规划器打分明细）
→ 打分网络 → 每个候选一个分；同一局面的候选做 softmax，目标 = softmax(推演结局值 / τ)。
检验：按战斗分出一部分不参与训练，比「挑错手的损失」（老师最好的 v − 挑中那手的 v）：规划器原样 vs 网络。
用 venv：/opt/slay-the-spire-2/codex-agent/research/claude-value/venv/bin/python tools/nn_train.py 数据.pkl 输出.pt [--epochs 30]
"""
import argparse, json, math, os, pickle, random, re, sys
import numpy as np
import torch, torch.nn as nn, torch.nn.functional as F

ap = argparse.ArgumentParser()
ap.add_argument('data'); ap.add_argument('out'); ap.add_argument('--epochs', type=int, default=30); ap.add_argument('--tau', type=float, default=4.0)
ap.add_argument('--dim', type=int, default=32); ap.add_argument('--hid', type=int, default=128); ap.add_argument('--lr', type=float, default=2e-3)
ap.add_argument('--val', type=float, default=0.2); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--no_feats', action='store_true')
ap.add_argument('--residual', action='store_true', help='输出 = 规划器分 × 可学系数 + 网络修正（修正层初始为 0，一开始就等于规划器）')
ap.add_argument('--init', help='从已有模型接着训（同一份数据、同样的划分，词表一致）')
ap.add_argument('--cos', action='store_true', help='学习率按余弦从 lr 降到 0')
ap.add_argument('--split', default='fight', choices=['fight', 'file'], help='留出检验按战斗分，还是按记录文件（一个进程一串种子，留出的是没见过的牌组）')
ap.add_argument('--wsc_fixed', action='store_true', help='残差版：规划器分的系数固定不学（数据少时让网络只学修正量）')
ap.add_argument('--select', default='regret', choices=['regret', 'gain'], help='按哪个检验指标挑最好的一轮（干净标签用 gain：全体网络 − 规划器）')
ap.add_argument('--reg', type=float, default=0.0, help='残差版：网络修正量的平方惩罚（让它只在数据真支持时才偏离规划器）')
a = ap.parse_args()
torch.manual_seed(a.seed); random.seed(a.seed)
CORE = ('sc', 'dealt', 'killed', 'unb', 'unb_hp', 'dead', 'ends', 'powers', 'draw', 'thresh', 'e_frac', 'over', 'en_left', 'n', 'blk_cards', 'ttk', 'fut_in', 'fut_str')
base = lambda s: re.split(r'[!%#@]', s)[0]

def _load(p):
    if p.endswith('.jsonl'):          # tools/nn_relabel.py 的干净标签
        return [json.loads(l) for l in open(p) if l.strip()]
    return pickle.load(open(p, 'rb'))


data = [d for p in a.data.split(',') for d in _load(p)]
grp = (lambda d: d['fight']) if a.split == 'fight' else (lambda d: d['fight'].split('#')[0])
fights = sorted({grp(d) for d in data}); random.Random(7).shuffle(fights); vf = set(fights[:int(len(fights) * a.val)])
tr = [d for d in data if grp(d) not in vf]; va = [d for d in data if grp(d) in vf]


class Vocab:
    def __init__(self): self.i = {'<unk>': 0}
    def add(self, s):
        if s not in self.i: self.i[s] = len(self.i)
    def __call__(self, s): return self.i.get(s, 0)


V = {k: Vocab() for k in ('card', 'mon', 'move', 'pow', 'pot', 'enc', 'it')}
for d in tr:
    s = d['s']; V['enc'].add(s['enc'])
    for c in s['hand'] + s['draw'] + s['disc'] + s['exh']: V['card'].add(base(c))
    for p, _ in s['ppw']: V['pow'].add(p)
    for p in s['pots']: V['pot'].add(p)
    for e in s['enemies']:
        V['mon'].add(e['m']); V['move'].add(e['mv'])
        for p, _ in e['pw']: V['pow'].add(p)
        for t in e['it']: V['it'].add(t)
    for c in d['c']:
        for x in c['cards']: V['card'].add(base(x))
print(f'局面 训练 {len(tr)} / 检验 {len(va)}；词表 牌 {len(V["card"].i)} 怪 {len(V["mon"].i)} 招 {len(V["move"].i)} 能力 {len(V["pow"].i)}', flush=True)
ME = 6   # 最多敌人


def featurize(d):
    s = d['s']
    scal = [s['hp'] / s['mx'], s['hp'] / 80, s['mx'] / 100, s['blk'] / 30, s['en'] / 4, min(s['rnd'], 20) / 10, s['act'] / 3,
            len(s['hand']) / 10, len(s['draw']) / 30, len(s['disc']) / 30, len(s['exh']) / 20, 1.0 if s['room'] == 'Boss' else 0.0, 1.0 if s['room'] == 'Elite' else 0.0]
    piles = [[V['card'](base(c)) for c in s[k]] or [0] for k in ('hand', 'draw', 'disc', 'exh')]
    ppw = [(V['pow'](p), math.log1p(abs(x)) * (1 if x >= 0 else -1)) for p, x in s['ppw']] or [(0, 0.0)]
    pots = [V['pot'](p) for p in s['pots']] or [0]
    ens = []
    for e in s['enemies'][:ME]:
        ens.append(dict(m=V['mon'](e['m']), mv=V['move'](e['mv']), x=[e['hp'] / 100, e['mhp'] / 100, e['blk'] / 30, e['dmg'] / 30, e['hits'] / 5, e['hp'] / max(e['mhp'], 1)],
                        pw=[(V['pow'](p), math.log1p(abs(x)) * (1 if x >= 0 else -1)) for p, x in e['pw']] or [(0, 0.0)]))
    cands = []
    for c in d['c']:
        f = [float(c['f'].get(k, 0.0)) for k in CORE]
        cands.append(dict(cards=[V['card'](base(x)) for x in c['cards']] or [0], f=f, v=c['v'], sc=c['sc'], n=c.get('n', 1)))
    return dict(scal=scal, piles=piles, ppw=ppw, pots=pots, enc=V['enc'](s['enc']), ens=ens, cands=cands)


TR = [featurize(d) for d in tr]; VA = [featurize(d) for d in va]


class Net(nn.Module):
    def __init__(self, D=a.dim, H=a.hid):
        super().__init__()
        self.card = nn.EmbeddingBag(len(V['card'].i), D, mode='sum'); self.cardm = nn.EmbeddingBag(len(V['card'].i), D, mode='mean')
        self.pow = nn.Embedding(len(V['pow'].i), D); self.pot = nn.EmbeddingBag(len(V['pot'].i), D, mode='sum')
        self.mon = nn.Embedding(len(V['mon'].i), D); self.move = nn.Embedding(len(V['move'].i), D); self.enc = nn.Embedding(len(V['enc'].i), D)
        self.enemy = nn.Sequential(nn.Linear(3 * D + 6, H), nn.ReLU(), nn.Linear(H, H))
        self.state = nn.Sequential(nn.Linear(13 + D * 4 + D + D + D + 2 * H, H * 2), nn.ReLU(), nn.Linear(H * 2, H))
        nf = 0 if a.no_feats else len(CORE)
        self.cand = nn.Sequential(nn.Linear(D + 1 + nf, H), nn.ReLU(), nn.Linear(H, H))
        self.head = nn.Sequential(nn.Linear(3 * H, H), nn.ReLU(), nn.Linear(H, 1))
        if a.residual:
            nn.init.zeros_(self.head[2].weight); nn.init.zeros_(self.head[2].bias)
            self.wsc = nn.Parameter(torch.tensor(10.0 / a.tau / 10.0), requires_grad=not a.wsc_fixed)   # 规划器分（约等于血）÷ τ

    def bag_pow(self, lst):
        ids = torch.tensor([p for p, _ in lst]); w = torch.tensor([x for _, x in lst], dtype=torch.float32)
        return (self.pow(ids) * w[:, None]).sum(0)

    def encode_state(self, x):
        piles = []
        for k, ids in enumerate(x['piles']):
            t = torch.tensor(ids)[None]
            piles.append((self.card if k == 0 else self.cardm)(t)[0])
        ens = [torch.cat([self.mon(torch.tensor(e['m'])), self.move(torch.tensor(e['mv'])), self.bag_pow(e['pw']), torch.tensor(e['x'], dtype=torch.float32)]) for e in x['ens']]
        if ens:
            E = self.enemy(torch.stack(ens)); epool = torch.cat([E.sum(0), E.max(0).values])
        else:
            epool = torch.zeros(2 * a.hid)
        v = torch.cat([torch.tensor(x['scal'], dtype=torch.float32)] + piles + [self.bag_pow(x['ppw']), self.pot(torch.tensor(x['pots'])[None])[0], self.enc(torch.tensor(x['enc'])), epool])
        return self.state(v)

    def forward(self, x):
        s = self.encode_state(x)
        cs = []
        for c in x['cands']:
            parts = [self.card(torch.tensor(c['cards'])[None])[0], torch.tensor([len(c['cards']) / 5.0])]
            if not a.no_feats: parts.append(torch.tensor(c['f'], dtype=torch.float32))
            cs.append(torch.cat(parts))
        C = self.cand(torch.stack(cs)); S = s[None].expand(C.shape[0], -1)
        out = self.head(torch.cat([S, C, S * C], 1))[:, 0]
        self.last_corr = out
        if a.residual:
            out = out + self.wsc * torch.tensor([c['sc'] for c in x['cands']], dtype=torch.float32)
        return out


def collate(X):
    """一批局面摊平成张量（变长的牌堆 / 能力 / 敌人 / 候选用 offsets + 所属局面编号）"""
    T = lambda v, dt=torch.long: torch.tensor(v, dtype=dt)
    def bag(lists):
        ids, offs = [], []
        for l in lists: offs.append(len(ids)); ids += l
        return T(ids), T(offs)
    def wbag(lists):
        ids, offs, w = [], [], []
        for l in lists: offs.append(len(ids)); ids += [p for p, _ in l]; w += [x for _, x in l]
        return T(ids), T(offs), T(w, torch.float32)
    ens = [(i, e) for i, x in enumerate(X) for e in x['ens']]
    cs = [(i, c) for i, x in enumerate(X) for c in x['cands']]
    return dict(B=len(X), scal=T([x['scal'] for x in X], torch.float32), piles=[bag([x['piles'][k] for x in X]) for k in range(4)],
                ppw=wbag([x['ppw'] for x in X]), pots=bag([x['pots'] for x in X]), enc=T([x['enc'] for x in X]),
                em=T([e['m'] for _, e in ens]), emv=T([e['mv'] for _, e in ens]), ex=T([e['x'] for _, e in ens], torch.float32).reshape(-1, 6),
                epw=wbag([e['pw'] for _, e in ens]), eidx=T([i for i, _ in ens]),
                cc=bag([c['cards'] for _, c in cs]), clen=T([[len(c['cards']) / 5.0] for _, c in cs], torch.float32).reshape(-1, 1),
                cf=T([c['f'] for _, c in cs], torch.float32).reshape(-1, len(CORE)), csc=T([c['sc'] for _, c in cs], torch.float32),
                cv=T([c['v'] for _, c in cs], torch.float32), cidx=T([i for i, _ in cs]))


def forward_batch(self, bt):
    B, H = bt['B'], a.hid
    eb = lambda W, ids_offs, mode, w=None: F.embedding_bag(ids_offs[0], W, ids_offs[1], mode=mode, per_sample_weights=w)
    piles = [eb(self.card.weight, bt['piles'][0], 'sum')] + [eb(self.cardm.weight, bt['piles'][k], 'mean') for k in (1, 2, 3)]
    ppw = eb(self.pow.weight, bt['ppw'][:2], 'sum', bt['ppw'][2])
    epool = torch.zeros(B, 2 * H)
    if len(bt['eidx']):
        E = self.enemy(torch.cat([self.mon(bt['em']), self.move(bt['emv']), eb(self.pow.weight, bt['epw'][:2], 'sum', bt['epw'][2]), bt['ex']], 1))
        idx = bt['eidx'][:, None].expand(-1, H)
        esum = torch.zeros(B, H).index_add(0, bt['eidx'], E)
        emax = torch.zeros(B, H).scatter_reduce(0, idx, E, 'amax', include_self=False)   # 没敌人的局面保持 0（和逐个算一致）
        epool = torch.cat([esum, emax], 1)
    v = torch.cat([bt['scal']] + piles + [ppw, eb(self.pot.weight, bt['pots'], 'sum'), self.enc(bt['enc']), epool], 1)
    S = self.state(v)
    parts = [eb(self.card.weight, bt['cc'], 'sum'), bt['clen']]
    if not a.no_feats: parts.append(bt['cf'])
    C = self.cand(torch.cat(parts, 1)); Sx = S[bt['cidx']]
    out = self.head(torch.cat([Sx, C, Sx * C], 1))[:, 0]
    self.last_corr = out
    if a.residual: out = out + self.wsc * bt['csc']
    return out


Net.forward_batch = forward_batch


def seg_logsoftmax(z, idx, B):
    mx = torch.zeros(B).scatter_reduce(0, idx, z.detach(), 'amax', include_self=False)
    ez = torch.exp(z - mx[idx]); s = torch.zeros(B).index_add(0, idx, ez)
    return z - mx[idx] - torch.log(s[idx])


net = Net(); opt = torch.optim.Adam(net.parameters(), lr=a.lr, weight_decay=1e-5)
if a.init:
    ck = torch.load(a.init)
    assert all(ck['vocab'][k] == V[k].i for k in V), '词表对不上（数据或划分变了）'
    net.load_state_dict(ck['state'])
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.epochs) if a.cos else None


PAIR = {}


def regret(X, use_net=True):
    tot = n = top = 0; dif = []; gain = []
    with torch.no_grad():
        for b in range(0, len(X), 512):
            xs = X[b:b + 512]
            outs = net.forward_batch(collate(xs)).numpy() if use_net else None; o = 0
            for x in xs:
                vs = [c['v'] for c in x['cands']]; m = len(vs)
                p = max(range(m), key=lambda i: x['cands'][i]['sc'])
                k = int(np.argmax(outs[o:o + m])) if use_net else p; o += m
                # 同推演量比较：网络和规划器挑得不一样、两边都推演了 8 遍以上（避免「只推 3 遍的被淘汰候选标签偏低」）
                if k != p and x['cands'][k]['n'] >= 8 and x['cands'][p]['n'] >= 8: dif.append(vs[k] - vs[p])
                gain.append(vs[k] - vs[p])          # 全体：每个局面网络挑的 − 规划器挑的（干净标签上这就是无偏的「每步多剩几点血」）
                if max(vs) - min(vs) <= 1: continue
                tot += max(vs) - vs[k]; n += 1; top += vs[k] >= max(vs) - 1e-6
    PAIR['n'] = len(dif); PAIR['d'] = sum(dif) / max(len(dif), 1)
    g = np.array(gain or [0.0]); PAIR['g'] = float(g.mean()); PAIR['gse'] = float(g.std() / np.sqrt(len(g)))
    return tot / max(n, 1), top / max(n, 1), n


with torch.no_grad():                                  # 成批前向和逐个前向核对一遍
    xs = VA[:200]; yb = net.forward_batch(collate(xs)); ys = torch.cat([net(x) for x in xs])
    print(f'成批 vs 逐个前向最大差 {float((yb - ys).abs().max()):.2e}', flush=True); assert float((yb - ys).abs().max()) < 1e-4


rp, tp, nn_ = regret(VA, False)
print(f'规划器原样：检验 {nn_} 个有区分度的局面，挑错手损失 {rp:.2f}，挑到最好 {tp:.0%}', flush=True)
best = (1e9, None)
if a.select == 'gain' and a.residual and not a.init:     # 残差版初始就等于规划器（全体 +0）：训练没超过它就留着初始模型
    best = (0.0, {k: v.clone() for k, v in net.state_dict().items()})
if a.init:
    net.eval(); r0, t0, _ = regret(VA); best = (r0 if a.select == 'regret' else -PAIR['g'], {k: v.clone() for k, v in net.state_dict().items()})
    print(f'起点模型：挑错手损失 {r0:.2f}，挑到最好 {t0:.0%}', flush=True)
TR = [x for x in TR if max(c['v'] for c in x['cands']) - min(c['v'] for c in x['cands']) > 1e-6]   # 候选结局全一样的局面不学
for ep in range(a.epochs):
    net.train(); random.shuffle(TR); L = 0.0
    for b in range(0, len(TR), 64):
        bt = collate(TR[b:b + 64]); B = bt['B']; idx = bt['cidx']
        opt.zero_grad()
        out = net.forward_batch(bt); logp = seg_logsoftmax(out, idx, B)
        tgt = torch.exp(seg_logsoftmax(bt['cv'] / a.tau, idx, B))
        loss = (tgt * (torch.log(tgt.clamp_min(1e-30)) - logp)).sum()
        if a.reg:
            cnt = torch.zeros(B).index_add(0, idx, torch.ones_like(out)); c = net.last_corr
            cm = torch.zeros(B).index_add(0, idx, c) / cnt
            loss = loss + a.reg * (torch.zeros(B).index_add(0, idx, (c - cm[idx]).pow(2)) / cnt).sum()
        (loss / 64).backward(); opt.step(); L += float(loss.detach())
    if sched: sched.step()
    net.eval(); r, t, _ = regret(VA)
    print(f'第 {ep + 1} 轮：训练损失 {L / len(TR):.4f}  检验 挑错手损失 {r:.2f}（规划器 {rp:.2f}）挑到最好 {t:.0%}  同推演量 {PAIR["n"]} 处不同、网络 − 规划器 {PAIR["d"]:+.2f}  全体 {PAIR["g"]:+.3f}±{PAIR["gse"]:.3f}'
          + (f'  wsc {float(net.wsc):.3f}' if a.residual else ''), flush=True)
    crit = r if a.select == 'regret' else -PAIR['g']
    if crit < best[0]: best = (crit, {k: v.clone() for k, v in net.state_dict().items()})
torch.save({'state': best[1], 'vocab': {k: v.i for k, v in V.items()}, 'args': vars(a), 'val_regret': best[0], 'planner_regret': rp}, a.out)
print(f'采用检验最好的一轮：挑错手损失 {best[0]:.2f}（规划器 {rp:.2f}）→ {a.out}')

# 导出 numpy 版（下场用 policy/nnpolicy.py，不依赖 torch），并逐数核对和 torch 前向一致
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from policy import nnpolicy
net.load_state_dict(best[1]); net.eval()
npz = re.sub(r'\.pt$', '', a.out) + '.npz'
W = {k: v.detach().numpy().astype(np.float32) for k, v in net.state_dict().items()}
np.savez(npz, meta=np.array({'vocab': {k: v.i for k, v in V.items()}, 'args': vars(a), 'val_regret': best[0], 'planner_regret': rp}, dtype=object), **W)
m = nnpolicy.load(npz); worst = 0.0
with torch.no_grad():
    for d in va[:300]:
        y0 = net(featurize(d)).numpy(); y1 = nnpolicy.scores(m, nnpolicy.featurize(d['s'], d['c'], m['V']))
        worst = max(worst, float(np.abs(y0 - y1).max()))
print(f'numpy 版 → {npz}；和 torch 前向最大差 {worst:.2e}（300 个检验局面）')
assert worst < 1e-3, 'numpy 前向和 torch 对不上'
