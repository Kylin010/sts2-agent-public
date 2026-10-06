"""选牌蒸馏：
老师 = 选牌实打（policy/simeval.py，拿候选牌组在新种子上模拟打本幕 / 下一幕的 Boss 和精英）。
学生 = 这里的线性函数：只看玩家看得见的东西（这张牌、牌组构成、第几幕、本幕 Boss、第一幕章节），预测实打会给它加多少分。
训练：tools/pick_distill.py → data/pick_distill.json。下场打牌时不再调用引擎，按 pick_distill_w 把预测分加到选牌分上。
"""
import json, os
from params import P
from policy import kb

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_M = {}
TAGS = ['damage', 'power', 'draw', 'block', 'energy', 'vuln', 'aoe', 'strength', 'self_damage', 'multi_hit', 'exhaust_fuel',
        'block_payoff', 'exhaust_payoff', 'exhaust_engine', 'scaling', 'weak']


def norm(c):
    return str(c or '').replace('CARD.', '')


def deck_profile(deck):
    """牌组构成：每种标签占的比例（不算基础打击 / 防御），和牌组张数"""
    ids = [norm(d).rstrip('+') for d in deck]
    real = [d for d in ids if d not in ('STRIKE_IRONCLAD', 'DEFEND_IRONCLAD')]
    n = max(len(ids), 1)
    prof = {t: sum(1 for d in real if t in kb.tags(d)) / n for t in TAGS}
    return prof, len(ids), ids


def features(card, deck, act, boss, act_name):
    """一个选项的特征（稀疏字典）。card='SKIP' 表示跳过"""
    c = norm(card); up = c.endswith('+'); b = c.rstrip('+')
    f = {}
    prof, n, ids = deck_profile(deck)
    if b == 'SKIP':
        f['SKIP'] = 1.0; f[f'SKIP|a{act}'] = 1.0; f['SKIP|n'] = n / 25.0
        return f
    f[f'c:{b}'] = 1.0; f[f'c:{b}|a{act}'] = 1.0
    if up: f['up'] = 1.0
    f['dup'] = ids.count(b) * 1.0; f[f'dup|c:{b}'] = ids.count(b) * 1.0
    t = kb.tags(b)
    for tg in t:
        f[f't:{tg}'] = 1.0; f[f't:{tg}|a{act}'] = 1.0
        if boss: f[f't:{tg}|B:{boss}'] = 1.0
        if act == 1 and act_name: f[f't:{tg}|A:{act_name}'] = 1.0
        for dt, v in prof.items():
            if v: f[f't:{tg}|d:{dt}'] = v
    f['n'] = n / 25.0
    return f


def _model():
    path = f"{HERE}/{P.get('pick_distill_file', 'data/pick_distill.json')}"
    if _M.get('path') != path:
        _M['path'] = path
        _M['w'] = json.load(open(path))['w'] if os.path.exists(path) else None
    return _M['w']


def score(card, st):
    """预测实打会给这个选项加的分（同一次选牌里各选项相减才有意义）"""
    w = _model()
    if not w: return 0.0
    ctx = st.get('context') or {}
    deck = [norm(c.get('id')) + ('+' if c.get('upgraded') else '') for c in (st.get('player') or {}).get('deck') or []]
    f = features(card, deck, ctx.get('act') or 1, (ctx.get('boss') or {}).get('id'), ctx.get('act_name'))
    return sum(w.get(k, 0.0) * v for k, v in f.items())
