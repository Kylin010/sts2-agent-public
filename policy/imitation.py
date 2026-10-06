"""出牌模仿层：从人类回放学一组修正权重，加在规划器给每个出牌组合的分数上（10/2）。

背景：同牌组同一场战斗，脚本比人类多掉 30% 的血，普通战多一倍；回放里人类打防御的次数是脚本的两倍，
整组出牌和人类一致的回合只有 18%。以前的「出牌偏好校准」只对齐每张牌的平均打出比例，不看局面；
这里的特征看局面（来伤多少、挡完还漏多少、挡多了多少、打了多少伤害、用了几费……），再加每张牌一个偏置。
训练：tools/train_imitation.py —— 每个人类回合，规划器列出所有可行的出牌组合，学权重让人类实际打的那组排第一
     （softmax 似然，按回放文件划分训练 / 检验）。权重存在 data/imitation.json。
使用：combat.evaluate 的分数 += P['imit_w'] × Σ 权重 × 特征。
"""
import json, os
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/imitation.json'
_M = {'m': None}


def model():
    f = f"{HERE}/data/{P.get('imit_file') or 'imitation.json'}"       # imit_file 选权重文件（对比不同版本用）
    if _M.get('f') != f:
        _M['m'] = json.load(open(f)) if os.path.exists(f) else {}; _M['f'] = f
    return _M['m']


def feats(combo, ctx):
    """一个出牌组合的特征（训练和使用共用同一个函数）"""
    from policy.knowledge import cid
    from policy.combat import card_cost
    energy = ctx['energy']; inc = ctx['incoming']; hp = max(ctx['hp'], 1)
    ids = [cid(c) for c in combo]
    blk = sum((c.get('stats') or {}).get('block') or 0 for c in combo)
    block = ctx['block'] + blk
    dmg = sum(((c.get('stats') or {}).get('damage') or 0) * max((c.get('stats') or {}).get('hits') or 1, 1) for c in combo if c.get('type') == 'Attack')
    cost = sum(max(card_cost(c, energy), 0) for c in combo)
    unb = max(0, inc - block)
    f = {'unb': unb / 10, 'unb_hp': min(unb / hp, 2.0), 'over': max(0, block - inc) / 10 if inc > 0 else 0.0,
         'blk_atk': blk / 10 if inc > 0 else 0.0, 'blk_noatk': blk / 10 if inc == 0 else 0.0,
         'dmg': dmg / 10, 'n': float(len(combo)), 'en_left': max(0, energy - cost) / 3,
         'pow': float(sum(1 for c in combo if c.get('type') == 'Power')),
         'status': float(sum(1 for c in combo if c.get('type') in ('Status', 'Curse')))}
    for i in ids:
        k = 'c:' + i; f[k] = f.get(k, 0.0) + 1.0
    return f


def bonus(combo, ctx):
    m = model()
    th = m.get('theta')
    if not th: return 0.0
    return sum(th.get(k, 0.0) * v for k, v in feats(combo, ctx).items()) * m.get('scale', 1.0)
