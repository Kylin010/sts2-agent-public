"""水晶球点击策略 v2（只用玩家可见信息）：后验采样 + 一步价值估计。来源：research/水晶球事件.md 附录 B。
仿真（600 盘配对）：6 次 177 → 361 金币当量，遗物 19% → 98%，诅咒 35% → 14%；3 次 55 → 117。
输入 = RunSimulator 导出的 crystal_sphere 局面（hidden / visible_item / divinations_left），
另外只用到游戏公开的生成规则（v0.111.0 CrystalSphereMinigame：物品种类、尺寸、放置顺序、均匀抽位置）。
"""
import hashlib
import numpy as np

N = 11; NC = N * N
def _cid(x, y): return x * N + y
CLEARED = np.zeros(NC, bool)                       # 球外 24 格：离四角曼哈顿距离 <=2
for _cx, _cy in [(0, 0), (N - 1, 0), (N - 1, N - 1), (0, N - 1)]:
    for _x in range(N):
        for _y in range(N):
            if abs(_x - _cx) + abs(_y - _cy) <= 2: CLEARED[_cid(_x, _y)] = True
CLASS = {'CrystalSphereRelic': 1, 'CrystalSpherePotion': 2, 'CrystalSphereCardReward': 3, 'CrystalSphereCurse': 4, 'CrystalSphereGold': 5}
# 放置顺序 = PopulateItems：(子类型, 尺寸(x宽,y高), 类)
ITEMS = [('relic', (4, 4), 1), ('cpot', (1, 3), 2), ('cpot', (1, 3), 2), ('rpot', (2, 2), 2),
         ('cardC', (2, 2), 3), ('cardU', (2, 2), 3), ('cardR', (2, 2), 3), ('curse', (2, 2), 4)] + \
        [('gold', (1, 1), 5)] * 5 + [('bgold', (2, 1), 5)] * 2
NI = len(ITEMS)
SIZE = np.array([a * b for _, (a, b), _ in ITEMS])
VALUES = dict(relic=200, cardR=120, cardU=60, cardC=25, rpot=60, cpot=30, bgold=30, gold=10, curse=-150)
POS = {}
for _, sz, _ in ITEMS:
    if sz in POS: continue
    pl, ms = [], []
    for px in range(N - sz[0] + 1):
        for py in range(N - sz[1] + 1):
            m = np.zeros(NC, bool)
            for i in range(sz[0]):
                for j in range(sz[1]): m[_cid(px + i, py + j)] = True
            pl.append((px, py)); ms.append(m)
    POS[sz] = (pl, np.array(ms), np.array(ms, np.float32))
BIG = np.zeros((NC, NC), bool)
for _x in range(N):
    for _y in range(N):
        for _dx in (-1, 0, 1):
            for _dy in (-1, 0, 1):
                if 0 <= _x + _dx < N and 0 <= _y + _dy < N: BIG[_cid(_x, _y), _cid(_x + _dx, _y + _dy)] = True
SMALL = np.eye(NC, dtype=bool)
RELIC_CELLS = np.array([[_cid(px + i, py + j) for i in range(4) for j in range(4)] for px, py in POS[(4, 4)][0]])

def _mincover_table():
    """4x4 遗物剩余未揭格的样式（16 位）→ 最少几次 3x3 大占卜才能全揭开"""
    wins = set()
    for cx in range(-1, 5):
        for cy in range(-1, 5):
            m = sum(1 << (i * 4 + j) for i in range(4) for j in range(4) if abs(i - cx) <= 1 and abs(j - cy) <= 1)
            if m: wins.add(m)
    best = np.full(1 << 16, 9, np.int8); best[0] = 0; level = {0}; idx = np.arange(1 << 16)
    for k in range(1, 5):
        level = {u | w for u in level for w in wins}
        g = np.zeros(1 << 16, bool); g[list(level)] = True
        for b in range(16):
            sel = (idx & (1 << b)) == 0
            g[idx[sel]] |= g[idx[sel] | (1 << b)]
        best[(best == 9) & g] = k
    return best
MINCOVER = _mincover_table()

def _mask(posidx, k): return POS[ITEMS[k][1]][1][posidx[:, k]]

def _sis(cons, L, K, rng, q=0.8):
    occ = np.zeros((K, NC), bool); occ[:, CLEARED] = True; cov = np.zeros((K, NC), bool)
    logw = np.zeros(K); alive = np.ones(K, bool); posidx = np.zeros((K, NI), int)
    last = np.full(NC, -1)
    for k, (_, sz, _) in enumerate(ITEMS): last[POS[sz][1][cons[k]].any(0) & L] = k
    if (L & (last < 0)).any(): return posidx, np.full(K, -np.inf)
    for k, (_, sz, _) in enumerate(ITEMS):
        masks, mf = POS[sz][1], POS[sz][2]
        free = (occ.astype(np.float32) @ mf.T) == 0
        valid = free & cons[k][None, :]
        U = L[None, :] & ~cov; R = U & (last == k)[None, :]
        base = valid & ((R.astype(np.float32) @ mf.T) == R.sum(1)[:, None])      # 必须盖住只剩我能盖的碎片
        cand = base & ((U.astype(np.float32) @ mf.T) > 0)
        nb, nc = base.sum(1), cand.sum(1)
        qq = np.where(nc > 0, q, 0.0)
        prob = qq[:, None] * cand / np.maximum(nc, 1)[:, None] + (1 - qq)[:, None] * base / np.maximum(nb, 1)[:, None]
        alive &= nb > 0; prob[~alive] = 0; prob[~alive, 0] = 1
        cum = prob.cumsum(1); p = np.minimum((cum < rng.random(K)[:, None] * cum[:, -1:]).sum(1), prob.shape[1] - 1)
        logw += -np.log(np.maximum(free.sum(1), 1)) - np.log(np.maximum(prob[np.arange(K), p], 1e-300))
        posidx[:, k] = p; occ |= masks[p]; cov |= masks[p]
    alive &= ~(L[None, :] & ~cov).any(1)
    return posidx, np.where(alive, logw, -np.inf)

def _logN(posidx):
    K = len(posidx); occ = np.zeros((K, NC), bool); occ[:, CLEARED] = True; out = np.zeros((K, NI))
    for j in range(NI):
        out[:, j] = np.log(np.maximum(((occ.astype(np.float32) @ POS[ITEMS[j][1]][2].T) == 0).sum(1), 1))
        occ |= _mask(posidx, j)
    return out

def _mh(posidx, cons, L, rng, sweeps=3):
    """Metropolis：每次把一件物品挪到与可见信息、其他物品相容的位置；目标 = 游戏的顺序放置先验"""
    K = len(posidx); posidx = posidx.copy(); logN = _logN(posidx)
    for _ in range(sweeps):
        for k in rng.permutation(NI):
            mf = POS[ITEMS[k][1]][2]
            occ_o = np.zeros((K, NC), bool); occ_o[:, CLEARED] = True
            for j in range(NI):
                if j != k: occ_o |= _mask(posidx, j)
            need = L[None, :] & ~occ_o
            cand = (((occ_o.astype(np.float32) @ mf.T) == 0) & cons[k][None, :]
                    & ((need.astype(np.float32) @ mf.T) == need.sum(1)[:, None]))
            nc = cand.sum(1); r = (rng.random(K) * np.maximum(nc, 1)).astype(int) + 1
            newp = np.minimum((cand.cumsum(1) < r[:, None]).sum(1), cand.shape[1] - 1)
            prop = posidx.copy(); prop[:, k] = newp
            occ = np.zeros((K, NC), bool); occ[:, CLEARED] = True
            for j in range(k + 1): occ |= _mask(prop, j)
            nl = logN.copy()
            for j in range(k + 1, NI):
                nl[:, j] = np.log(np.maximum(((occ.astype(np.float32) @ POS[ITEMS[j][1]][2].T) == 0).sum(1), 1))
                occ |= _mask(prop, j)
            acc = (nc > 0) & (np.log(rng.random(K) + 1e-300) < -(nl[:, k + 1:].sum(1) - logN[:, k + 1:].sum(1)))
            posidx[acc, k] = newp[acc]; logN[acc] = nl[acc]
    return posidx

def choose(state, values=None, K=150, B=15.0, eps=0.5, first_click=True):
    left = int(state.get('divinations_left') or 0)
    if left <= 0: raise ValueError('No remaining crystal divination')
    if state.get('width') != N or state.get('height') != N: raise ValueError('Unexpected crystal board size')
    hidden = np.zeros(NC, bool); lab = np.full(NC, -1)
    for c in state.get('cells') or []:
        i = _cid(int(c['x']), int(c['y']))
        hidden[i] = bool(c.get('hidden'))
        if not hidden[i]: lab[i] = CLASS.get(c.get('visible_item'), 0) if c.get('visible_item') else 0
    if (hidden & CLEARED).any() or not hidden.any(): raise ValueError('Unexpected crystal board')
    if first_click and hidden.sum() == (~CLEARED).sum():          # 开局：6 次先点正中找遗物；3 次点外圈中点（仿真最优）
        x, y = (5, 5) if left >= 4 else (2, 5)
        return 'crystal_click', {'x': x, 'y': y, 'tool': 'Big'}
    V = np.array([(values or VALUES)[s] for s, _, _ in ITEMS], float)
    seed = int.from_bytes(hashlib.sha256(hidden.tobytes() + lab.tobytes() + bytes([left])).digest()[:8], 'little')
    rng = np.random.default_rng(seed)                               # 同一局面同一决定，便于配对实验
    rev = ~hidden
    cons = [~(POS[sz][1] & (rev & (lab != cls))[None, :]).any(1) for _, sz, cls in ITEMS]
    L = lab > 0
    P_, W_ = [], []
    for _ in range(15):
        p_, w_ = _sis(cons, L, 300, rng); P_.append(p_); W_.append(w_)
        if sum(np.isfinite(w).sum() for w in W_) >= 5: break
    posidx = np.concatenate(P_); lw = np.concatenate(W_); ok = np.isfinite(lw)
    if not ok.any(): raise ValueError('Crystal board inconsistent with public generation rules')
    w = np.exp(lw[ok] - lw[ok].max()); post = _mh(posidx[rng.choice(np.flatnonzero(ok), size=K, p=w / w.sum())], cons, L, rng)
    im = np.zeros((K, NI, NC), np.float32)
    for k in range(NI): im[:, k] = _mask(post, k)
    centers = np.flatnonzero(hidden)                                # 真实界面只能点还被雾盖着的格
    acts = [(c, 'Big') for c in centers] + [(c, 'Small') for c in centers]
    Wm = np.array([BIG[c] if t == 'Big' else SMALL[c] for c, t in acts])
    Hh = (Wm & hidden[None, :]).astype(np.float32)
    R0 = im @ hidden.astype(np.float32)
    rem = R0[:, :, None] - (im.reshape(K * NI, NC) @ Hh.T).reshape(K, NI, len(acts))
    imm = np.einsum('kia,i->ka', ((R0[:, :, None] > 0) & (rem < 0.5)).astype(np.float32), V)
    kp = left - 1; fut = np.full_like(imm, kp * B)
    if kp > 0:                                                      # 后续价值：已露头的物品各需 1 次（遗物查表），空余次数按盲点 B 算
        located = (rem > 0.5) & (rem < SIZE[None, :, None] - 0.5)
        gain = np.maximum(V - B, 0)[None, :, None] * located; gain[:, 0, :] = 0
        cs = np.concatenate([np.zeros((K, 1, len(acts))), np.cumsum(-np.sort(-gain, axis=1), axis=1)], axis=1)
        best = cs[:, min(kp, NI), :].copy()
        pat = ((hidden[None, :] & ~Wm)[:, RELIC_CELLS[post[:, 0]]] * (1 << np.arange(16))).sum(2).T
        cr = MINCOVER[pat]
        for c in range(1, min(kp, 4) + 1):
            m = located[:, 0, :] & (cr == c)
            best = np.where(m, np.maximum(best, V[0] - c * B + cs[:, kp - c, :]), best)
        fut += best
    Q = (imm + fut).mean(0) + eps * Hh.sum(1)
    c, tool = acts[int(np.argmax(Q))]
    x, y = divmod(int(c), N)
    return 'crystal_click', {'x': x, 'y': y, 'tool': tool}
