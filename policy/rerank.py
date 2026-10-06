"""重排函数：推演老师蒸馏成「不开引擎」的打分。

推演的做法：规划器给出前几名出法，用引擎各打到底几遍，挑结局最好的。这里把「打到底的结局值」学成一个函数：
特征 = 规划器对这组牌的打分明细（这回合打掉多少血、挨多少、杀几个、能力 / 抽牌估值、打完敌人还剩几成血……）
     + 每张牌一个偏置 + 按遭遇复制一份（每个精英 / Boss 一套专属权重）+ 按遭遇 × 敌人这回合的招再复制一份（阶段函数）。
训练（tools/train_rerank.py）：老师记录（search_teach_log）里每个局面前 8 种出法的推演结局值 v，
同一局面内减去平均值后做岭回归——只学「同一局面里哪种出法更好」。下场时 search_on=false，只在规划器的候选里按学到的值挑。
"""
import json, os
from params import P
from policy import foresight
from policy.knowledge import cid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_M = {'f': None, 'm': None}
CORE = ('sc', 'dealt', 'killed', 'unb', 'unb_hp', 'dead', 'ends', 'powers', 'draw', 'thresh', 'e_frac', 'over', 'en_left', 'n', 'blk_cards',
        'ttk', 'fut_in', 'fut_str')


def model():
    f = f"{HERE}/data/{P.get('rerank_file') or 'rerank.json'}"
    if _M['f'] != f:
        _M['m'] = json.load(open(f)) if os.path.exists(f) else None; _M['f'] = f
    return _M['m']


def enc_of(st):
    return str((st.get('context') or {}).get('encounter') or '').replace('ENCOUNTER.', '')


def phase(ctx):
    for e in ctx['mains']:
        mv = foresight.identify(e)
        if mv: return mv
    return None


def parts(combo, ctx, evaluate):
    ctx['_parts'] = {}
    try:
        evaluate(combo, ctx)
        return ctx['_parts'].get('best')
    finally:
        ctx.pop('_parts', None)


_D = {}


def deck_dpt(ctx):
    from policy import deckeval
    dk = ctx.get('deck') or []
    if not dk: return max(ctx.get('my_dpt', 1.0), 1.0)
    k = tuple(sorted(cid(c) + ('+' if c.get('upgraded') else '') for c in dk))
    if k not in _D:
        if len(_D) > 500: _D.clear()
        _D[k] = max(deckeval.evaluate_mc(dk)[0], 1.0)
    return _D[k]


def _amt(e, word):
    return sum(p.get('amount') or 0 for p in e.get('powers') or [] if word in str(p.get('name', '')).lower())


def feats(combo, ctx, pt, enc, mv, sc):
    """sc = 规划器给这组牌的最终分（含出牌模仿层），pt = 打分明细"""
    hp = max(ctx['hp'], 1)
    e0 = sum((e.get('max_hp') or e.get('hp') or 1) for e in ctx['mains']) or 1
    f = {'sc': sc / 10, 'dealt': pt['dealt'] / 10, 'killed': float(pt['killed']), 'unb': pt['unblocked'] / 10,
         'unb_hp': min(pt['unblocked'] / hp, 2.0), 'dead': float(pt['left'] <= 0), 'ends': pt['ends'], 'powers': pt['powers'] / 10,
         'draw': pt['draw'] / 10, 'thresh': pt['thresh'] / 10, 'e_frac': pt['e_after'] / e0,
         'over': max(0.0, pt['block'] - pt['incoming']) / 10, 'en_left': pt['unspent'] / 3, 'n': float(len(combo)),
         'blk_cards': float(sum(1 for c in combo if ((c.get('stats') or {}).get('block') or 0) > 0))}
    # 多回合的账（不开引擎，粗估）：打完这回合还要几回合打死（剩余血 ÷ 牌组每回合输出），这几回合大概挨多少，
    # 敌人每回合涨力量的话越拖越疼（地精佣兵、软泥纺纱者：规划器只看一回合，老想慢慢磨，推演显示会被拖死）
    D = deck_dpt(ctx)
    ttk = 0.0 if pt['ends'] else min(10.0, pt['e_after'] / D)
    inc = max(ctx['incoming'], 1.0)
    srate = sum(max(0.0, _amt(e, 'strength')) for e in ctx['mains']) / max(ctx.get('round', 1) - 1, 1)
    f['ttk'] = ttk; f['fut_in'] = ttk * inc / 10; f['fut_str'] = srate * ctx.get('hits_in', 1) * ttk * ttk / 2 / 10
    for k in CORE:
        v = f[k]
        if enc: f[f'{enc}|{k}'] = v
        if enc and mv: f[f'{enc}|{mv}|{k}'] = v
    for c in combo:
        k = 'c:' + cid(c); f[k] = f.get(k, 0.0) + 1.0
        if enc: f[f'{enc}|{k}'] = f.get(f'{enc}|{k}', 0.0) + 1.0
    return f


def choose(cands, ctx, st, mem):
    """cands = combat.candidates() 的 [(规划器分, 组合)]；返回学到的值最高的组合（没有模型返回 None）"""
    m = model()
    if not m or len(cands) < 2: return None
    from policy.combat import evaluate
    th = m['theta']; enc = enc_of(st); mv = phase(ctx)
    best = None
    for sc, combo in cands:
        pt = parts(combo, ctx, evaluate)
        if pt is None: continue
        v = sum(th.get(k, 0.0) * x for k, x in feats(combo, ctx, pt, enc, mv, sc).items())
        if best is None or v > best[0]: best = (v, combo)
    return best[1] if best else None
