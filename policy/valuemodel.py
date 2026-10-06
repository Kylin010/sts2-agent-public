"""胜率预测（tools/train_value_model.py 训练的因子分解机）：局面 → 这局最终能赢的概率。
做选择时把每个选项会变成的局面都算一遍，挑胜率最高的。
纯 Python，不依赖 numpy。练习模式（999 血）下血量特征会截到正常范围，避免超出训练数据。
"""
import json, math, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/value_model.json'
M = None


def _load():
    global M
    if M is None and os.path.exists(PATH):
        d = json.load(open(PATH))
        M = {'idx': {k: i + 1 for i, k in enumerate(d['vocab'])}, 'w0': d['w0'][0], 'W': d['W'], 'V': d['V']}
    return M


def available():
    return _load() is not None


norm = lambda x: str(x or '').replace('CARD.', '').replace('RELIC.', '').rstrip('+')


def state_of(st):
    """从引擎状态取出模型要的局面：{deck: [(id, 升级?)], relics, hp, max_hp, gold, pots, act, floor}"""
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    act = min(max(int(ctx.get('act') or 1), 1), 3)
    return {'deck': [(norm(c.get('id')), bool(c.get('upgraded'))) for c in pl.get('deck') or []],
            'relics': [norm(r.get('id')) for r in pl.get('relics') or []],
            'hp': pl.get('hp', 1), 'max_hp': pl.get('max_hp', 80), 'gold': pl.get('gold', 0),
            'pots': sum(1 for p in pl.get('potions') or [] if p and p.get('name')), 'act': act,
            'floor': (act - 1) * 17 + int(ctx.get('floor') or 0)}


def _feats(s):
    f = {}
    for c, up in s['deck']:
        f[f'c:{c}'] = f.get(f'c:{c}', 0) + 0.5
        if up: f[f'u:{c}'] = f.get(f'u:{c}', 0) + 0.5
    for k in list(f): f[k] = min(f[k], 3.0)
    for r in s['relics']: f[f'r:{r}'] = 1.0
    mx = min(s['max_hp'], 120); hp = min(s['hp'], mx) if s['max_hp'] <= 120 else s['hp'] / s['max_hp'] * mx   # 练习模式按比例折回正常范围
    f.update({'hp_frac': hp / max(mx, 1), 'hp': hp / 80.0, 'max_hp': mx / 80.0, 'gold': min(s['gold'], 600) / 300.0,
              'pots': s['pots'] / 3.0, 'size': len(s['deck']) / 30.0, f"act{s['act']}": 1.0, 'floor': s['floor'] / 50.0})
    return f


def win_prob(s):
    m = _load(); z = m['w0']; K = len(m['V'][0]); acc = [0.0] * K; sq = 0.0
    for k, x in _feats(s).items():
        i = m['idx'].get(k)
        if not i or not x: continue
        z += m['W'][i] * x
        v = m['V'][i]
        for j in range(K): acc[j] += v[j] * x
        sq += sum(t * t for t in v) * x * x
    z += 0.5 * (sum(t * t for t in acc) - sq)
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def with_card(s, card_id, upgraded=False):
    return dict(s, deck=s['deck'] + [(norm(card_id), upgraded)])


def without_card(s, card_id):
    d = list(s['deck']); c = norm(card_id)
    for i, (x, up) in enumerate(d):
        if x == c and not up: d.pop(i); break
    else:
        for i, (x, up) in enumerate(d):
            if x == c: d.pop(i); break
    return dict(s, deck=d)


def upgraded(s, card_id):
    d = list(s['deck']); c = norm(card_id)
    for i, (x, up) in enumerate(d):
        if x == c and not up: d[i] = (x, True); break
    return dict(s, deck=d)
