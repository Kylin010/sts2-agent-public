"""牌组评估：估算这副牌每回合能打多少、挡多少，有没有群伤、成长、消耗引擎。
选牌（补什么）和路线（敢不敢打精英）都用它。
"""
from params import P
from policy import kb


def evaluate(deck, relic_ids=(), energy=3):
    """deck 是状态里的牌组列表（带 id、upgraded）。返回每回合伤害 / 格挡等估计"""
    n = max(len(deck), 1)
    hand = 5
    dmg_per_e = blk_per_e = 0.0; attacks = blocks = 0
    for c in deck:
        e = kb.card(c.get('id')); cost = e.get('cost') if isinstance(e.get('cost'), int) and e.get('cost') >= 0 else 1
        up = 1.3 if c.get('upgraded') else 1.0
        if e.get('damage'):
            dmg_per_e += up * e['damage'] * (e.get('hits') or 1) * (len([1]) if 'aoe' not in (e.get('tags') or []) else 1.5) / max(cost, 0.7)
            attacks += 1
        if e.get('block'):
            blk_per_e += up * e['block'] / max(cost, 0.7); blocks += 1
    # 平均每张牌的「每费伤害 / 每费格挡」× 每回合能量 × 抽到的比例
    tc = kb.deck_tag_counts([c.get('id') for c in deck])
    dpt = dmg_per_e / n * hand * min(energy / 3, 1.5) * 1.0
    bpt = blk_per_e / n * hand * min(energy / 3, 1.5)
    scaling = tc['scaling'] + tc['strength'] * 0.5 + tc['power'] * 0.3
    return {'dmg_per_turn': round(dpt * (1 + 0.08 * scaling), 1), 'block_per_turn': round(bpt, 1), 'aoe': tc['aoe'] + tc['multi_hit'] * 0.5,
            'draw': tc['draw'], 'scaling': round(scaling, 1), 'engine': tc['exhaust_engine'], 'fuel': tc['exhaust_fuel'], 'size': n}


def elite_ready(st):
    """路线用：现在的牌组和血量，敢不敢打精英。返回 0（别打）~ 1（放心打）"""
    pl = st.get('player') or {}; act = (st.get('context') or {}).get('act', 1)
    hpf = pl.get('hp', 1) / max(pl.get('max_hp', 1), 1)
    ev = evaluate(pl.get('deck') or [])
    need = {1: P['elite_dpt_act1'], 2: P['elite_dpt_act2'], 3: P['elite_dpt_act3']}.get(act, 25)
    power = min(1.0, ev['dmg_per_turn'] / need + 0.15 * min(ev['aoe'], 2) + 0.05 * ev['scaling'])
    hp_ok = min(1.0, max(0.0, (hpf - P['elite_hp_mid']) / max(P['elite_hp_hi'] - P['elite_hp_mid'], 0.05)))
    return power * hp_ok


_MC = {}


def evaluate_mc(deck, energy=3, n=300):
    """蒙特卡洛版（参考 Codex 研究 25 号「随机五张手牌、共享能量预算」）：随机抽 n 手 5 张牌，在能量预算内
    分别求最多能打多少伤害、最多能挡多少（小背包，0 费牌免费），取平均。诅咒 / 状态占手牌位置。按牌组缓存。
    10/3 对比我们 150 副实战牌组：和原来的 evaluate 比，伤害中位 0.88 倍、格挡 1.07 倍——平均偏差不大，好处是逐副牌更准（能量限制、0 费、高费）。"""
    import random
    key = (tuple(sorted(str(c.get('id')) + ('+' if c.get('upgraded') else '') for c in deck)), energy)
    if key in _MC: return _MC[key]
    items = []
    for c in deck:
        e = kb.card(c.get('id')); up = 1.3 if c.get('upgraded') else 1.0
        cost = e.get('cost') if isinstance(e.get('cost'), int) and e.get('cost') >= 0 else (energy if e.get('cost') == -1 else 1)
        if e.get('type') in ('Curse', 'Status') or not e: items.append((99, 0.0, 0.0)); continue
        dmg = up * (e.get('damage') or 0) * (e.get('hits') or 1) * (1.5 if 'aoe' in (e.get('tags') or []) else 1.0)
        items.append((cost, dmg, up * (e.get('block') or 0)))
    rng = random.Random(len(items) * 7919 + sum(int(i[1] + i[2]) for i in items))

    def best(hand, k):                                 # 能量预算内第 k 项（1 = 伤害，2 = 格挡）的最大和
        dp = [0.0] * (energy + 1)
        for it in hand:
            c, v = it[0], it[k]
            if c > energy or v <= 0: continue
            for e_ in range(energy, c - 1, -1): dp[e_] = max(dp[e_], dp[e_ - c] + v)
        return dp[energy]
    d = b = 0.0
    for _ in range(n):
        hand = rng.sample(items, min(5, len(items))) if items else []
        d += best(hand, 1); b += best(hand, 2)
    out = (d / n, b / n)
    if len(_MC) > 2000: _MC.clear()
    _MC[key] = out
    return out
