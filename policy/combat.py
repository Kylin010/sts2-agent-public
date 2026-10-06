"""战斗：这回合怎么出牌（组合规划）。

把手里「费用付得起的牌的组合」全部列出来（10 张手牌最多约 1000 种），每种组合估算：
能打多少伤害、挡多少、打死谁（死掉的敌人这回合不打我）、我还会掉多少血，按「伤害和血的兑换率」打分，
挑总分最高的组合，按合理顺序先打其中一张。打完一张局面就变了（抽到新牌、敌人掉血），再重新规划。

兑换率：现在多打 1 点伤害，战斗就短一点，以后少挨打。
  1 点伤害值多少血 ≈ 敌人每回合平均打我多少 ÷ 我每回合能打多少（夹在 alpha_min ~ alpha_max 之间）
"""
import itertools, json, os
from math import isfinite
from params import P
from policy.knowledge import (cid, intent_damage, is_attack_intent, has_power, HITS, AOE, VULN, WEAK, DRAW, ENERGY, SELF_HP, STR_NOW, POWER_VALUE, XCOST)
from policy import potions, longterm, handrules, kb
from policy import enemy_powers as EP
from policy import foresight
from policy import player_powers as PP
from policy import combatvalue as CV
STR_POWERS = {'INFLAME': ('flat', 2), 'DEMON_FORM': ('per_turn', 3)}     # 力量类能力：(一次加 / 每回合加, 数量)；实际数量读牌面 strengthpower

# 只核对了这四张牌的 CardsVar 是本次打出的抽牌数；其他牌的 CardsVar 可能是门槛、选牌数或下回合抽牌。
_PUBLIC_DRAW_UPGRADES = {'BATTLE_TRANCE': 1, 'POMMEL_STRIKE': 1, 'BURNING_PACT': 1, 'OFFERING': 2}


def draw_amount(c):
    """名义抽牌数：可选地读当前公开牌面，仍由 evaluate 的不能抽牌 / 战斗结束规则决定是否计分。"""
    i = cid(c); base = DRAW.get(i, 0)
    if not P.get('combat_public_draw', False) or i not in _PUBLIC_DRAW_UPGRADES:
        return base
    n = (c.get('stats') or {}).get('cards')
    if type(n) in (int, float) and isfinite(n) and n >= 0 and n == int(n):
        return int(n)
    # 老导出没有数值时，只用公开升级标记及源码固定升级量，不推测隐藏牌面。
    return base + (_PUBLIC_DRAW_UPGRADES[i] if c.get('upgraded') is True else 0)


def str_amount(c, default):
    """这张牌给多少力量：读手牌预览 stats.strengthpower（升级后的数值也在这里）。
    引擎的战斗手牌不导出 upgraded，原来 `+1 if upgraded` 永远加不上；恶魔形态实际每回合 +3（升级 +4），原来写的 2（梳理表 C11）"""
    v = (c.get('stats') or {}).get('strengthpower')
    return v if isinstance(v, (int, float)) and v > 0 else default


def str_now(c):
    """打出后本回合其他攻击马上多吃的力量（燃烧、整顿打击、单挑）"""
    i = cid(c)
    return str_amount(c, STR_NOW[i]) if i in STR_NOW else 0
_PB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kb', 'card_play_bias.json')
PLAY_BIAS = {k: v for k, v in (json.load(open(_PB)) if os.path.exists(_PB) else {}).items() if not k.startswith('_')}


def power_amount(e, word):
    for p in e.get('powers') or []:
        if word in str(p.get('name', '')).lower(): return p.get('amount') or 0
    return 0


def card_cost(c, energy):
    if cid(c) in XCOST: return 0                   # X 费牌：引擎报 0，花掉的是「其他牌打完剩下的」，段数另算（x['whirl']）
    k = c.get('cost')
    return energy if k is None or k < 0 else k


def per_hit(c, e):
    """这张牌打敌人 e 的 (每段伤害, 段数)。每段伤害用引擎 damage_by_target 的预览（已经算了力量、易伤、虚弱）；
    段数：引擎给了 repeat 就用它（拆解打已有易伤的目标是 2 段），扯碎用牌面的 calculatedhits（1 + 本场受到未格挡伤害的次数），
    否则用知识库的固定段数（Codex 发现，梳理表 C07；原来两张都按 1 段）。X 费牌的段数另算（x['whirl']）"""
    i = cid(c); st = c.get('stats') or {}
    hits = HITS.get(i, 1)
    if i == 'TEAR_ASUNDER': hits = max(1, int(st.get('calculatedhits') or 1))
    for r in c.get('damage_by_target') or []:
        if r.get('target_index') == e['index']:
            return (r.get('damage') or 0), (r.get('repeat') if r.get('repeat') and i not in XCOST else hits)
    return (st.get('damage') or st.get('calculateddamage') or 0), hits


def base_damage(c, e):
    """这张牌对敌人 e 的总伤害（每段 × 段数）"""
    per, hits = per_hit(c, e)
    return per * hits


def _hits_on(c, e, x, vuln):
    """单张攻击打敌人 e：返回 (每段伤害, 段数)，还没算敌人的格挡 / 滑溜这类状态（那些在 Foe.hit 里结算）"""
    i = cid(c); hits = HITS.get(i, 1)
    if i == 'BODY_SLAM':
        per = x['slam']
    elif id(c) in x.get('whirl', {}):             # X 费攻击（旋风斩 / 齐射）：段数 = 其他牌打完剩下的能量
        per, hits = x['whirl'][id(c)]
        if id(c) in x.get('pen_halve', ()): per /= 2
    else:
        per, hits = per_hit(c, e)
        if id(c) in x.get('pen_halve', ()): per /= 2   # 钢笔尖计数 9：预览里每张攻击都翻倍了，实际只有第一张（梳理表 C14）
        if i == 'FIEND_FIRE': hits = x.get('ff_hits', hits)   # 恶魔之焰：段数 = 打出时手里剩下的牌（全部消耗），它放最后打
        if i not in STR_NOW:   # 整顿打击 / 单挑打完才加力量：排在它们前面打的牌（易伤攻击）只吃到能力 / 技能给的力量
            per += x['str_bonus'] if ORDER(c) > 5.5 else x.get('str_pre', x['str_bonus'])
    if vuln and not has_power(e, 'vulner') and id(c) not in x.get('no_self_vuln', ()):
        per *= 1.5
        if i == 'DISMANTLE': hits = 2          # 拆解：目标有易伤就打 2 段（源码 Dismantle.OnPlay）
    per *= EP.slow_mult(e, x['n_pre'])
    cap = x['cap']
    if cap: per = min(per, cap)                        # 外骨骼虫：每次伤害最多 9
    if has_power(e, 'intangible'): per = min(per, 1)   # 无实体：每段只算 1
    return per, hits


def _assign(singles, aoe, p, ctx, x, vuln_on):
    """给单体攻击分配目标：主目标 p 先吃易伤牌；然后按威胁从高到低，能用最少的牌打死谁就打死谁；
    剩下的牌全打 p（p 死了就打剩血最少的主怪）。返回 {id(牌): 敌人}, {敌人 index: Foe 状态}"""
    enemies = ctx['enemies']
    foes = {e['index']: EP.Foe(e) for e in enemies}
    tcap = ctx['rules'].get('damage_cap')
    if tcap:
        for f in foes.values(): f.shell = tcap if f.shell is None else min(f.shell, tcap)   # 鬼祟珊瑚群：每回合最多掉 20
    hp_left = lambda e: (e.get('hp') or 0) - foes[e['index']].lost
    tgt = {}; hits_on = {e['index']: 0 for e in enemies}

    def hit(c, e):
        per, h = _hits_on(c, e, x, vuln_on(e))
        foes[e['index']].hit(per, h); hits_on[e['index']] += h
        tgt[id(c)] = e

    def peek(c, e):
        per, h = _hits_on(c, e, x, vuln_on(e))
        f = foes[e['index']].copy(); f.hit(per, h)
        return f.lost - foes[e['index']].lost

    for c in aoe:
        for e in enemies:
            per, h = _hits_on(c, e, x, vuln_on(e))
            foes[e['index']].hit(per, h); hits_on[e['index']] += h
        tgt[id(c)] = None
    left = list(singles)
    slip_p = foes[p['index']].slip > 0
    for c in [c for c in left if cid(c) in VULN or cid(c) in WEAK]:   # 痛击这类：打主目标
        if not slip_p:
            hit(c, p); left.remove(c)
    order = [p] + sorted((e for e in enemies if e is not p), key=lambda e: (-intent_damage(e), hp_left(e)))
    for e in order:
        rem = hp_left(e)
        if rem <= 0 or not left: continue
        if e is not p and has_power(e, 'minion') and intent_damage(e) <= 0: continue
        if foes[e['index']].slip > 0: continue          # 滑溜的敌人一回合打不死，留给下面按小伤害先打
        if EP.amt(e, 'reattach') and not ctx.get('reattach_finish'): continue   # 千足虫：还收不完时不单独打死某一节
        d = {id(c): peek(c, e) for c in left}
        one = [c for c in left if d[id(c)] >= rem]
        if one:
            pick = [min(one, key=lambda c: (d[id(c)], cid(c) != 'FEED'))]
        else:
            pick, s = [], 0
            for c in sorted(left, key=lambda c: -d[id(c)]):
                pick.append(c); s += d[id(c)]
                if s >= rem: break
            if s < rem: continue
        for c in pick:
            hit(c, e); left.remove(c)
    # 剩下的打主目标；主目标有滑溜时先打每段伤害小的（磨掉滑溜层数，大伤害留到后面）
    per_p = lambda c: _hits_on(c, p, x, vuln_on(p))[0]
    for c in sorted(left, key=(per_p if slip_p else (lambda c: -per_p(c)))):
        alive = [e for e in enemies if hp_left(e) > 0]
        seg = [e for e in alive if EP.amt(e, 'reattach')]
        if seg and not ctx.get('reattach_finish'):
            e = max(seg, key=hp_left)                      # 千足虫：把血最多的那节往下压，几节一起变低
        else:
            e = p if p in alive else (min([m for m in alive if m in ctx['mains']] or alive or [p], key=hp_left))
        hit(c, e)
    return tgt, foes, hits_on


def evaluate(combo, ctx, want_targets=False, detail=None):
    """估算打出这组牌的结果，返回分数（want_targets 时返回 (分数, {id(牌): 目标})）；费用不够返回 None。
    单体攻击的目标逐个试「主目标」，每个主目标下贪心分配（先打死威胁大的），取最好的一种。"""
    enemies, energy, block0, hp = ctx['enemies'], ctx['energy'], ctx['block'], ctx['hp']
    ids = [cid(c) for c in combo]
    gain = sum(ENERGY.get(i, 0) for i in ids)
    if 'DRUM_OF_BATTLE' in ids and PP.amt(ctx.get('player_powers') or [], 'corruption'):   # 腐化：技能打出就被消耗 → 战鼓立刻给能量
        gain += sum(((c.get('stats') or {}).get('energy') or 2) for c in combo if cid(c) == 'DRUM_OF_BATTLE')
    cost = sum(card_cost(c, energy) for c in combo)
    if 'UNRELENTING' in ids:   # 无情猛攻：下一张攻击 0 费（粗略：省掉它之后打的攻击里最贵的那张）
        others = [card_cost(c, energy) for c in combo if c.get('type') == 'Attack' and cid(c) != 'UNRELENTING' and ORDER(c) > ORDER_UNRELENTING]
        if others: cost -= max(others)
    if cost > energy + gain:
        return None
    if 'FIEND_FIRE' in ids and any(i in XCOST for i in ids):
        return None            # 恶魔之焰要最后打（不然把后面的牌烧掉），X 费也要最后打（花光能量）：两张不能同组
    block = block0 + sum((c.get('stats') or {}).get('block') or 0 for c in combo if cid(c) != 'SECOND_WIND')
    if 'SECOND_WIND' in ids:   # 重振精神：每消耗一张非攻击牌得一次牌面格挡（预览已含升级 / 敏捷）。原来算成牌面 + 5×张数（梳理表 C13）
        n_fuel = sum(1 for c in ctx['hand'] if c.get('type') != 'Attack' and c not in combo)
        block += sum(((c.get('stats') or {}).get('block') or 5) * n_fuel for c in combo if cid(c) == 'SECOND_WIND')
    rage = 3 * sum(1 for c in combo if c.get('type') == 'Attack') if 'RAGE' in ids else 0
    block += rage
    ppx = PP.effects(combo, ids, ctx)                 # 场上已有能力的联动：无惧疼痛、黑暗之拥、主宰、岿然不动、地狱之火……
    block += ppx['block']
    if detail is not None: detail['block'] = block      # 测试用：出完这组牌的格挡（回合末遗物之前）
    str_bonus = sum(str_now(c) for c in combo)
    str_pre = sum(str_now(c) for c in combo if c.get('type') != 'Attack')    # 能力 / 技能给的力量：所有攻击之前就生效
    attacks = [c for c in combo if c.get('type') == 'Attack']
    # 恶魔之焰（源码 FiendFire.OnPlay：先消耗全部手牌，再 WithHitCount(手牌张数) 段）：段数 = 这组其他牌打完后手里剩几张
    # （Codex 发现，梳理表 C06；原来按 1 段 7 伤）
    x = {'str_bonus': str_bonus, 'str_pre': str_pre, 'ff_hits': sum(1 for c in ctx['hand'] if c not in combo),
         'slam': block - rage, 'cap': ctx['rules'].get('damage_cap_per_hit'),
         'n_pre': sum(1 for c in combo if c.get('type') != 'Attack'),
         # X 费攻击放在最后打（ORDER），段数 = 这组其他牌付完费用后剩下的能量（Codex 发现，梳理表 C04：
         # 原来和普通攻击同一档，按手牌位置可能先打旋风斩把能量花光，计划里的打击打不出；齐射原来当成 0 费单发）
         'whirl': {id(c): (((c.get('stats') or {}).get('damage') or 5), max(energy + gain - cost, 0))
                   for c in attacks if cid(c) in XCOST}}
    # 痛击 / 上勾拳 / 雷霆一击 / 破坏：源码里先结算伤害、再上易伤（Bash.OnPlay 等），同一组牌里第一张施加易伤的攻击
    # 自己这一击吃不到这次易伤，后面的牌才吃得到（Codex 发现，梳理表 C02；原来连它自己也 ×1.5，8 伤算成 12，误判能打死）
    vsrc = [c for c in sorted(combo, key=ORDER) if c.get('type') == 'Attack' and cid(c) in VULN]
    x['no_self_vuln'] = {id(vsrc[0])} if vsrc else set()
    # 钢笔尖计数 9（下一张攻击翻倍）：源码 PenNib.ModifyDamageMultiplicative 对手里每张攻击的预览都 ×2，
    # 实际只有接下来打出的第一张攻击翻倍——其余攻击按预览的一半算（Codex 发现，梳理表 C14）
    pn = (ctx.get('relics') or {}).get('PEN_NIB')
    if pn and pn[0] == 9:
        x['pen_halve'] = {id(c) for c in [c for c in sorted(combo, key=ORDER) if c.get('type') == 'Attack'][1:]}
    aoe = [c for c in attacks if cid(c) in AOE or cid(c) == 'WHIRLWIND']
    singles = [c for c in attacks if c not in aoe]
    aoe_vuln = any(i in ('THUNDERCLAP', 'SHOCKWAVE') for i in ids)
    st_vuln = any(i in VULN and i not in ('THUNDERCLAP', 'SHOCKWAVE') for i in ids)
    st_weak = any(i in WEAK and i != 'SHOCKWAVE' for i in ids)
    need_targets = bool(singles) or st_vuln or st_weak
    prims = ctx['primaries'] if need_targets else ctx['primaries'][:1]
    best = None
    for p in prims:
        vuln_on = lambda e: (aoe_vuln or (st_vuln and e is p)) and not EP.debuff_blocked(e)
        weak_on = lambda e: ('SHOCKWAVE' in ids or (st_weak and e is p)) and not EP.debuff_blocked(e)
        tgt, foes, hits_on = _assign(singles, aoe, p, ctx, x, vuln_on)
        sc = _score(combo, ids, ctx, p, tgt, foes, hits_on, block, gain, cost, weak_on, vuln_on, ppx)
        if best is None or sc > best[0]:
            best = (sc, tgt, p)
            if ctx.get('_parts') is not None: ctx['_parts']['best'] = ctx['_parts'].get('cur')
            if detail is not None: detail['lost'] = {k: f.lost for k, f in foes.items()}   # 测试用：每个敌人掉多少血
    if P.get('imit_w'):                                # 出牌模仿层（policy/imitation.py，从人类回放学的修正）
        from policy import imitation
        best = (best[0] + P['imit_w'] * imitation.bonus(combo, ctx), best[1], best[2])
    return (best[0], best[1], best[2]) if want_targets else best[0]


def _score(combo, ids, ctx, p, tgt, foes, hits_on, block, gain, cost, weak_on, vuln_on, ppx):
    enemies, energy, hp = ctx['enemies'], ctx['energy'], ctx['hp']
    rl = ctx['rules']
    dmg = {k: f.lost for k, f in foes.items()}            # 这组牌让每个敌人掉多少血（打在格挡上的不算）
    thorns_hp = sum(power_amount(e, 'thorns') * hits_on[e['index']] for e in enemies)     # 荆棘：每打一段反伤
    hive = sum(hits_on[e['index']] * (EP.amt(e, 'personal hive') if P.get('hive_by_layers', True) else 1)
               for e in enemies if EP.amt(e, 'personal hive'))    # 人体蜂房：每段攻击塞「蜂房层数」张晕眩（1 → 2 → 3，研究 12 号 3.2）
    stripped = sum(f.stripped for f in foes.values())     # 磨掉的滑溜层数：后面的大伤害就不会被吞
    n_skills = sum(1 for c in combo if c.get('type') == 'Skill')
    incoming = n_skills * EP.skill_strength(enemies)       # 激怒：每张技能让它加力量，这回合就多挨打
    enr = sum(EP.amt(e, 'enrage') for e in enemies)
    if enr and n_skills:                                   # 力量是整场的：以后每回合每段攻击都多打（实验体的爪击段数还会越来越多）
        future_pen = n_skills * enr * P['enrage_future_hits']
    else:
        future_pen = 0
    killed = 0; dealt = 0; thresh = 0; stun = 0
    shriek_stunned = set()                    # candidate-local; do not leak into other evaluations
    pref = (rl.get('prefer_target') or '').lower()
    alive_after = [e for e in enemies if dmg[e['index']] < (e.get('hp') or 0)]
    cum_in = 0; stun_need = 0                          # 失衡（10/3）：敌人按顺序出手，格挡先吃前面的；挡到「它和它前面的来伤」就晕
    for e in enemies:
        ehp = e.get('hp') or 0
        d = dmg[e['index']]
        sl = EP.amt(e, 'slumber')
        if sl and 0 < d < ehp and P.get('slumber_wake_pen', 0):     # 熟睡甲虫：没打死却打穿格挡，每一段都让它早醒一回合（醒了每回合 18 起）
            thresh -= P['slumber_wake_pen'] * min(sl, max(1, hits_on[e['index']]))
        asl = EP.amt(e, 'asleep') if P.get('asleep_wake_pen', 0) else 0
        if asl > 1 and 0 < d < ehp:
            # 10/4 暗港：乐加维林族母开局睡 3 回合（带 12 镀甲），打出穿透伤害就醒、剩下的免费回合全丢；醒后 4 招一循环、吸魂越拖越弱。
            # 我们每场掉 49 血（人类赢家 26）。睡着时意图 0，规划器以为安全就猛打把它打醒。最后一回合（asl ≤ 1）反正要醒，不扣
            thresh -= P['asleep_wake_pen'] * (asl - 1)
        th = rl.get('hp_threshold')
        if th and ehp > th >= ehp - d:
            g = P['threshold_bonus'] + intent_damage(e)    # 仪式兽 160 / 骇鳗 75：跨线当回合攻击取消、晕一回合
            if rl.get('threshold_care'):              # 骇鳗：跨线后两回合内打不完，就别跨（之后挂 99 层易伤）
                if ehp - d > P['threshold_finish_turns'] * ctx['my_dpt']: g = -g
            thresh += g
        if EP.amt(e, 'shriek') and ehp > (e.get('max_hp') or ehp) / 2 >= ehp - d > 0:
            thresh += P['threshold_bonus'] + intent_damage(e)   # 尖啸：第一次降到半血以下晕一回合
        dealt += min(d, ehp) * (P['prefer_dmg_factor'] if pref and pref in str(e.get('name', '')).lower() else 1)
        inc = intent_damage(e)
        if P.get('public_mangle_strength_score', False):
            from policy.public_strength_loss import mangle_incoming_bound
            bounded = mangle_incoming_bound(combo, e, ctx, tgt)
            if bounded is not None: inc = bounded['after_upper']
        if P.get('combat_public_shriek_stun', False) and EP.shriek_stuns_after_damage(e, d):
            inc = 0; shriek_stunned.add(e['index'])
        if EP.amt(e, 'burrowed'):                        # 地道虫钻地：格挡不会消失，打掉的格挡算进度；破盾当场眩晕、不出手
            b0 = e.get('block') or 0; f = foes[e['index']]
            dealt += max(0, b0 - f.blk)
            if b0 > 0 and f.blk <= 0 and d < ehp:
                thresh += P['threshold_bonus']; inc = 0
        if weak_on(e) and not has_power(e, 'weak'): inc *= 0.75
        if 'COLOSSUS' in ids and (vuln_on(e) or has_power(e, 'vulner')): inc *= 0.5
        if d >= ehp > 0:
            killed += 1           # 打死了：这回合它不打我
            if rl.get('revive') or EP.revives(e): killed -= 1 - P['revive_kill_factor']   # 会复活的：单独打死不太值
            if pref and pref in str(e.get('name', '')).lower(): killed += P['prefer_kill_bonus'] / max(P['kill_bonus'], 1)
            if has_power(e, 'minion') and intent_damage(e) <= 0: killed -= 0.5
            rage = [o for o in alive_after if o is not e and EP.amt(o, 'crab rage')]
            if rage and P.get('crab_kill_timing', True):
                # 帝皇蟹（研究 12 号 2.1）：一只死了，另一只立刻 +6 力量、+99 格挡。挑它「这回合不攻击」时杀：
                # 它这回合的每段攻击 +6；同一组牌再打它的伤害被 99 格挡吃掉；+6 力量以后一直都在（基础扣分）
                pen = P.get('crab_rage_base', 5.0)
                for o in rage:
                    hits = sum((it.get('hits') or 1) for it in o.get('intents') or [] if is_attack_intent(it))
                    pen += 6 * hits * P['block_mult'] + ctx['alpha'] * dmg[o['index']]
                thresh -= pen
            elif rage:
                thresh -= P['crab_rage_penalty']
            if EP.amt(e, 'reattach'):                    # 千足虫：其他节两回合内打不完，这一节死了也会接回来
                rest = sum(max(0, (o.get('hp') or 0) - dmg[o['index']]) for o in enemies if o is not e and EP.amt(o, 'reattach'))
                if rest > P['reattach_finish_turns'] * ctx['my_dpt']: killed -= 1; thresh -= P['reattach_early_penalty']
        else:
            incoming += inc; cum_in += inc
            if EP.amt(e, 'imbalanced') and inc > 0:
                stun += inc; stun_need = max(stun_need, cum_in if P.get('imbalanced_seq', True) else 10 ** 9)
    ends_fight = bool(ctx['mains']) and all(dmg[e['index']] >= (e.get('hp') or 0) for e in ctx['mains'])
    if ends_fight:
        incoming = 0; killed += 5       # 主怪全死，战斗结束（随从会跟着跑）
    if not ends_fight and P.get('disintegration_in', True):
        # 知识恶魔的「瓦解」：你每个回合结束时受 N 点伤害，能被格挡挡住（研究 12 号 2.3）。
        # 10/3 高手录像研究：第四代起选瓦解，但规划器没把它算进来伤，知识恶魔胜率 26% → 16%
        incoming += PP.amt(ctx.get('player_powers') or [], 'disintegrat')
    sand = max((EP.amt(e, 'sandpit') for e in enemies), default=0)
    sand_dead = False
    if sand and not ends_fight:          # 无厌沙虫的沙坑：敌方回合开始 -1，归零直接死；狂乱逃离每张 +1
        n_fe = ids.count('FRANTIC_ESCAPE')
        after = sand + n_fe - 1
        left_ehp = sum(max(0, (e.get('hp') or 0) - dmg[e['index']]) for e in ctx['mains'])
        need = -(-left_ehp // max(ctx['my_dpt'], 1))                   # 还要几回合才打得死
        # 整手 / 整类烧牌的牌会把手里没打的狂乱逃离一起烧掉（每张逃离 = 多活一回合，研究 12 号）
        if any(x in ids for x in ('SECOND_WIND', 'FIEND_FIRE', 'STOKE')):
            burned = sum(1 for c in ctx['hand'] if cid(c) == 'FRANTIC_ESCAPE') - n_fe
            if burned > 0: thresh -= burned * P.get('sandpit_burn_fe', 15.0)
        if after <= 0: sand_dead = True
        else:
            if n_fe: thresh += n_fe * (P['sandpit_fe_value'] if after - n_fe < need + 1 else P['sandpit_fe_value_low'])
            # 沙坑只剩 1：下回合必须刚好抽到狂乱逃离且付得起，否则就死；剩 2 也有风险（还打不死它的前提下）
            if after == 1 and need > 1: thresh -= P['sandpit_risk1']
            elif after == 2 and need > 2: thresh -= P['sandpit_risk2']
    unspent = max(0, energy + gain - cost)
    blk_x, dealt_x, dmg_in_x, hp_loss_x, bonus_x = handrules.turn_end(combo, ctx, block, unspent)
    # 这组牌打完战斗就结束了：回合末的手牌 / 遗物效果（灼伤、遗憾、冰淇淋存能量、孙子兵法……）不会发生，
    # 抽牌、能力、易伤持续、壁垒留格挡、激怒以后的力量这些「以后才有用」的分也都作废——只留跨战斗的收益（狂宴、钢笔尖、带骨肉、回血）。
    # 原来照算，收尾回合会顺手白打祭品（自损 6、抽 3）这类牌（Codex 发现，梳理表 C10）
    live = not ends_fight
    if not live: blk_x = dealt_x = dmg_in_x = hp_loss_x = bonus_x = 0
    block += blk_x; dealt += dealt_x + ppx['dealt']; incoming += dmg_in_x
    unblocked = max(0, incoming - block) + hp_loss_x
    if ppx['barricade'] and live: thresh += P['barricade_block_value'] * min(max(0, block - incoming), 40)   # 壁垒：多出来的格挡留到下回合
    # 战斗专注（BATTLE_TRANCE）打出后挂「不能抽牌」（源码 NoDrawPower）：它排最先打，同组其他牌的抽牌、黑暗之拥的抽牌都作废；
    # 身上已经有「不能抽牌」时所有抽牌都不算（Codex 发现，梳理表 C15）
    no_draw = 'BATTLE_TRANCE' in ids or any('no draw' in str(pp.get('name', '')).lower() for pp in ctx.get('player_powers') or [])
    if live: thresh += ppx['value'] + (0 if no_draw else ppx['draw'] * P['draw_value']) - future_pen
    # 掉血的代价随剩余血量变大：剩得越少，每点血越贵；这回合会死就重罚
    extra_hp = thorns_hp * P['thorns_weight'] + rl.get('power_penalty', 0) * sum(1 for c in combo if c.get('type') == 'Power')
    self_hp = sum(SELF_HP.get(i, 0) for i in ids)
    left = hp - unblocked - self_hp - extra_hp
    risk = P['risk_hp']
    if P.get('giant_steam_risk', False):
        # 瀑布巨兽：打到 0 血后再下个敌人回合爆炸，伤害 = 蒸汽层数（每招 +3，第 N 回合打死 = 3N+14）。
        # 暗港对照死在它手里的一半是被爆炸炸死（剩 9~30 血对 35~53）→ 血线按「当前蒸汽 + 余量」算，血快掉到爆炸线以下就多挡
        steam = max((EP.amt(e, 'steam') for e in enemies), default=0)
        if steam: risk = max(risk, steam + P.get('giant_risk_margin', 5))
    hp_cost = unblocked * (1 + max(0, risk - left) / risk * 2) * rl.get('block_priority', 1) * EP.block_priority(enemies) * P['block_mult'] + extra_hp
    if stun and (unblocked == 0 or block >= stun_need): thresh += stun * P['stun_value']   # 原来要求全部来伤挡满，石虫在前面时挡住它的 16 就够
    if live: thresh += stripped * P['slippery_strip_value'] * ctx['alpha'] - hive * P['dazed_cost']
    if rl.get('card_penalty'): hp_cost += rl['card_penalty'] * max(0, len(combo) - 1)
    if left <= 0 or sand_dead: hp_cost += P['death_penalty']
    if 'FLAME_BARRIER' in ids: dealt += 4 * ctx['hits_in']
    if live and P.get('toxic_exhaust_value', 0.0) and 'TOXIC' in ids:
        # 异螨的毒素（10/4）：打出就消耗；留在手里回合末受 5（可挡）后进弃牌堆、还会洗回来。规划器只算这回合的 5，
        # 没算「打掉就永远少一张」——整局实验异螨战 128 回合留在手里 76 张，我们掉 21.6 / 场，人类赢家 8.6
        thresh += P['toxic_exhaust_value'] * ids.count('TOXIC')
    # 牌面没有数值、规划器原本看不懂的牌（10/2 加）：按近似效果折算
    rest_hand = [c for c in ctx['hand'] if c not in combo]
    if 'INFERNAL_BLADE' in ids: dealt += P['infernal_blade_dmg']                      # 生成一张本回合免费的随机攻击
    if 'CASCADE' in ids and live: thresh += P['cascade_card_value'] * ctx['alpha'] * max(0, energy + gain - (cost - card_cost(next(c for c in combo if cid(c) == 'CASCADE'), energy)))
    if 'ONE_TWO_PUNCH' in ids:                                                         # 下一张攻击多打一次
        dealt += max([_hits_on(c, p, {'str_bonus': 0, 'slam': 0, 'cap': None, 'n_pre': 0, 'whirl': {}}, False)[0] * HITS.get(cid(c), 1)
                      for c in combo if c.get('type') == 'Attack'] or [0])
    if 'BRAND' in ids and live: thresh += P['str_perm_value'] * ctx['long']                    # 永久 +1 力量（还附带消耗一张、扣 1 血）
    if 'STOKE' in ids and live: thresh += P['draw_value'] * 0.8 * len(rest_hand)               # 消耗手牌、换同样多张随机牌
    if 'NOT_YET' in ids: thresh += min(10, ctx['max_hp'] - hp) * P['heal_value']      # 回 10 血
    # 易伤 / 虚弱不只管这回合：持续的那几回合也有价值（之前只算了这回合里其他攻击的加成）
    for i in (ids if live else ()):
        if i in VULN and not has_power(p, 'vulner') and not EP.debuff_blocked(p):
            thresh += P['vuln_future'] * ctx['alpha'] * 0.5 * ctx['my_dpt'] * max(0, VULN[i] - 1)
        if i in WEAK and not has_power(p, 'weak') and not EP.debuff_blocked(p):
            thresh += P['weak_future'] * 0.25 * intent_damage(p) * max(0, WEAK[i] - 1)
    powers = 0.0
    for c, i in zip(combo, ids):
        if c.get('type') != 'Power' or not live: continue
        sp = STR_POWERS.get(i)
        if sp:                                   # 力量类能力：按「剩几回合 × 每回合几段攻击」动态估值（静态值在长的 Boss 战里严重低估）
            kind, amt = sp; amt = str_amount(c, amt)
            T = ctx['turns_left']; hits = ctx['atk_hits_turn']
            str_turns = amt * T if kind == 'flat' else amt * T * (T - 1) / 2
            powers += P['str_future_weight'] * ctx['alpha'] * hits * str_turns
        else:
            powers += P['power_weight'] * POWER_VALUE.get(i, 1.5) * ctx['long']
    if not live or any('no draw' in str(pp.get('name', '')).lower() for pp in ctx.get('player_powers') or []): draw = 0.0
    elif 'BATTLE_TRANCE' in ids: draw = draw_amount(next(c for c in combo if cid(c) == 'BATTLE_TRANCE')) * P['draw_value']
    else: draw = sum(draw_amount(c) for c in combo) * P['draw_value']
    score = (ctx['alpha'] * dealt + P['kill_bonus'] * killed + thresh - hp_cost
             - self_hp * (P['self_hp_weight_low'] if hp < 25 else P['self_hp_weight']) + powers + draw)
    score += bonus_x
    segs = [e for e in enemies if EP.amt(e, 'reattach')]
    if len(segs) >= 2 and P.get('reattach_spread_w', 0):
        # 残杀千足虫（研究 12 号 3.1）：死了的节下回合回 25 血复活，三节要在相邻两回合内打死 → 先把三节一起压低。
        # 压低「血最多的那节」的伤害额外加分（三节越接近，越容易在窗口里一起打死）
        before = max(e.get('hp') or 0 for e in segs)
        after = max(max(0, (e.get('hp') or 0) - dmg[e['index']]) for e in segs)
        score += P['reattach_spread_w'] * ctx['alpha'] * (before - after)
    if rl.get('facing') and len(enemies) == 2 and P.get('crab_facing_w', 1.0):
        score -= P.get('crab_facing_w', 1.0) * P['block_mult'] * _facing_extra(combo, ctx, tgt, p, enemies, block, alive_after=alive_after)
    dmg_by_card = {id(c): (dmg[tgt[id(c)]['index']] if tgt.get(id(c)) else 0) for c in combo if c.get('type') == 'Attack'}
    feed = [c for c in combo if cid(c) == 'FEED']
    fe = tgt.get(id(feed[0])) if feed else p
    killed_focus = bool(fe) and dmg[fe['index']] >= (fe.get('hp') or 0)
    score += longterm.combat_bonus(combo, ctx, {'dmg_by_card': dmg_by_card, 'ends_fight': ends_fight, 'self_hp': self_hp,
                                                'killed_focus': killed_focus})
    if PLAY_BIAS:                   # 按牌的出牌偏好（tools/calibrate_play_bias.py 对齐人类回放里「在手里时打出的比例」）
        score += P['play_bias_weight'] * sum(PLAY_BIAS.get(i, 0.0) for i in ids)
    if rl.get('skill_penalty'):     # 感染棱柱：每张技能让它下个回合每段攻击 +「活力火花」层数（3 → 6 → 9，研究 12 号 3.3；原来固定按 3）
        spark = max((EP.amt(e, 'vital spark') for e in enemies), default=0) if P.get('prism_spark_live', True) else 0
        score -= (spark or rl['skill_penalty']) * ctx['hits_in'] * sum(1 for c in combo if c.get('type') == 'Skill')
    if P['cv_weight'] > 0 and ctx.get('sit') and CV.available():
        # 战斗估值模型：「打完这组牌、结束回合」时的局面，预计到战斗结束还要掉多少血。
        # 用它代替经验性的兑换率（alpha × 伤害）和这回合的掉血代价
        s0 = ctx['sit']; ens = []
        for e in enemies:
            e_left = (e.get('hp') or 0) - dmg[e['index']]      # 注意别叫 left：外面的 left 是「我还剩多少血」（10/2 就因为重名，打死敌人被当成自己死了）
            if e_left <= 0: continue
            inc = intent_damage(e) * (0.75 if weak_on(e) and not has_power(e, 'weak') else 1)
            fut0 = next((x.get('fut', inc) for x in s0['enemies'] if x.get('index') == e.get('index')), inc)
            if P.get('foresight_public_matriarch_sleep', False) and e.get('name') == 'Lagavulin Matriarch':
                from policy import foresight
                mv = foresight.identify(e)
                f3 = foresight.future(e, mv, 3, projected_hp_damage=dmg[e['index']]) if mv == 'SLEEP_MOVE' else None
                if f3: fut0 = sum(f3) / len(f3)
            ens.append({'index': e.get('index'), 'fut': fut0, 'ehp': e_left + foes[e['index']].blk, 'intent': 0 if (e.get('index') in shriek_stunned or e.get('index') in ctx.get('_stunned', ())) else inc,
                        'str': next((pp.get('amount') or 0 for pp in e.get('powers') or [] if str(pp.get('name', '')).lower() == 'strength'), 0),
                        'minion': 1 if has_power(e, 'minion') else 0, 'vuln': 1 if (vuln_on(e) or has_power(e, 'vulner')) else 0,
                        'weak': 1 if (weak_on(e) or has_power(e, 'weak')) else 0})
        if ends_fight: ens = []                           # 主怪全死：战斗结束（随从跟着跑）
        # 口径和采集时一致（点「结束回合」之前）：回合末的遗物格挡、手里灼伤的掉血还没发生，不算进局面
        sit = dict(s0, hp=hp - self_hp, block=block - blk_x, str=s0['str'] + sum(str_now(c) for c in combo),
                   n_pw=s0['n_pw'] + sum(1 for c in combo if c.get('type') == 'Power'), enemies=ens)
        v = CV.predict(sit)
        if ctx.get('_parts') is not None: ctx['_parts']['sit'] = sit          # 估值模型蒸馏（tools/train_cv_teacher.py）用
        old_core = ctx['alpha'] * dealt + P['kill_bonus'] * killed - hp_cost
        # 新代价 = 这回合自己扣的血 + 预测之后还要掉的血 + 荆棘等额外掉血 + 出牌惩罚 + 当回合必死重罚
        # （模型的目标是「之后掉的血」，血多的局面数值也大，所以自伤必须单独算上，不然自伤牌会被当成好事）
        # v2：这次敌方回合的伤害（unblocked，含回合末灼伤等）精确算，模型只给之后的部分
        cv_cost = (unblocked + v + self_hp + extra_hp + (rl.get('card_penalty', 0) * max(0, len(combo) - 1))
                   + (P['death_penalty'] if (left <= 0 or sand_dead) else 0))
        if os.environ.get('STS2_CV_DEBUG'):
            print('CVDBG', [c.get('name') for c in combo], 'ends', ends_fight, 'left', left, 'unb', unblocked, 'v', round(v, 1), 'self', self_hp,
                  'extra', extra_hp, 'old_core', round(old_core, 1), 'hp_cost', round(hp_cost, 1), 'score_before', round(score, 1))
        score = score - old_core * P['cv_weight'] - cv_cost * P['cv_weight'] * P['cv_scale']
    if P.get('mental_on') and ctx.get('mm') is not None:
        # 脑内战斗模型：不碰引擎，按源码出招表和牌组强度心算之后几回合，
        # 把「伤害 × alpha − 掉血代价」这一块换成心算的结局（赢 = 剩余血，输 = −罚分），权重 mental_w
        from policy import mentalmodel as MM
        mm = ctx['mm']
        sched, cur_heal, cur_blk = mm['sched'], mm['cur_heal'], mm['cur_blk']
        if P.get('foresight_public_matriarch_sleep', False) and any(e.get('name') == 'Lagavulin Matriarch' and dmg[e['index']] > 0 for e in ctx['mains']):
            projected = MM.schedule(ctx['mains'], len(sched), {}, public_player_powers=ctx.get('player_powers'), hp_damage_by_index=dmg)
            if projected is not None: cur_heal, cur_blk, sched = projected
        e1 = 0 if ends_fight else sum(max(0, (e.get('hp') or 0) - dmg[e['index']]) for e in ctx['mains'])
        sflat = sum(str_amount(c, STR_POWERS[cid(c)][1]) for c in combo if cid(c) in STR_POWERS and STR_POWERS[cid(c)][0] == 'flat')
        sturn = sum(str_amount(c, STR_POWERS[cid(c)][1]) for c in combo if cid(c) in STR_POWERS and STR_POWERS[cid(c)][0] == 'per_turn')
        vt = max([VULN[i] - 1 for i in ids if i in VULN] + [mm['vuln'] - 1, 0])
        v = MM.value(left, e1, mm['e0'], mm['D'], mm['B'], mm['hits'], sched, str_flat=mm['str'] + sflat, str_turn=mm['str_turn'] + sturn,
                     vuln_turns=vt, cur_heal=0 if ends_fight else cur_heal, cur_blk=0 if ends_fight else cur_blk)
        core = ctx['alpha'] * dealt + P['kill_bonus'] * killed - hp_cost
        w = P.get('mental_w', 1.0)
        score = score - w * core + w * P.get('mental_scale', 1.0) * v
    if ctx.get('_parts') is not None:                  # 重排函数（policy/rerank.py）用的打分明细
        ctx['_parts']['cur'] = dict(sit=ctx['_parts'].pop('sit', None), score=score, dealt=dealt, killed=killed, thresh=thresh, hp_cost=hp_cost, unblocked=unblocked, powers=powers,
                                    draw=draw, self_hp=self_hp, left=left, ends=float(ends_fight), block=block, incoming=incoming, unspent=unspent,
                                    e_after=sum(max(0, (e.get('hp') or 0) - dmg[e['index']]) for e in ctx['mains']))
    return score


def _facing_extra(combo, ctx, tgt, p, enemies, block, alive_after=None):
    """帝皇蟹（研究 12 号 2.1）：背后那只伤害 ×1.5；这回合最后一张带目标的牌决定朝向。
    返回「打完这组牌后的实际来伤 − 现在显示的来伤」里没被格挡吃掉的部分（正 = 多挨打）。显示的意图已经含 ×1.5（背后那只）"""
    if (P.get('crab_facing_after_kill', False) and alive_after is not None
            and {e.get('name') for e in enemies} == {'Crusher', 'Rocket'}
            and any(str(pw.get('id', '')).split('.')[-1] == 'SURROUNDED_POWER' for pw in ctx.get('player_powers') or [])
            and not any(EP.revives(e) for e in enemies) and len(alive_after) < 2):
        # Surrounded.AfterDeath turns toward the surviving crab. Once both
        # are dead there is no attack. Do not charge a fictional back attack;
        # current HUD and Crab Rage costs retain their existing estimates.
        return 0.0
    facing = ctx.get('facing') or 'rocket'
    name = lambda e: 'rocket' if 'rocket' in str(e.get('name', '')).lower() else 'crusher'
    shown = {name(e): intent_damage(e) for e in enemies}
    raw = {k: (v / 1.5 if k != facing else v) for k, v in shown.items()}
    if P.get('crab_facing_big_only', True) and raw.get('rocket', 0) < 15:
        return 0.0      # 高手录像研究 T3：只在火箭光束 / 激光回合（20~41）讲朝向；其他回合朝错只多挨 5~10，不准为了转身把伤害从火箭挪走
    last = None
    for c in sorted(combo, key=ORDER):
        if c.get('target_type') == 'AnyEnemy':
            t = tgt.get(id(c)) or p
            if t: last = name(t)
    new = last or facing
    now_in = sum(shown.values()); after_in = sum(v * (1.5 if k != new else 1.0) for k, v in raw.items())
    return max(0.0, after_in - block) - max(0.0, now_in - block)


def note_facing(st, mem, a, args):
    """记下现在面朝帝皇蟹的哪一只（打出带目标的牌 / 对敌人用药水就转过去）"""
    t = (args or {}).get('target_index')
    if t is None: return
    e = next((x for x in st.get('enemies') or [] if x.get('index') == t), None)
    if e and ('rocket' in str(e.get('name', '')).lower() or 'crusher' in str(e.get('name', '')).lower()):
        mem['crab_facing'] = 'rocket' if 'rocket' in str(e.get('name', '')).lower() else 'crusher'


ORDER_UNRELENTING = 5.6


def ORDER(c):
    """同一回合内的出牌顺序：免费抽牌 → 加能量 → 能力 → 加力量 → 易伤 / 虚弱 → 技能 → 攻击 → 全身撞击"""
    i = cid(c)
    # evaluate 已把本组逃离计入沙坑 +1：先打出去，避免后面的坚毅 / 重振精神 / 添柴 / 余烬烧掉它。
    if i == 'FRANTIC_ESCAPE' and P.get('sandpit_escape_first', False): return 4.5
    k = longterm.order_key(c)
    if k is not None: return k
    if i in DRAW and card_cost(c, 99) == 0: return 0
    if i in ENERGY: return 1
    if c.get('type') == 'Power': return 2
    if i in STR_NOW and c.get('type') != 'Attack': return 3
    if i in VULN or i in WEAK or i == 'RAGE': return 4
    if c.get('type') == 'Skill': return 5
    # 整顿打击（本回合 +3 临时力量）/ 单挑（+3 力量）是攻击，打完才加力量：排在普通攻击前面，后面的攻击才吃得到；
    # 无情猛攻（下一张攻击免费）同理先打（Codex 发现，梳理表 C05；原来都和普通攻击同档，按手牌位置谁先谁后）
    if i in STR_NOW: return 5.5
    if i == 'UNRELENTING': return ORDER_UNRELENTING
    if i == 'BODY_SLAM': return 7
    if i in XCOST: return 8                    # X 费（旋风斩 / 齐射 / 瀑流）：花掉剩下的全部能量，最后打
    if i == 'FIEND_FIRE': return 9             # 恶魔之焰：消耗全部手牌，同组其他牌都打完再打
    return 6


def _atk_hits_per_turn(deck):
    """每回合大概打出几段攻击（牌组里攻击牌的比例 × 5 张手牌 × 段数），给力量类能力估值用"""
    if not deck: return 2.0
    hits = sum(HITS.get(cid(c), 1) for c in deck if c.get('type') == 'Attack')
    return max(1.0, min(4.0, hits / len(deck) * 5))


def card_limit(st, mem):
    """这回合还能打几张牌：读玩家身上「最多打出 N 张 / 只能打出一张」这类减益（嚎叫、懒惰……）"""
    import re
    lim = 99
    for p in st.get('player_powers') or []:
        txt = f"{p.get('name', '')} {p.get('description', '')}"
        m = re.search(r'(?:more than|only play|最多|只能打出)\s*(\d+)?', txt)
        if m and re.search(r'card|牌', txt):
            n = int(m.group(1)) if m.group(1) else (p.get('amount') or 1)
            lim = min(lim, n)
    return max(lim - mem.get('plays_this_turn', 0), 0) if lim < 99 else 99


APPLIERS = {'Shrinker Beetle'}   # 施加「它死才解除」减益的怪（applier_focus）。滑行绞杀藤（缠绕）、幽灵骑士（诅咒印记）同类机制但还没测，先不加


def candidates(pool, ctx, topk):
    """规划器的前 K 名候选 [(分数, 组合)]（推演和重排函数共用）：前 K 名 + 格挡最多 / 伤害最多的各一种 +「什么都不打」"""
    e0 = evaluate((), ctx) or 0
    picked = sorted(pool.values(), key=lambda t: -t[0])[:topk]
    # 10/3：「什么都不打」只在规划器自己也觉得差不多时才当候选——推演样本少，空方案偶尔靠运气赢，
    # 再被「留牌」锁死，就会出现「3 能量、敌人要打 20、手里全是攻击、一张不打」（SK3CDB8PYY0L 打异蛙寄生虫）
    top = picked[0][0] if picked else e0
    res = [(e0, ())] if e0 >= top - P.get('search_empty_margin', 3.0) else []
    # 再补两种「风格不同」的：格挡最多的、伤害最多的（规划器分数前几名往往大同小异，像「两张防御 + 一张打击」这种可能排不进去）
    st_ = lambda c, k: ((c.get('stats') or {}).get(k) or 0)
    for key in (lambda t: (sum(st_(c, 'block') for c in t[1]), t[0]), lambda t: (sum(st_(c, 'damage') for c in t[1]), t[0])):
        extra = max(pool.values(), key=key, default=None)
        if extra is not None and all(extra[1] is not x[1] for x in picked): picked.append(extra)
    return res + picked


def plan(st, mem, bad, want_score=False, topk=0):
    hand = st.get('hand') or []
    energy = st.get('energy') or 0
    enemies = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    pl = st.get('player') or {}
    hp, block = pl.get('hp', 1), pl.get('block', 0)
    if not enemies: return None
    is_minion = lambda e: has_power(e, 'minion')
    mains = [e for e in enemies if not is_minion(e)] or enemies
    incoming = sum(intent_damage(e) for e in enemies)
    hits_in = sum(max(it.get('hits') or 1, 1) for e in enemies for it in e.get('intents') or []
                  if is_attack_intent(it))
    playable = [c for c in hand if c.get('can_play') and card_cost(c, energy) <= energy + 3 and (c['index'], cid(c)) not in bad]
    if not playable: return None
    rules = kb.enemy_rules((st.get('context') or {}).get('encounter'), [e.get('name') for e in enemies])
    if P.get('ud_rules', False):                       # 暗港经验（源码核对见 policy/mapprep.py 文档）
        enc = str((st.get('context') or {}).get('encounter') or '').replace('ENCOUNTER.', '')
        if enc in ('SEAPUNK_NORMAL', 'CULTISTS_NORMAL'):
            # 钙化教徒（左边那只）第 1 回合拿 2 层仪式，之后每回合 +2 力量（11 → 13 → 15…）；海洋混混每 3 回合才 +2 → 先打教徒
            rules = dict(rules, prefer_target='Calcified Cultist', scaling=True)
        fysh = [e for e in enemies if 'soul fysh' in str(e.get('name', '')).lower()]
        if fysh and any(str(it.get('type', '')).lower() == 'buff' for it in fysh[0].get('intents') or []) and not EP.amt(fysh[0], 'intangible'):
            # 灵魂异鱼这回合的招是「消逝」（Buff，不攻击）：它出完给自己 2 层无形，我下一回合每次掉血压到 1（源码 SoulFysh.cs / IntangiblePower.cs）
            # 这回合是它无形前最后一个输出回合，按死线把伤害打满
            rules = dict(rules, deadline=True)
        if enc == 'HAUNTED_SHIP_NORMAL' and (st.get('round') or 1) == 1:
            # 幽灵船第 1 回合「纠缠」：不攻击，给我 3 层虚弱 + 5 张晕眩 → 之后我的伤害打七五折，第 1 回合把输出打满
            rules = dict(rules, deadline=True)
    if P.get('applier_focus', False) and len(enemies) > 1 and not rules.get('prefer_target'):
        # 「施加者死了才解除」的减益（源码 ShrinkPower / ConstrictPower / HexPower 的 AfterDeath）：缩小甲虫第 1 回合给缩小（攻击 −30%，
        # 没有回合数，甲虫死才解除）、滑行绞杀藤（缠绕每回合扣血）、幽灵骑士（手牌全虚无）→ 先打施加者。
        # 10/5 实测：毛绒蠕虫 + 缩小甲虫我们第 1 回合都打蠕虫（攻击意图 ×0.6 让它当主攻），平均掉血 21.6，人类赢家 9.3 / 输家 14.8
        ap = next((e for e in enemies if str(e.get('name', '')) in APPLIERS), None)
        if ap is not None: rules = dict(rules, prefer_target=ap['name'])
    focus = min(mains, key=lambda e: ((e.get('hp') or 0) + (e.get('block') or 0)) * (0.6 if intent_damage(e) > 0 else 1))
    atk = sorted([c for c in playable if c.get('type') == 'Attack'], key=lambda c: -base_damage(c, focus))
    my_dpt = max(1.0, sum(base_damage(c, focus) for c in atk[:max(energy, 1)]))
    mem['last_my_dpt'] = my_dpt
    # 敌人「平均每回合」打多少：ema = 跨回合的平均（不攻击的回合也算进去）；max = 取这回合和平均里大的
    turn_key = ((st.get('context') or {}).get('floor'), st.get('round'))
    if mem.get('in_turn') != turn_key:
        mem['in_turn'] = turn_key
        mem['avg_in'] = (1 - P['alpha_ema']) * mem.get('avg_in', incoming) + P['alpha_ema'] * incoming
    avg_in = max(incoming, mem.get('avg_in', 8)) if P['alpha_in_mode'] == 'max' else mem.get('avg_in', incoming)
    if P['foresight_w'] > 0:                               # 预判：按出招表推算接下来几回合的平均伤害（认不出招就不用）
        fut = foresight.expected_incoming(enemies, mem, public_player_powers=st.get('player_powers'))
        if fut is not None: avg_in = (1 - P['foresight_w']) * avg_in + P['foresight_w'] * (incoming + fut * P['foresight_turns']) / (1 + P['foresight_turns'])
    # 兑换率 = 「挡不住的部分」÷ 我每回合的伤害：能挡满时多挡，挡不住时多打（越早打完越少挨打）
    blockers = sorted([c for c in playable if ((c.get('stats') or {}).get('block') or 0) > 0],
                      key=lambda c: -((c.get('stats') or {}).get('block') or 0) / max(card_cost(c, energy), 0.5))
    cap, e_left = 0, energy
    for c in blockers:
        k = card_cost(c, energy)
        if k <= e_left: cap += (c.get('stats') or {}).get('block') or 0; e_left -= k
    unblockable = max(0, avg_in - cap - block)
    scaling = rules.get('scaling') or any(has_power(e, 'strength') or has_power(e, 'ritual') or has_power(e, 'territorial') for e in mains)
    # 10/3 claude-value：兑换率的分母原来用「这手牌里的攻击」，手里攻击少时分母变小、兑换率暴涨，反而更想打攻击不格挡
    # （g8 对照第一幕 Boss：37% 的挨打回合能多挡 >2 却打了攻击，平均少挡 6.3）。alpha_dpt_source：hand = 原样；
    # deck = 用整副牌的平均每回合伤害（deckeval，按牌组缓存）；max = 两者取大。只改兑换率，my_dpt 的其他用途不变
    src = P.get('alpha_dpt_source', 'hand')
    alpha_dpt = my_dpt
    if src != 'hand' and pl.get('deck'):               # 状态里没有牌组就退回按手牌算
        deck = pl.get('deck') or []
        dk = (len(deck), tuple(sorted(cid(c) + ('+' if c.get('upgraded') else '') for c in deck)))
        if mem.get('_deck_dpt_key') != dk:
            from policy import deckeval
            mem['_deck_dpt_key'] = dk
            mem['_deck_dpt'] = max(1.0, (deckeval.evaluate(deck) or {}).get('dmg_per_turn') or 1.0)
        alpha_dpt = mem['_deck_dpt'] if src == 'deck' else max(my_dpt, mem['_deck_dpt'])
    alpha = P['alpha_base'] + unblockable / alpha_dpt + (P['alpha_scaling_enemy'] if scaling else 0)
    alpha = min(P['alpha_max'], max(P['alpha_min'], alpha))
    pa_all = P.get('phase_alpha') or {}
    if pa_all == 'file':                              # 10/4：tools/phase_alpha.py 从人类分阶段打法生成的表
        from policy import knowledge as _kn
        pa_all = _kn.PHASE_ALPHA
    pa = pa_all.get(str((st.get('context') or {}).get('encounter') or '').replace('ENCOUNTER.', ''))
    if pa:
        # 按 Boss / 精英的出招阶段调伤害估值：
        # 认出主要敌人这回合的招（源码出招表 kb/monsters.json），乘上这一招的倍数——它不打人的回合全力输出、重击回合多防守。
        # 倍数由 policy/fightmodel.py（源码数值的动态规划）给方向、同牌组实打定大小；规划器和推演里接手的回合都用它
        from policy.public_move_beliefs import unique_move
        for e in mains:
            mv = unique_move(st, e, mem)  # only publicly distinguishable phases
            if mv and mv in pa:
                alpha = min(P['alpha_max'] * max(pa[mv], 1.0), max(P['alpha_min'], alpha * pa[mv])); mem['phase_move'] = mv
                break
    if rules.get('deadline'): alpha = max(alpha, P['deadline_alpha'])     # 无厌沙虫：死线前多余的血都换输出
    steam = max((EP.amt(e, 'steam') for e in mains), default=0)
    if steam and P.get('giant_race_w', 0):
        # 瀑布巨兽（源码 WaterfallGiant.cs：每招蒸汽 +3，打到 0 血后下个敌方回合按蒸汽层数爆炸）：多拖一回合 = 多挨一回合打 + 爆炸 +3。
        # 多打 1 点伤害 ≈ 少拖 1/每回合输出 回合，值 (3 + 平均来伤) / 每回合输出 点血 → 兑换率至少这么多。
        # 只当老师诊断：规划器在它身上每回合亏 10 血（手里防御多时一直挡，拖到第 17 回合被 62 点爆炸炸死）
        alpha = max(alpha, P['giant_race_w'] * (3 + avg_in) / max(alpha_dpt, 1))
    total_ehp = sum((e.get('hp') or 0) + (e.get('block') or 0) for e in mains)
    long = min(P['long_max'], max(P['long_min'], total_ehp / max(my_dpt, 1) / 3))
    ctx = dict(enemies=enemies, energy=energy, block=block, hp=hp, max_hp=pl.get('max_hp', hp), hand=hand, focus=focus, alpha=alpha, long=long, deck=pl.get('deck') or [], round=st.get('round') or 1,
               relics=longterm.relics(st), incoming=incoming, player_powers=st.get('player_powers') or [],
               stampede=any('stampede' in str(p.get('name', '')).lower() for p in st.get('player_powers') or []),
               hits_in=hits_in, mains=mains, rules=rules, my_dpt=my_dpt, facing=mem.get('crab_facing'),
               card_blocks=mem.get('card_blocks_this_turn', 0) if mem.get('plays_key') == ((st.get('context') or {}).get('floor'), st.get('round') or 1) else 0,
               sit=CV.situation_from_state(st) if P['cv_weight'] > 0 else None,
               turns_left=min(P['str_turns_cap'], total_ehp / max(my_dpt, 1)),
               atk_hits_turn=_atk_hits_per_turn(pl.get('deck') or []),
               reattach_finish=sum((e.get('hp') or 0) + (e.get('block') or 0) for e in enemies if EP.amt(e, 'reattach'))
                               <= (P['reattach_finish_turns'] + 0.5) * my_dpt,
               primaries=[focus] + [e for e in enemies if e is not focus][:P['max_primaries'] - 1])
    if P.get('mental_on'):
        from policy import mentalmodel as MM, deckeval
        sch = MM.schedule(mains, P.get('mental_turns', 6), mem, public_player_powers=st.get('player_powers'))
        if sch is not None:
            dk = pl.get('deck') or []
            D, B = deckeval.evaluate_mc(dk) if dk else (my_dpt, 10.0)
            pstr = sum(pp.get('amount') or 0 for pp in st.get('player_powers') or [] if str(pp.get('name', '')).lower() == 'strength')
            pturn = sum(pp.get('amount') or 0 for pp in st.get('player_powers') or [] if 'demon form' in str(pp.get('name', '')).lower())
            vul = max([pp.get('amount') or 0 for e in mains for pp in e.get('powers') or [] if 'vulner' in str(pp.get('name', '')).lower()] + [0])
            ctx['mm'] = dict(D=max(D * P.get('mental_dscale', 1.0), 1.0), B=max(B * P.get('mental_bscale', 1.0), 1.0), hits=ctx.get('atk_hits_turn') or 2, sched=sch[2], cur_heal=sch[0], cur_blk=sch[1],
                             e0=sum((e.get('max_hp') or e.get('hp') or 0) for e in mains), str=pstr, str_turn=pturn, vuln=vul)
    best = evaluate((), ctx) or 0; best_combo = ()
    cands = playable[:10]
    limit = card_limit(st, mem)
    pool = {}                                          # topk 用：每种「牌名组合」只留分最高的一种出法
    for r in range(1, min(len(cands), limit) + 1):
        for combo in itertools.combinations(cands, r):
            if sum(card_cost(c, energy) for c in combo) > energy + 3 + sum(ENERGY.get(cid(c), 0) for c in combo):
                continue
            ev = evaluate(combo, ctx)
            if ev is None: continue
            if topk or P.get('rerank_on') or P.get('nn_on'):
                k = tuple(sorted(cid(c) + ('+' if c.get('upgraded') else '') for c in combo))
                if k not in pool or ev > pool[k][0]: pool[k] = (ev, combo)
            if ev > best + 1e-6:
                best, best_combo = ev, combo
    if want_score: return best
    if topk == -1:                                     # 训练模仿层用：所有可行组合（每种牌名组合一个）和上下文
        return {'ctx': ctx, 'pool': [(evaluate((), ctx) or 0, ())] + list(pool.values())}
    if topk:
        # 前 K 名候选（推演用）：[(分数, 按出牌顺序排好的 [(牌, 目标 index)])]，「什么都不打」也算一个
        res = []
        for sc, combo in candidates(pool, ctx, topk):
            if not combo: res.append((sc, [])); continue
            _, tgt, p = evaluate(combo, ctx, want_targets=True)
            seq = sorted(combo, key=ORDER)
            res.append((sc, [(c, (tgt.get(id(c)) or p)['index']) for c in seq]))
        res.sort(key=lambda t: -t[0])
        return res
    if P.get('rerank_on') and pool:
        # 重排函数（policy/rerank.py）：从推演老师的打分学来的，在规划器的前几名候选里重新挑（不开引擎，代替推演）
        from policy import rerank
        bc = rerank.choose(candidates(pool, ctx, P.get('rerank_k', 8)), ctx, st, mem)
        if bc is not None: best_combo = bc
    if P.get('nn_on') and pool:
        # 神经网络策略（policy/nnpolicy.py，AlphaGo 路线）：从自我对弈的推演结局学来的，在规划器的前 K 名候选里挑
        from policy import nnpolicy
        bc = nnpolicy.choose(candidates(pool, ctx, P.get('nn_k', 5)), ctx, st, mem)
        if bc is not None: best_combo = bc
    if not best_combo:
        return None
    _, tgt, p = evaluate(best_combo, ctx, want_targets=True)
    now = [c for c in best_combo if card_cost(c, energy) <= energy] or list(best_combo)
    slip = lambda c: tgt.get(id(c)) is not None and EP.amt(tgt[id(c)], 'slippery') > 0
    def key(c):   # 打滑溜的敌人：先出每段伤害小的攻击磨层数，易伤牌不再抢先（必须最后打的 X 费 / 全身撞击 / 狂宴不动）
        if c.get('type') == 'Attack' and slip(c) and ORDER(c) <= 6:
            return (6, _hits_on(c, tgt[id(c)], {'str_bonus': 0, 'slam': 0, 'cap': None, 'n_pre': 0, 'whirl': {}}, False)[0])
        return (ORDER(c), 0)
    c = min(now, key=key)
    return c, (tgt.get(id(c)) or p)['index']


def _note_block_play(mem, c):
    """本回合已经打了几张「从牌获得格挡」的牌（岿然不动只翻倍前 N 次，规划时要知道还剩几次）"""
    if ((c.get('stats') or {}).get('block') or 0) > 0:
        mem['card_blocks_this_turn'] = mem.get('card_blocks_this_turn', 0) + 1


def decide(st, mem, sim=None):
    enemies = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    pl = st.get('player') or {}
    room = (st.get('context') or {}).get('room_type', '')
    rnd = st.get('round') or 1
    ck = ((st.get('context') or {}).get('act'), (st.get('context') or {}).get('floor'))
    if mem.get('combat_key') != ck:            # 新的一场战斗：重置只在本场有效的记录
        mem['combat_key'] = ck; mem.pop('paels_used', None); mem.pop('avg_in', None); mem.pop('crab_facing', None)
    bad = mem.setdefault('bad', set())          # 这回合打出时报错的牌（牌名 + 当时的位置）
    key = ((st.get('context') or {}).get('floor'), rnd)
    if mem.get('turn_key') != key:
        mem['turn_key'] = key; bad.clear()
    incoming = sum(intent_damage(e) for e in enemies)
    need = max(0, incoming - pl.get('block', 0))
    perm = longterm.permanent_potion(st)
    if perm and enemies: return ('use_potion', {'potion_index': perm['index']})
    from policy import search as _srch
    # 10/4 药水进推演：推演管着这回合（真实对局里要推演，或推演模拟里正在按候选方案打这回合）时，药水交给推演比较，规则只管「这回合会死」
    tp_now = (mem.get('turn_plan') or {}).get('key') == key
    pot_by_search = (P.get('search_potions', False) and not P.get('search_teach_only') and need < pl.get('hp', 1)
                     and (tp_now or (sim is not None and _srch.enabled(st, mem))))   # 只当老师时药水照规则喝（推演不下场）
    p = None if pot_by_search else potions.decide(st, mem, need, pl.get('hp', 1), room, rnd, enemies)
    if p: return p
    if not enemies: return ('end_turn', {})
    if mem.get('plays_key') != key: mem['plays_key'] = key; mem['plays_this_turn'] = 0; mem['card_blocks_this_turn'] = 0
    from policy import search                   # 放这里：search 也 import 了本模块
    every_act = P.get('search_every_action', False)   # 每个决策点都重推，不沿用上一次的方案
    if sim is not None and search.enabled(st, mem) and (mem.get('searched_key') != key or every_act):
        mem['searched_key'] = key
        seq = search.search_turn(st, mem, sim)       # 精英 / Boss：每回合开始先用引擎推演选方案
        mem['turn_plan'] = search.make_plan(key, st.get('hand') or [], seq) if seq is not None else None
    nxt = search.next_action(st, mem)
    if nxt is None and sim is not None and mem.get('searched_key') is None and search.enabled(st, mem):
        # search_replan_on_draw=2：方案执行中抽到 / 生成了新牌，在当前局面重新推演（10/3 claude-value）
        mem['searched_key'] = key
        seq = search.search_turn(st, mem, sim)
        mem['turn_plan'] = search.make_plan(key, st.get('hand') or [], seq) if seq is not None else None
        nxt = search.next_action(st, mem)
    if nxt and nxt[0] == 'use_potion':
        return nxt
    if nxt:
        c = next((x for x in st.get('hand') or [] if x.get('index') == nxt[1]['card_index']), {})
        mem['last_try'] = (c.get('index'), cid(c)); mem['last_card'] = cid(c); mem['plays_this_turn'] = mem.get('plays_this_turn', 0) + 1
        _note_block_play(mem, c)
        note_facing(st, mem, *nxt)
        return nxt
    st = search.reserve(st, mem)                 # 方案打完：留着不打的牌不再打，规划器只管新抽到的牌
    rel = longterm.relics(st)
    if 'PAELS_EYE' in rel and not mem.get('paels_used') and mem['plays_this_turn'] == 0:
        best = plan(st, mem, bad, want_score=True)
        if handrules.hand_is_junk(st.get('hand') or []) or (best is not None and best < P['paels_eye_min_score']):
            mem['paels_used'] = True
            return ('end_turn', {})
    r = plan(st, mem, bad)
    if r is None: return ('end_turn', {})
    c, t = r
    mem['last_try'] = (c['index'], cid(c)); mem['last_card'] = cid(c); mem['plays_this_turn'] = mem.get('plays_this_turn', 0) + 1
    _note_block_play(mem, c)
    args = {'card_index': c['index']}
    if c.get('target_type') == 'AnyEnemy' and len(enemies) > 1: args['target_index'] = t
    note_facing(st, mem, 'play_card', args)
    return ('play_card', args)
