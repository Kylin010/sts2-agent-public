"""遗物估值（tools/train_relic_model.py 从社区商店的买 / 不买记录学的）：这件遗物在当前牌组下值不值得买。
logit = bias + a[遗物] + w[遗物] · m(牌组) + 幕修正 + 金币项（按「手上有 200 金」算）；m(牌组) 和选牌模型共用同一套牌向量。
没见过的遗物返回 None。纯 Python，不依赖 numpy。
"""
import json, os
from policy import pickmodel

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/relic_model.json'
M = None


def _load():
    global M, PATH
    from params import P
    want = f"{HERE}/{P.get('relic_model_file', 'data/relic_model.json')}"          # 模型文件可以用 --set relic_model_file=... 换（A/B 测试用）
    if M is not None and want != PATH: M = None
    PATH = want
    if M is None and os.path.exists(PATH):
        d = json.load(open(PATH)); M = dict(d, idx={k: i for i, k in enumerate(d['vocab'])})
    return M


def logit(relic_id, deck_ids, act):
    m = _load()
    if not m or relic_id not in m['idx'] or not pickmodel.available(): return None
    i = m['idx'][relic_id]; mv, _ = pickmodel._deck_vec(deck_ids)
    a = min(max(int(act or 1), 1), 3) - 1
    return m['bias'][0] + m['a'][i] + sum(x * y for x, y in zip(m['W'][i], mv)) + m['c'][a] + m['g'][0] * 1.0
