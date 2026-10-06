"""选牌模型（tools/train_pick_model.py 从社区赢家的选择学出来的）：给「在当前牌组下拿这张牌」打效用分。

U(牌) = 基础价值 + 本幕修正 + 重复惩罚 × 已有张数 + 联动（这张牌需要的 · 牌组提供的）+ 牌组大小修正
U(跳过) = 本幕跳过倾向 + 牌组大小修正
模型文件不存在时 available() 返回 False，选牌退回旧的打分。
"""
import json, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/pick_model.json'
M = None


def _load():
    global M, PATH
    from params import P
    want = f"{HERE}/{P.get('pick_model_file', 'data/pick_model.json')}"          # 模型文件可以用 --set pick_model_file=... 换（A/B 测试用）
    if M is not None and want != PATH: M = None
    PATH = want
    if M is None and os.path.exists(PATH):
        d = json.load(open(PATH))
        M = {'idx': {c: i for i, c in enumerate(d['vocab'])}, 'didx': {c: i for i, c in enumerate(d['deck_vocab'])},
             'pool': d.get('pool', 'mean'), **{k: d[k] for k in ('types', 'a', 'b', 'dup', 'u', 'v', 'size_w', 'skip0', 'skip1')}}   # 纯 Python，不依赖 numpy
    return M


def available():
    return _load() is not None


def _deck_vec(deck_ids):
    m = _load(); vec = [0.0] * len(m['v'][0]); n = 0
    for c in deck_ids:
        c = str(c).replace('CARD.', '').rstrip('+')
        if not c.startswith(('R:', 'B:')): n += 1        # R: 遗物、B: 本幕 Boss（也算进牌组画像，但不算牌组大小）
        if c in m['didx']:
            for j, x in enumerate(m['v'][m['didx'][c]]): vec[j] += x
    div = max(n, 1) if m.get('pool', 'mean') == 'mean' else 10.0     # sum：求和（固定除以 10 只是缩放）
    return [x / div for x in vec], n


def utility(card_id, card_type, deck_ids, act):
    """这张牌的效用；模型没见过这张牌返回 None"""
    m = _load(); c = str(card_id).replace('CARD.', '').rstrip('+')
    if c not in m['idx']: return None
    i = m['idx'][c]; mv, n = _deck_vec(deck_ids)
    same = sum(1 for x in deck_ids if str(x).replace('CARD.', '').rstrip('+') == c)
    t = m['types'].index(card_type) if card_type in m['types'] else len(m['types']) - 1
    a = min(max(int(act or 1), 1), 3) - 1
    return float(m['a'][i] + m['b'][i][a] + m['dup'][i] * same + sum(x * y for x, y in zip(m['u'][i], mv)) + m['size_w'][t] * n / 25.0)


def skip_utility(deck_ids, act):
    m = _load(); a = min(max(int(act or 1), 1), 3) - 1
    n = sum(1 for x in deck_ids if not str(x).startswith(('R:', 'B:')))
    return float(m['skip0'][a] + m['skip1'][0] * n / 25.0)


def with_relics(deck_ids, st):
    """牌组 id 列表 + 玩家遗物（R: 前缀）+ 本幕 Boss（B: 前缀，开局就看得到），给选牌模型的「牌组画像」用"""
    boss = ((st.get('context') or {}).get('boss') or {}).get('id')
    return (list(deck_ids) + ['R:' + str(r.get('id') or '').replace('RELIC.', '') for r in (st.get('player') or {}).get('relics') or []]
            + (['B:' + str(boss)] if boss else []))
