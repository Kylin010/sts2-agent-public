"""脑内战斗模型。
根源：规划器只给「这一回合」打分（combat._score），推演用真实引擎复制局面去试打
这里用程序自己掌握的规则知识「心算」接下来几回合，像人类那样，不碰游戏引擎、不读档：
- 敌人：源码出招表（kb/monsters.json）按当前招往后推，每个敌方回合的期望伤害（含力量成长）、回血、加格挡；
- 我方：牌组每回合「全力进攻能打多少 / 全力格挡能挡多少」（deckeval.evaluate_mc），这回合打出的力量类能力、易伤会抬高之后的伤害；
- 对这回合每个候选出法，从「打完这回合、敌人出完这一招」的局面开始，按三种后续打法（全攻 / 攻守各半 / 偏守）往下算 T 回合，
  取结局最好的那种：赢 = 剩余血量，输 = −死亡罚分（离打死越近罚得越轻），算不完 = 按平均来伤和输出估剩下要掉的血。
combat._score 把这个值乘 mental_w 加进出法的分数（参数 mental_on / mental_w / mental_turns / mental_curve / mental_death）。
"""
import json, os
from params import P
from policy import foresight

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    _M = json.load(open(f'{HERE}/kb/monsters.json'))
except Exception:
    _M = {}
_BY = {v.get('name'): v for k, v in _M.items() if isinstance(v, dict) and not k.startswith('_')}


def _num(x):
    if isinstance(x, dict): return x.get('a10', x.get('a0', 0)) or 0
    return x if isinstance(x, (int, float)) else 0


def _effects(m, mv):
    """一招的 回血 / 自己加格挡"""
    heal = blk = 0
    for ef in (m.get('moves') or {}).get(mv, {}).get('effects') or []:
        if ef.get('target') not in (None, 'self', 'allies_incl_self'): continue
        if ef.get('kind') == 'heal': heal += _num(ef.get('amount'))
        elif ef.get('kind') == 'block': blk += _num(ef.get('amount'))
    return heal, blk


def schedule(enemies, turns, mem, public_player_powers=None, hp_damage_by_index=None):
    """当前招的 (回血, 加格挡) + 之后 turns 个敌方回合每回合的 (期望伤害, 回血, 加格挡)。认不出任何一个敌人就返回 None"""
    prev = mem.setdefault('fs_prev', {})
    cur_heal = cur_blk = 0.0; per = [[0.0, 0.0, 0.0] for _ in range(turns)]
    for e in enemies:
        if (e.get('hp') or 0) <= 0: continue
        m = _BY.get(e.get('name'))
        mv = foresight.identify(e, prev.get((e.get('name'), e.get('index'))))
        if not m or not mv: return None
        h, b = _effects(m, mv); cur_heal += h; cur_blk += b
        projected_damage = (hp_damage_by_index or {}).get(e.get('index'), 0)
        dmg = foresight.future(e, mv, turns, public_player_powers=public_player_powers, projected_hp_damage=projected_damage)
        if dmg is None:
            if P.get('foresight_public_stat_expiry', False): return None
            if P.get('foresight_public_matriarch_sleep', False) and e.get('name') == 'Lagavulin Matriarch': return None
            dmg = []                       # preserve legacy fallback elsewhere
        fixed_moves = None
        if P.get('foresight_public_matriarch_sleep', False) and e.get('name') == 'Lagavulin Matriarch' and mv == 'SLEEP_MOVE':
            from policy.public_matriarch import future_moves
            fixed_moves = future_moves(e, turns, projected_damage)
        # 之后每回合的回血 / 格挡：顺着出招表期望值往后推（和 foresight.future 一样的分布推进）
        dist = {mv: 1.0}
        for t in range(turns):
            nd = {}
            if fixed_moves is not None:
                nd = {fixed_moves[t]: 1.0}
            else:
                for k, p in dist.items():
                    for k2, q in foresight.resolve_next(m, (m['moves'].get(k) or {}).get('next'), k, public_player_powers).items(): nd[k2] = nd.get(k2, 0) + p * q
            if not nd: break
            hh = sum(p * _effects(m, k)[0] for k, p in nd.items()); bb = sum(p * _effects(m, k)[1] for k, p in nd.items())
            per[t][0] += dmg[t] if t < len(dmg) else 0.0; per[t][1] += hh; per[t][2] += bb
            dist = nd
    return cur_heal, cur_blk, per


def value(h, e, e0, D, B, hits, sched, str_flat=0.0, str_turn=0.0, vuln_turns=0, cur_heal=0.0, cur_blk=0.0):
    """打完这回合后的局面值：h 我剩的血、e 敌人剩的血（主要敌人合计）、D / B 每回合全力进攻 / 格挡、hits 每回合攻击段数、
    sched = [(来伤, 回血, 加格挡)]（从下个敌方回合起）；str_flat / str_turn = 这回合打出的力量（一次性 / 每回合再加）；vuln_turns = 敌人易伤还剩几回合"""
    if e <= 0: return h
    if h <= 0: return -P.get('mental_death', 60) * (0.5 + 0.5 * min(1.0, e / max(e0, 1)))
    c = P.get('mental_curve', 0.7); T = len(sched)
    best = None
    e_start = e + cur_heal
    for a in (1.0, 0.6, 0.3):
        hh, ee, eblk = h, e_start, cur_blk; out = None
        s = str_flat
        for t in range(T):
            inc, heal, blk_e = sched[t]
            s += str_turn
            d_t = (D + s * hits) * (1.5 if t < vuln_turns else 1.0)
            dmg = (a ** c) * d_t; blk = ((1 - a) ** c) * B
            ee -= max(0.0, dmg - eblk)
            if ee <= 0: out = hh; break
            hh -= max(0.0, inc - blk)
            if hh <= 0: out = -P.get('mental_death', 60) * (0.5 + 0.5 * min(1.0, ee / max(e0, 1))); break
            ee += heal; eblk = blk_e
        if out is None:                                    # 算不完：按平均来伤估还要掉多少血
            avg_inc = sum(x[0] for x in sched) / max(T, 1)
            d_bal = (0.6 ** c) * (D + s * hits); b_bal = (0.4 ** c) * B
            need = ee / max(d_bal, 1.0)
            hh -= need * max(0.0, avg_inc - b_bal)
            out = hh if hh > 0 else -P.get('mental_death', 60) * (0.5 + 0.5 * min(1.0, ee / max(e0, 1)))
        if best is None or out > best: best = out
    return best
