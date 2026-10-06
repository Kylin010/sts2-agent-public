"""大版战斗价值网络：局面 → 从这里到战斗结束还要掉多少血（死了另加罚分）。

和 policy/combatvalue.py（一层 16 个神经元、十几个汇总数字）的区别：输入逐张看牌（手牌 / 抽牌堆 / 弃牌堆 / 消耗堆分开数）、
每种怪的血和意图、双方能力、遗物、药水，约 1500 个数。
数据：推演模拟记录（search._compact 格式，带这次模拟的结局）——训练脚本 tools/nn_combat_train.py。
运行时只用 numpy 前向（不依赖 torch）；模型文件 data/<cvnet_file>（默认 cvnet.npz）。
"""
import os, re
import numpy as np
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTENT_TYPES = ['attack', 'buff', 'defend', 'debuff', 'summon', 'heal', 'deathblow', 'statuscard', 'carddebuff', 'stun', 'escape', 'sleep']
ROOMS = ['Monster', 'Elite', 'Boss']
GLOBAL = ['act1', 'act2', 'act3', 'room_m', 'room_e', 'room_b', 'round', 'energy', 'hp', 'max_hp', 'hp_frac', 'block',
          'n_hand', 'n_draw', 'n_discard', 'n_exhaust', 'n_potions', 'n_enemies', 'ehp_total', 'inc_total', 'inc_max', 'n_attack',
          'up_hand', 'up_draw', 'up_discard']
_M = {}


def base(card):
    """牌规格串 ID[+][!属性][%负面][#附魔][@费用] → (基础 ID, 是否升级)"""
    s = str(card or '').replace('CARD.', '')
    b = re.split(r'[+#!%@]', s, 1)[0]
    return b, '+' in s.split('#')[0].split('%')[0].split('!')[0]


def vocab_from(snaps):
    """从一批局面里收集词表（牌 / 怪 / 能力 / 遗物 / 药水）"""
    v = {k: set() for k in ('card', 'mon', 'pw', 'rel', 'pot')}
    for s in snaps:
        for k in ('h', 'd', 'x', 'z'):
            for c in s['h' if k == 'h' else k]: v['card'].add(base(c)[0])
        for p in s['pp']: v['pw'].add(p[0])
        for r in s['rl']: v['rel'].add(r[0])
        for p in s['po']: v['pot'].add(p)
        for e in s['en']:
            v['mon'].add(e[0])
            for p in e[5]: v['pw'].add(p[0])
    return {k: sorted(x) for k, x in v.items()}


def layout(vocab):
    """特征位置表：名字 → 下标"""
    names = list(GLOBAL) + [f'it:{t}' for t in INTENT_TYPES]
    for loc in ('h', 'd', 'x', 'z'):
        names += [f'{loc}:{c}' for c in vocab['card']]
    names += [f'pp:{p}' for p in vocab['pw']] + [f'ep:{p}' for p in vocab['pw']]
    names += [f'rel:{r}' for r in vocab['rel']] + [f'pot:{p}' for p in vocab['pot']]
    names += [f'mhp:{m}' for m in vocab['mon']] + [f'mn:{m}' for m in vocab['mon']] + [f'minc:{m}' for m in vocab['mon']]
    return {n: i for i, n in enumerate(names)}


def encode(s, idx):
    """一个紧凑局面 → (下标列表, 值列表)；词表里没有的牌 / 怪 / 能力直接忽略"""
    ix, val = [], []

    def put(name, v):
        j = idx.get(name)
        if j is not None and v: ix.append(j); val.append(float(v))
    ctx = s.get('c') or [None, None, None, None]
    act, room = ctx[0], ctx[2]
    if act in (1, 2, 3): put(f'act{act}', 1)
    if room in ROOMS: put({'Monster': 'room_m', 'Elite': 'room_e', 'Boss': 'room_b'}[room], 1)
    hp, mx, blk = (s.get('p') or [0, 1, 0])[:3]
    put('round', min(s.get('r') or 0, 20) / 10); put('energy', (s.get('e') or 0) / 3)
    put('hp', (hp or 0) / 50); put('max_hp', (mx or 0) / 50); put('hp_frac', (hp or 0) / max(mx or 1, 1)); put('block', (blk or 0) / 20)
    for loc, name in (('h', 'n_hand'), ('d', 'n_draw'), ('x', 'n_discard'), ('z', 'n_exhaust')):
        cs = s.get(loc) or []
        put(name, len(cs) / 10)
        cnt = {}
        ups = 0
        for c in cs:
            b, up = base(c); cnt[b] = cnt.get(b, 0) + 1; ups += up
        for b, n in cnt.items(): put(f'{loc}:{b}', n)
        if loc in ('h', 'd', 'x'): put(f'up_{ {"h": "hand", "d": "draw", "x": "discard"}[loc] }', ups / 5)
    put('n_potions', len(s.get('po') or []))
    for p in s.get('pp') or []: put(f'pp:{p[0]}', (p[1] or 0) / 5)
    for r in s.get('rl') or []: put(f'rel:{r[0]}', 1)
    for p in s.get('po') or []: put(f'pot:{p}', 1)
    en = s.get('en') or []
    put('n_enemies', len(en))
    ehp = inc = incmax = natt = 0
    mhp, mn, minc, eps, its = {}, {}, {}, {}, {}
    for e in en:
        mid, h = e[0], e[1] or 0
        ehp += h + (e[3] or 0)
        mhp[mid] = mhp.get(mid, 0) + h; mn[mid] = mn.get(mid, 0) + 1
        dmg = 0
        for t, d, hits in e[4] or []:
            its[t] = its.get(t, 0) + 1
            if t in ('attack', 'deathblow') and d: dmg += d * (hits or 1)
        inc += dmg; incmax = max(incmax, dmg); natt += dmg > 0
        minc[mid] = minc.get(mid, 0) + dmg
        for p in e[5] or []: eps[p[0]] = eps.get(p[0], 0) + (p[1] or 0)
    put('ehp_total', ehp / 100); put('inc_total', inc / 20); put('inc_max', incmax / 20); put('n_attack', natt)
    for t, n in its.items(): put(f'it:{t}', n)
    for m, v in mhp.items(): put(f'mhp:{m}', v / 100)
    for m, v in mn.items(): put(f'mn:{m}', v)
    for m, v in minc.items(): put(f'minc:{m}', v / 20)
    for p, v in eps.items(): put(f'ep:{p}', v / 5)
    return ix, val


def _model():
    path = f"{HERE}/data/{P.get('cvnet_file', 'cvnet.npz')}"
    if _M.get('path') != path:
        _M['path'] = path; _M['m'] = None
        if os.path.exists(path):
            z = np.load(path, allow_pickle=True)
            _M['m'] = {k: z[k] for k in z.files}
            _M['idx'] = {n: i for i, n in enumerate(z['names'].tolist())}
    return _M.get('m')


def available():
    return _model() is not None


def predict_compact(s):
    """紧凑局面 → 预测之后掉血（含死亡罚分）"""
    m = _model()
    if m is None: return None
    ix, val = encode(s, _M['idx'])
    x = np.zeros(len(_M['idx']), dtype=np.float32); x[ix] = val
    x = (x - m['mu']) / m['sd']
    h = x
    for i in range(int(m['nlayers'])):
        h = h @ m[f'W{i}'] + m[f'b{i}']
        if i < int(m['nlayers']) - 1: h = np.maximum(h, 0)
    return float(h[0] * m['ysd'] + m['ymu'])


def predict(st):
    """完整局面（引擎状态）→ 预测之后掉血"""
    from policy.search import _compact
    return predict_compact(_compact(st))
