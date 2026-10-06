"""预判：用怪物出招表（kb/monsters.json，从源码提取）推算敌人接下来几回合的期望伤害。

1. 认招：拿敌人当前意图（类型、伤害、段数）去对它的招式表，找最像的那一招；
   同样意图的招有好几个时（比如沙虫两个「撕扯」），用上一回合认出来的招的「下一招」来区分。
2. 往后推：从这一招出发，顺着 next 走；遇到随机分支按权重（去掉不能重复的）取概率，条件分支看不到条件就平均。
3. 每回合期望伤害 = Σ 概率 × (基础伤害 + 当前力量 + 之前招式加的力量) × 段数。
认不出来就返回 None，战斗规划退回用移动平均。
"""
import json, os
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    _M = json.load(open(f'{HERE}/kb/monsters.json'))
except Exception:
    _M = {}
BY_NAME = {}
for _k, _v in _M.items():
    if _k.startswith('_') or not isinstance(_v, dict): continue
    if _v.get('category') in ('test', 'unused', 'pet'): continue
    BY_NAME.setdefault(_v.get('name'), _v)


def _num(x):
    if isinstance(x, dict): return x.get('a10', x.get('a0', 0)) or 0
    return x if isinstance(x, (int, float)) else 0


def _move_sig(mv):
    """招式的意图签名：[(类型, 基础伤害, 段数)]"""
    return [(str(it.get('cli_type') or it.get('type')).lower(), _num(it.get('damage')), _num(it.get('hits')) or 1) for it in mv.get('intents') or []]   # 段数也可能按难度写成 {a0, a10}


def _str_gain(mv):
    return sum(_num(ef.get('amount')) for ef in mv.get('effects') or []
               if ef.get('kind') == 'apply_power' and 'Strength' in str(ef.get('power')) and ef.get('target') in ('self', 'allies_incl_self'))


def _strength(e):
    for p in e.get('powers') or []:
        if str(p.get('name', '')).lower() == 'strength': return p.get('amount') or 0
    return 0


def identify(e, prev=None):
    m = BY_NAME.get(e.get('name'))
    if not m: return None
    s = _strength(e)
    cur = [(str(it.get('type')).lower(), it.get('damage') or 0, it.get('hits') or 1) for it in e.get('intents') or []]
    best, bk = None, None
    for mid, mv in (m.get('moves') or {}).items():
        sig = _move_sig(mv)
        if len(sig) != len(cur) or any(a[0] != b[0] for a, b in zip(sig, cur)): continue
        err = sum(abs((a[1] + s if a[1] else 0) - b[1]) + 3 * abs(a[2] - b[2]) for a, b in zip(sig, cur))
        if prev and prev in m['moves'] and _resolve_first(m, m['moves'][prev].get('next')) and mid in _resolve_first(m, m['moves'][prev].get('next')):
            err -= 0.5                                   # 上一招的后续里有它：同分时优先
        if best is None or err < best: best, bk = err, mid
    if best is None or best > 6: return None
    return bk


def _resolve_first(m, state, last=None):
    """状态 id → {招式: 概率}"""
    if not state: return {}
    if state in (m.get('moves') or {}): return {state: 1.0}
    br = (m.get('branches') or {}).get(state)
    if not br: return {}
    out = {}
    if br.get('kind') == 'random':
        opts = [o for o in br.get('options') or [] if not (o.get('cannot_repeat') and o.get('move') == last)]
        ws = [(o, o.get('weight') if isinstance(o.get('weight'), (int, float)) else 1) for o in opts]
        tot = sum(w for _, w in ws) or 1
        for o, w in ws:
            for k, p in _resolve_first(m, o.get('move'), last).items(): out[k] = out.get(k, 0) + p * w / tot
    else:
        conds = [c for c in br.get('conditions') or [] if c.get('move')]
        for c in conds:
            for k, p in _resolve_first(m, c['move'], last).items(): out[k] = out.get(k, 0) + p / len(conds)
    return out


def public_mangle_strength_return(e):
    """Return known Mangle loss from visible power amounts, or defer malformed input.

    This is not an estimate of hidden Strength or a permanent debuff. Other
    temporary powers retain legacy behavior pending their own source review.
    """
    total = 0
    for power in e.get('powers') or []:
        if power.get('id') != 'MANGLE_POWER': continue
        amount = power.get('amount')
        if type(amount) is not int or amount <= 0: return None
        total += amount
    return total


def resolve_next(m, state, last=None, public_player_powers=None):
    """Resolve a source branch with only a proved public curse completion."""
    if (P.get('foresight_public_kd_loop', False) and m.get('name') == 'Knowledge Demon'
            and state == 'CurseOfKnowledgeBranch' and 'SLAP_MOVE' in m.get('moves', {})):
        from policy.public_knowledge_demon import possible_curse_stages
        if possible_curse_stages(public_player_powers) == (3,):
            return {'SLAP_MOVE': 1.0}
    return _resolve_first(m, state, last)


def future(e, move, turns, public_player_powers=None, projected_hp_damage=0):
    """从当前招之后，接下来 turns 个敌方回合每回合的期望伤害列表"""
    m = BY_NAME.get(e.get('name'))
    fixed_moves = None
    if P.get('foresight_public_matriarch_sleep', False) and e.get('name') == 'Lagavulin Matriarch' and move == 'SLEEP_MOVE':
        from policy.public_matriarch import future_moves
        fixed_moves = future_moves(e, turns, projected_hp_damage)
        if fixed_moves is None: return None
    if not m or (move not in (m.get('moves') or {}) and fixed_moves is None): return None
    s = _strength(e) + _str_gain(m['moves'].get(move, {}))
    if P.get('foresight_public_stat_expiry', False):
        from policy.public_stat_expiry import negative_strength_return
        returned = negative_strength_return(e.get('powers'))
        if returned is None: return None
        s += returned
    elif P.get('foresight_public_mangle_expiry', False):
        # Mangle returns Strength after this enemy turn; future() starts
        # with the following turn, where the visible temporary loss is gone.
        returned = public_mangle_strength_return(e)
        if returned is None: return None
        s += returned
    dist = {move: 1.0}; out = []
    for step in range(turns):
        nd = {}
        if fixed_moves is not None:
            nd = {fixed_moves[step]: 1.0}
        else:
            for mv, p in dist.items():
                for k, q in resolve_next(m, m['moves'][mv].get('next'), mv, public_player_powers).items(): nd[k] = nd.get(k, 0) + p * q
        if not nd: break
        dmg = 0.0; gain = 0.0
        for mv, p in nd.items():
            for typ, d, h in _move_sig(m['moves'][mv]):
                if 'attack' in typ or typ == 'deathblow': dmg += p * max(0, d + s) * h
            gain += p * _str_gain(m['moves'][mv])
        out.append(dmg); s += gain; dist = nd
    return out


def expected_incoming(enemies, mem, turns=None, public_player_powers=None):
    """所有活着的敌人接下来几回合的平均每回合伤害；任何一个认不出来就返回 None"""
    turns = turns or P['foresight_turns']
    prev = mem.setdefault('fs_prev', {}); tot = []
    for e in enemies:
        key = (e.get('name'), e.get('index'))
        mv = identify(e, prev.get(key))
        if mv is None: return None
        prev[key] = mv
        f = future(e, mv, turns, public_player_powers=public_player_powers)
        if f is None: return None
        tot.append(f)
    if not tot: return 0.0
    n = max(len(f) for f in tot)
    if n == 0: return None
    per_turn = [sum(f[i] for f in tot if i < len(f)) for i in range(n)]
    return sum(per_turn) / len(per_turn)
