"""别家角色的牌（色彩哲学家事件、万花筒、棱彩宝石）：按研究文档 docs/色彩哲学家.md 的分档表选，不走模型和模拟实打。

为什么单独处理（研究代理定位的原因）：别家牌不在知识库，选牌模型一律给 −0.5，战斗规划器也不会打这些牌，
模拟实打（2 个样本）噪声比牌的价值大 → 三次全跳过。

规则（文档 4.2、0 节第 4 条）：
  选色：默认 蓝 ≥ 绿 > 橙 > 粉；有消耗引擎（≥2 张）→ 橙第一；缺格挡 → 绿第一；缺群伤 → 蓝第一
  选牌：S / A 档拿（挑档最高的）；B 档只在缺这类东西时拿（群伤牌且群伤不够、格挡牌且格挡不够），牌组 > 25 张不拿 B；C / X（表里没有）不拿
"""
import json, os
from params import P
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_T = {}
_TEXT = {}
EXHAUST_ENGINE = {'FEEL_NO_PAIN', 'DARK_EMBRACE', 'ASHEN_STRIKE', 'BURNING_PACT', 'SECOND_WIND', 'FIEND_FIRE'}
COLOR_OPT = {'DEFECT': '蓝', 'SILENT': '绿', 'REGENT': '橙', 'NECROBINDER': '粉'}
RANK = {'S': 3, 'A': 2, 'B': 1}


def tiers():
    if not _T:
        try: _T.update(json.load(open(f'{HERE}/data/offclass_tiers.json')))
        except Exception: pass
    return _T


def feats(cid):
    """别家牌的特征（data/offclass_cards.json：从卡牌数据里提取的「打所有敌人」「给格挡」）"""
    if not _TEXT:
        try: _TEXT.update(json.load(open(f'{HERE}/data/offclass_cards.json')))
        except Exception: pass
    return _TEXT.get(cid)


def is_offclass(cid):
    from policy import kb
    return bool(cid) and not kb.card(cid) and (cid in tiers() or feats(cid) is not None)


def _deck_ids(st):
    return [str(c.get('id', '')).replace('CARD.', '') for c in (st.get('player') or {}).get('deck') or []]


def _needs(st):
    """缺群伤 / 缺格挡"""
    from policy import elites, deckeval
    pl = st.get('player') or {}; act = (st.get('context') or {}).get('act', 1)
    ev = deckeval.evaluate(pl.get('deck') or [])
    blk_need = {1: P['block_target_act1'], 2: P['block_target_act2'], 3: P['block_target_act3']}.get(act, 18)
    return elites.aoe_capacity(st) < 0.5, ev['block_per_turn'] < blk_need


def choose_color(st, opts):
    """色彩哲学家：返回选项下标；不是这个事件返回 None"""
    key = lambda o: str(o.get('text_key') or '')
    if not any('COLORFUL_PHILOSOPHERS' in key(o) for o in opts): return None
    by = {c: o['index'] for o in opts for c in COLOR_OPT if f'.{c}' in key(o) or key(o).endswith(c)}
    order = ['DEFECT', 'SILENT', 'REGENT', 'NECROBINDER']
    deck = set(_deck_ids(st))
    lack_aoe, lack_blk = _needs(st)
    if len(EXHAUST_ENGINE & deck) >= 2: order = ['REGENT', 'DEFECT', 'SILENT', 'NECROBINDER']
    elif lack_blk and not lack_aoe: order = ['SILENT', 'DEFECT', 'REGENT', 'NECROBINDER']
    for c in order:
        if c in by: return by[c]
    return None


def choose_reward(st, mem=None):
    """选牌奖励里全是别家牌时按分档表选：返回下标 / None（跳过）；不是别家牌的奖励返回 'n/a'"""
    if not P.get('offclass_rules', True): return 'n/a'
    cards = st.get('cards') or []
    ids = [str(c.get('id', '')).replace('CARD.', '') for c in cards]
    if not cards or not all(is_offclass(i) for i in ids): return 'n/a'
    T = tiers(); deck = _deck_ids(st)
    lack_aoe, lack_blk = _needs(st)
    best, bi = 0, None
    for c, i in zip(cards, ids):
        t = T.get(i, {}).get('tier')
        r = RANK.get(t, 0)
        if t == 'B':
            f = feats(i) or {}
            useful = (lack_aoe and f.get('aoe')) or (lack_blk and f.get('block'))
            if not useful or len(deck) > 25: r = 0
        if r > best: best, bi = r, c['index']
    if mem is not None: mem.setdefault('offclass_log', []).append({'opts': ids, 'pick': bi})
    return bi
