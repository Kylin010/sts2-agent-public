"""路线（期望值版，route_mode = ev）：把血当货币，枚举这一幕剩下的所有路线，沿途模拟血量，挑「收益 − 风险」最高的。

每类房间：
  期望掉血  E = 基础值（按幕、房间类型，params 里 route_dmg_*）× 牌组强度修正（牌组越弱掉得越多）
  期望收益（都折算成「值多少血」）：卡牌奖励 route_v_card、遗物 route_v_relic、升级 route_v_upgrade、金币、药水……
  问号房：按源码规则（kb/rules.json）：怪物 / 商店 / 宝箱各有计数，起步 10% / 3% / 2%，开出哪种它就回到起步值，
  其余各加一档，剩下的都是事件；每幕重置。实际开出什么由 resolve_unknown 记下来
  第一幕前 3 场普通战（第二、三幕前 2 场）必定是弱遭遇（源码规则），掉血按弱遭遇算
死亡风险：每场战斗按「进场血量 vs 期望掉血」估一个死亡概率，乘 route_death_cost 扣分。
到 Boss 时剩的血也算价值（route_v_boss_hp 每点），Boss 本身的风险也算进去。
休息点：血量低于 route_rest_below 就当作回血，否则当作升级。
"""
import math
from params import P
from policy import deckeval


def _projected_rest_threshold(act, before_boss):
    """Optional base-rule alignment, without running a policy or native model.

    This forecasts the existing camp rule; it does not choose more upgrades
    or change the player's actual camp decision. Custom camp policies retain
    the old approximation rather than pretending their future choice is known.
    """
    threshold = P['route_rest_below']
    override = P.get('route_rest_boss_heal_below')
    if override is None or not before_boss:
        return threshold
    if act not in P.get('route_rest_boss_heal_acts', [2]):
        return threshold
    if P.get('rest_mode', 'rule') != 'rule' or P.get('rest_boss_sim') or P.get('rest_potion_smith'):
        return threshold
    if not isinstance(override, (int, float)) or isinstance(override, bool) or not math.isfinite(override):
        return threshold
    return max(threshold, min(1.0, max(0.0, override)))


def _death_p(hp, e):
    """带着 hp 进一场期望掉 e 血的战斗，死掉的概率（掉血近似正态，标准差 = route_dmg_spread × 期望）"""
    if e <= 0: return 0.0
    z = (hp - e * P['route_dmg_spread_k']) / (P['route_dmg_spread'] * e)     # 掉血按 ±55% 波动（80 血第一幕实测：普通战 22±12，精英 33±17）
    return 1 / (1 + math.exp(min(30, max(-30, 1.7 * z))))


def _entry_relic_heal(room_type, player):
    """Fixed room-entry effects from currently visible owned relics only.

    The deck size stays at its current public value. Future rewards, shop
    stock, and random question-mark outcomes are not inferred here.
    """
    relics = {str(r.get('id') or '').removeprefix('RELIC.')
              for r in player.get('relics') or []}
    if room_type == 'Shop' and 'MEAL_TICKET' in relics:
        return 15
    if room_type == 'RestSite' and 'ETERNAL_FEATHER' in relics:
        return 3 * (len(player.get('deck') or []) // 5)
    return 0


def _project_entry_hp(hp, max_hp, room_type, player, act):
    if (not P.get('route_entry_relic_heal', False)
            or act not in P.get('route_entry_relic_heal_acts', [2]) or hp <= 0):
        return hp
    return min(max_hp, hp + _entry_relic_heal(room_type, player))


def _combat_reward_amounts(player, act):
    """Expected resource gains, respecting currently owned public prohibitions.

    These amounts retain the route model's existing expectations. Ectoplasm
    forbids new gold; Sozu forbids new potions, not the use of existing ones.
    Future acquisitions/removals and unseen reward rolls are not inputs.
    """
    gold_ok = potion_ok = True
    if (P.get('route_forbidden_reward_gains', False)
            and act in P.get('route_forbidden_reward_gains_acts', [2])):
        relics = {str(r.get('id') or '').removeprefix('RELIC.')
                  for r in player.get('relics') or []}
        gold_ok = 'ECTOPLASM' not in relics
        potion_ok = 'SOZU' not in relics
    return {'monster_gold': 11 if gold_ok else 0, 'elite_gold': 30 if gold_ok else 0,
            'monster_potion': 0.4 if potion_ok else 0.0,
            'elite_potion': 0.52 if potion_ok else 0.0}


def choose(sim_map, st, mem):
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    hp0, mx = pl.get('hp', 1), max(pl.get('max_hp', 1), 1); gold0 = pl.get('gold', 0)
    act = min(max(int(ctx.get('act') or 1), 1), 3)
    reward_amounts = _combat_reward_amounts(pl, act)
    nodes = {(n['col'], n['row']): n for row in sim_map.get('rows') or [] for n in row}
    ev = deckeval.evaluate(pl.get('deck') or [])
    extra = 0.0
    if P.get('route_body_slam_strength', False) and act in P.get('route_body_slam_strength_acts', [2]):
        relics = {str(r.get('id') or '').removeprefix('RELIC.') for r in pl.get('relics') or []}
        if 'SNECKO_EYE' not in relics:
            from policy import route_body_slam
            extra = route_body_slam.increment(pl.get('deck') or [], P.get('route_body_slam_samples', 160))
            ev = {**ev, 'dmg_per_turn': ev['dmg_per_turn'] + extra}
    need = {1: P['elite_dpt_act1'], 2: P['elite_dpt_act2'], 3: P['elite_dpt_act3']}[act]
    weak_deck = max(0.6, min(2.5, (need / max(ev['dmg_per_turn'], 1)) ** P['route_deck_gamma']))   # 牌组弱 → 掉血多
    dm = {t: P[f'route_dmg_{t}'][act - 1] * weak_deck for t in ('monster', 'elite', 'boss')}
    if P.get('simeval_route'):                     # 实打估计：这副牌打这一幕精英 / Boss 平均掉多少血（policy/simeval.deck_damage）
        from policy import simeval
        dd = simeval.deck_damage(st)
        for t in ('elite', 'boss'):
            if t in dd: dm[t] = dd[t] * P['simeval_route_k']
    dm['weak'] = dm['monster'] * P['route_weak_factor']
    n_weak = 3 if act == 1 else 2
    fights_done = mem.get('act_fights', {}).get(act, 0)          # 本幕已经打过几场普通战（含问号里的）
    odds0 = dict(unknown_odds(mem, act))                          # 下一个问号开出 怪物 / 商店 / 宝箱 的概率（源码规则，见 note_room）
    pots = sum(1 for p in pl.get('potions') or [] if p and p.get('name'))
    V = lambda k: P[f'route_v_{k}']
    eb = P.get('route_elite_bonus', 0)                # 一个数 = 每幕一样；列表 = 第一 / 二 / 三幕分开（第二幕精英难得多）
    elite_bonus = eb[act - 1] if isinstance(eb, list) else eb
    shop_cap = P.get('route_shop_cap', 1.0)            # 商店价值按「每 150 金算一份」，最多几份（10/3：原来封顶 1 份，带着 551 金整局没进过商店）
    shop_min = P.get('route_shop_min_gold', 0)         # 低于这个钱数在商店什么都买不起：不算价值
    # 准备度分数：
    # 血 40 + 输出 25 + 格挡 10 + 群伤 5 + 成长 5 + 遗物 10（每个 1.25）+ 药水 10（每瓶 4），满分 100。
    # 路线里血量是沿路模拟的（每打一场，后面节点的分数跟着降）；牌组 / 遗物 / 药水按现在的算
    blk_need = {1: P['block_target_act1'], 2: P['block_target_act2'], 3: P['block_target_act3']}[act]
    n_rel = len(pl.get('relics') or [])

    ready_on = P.get('route_ready_on', False) and act in P.get('route_ready_acts', [1, 2, 3])   # 10/3 第二代：分数制第一幕有利、第二幕不明显 → 可按幕开
    # 精英按对手算：多怪精英看群伤，单怪精英看单体输出和成长；按「打过哪些 → 下一个是谁」的概率加权
    from policy import elites as _el
    seen = list((mem.get('elites_seen') or {}).get(act, []))
    dpt_, bpt_ = ev['dmg_per_turn'], ev['block_per_turn']
    if P.get('deck_mc'):                               # 蒙特卡洛牌组强度（参考 Codex 25 号：随机 5 张 + 共享能量预算）
        dpt_, bpt_ = deckeval.evaluate_mc(pl.get('deck') or [])
        dpt_ += extra
    aoe_c = _el.aoe_capacity(st); dmg_r = min(1.0, dpt_ / max(need, 1)); blk_r = min(1.0, bpt_ / max(blk_need, 1))
    W = lambda k, d: P.get('route_w_' + k, d)          # 计分权重
    from policy import combos as _cb
    cpts, cfull, cnear = _cb.score(st)                  # 联动 / 核心成型 / 强力牌遗物药水（kb/combos.json）
    scale_r = min(1.0, ev['scaling'] / 2); misc = min(10.0, W('relic', 1.25) * n_rel) + min(10.0, W('pot', 4) * pots) + cpts
    mem['route_combos'] = [c.get('zh', c.get('id')) for c in cfull][:8]
    base_pts = (W('dmg', 25) * dmg_r + W('blk', 10) * blk_r + 5 * min(1.0, ev['aoe'] / 2) + 5 * scale_r + misc)
    fixed_multi = W('multi_dmg', 15) * dmg_r + W('blk', 10) * blk_r + W('multi_aoe', 15) * aoe_c + misc     # 多怪精英：群伤 15、输出 15
    fixed_single = W('dmg', 25) * dmg_r + W('blk', 10) * blk_r + W('single_scale', 5) * scale_r + misc     # 单怪精英：输出 25、成长 5
    n_seen = mem.get('act_elites', {}).get(act, 0)
    _dcache = {}

    def elite_ready(h, j):
        if j not in _dcache:
            d = _el.dist(act, seen, max(0, j))
            pm = sum(p for e, p in d.items() if e in _el.MULTI)
            _dcache[j] = (pm, d)
        pm = _dcache[j][0]
        return W('hp', 40) * max(0.0, h) / mx + pm * fixed_multi + (1 - pm) * fixed_single
    t_elite = P.get('route_ready_elite', [60, 65, 70])[act - 1]; t_mon = P.get('route_ready_monster', [35, 40, 45])[act - 1]

    def ready(h):
        return W('hp', 40) * max(0.0, h) / mx + base_pts

    def fight_adj(h, kind, j=0):
        """分数够 → 精英加分；不够 → 按差多少扣分（普通战只在低于战斗线时扣）。j = 路上第几个精英（0 = 下一个）"""
        if not ready_on: return 0.0
        pen = P.get('route_ready_pen', 15)
        if kind == 'elite':
            R = elite_ready(h, j) if P.get('route_elite_matchup', True) else ready(h)
            return P.get('route_ready_bonus', 40) if R >= t_elite else -pen * (t_elite - R) / 10
        return -pen * max(0.0, t_mon - ready(h)) / 10

    nd = _el.dist(act, seen, 0)
    mem['route_ready'] = (round(elite_ready(hp0, 0), 1), t_elite, t_mon,                   # 记进对局记录：打下一个精英的分数、精英线、战斗线、
                          {_el.ZH.get(e, e): round(p, 2) for e, p in nd.items()}, round(aoe_c, 2))   # 下一个精英的概率、群伤能力

    def shop_value(g):
        return V('shop') * min(shop_cap, max(0, g - shop_min) / 150)

    def fight(hp, e, kind):
        """打一场：返回 (新血量, 死亡风险扣分)"""
        risk = _death_p(hp + V('potion_hp') * min(pots, 2), e) * P['route_death_cost']
        return hp - e, risk

    SURV = P.get('route_survival', False)
    # 10/3（Codex 在它的路线模型里发现分数退化，我在 master 上量）：原来每场战斗单独扣「死亡概率 × 400」，沿路模拟的血量降到 0 以下后
    # 后面每一场都再扣 ~400——一条路线扣到 -1600（= 死了 4 次），战斗越多的路线被扣得越离谱，第二幕开局所有路线都在 -1000 上下。
    # route_survival：死亡只算一次——带着「还活着的概率」往下走，每个节点的收益和风险都乘它，死亡扣分总共不超过 route_death_cost
    def acc(val, alive, gain, p):
        if not SURV: return val + gain - p * P['route_death_cost'], alive
        return val + alive * ((1 - p) * gain - p * P['route_death_cost']), alive * (1 - p)

    best = {'v': -1e18}
    def walk(k, hp, gold, fights, odds, val, elites, path_first, alive=1.0):
        n = nodes.get(k) or {'type': 'Boss'}           # get_map 的节点表里没有 Boss 本身：查不到的就是 Boss（10/2 之前这里直接 return，
        t = n.get('type'); kids = n.get('children') or []   #  所有路线都没打分、永远选第一个——期望值路线一直没生效）
        if t == 'Boss' or not kids and t not in ('Monster', 'Elite', 'Unknown', 'RestSite', 'Shop', 'Treasure'):
            hp2, risk = fight(hp, dm['boss'], 'boss')
            hk = P.get('route_hp_util_k', 0.0)            # 非线性血量价值（参考 Codex 25 号 H(h,m)=h+k·m·ln(1+h/m)）：低血时每点血更值钱
            hv = max(0, min(hp, mx)); hv = hv + hk * mx * math.log1p(hv / mx) if hk else hv
            v, _ = acc(val, alive, V('boss_hp') * hv, risk / P['route_death_cost'])
            if v > best['v']: best.update(v=v, first=path_first)
            return
        if t == 'Monster':
            e = dm['weak'] if fights < n_weak else dm['monster']
            adj = fight_adj(hp, 'monster')
            hp, r = fight(hp, e, 'monster'); val, alive = acc(val, alive, adj + V('card') + V('gold') * reward_amounts['monster_gold'] + V('potion') * reward_amounts['monster_potion'], r / P['route_death_cost']); fights += 1; gold += reward_amounts['monster_gold']
        elif t == 'Elite':
            adj = fight_adj(hp, 'elite', elites - n_seen)
            hp, r = fight(hp, dm['elite'] * (1 + 0.1 * elites), 'elite')
            val, alive = acc(val, alive, adj + V('relic') + V('card_elite') + V('gold') * reward_amounts['elite_gold'] + V('potion') * reward_amounts['elite_potion'] + elite_bonus, r / P['route_death_cost']); elites += 1; gold += reward_amounts['elite_gold']
            # route_elite_bonus（10/3）：遗物和稀有牌的好处会滚到后面每一场，单幕里的「值多少血」算不出来；人类赢家第一幕打 2.57 个精英，我们 0.6
        elif t == 'Unknown':
            pm, ps, pt = odds['monster'], odds['shop'], odds['treasure']; pe = max(0.0, 1 - pm - ps - pt)
            e = dm['weak'] if fights < n_weak else dm['monster']
            _, r = fight(hp, e, 'monster')
            ub = P.get('route_unknown_bonus', 0.0)
            if hp < P.get('route_unknown_lowhp', 0.5) * mx: ub += P.get('route_unknown_lowhp_bonus', 0.0)
            if gold >= P.get('route_unknown_gold', 100): ub += P.get('route_unknown_gold_bonus', 0.0)
            val, alive = acc(val, alive, pm * (V('card') + V('gold') * reward_amounts['monster_gold'] + fight_adj(hp, 'monster')) + pe * V('event') + ps * shop_value(gold) + pt * V('relic') + ub,
                             pm * r / P['route_death_cost'])
            hp -= pm * e + pe * P['route_event_dmg']; fights += pm
            odds = _odds_step(odds, None)          # 期望意义下：每个计数按「没开出它」的概率往上加（近似）
        elif t == 'RestSite':
            hp = _project_entry_hp(hp, mx, t, pl, act)
            boss = sim_map.get('boss') or {}
            before_boss = bool(kids) and all(
                (c.get('col'), c.get('row')) == (boss.get('col'), boss.get('row'))
                or (nodes.get((c.get('col'), c.get('row'))) or {}).get('type') == 'Boss'
                for c in kids)
            if hp < _projected_rest_threshold(act, before_boss) * mx: hp = min(mx, hp + 0.3 * mx)
            else: val += alive * V('upgrade') if SURV else V('upgrade')
        elif t == 'Shop':
            hp = _project_entry_hp(hp, mx, t, pl, act)
            val += (alive if SURV else 1.0) * shop_value(gold); gold = max(0, gold - 150 * shop_cap)
        elif t == 'Treasure':
            val += (alive if SURV else 1.0) * V('relic')
        for c in kids:
            walk((c['col'], c['row']), hp, gold, fights, odds, val, elites, path_first, alive)

    scores = {}
    for c in st.get('choices') or []:
        best['v'] = -1e18; best.pop('first', None)
        walk((c['col'], c['row']), hp0, gold0, fights_done, odds0, 0.0, mem.get('act_elites', {}).get(act, 0), c)
        scores[(c['col'], c['row'])] = best['v']
    mem['route_scores'] = scores                     # 每个选项的最优路线价值（调试用）
    from policy import learn                       # 学出来的偏好 + 训练时的探索（policy/learn.py）
    opts = [(c, max(scores.get((c['col'], c['row']), -1e18), -1e6), learn.feats('route', (nodes.get((c['col'], c['row'])) or c).get('type') or 'Boss', st))
            for c in st.get('choices') or []]
    return learn.pick('route', opts, st, mem) if opts else None


BASE = {'monster': 0.10, 'shop': 0.03, 'treasure': 0.02}       # 源码 UnknownMapPointOdds：起步值 = 每次增量


def _odds_step(odds, hit):
    """问号开出 hit 之后：hit 回到起步值，其余各加一档；hit=None 表示规划时的期望近似（都按没开出算，怪物封顶 0.9）"""
    return {k: (BASE[k] if k == hit else min(v + BASE[k], 0.9)) for k, v in odds.items()}


def unknown_odds(mem, act):
    return mem.setdefault('unk_odds', {}).setdefault(act, dict(BASE))


def note_room(mem, st, room_type):
    """选了下一个地图点时记一下（本幕打了几场普通战、几个精英；问号待开奖），给上面的概率用"""
    act = (st.get('context') or {}).get('act', 1)
    for key, hit in (('act_fights', room_type == 'Monster'), ('act_elites', room_type == 'Elite')):
        d = mem.setdefault(key, {})
        if hit: d[act] = d.get(act, 0) + 1
    mem['pending_unknown'] = act if room_type == 'Unknown' else None


def resolve_unknown(mem, st):
    """进了问号房后，看它实际开出了什么，按源码规则更新计数（每进新的一幕全部重置）"""
    act = mem.get('pending_unknown')
    if not act: return
    rt = (st.get('context') or {}).get('room_type')
    if not rt or rt == 'Map': return
    hit = {'Monster': 'monster', 'Shop': 'shop', 'Treasure': 'treasure'}.get(rt)
    mem['unk_odds'][act] = _odds_step(unknown_odds(mem, act), hit) if hit else {k: min(v + BASE[k], 0.9) for k, v in unknown_odds(mem, act).items()}
    if hit == 'monster':
        d = mem.setdefault('act_fights', {}); d[act] = d.get(act, 0) + 1
    mem['pending_unknown'] = None
