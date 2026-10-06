"""神经网络策略：从推演的自我对弈记录学来的「这几种出法哪个好」。
训练：tools/nn_dataset.py 出数据 → tools/nn_train.py（torch）训练 → tools/nn_export.py 导出成 numpy 权重（data/nn_*.npz）。
下场只用 numpy 算（不依赖 torch，三台远端都能跑），和 torch 版逐数核对过（tools/nn_export.py --check）。
用法：规划器列出前 K 名候选（和推演同一套 combat.candidates），网络给每个候选打分，挑最高的。
输入只有玩家看得见的东西：自己、手牌、三个牌堆的内容（抽牌堆只当一袋牌，不看顺序）、敌人和意图、能力、药水、遭遇。
"""
import math, os, re
import numpy as np
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = ('sc', 'dealt', 'killed', 'unb', 'unb_hp', 'dead', 'ends', 'powers', 'draw', 'thresh', 'e_frac', 'over', 'en_left', 'n', 'blk_cards',
        'ttk', 'fut_in', 'fut_str')
ME = 6
base = lambda s: re.split(r'[!%#@]', s)[0]
_M = {'f': None, 'm': None}


# ---------- 局面编码（tools/nn_dataset.py 也用这一份） ----------
def spec(c):
    if c.get('spec'): return str(c['spec'])
    return str(c.get('id') or '').replace('CARD.', '') + ('+' if c.get('upgraded') else '')


def _pw(lst):
    return [(str(p.get('id') or p.get('name') or '').replace('POWER.', ''), float(p.get('amount') or 1)) for p in lst or [] if p]


def encode_state(st):
    from policy.public_move_beliefs import unique_move
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    mx = max(pl.get('max_hp') or 1, 1); hp = pl.get('hp') or 0
    ens = []
    for e in st.get('enemies') or []:
        if (e.get('hp') or 0) <= 0: continue
        dmg = sum((it.get('damage') or 0) * max(it.get('hits') or 1, 1) for it in e.get('intents') or [] if str(it.get('type')) in ('Attack', 'DeathBlow'))
        hits = sum(max(it.get('hits') or 1, 1) for it in e.get('intents') or [] if str(it.get('type')) == 'Attack')
        ens.append(dict(m=str(e.get('monster_id') or e.get('name')), mv=str(unique_move(st, e) or ''), hp=min(e.get('hp') or 0, 999), mhp=min(e.get('max_hp') or 1, 999),
                        blk=e.get('block') or 0, dmg=dmg, hits=hits, it=[str(it.get('type')) for it in e.get('intents') or []], pw=_pw(e.get('powers'))))
    return dict(enc=str(ctx.get('encounter') or '').replace('ENCOUNTER.', ''), act=int(ctx.get('act') or 1), room=str(ctx.get('room_type') or ''),
                hp=hp, mx=mx, blk=pl.get('block') or 0, en=st.get('energy') or 0, rnd=st.get('round') or 1,
                ppw=_pw(st.get('player_powers')), hand=[spec(c) for c in st.get('hand') or []],
                draw=list(st.get('draw_pile') or []), disc=list(st.get('discard_pile') or []), exh=list(st.get('exhaust_pile') or []),
                pots=[str(p.get('id') or p.get('name') or '') for p in pl.get('potions') or [] if p], enemies=ens)


def _slog(x):
    return math.log1p(abs(x)) * (1 if x >= 0 else -1)


def featurize(s, cands, V):
    """s = encode_state 的结果，cands = [{'cards': [牌 spec], 'f': {CORE 特征}, 'sc': 规划器分}]，V = 词表 {类: {名: 号}}"""
    g = lambda k, x: V[k].get(x, 0)
    scal = [s['hp'] / s['mx'], s['hp'] / 80, s['mx'] / 100, s['blk'] / 30, s['en'] / 4, min(s['rnd'], 20) / 10, s['act'] / 3,
            len(s['hand']) / 10, len(s['draw']) / 30, len(s['disc']) / 30, len(s['exh']) / 20, 1.0 if s['room'] == 'Boss' else 0.0, 1.0 if s['room'] == 'Elite' else 0.0]
    piles = [[g('card', base(c)) for c in s[k]] or [0] for k in ('hand', 'draw', 'disc', 'exh')]
    ppw = [(g('pow', p), _slog(x)) for p, x in s['ppw']] or [(0, 0.0)]
    pots = [g('pot', p) for p in s['pots']] or [0]
    ens = []
    for e in s['enemies'][:ME]:
        ens.append(dict(m=g('mon', e['m']), mv=g('move', e['mv']), x=[e['hp'] / 100, e['mhp'] / 100, e['blk'] / 30, e['dmg'] / 30, e['hits'] / 5, e['hp'] / max(e['mhp'], 1)],
                        pw=[(g('pow', p), _slog(x)) for p, x in e['pw']] or [(0, 0.0)]))
    cs = [dict(cards=[g('card', base(x)) for x in c['cards']] or [0], f=[float(c['f'].get(k, 0.0)) for k in CORE], sc=float(c['sc'])) for c in cands]
    return dict(scal=scal, piles=piles, ppw=ppw, pots=pots, enc=g('enc', s['enc']), ens=ens, cands=cs)


# ---------- numpy 前向（和 tools/nn_train.py 的 Net 一一对应） ----------
def load(path):
    z = np.load(path, allow_pickle=True)
    W = {k: z[k] for k in z.files if k != 'meta'}
    meta = z['meta'].item()
    return dict(W=W, V=meta['vocab'], args=meta['args'])


def model():
    f = f"{HERE}/data/{P.get('nn_file') or 'nn_policy.npz'}"
    if _M['f'] != f:
        _M['m'] = load(f) if os.path.exists(f) else None; _M['f'] = f
    return _M['m']


def _lin(W, name, x):
    return x @ W[f'{name}.weight'].T + W[f'{name}.bias']


def _mlp(W, name, x):          # Linear → ReLU → Linear
    return _lin(W, f'{name}.2', np.maximum(_lin(W, f'{name}.0', x), 0.0))


def scores(m, x):
    W, a = m['W'], m['args']
    piles = [W['card.weight'][x['piles'][0]].sum(0)] + [W['cardm.weight'][ids].mean(0) for ids in x['piles'][1:]]
    bag_pow = lambda lst: (W['pow.weight'][[p for p, _ in lst]] * np.array([w for _, w in lst], dtype=np.float32)[:, None]).sum(0)
    if x['ens']:
        E = np.stack([np.concatenate([W['mon.weight'][e['m']], W['move.weight'][e['mv']], bag_pow(e['pw']), np.array(e['x'], dtype=np.float32)]) for e in x['ens']])
        E = _mlp(W, 'enemy', E); epool = np.concatenate([E.sum(0), E.max(0)])
    else:
        epool = np.zeros(2 * a['hid'], dtype=np.float32)
    v = np.concatenate([np.array(x['scal'], dtype=np.float32)] + piles + [bag_pow(x['ppw']), W['pot.weight'][x['pots']].sum(0), W['enc.weight'][x['enc']], epool])
    S = _mlp(W, 'state', v)
    C = []
    for c in x['cands']:
        parts = [W['card.weight'][c['cards']].sum(0), np.array([len(c['cards']) / 5.0], dtype=np.float32)]
        if not a.get('no_feats'): parts.append(np.array(c['f'], dtype=np.float32))
        C.append(np.concatenate(parts))
    C = _mlp(W, 'cand', np.stack(C)); Sx = np.broadcast_to(S, C.shape)
    out = _mlp(W, 'head', np.concatenate([Sx, C, Sx * C], 1))[:, 0]
    if a.get('residual'):
        out = out + float(W['wsc']) * np.array([c['sc'] for c in x['cands']], dtype=np.float32)
    return out


# ---------- 下场 ----------
def choose(cands, ctx, st, mem):
    """cands = combat.candidates() 的 [(规划器分, 组合)]；返回网络打分最高的组合（没有模型返回 None）"""
    m = model()
    if not m or len(cands) < 2: return None
    # 只在这些房间用（10/5：留出种子上网络普通怪 +0.41 / 精英 +0.89，Boss −0.45——修 bug 后 Boss 数据太少，交还规划器）
    if str((st.get('context') or {}).get('room_type') or '') not in (P.get('nn_rooms') or ('Monster', 'Elite', 'Boss')): return None
    from policy import rerank
    from policy.combat import evaluate
    enc = rerank.enc_of(st); mv = rerank.phase(ctx)
    cs, combos = [], []
    for sc, combo in cands:
        pt = rerank.parts(combo, ctx, evaluate)
        if pt is None: continue
        f = rerank.feats(combo, ctx, pt, enc, mv, sc)
        cs.append(dict(cards=[spec(c) for c in combo], f={k: f[k] for k in CORE}, sc=sc)); combos.append(combo)
    if len(cs) < 2: return None
    out = scores(m, featurize(encode_state(st), cs, m['V']))
    k = int(np.argmax(out)); p = int(np.argmax([c['sc'] for c in cs]))
    # 保守：网络挑的比规划器第一名高出 nn_margin（打分单位 ≈ 推演值 ÷ τ，τ=4 时 0.25 ≈ 1 点血）才改
    if out[k] - out[p] < P.get('nn_margin', 0.0): k = p
    ns = mem.setdefault('nn_stats', {'turns': 0, 'changed': 0})
    ns['turns'] += 1; ns['changed'] += k != p
    return combos[k]
