"""社区整局记录 → 每一层「进入这一层之前」的家底（整局价值网络的训练数据，tools/train_run_value.py 用）。

一局 = map_point_history[幕][点]，每个点的 player_stats 是「打完这个点之后」的数值和这个点里发生的变化。
所以「进入第 k 个点之前」= 前 k-1 个点的变化累加起来；血量 / 上限 / 金币取上一个点打完时的值。

牌组：开局牌 + cards_gained（含商店买的、事件给的，带 current_upgrade_level）− cards_removed
      + cards_transformed（original → final，这两张不出现在 gained / removed 里）+ upgraded_cards / downgraded_cards。
遗物：结局遗物列表带 floor_added_to_deck（全局层号 = 第几个点，1 = 第一幕开头的先古之民）；
      中途被换掉 / 交易掉的遗物（relics_removed）用 relic_choices / bought_relics 记下的获得层补回去。
药水：potion_choices 选中 + bought_potions − potion_used − potion_discarded（只记 id 列表）。
校验：正向还原到最后一层的牌组，和结局 players[0].deck 逐张（id + 是否升级）对比，check_reconstruction() 报一致率。
"""
import collections, json

START_DECK = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']
START_HP, START_MAX_HP, START_GOLD = 64, 80, 99            # A10 铁甲开局（引擎里第一层先古之民时就是 64/80/99）
CHAPTERS = {'ACT.OVERGROWTH': 'OVERGROWTH', 'ACT.UNDERDOCKS': 'UNDERDOCKS'}
# 打法风格 / 水平的人群平均（v0.111 实测，按幕）：普通战掉血、精英战掉血、普通战回合数。历史统计记「和平均的差」
MU_DMG_M, MU_DMG_E, MU_TURNS_M = (9.1, 12.6, 11.2), (23.9, 26.6, 23.4), (4.15, 4.26, 3.91)

cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
rid = lambda x: str(x).replace('RELIC.', '')
pid = lambda x: str(x).replace('POTION.', '')
upg = lambda x: bool(isinstance(x, dict) and (x.get('current_upgrade_level') or 0) > 0)


def usable(d):
    """能用来训练的局：单人、没放弃、没模组、标准三幕、每幕点数正常"""
    if d.get('was_abandoned') or d.get('modifiers') or len(d.get('players') or []) != 1: return False
    if d.get('game_mode', 'standard') != 'standard': return False
    acts = d.get('acts') or []; mph = d.get('map_point_history') or []
    if len(acts) != 3 or acts[0] not in CHAPTERS or not mph or len(mph) > 3: return False
    if any(len(a) > 20 or len(a) == 0 for a in mph): return False
    return True


def _remove(deck, c, up):
    """从牌组拿掉一张：优先拿升级状态一致的，没有就拿另一种"""
    if deck[(c, up)] > 0: deck[(c, up)] -= 1; return True
    if deck[(c, not up)] > 0: deck[(c, not up)] -= 1; return True
    return False


def parse_run(d):
    """→ (局信息, 快照列表)。快照 = 进入某个点之前的家底：
    {act 1..3, done 本幕已打完几个点, gfloor 全局已打完几个点, hp, max_hp, gold, deck Counter{(id, 升级?): 张数},
     relics [id], potions [id], elites 已打精英数（整局）, elites_act 本幕已打精英数, next 下一个点的类型,
     hist 到目前为止的打法历史（普通战 / 精英战掉血和回合数相对人群平均、选牌跳过次数、篝火升级次数、删牌数）}
    另外每幕打完（Boss 之后、进下一幕之前）也出一个 done = 本幕点数 的快照；整局最后一个点之后（死了 / 赢了）不出。"""
    mph = d['map_point_history']; win = bool(d.get('win'))
    final_relics = [(rid(r.get('id')), int(r.get('floor_added_to_deck') or 1)) for r in d['players'][0].get('relics') or []]
    # 遗物获得层：结局列表里有的用它的 floor_added；中途丢掉的用获得记录补
    gained_at = collections.defaultdict(list)                   # 层号 → [遗物]
    for r, f in final_relics: gained_at[f].append(r)
    removed_at = collections.defaultdict(list)
    g = 0
    for act in mph:
        for p in act:
            g += 1; ps = (p.get('player_stats') or [{}])[0]
            for r in ps.get('relics_removed') or []:
                r = rid(r); removed_at[g].append(r)
                gained_at[_last_gain(mph, r, g)].append(r)    # 丢掉的那件不在结局列表里：按最近一次获得记录补获得层（没有记录 = 开局就有，比如燃烧之血）
    info = {'win': win, 'build': d.get('build_id'), 'chapter': CHAPTERS[d['acts'][0]], 'hash': d.get('run_hash'),
            'acts_len': [len(a) for a in mph]}

    deck = collections.Counter((c, False) for c in START_DECK); relics = collections.Counter(); pots = []
    hp, mhp, gold = START_HP, START_MAX_HP, START_GOLD; elites = 0; snaps = []; g = 0; picks = []
    # 到目前为止的打法历史（水平 / 风格的代理变量：训练时用真实值，运行时统一填人群平均，见 policy/runvalue.py）
    hist = {'n_m': 0, 'dmg_m': 0.0, 'turns_m': 0.0, 'n_e': 0, 'dmg_e': 0.0, 'n_rw': 0, 'n_skip': 0, 'n_rest': 0, 'n_smith': 0, 'n_rm': 0}
    n_total = sum(len(a) for a in mph)
    for ai, act in enumerate(mph):
        elites_act = 0
        for fi, p in enumerate(act):
            # ---- 进入这个点之前 ----
            snaps.append({'act': ai + 1, 'done': fi, 'gfloor': g, 'hp': hp, 'max_hp': mhp, 'gold': gold,
                          'deck': +deck, 'relics': sorted(relics.elements()), 'potions': list(pots),
                          'elites': elites, 'elites_act': elites_act, 'next': p.get('map_point_type'), 'hist': dict(hist)})
            g += 1; ps = (p.get('player_stats') or [{}])[0]
            if p.get('map_point_type') == 'rest_site':
                snaps[-1]['rest'] = list(ps.get('rest_site_choices') or []); snaps[-1]['rest_up'] = [cid(u) for u in ps.get('upgraded_cards') or []]
            if fi + 1 < len(act): snaps[-1]['after'] = act[fi + 1].get('map_point_type')       # 这个点之后的下一个点（篝火检验用：程序做决定时看得到地图）
            # ---- 这个点里发生的变化 ----
            for r in gained_at.get(g, []): relics[r] += 1
            for r in removed_at.get(g, []):
                if relics[r] > 0: relics[r] -= 1
            for c in ps.get('cards_gained') or []: deck[(cid(c), upg(c))] += 1
            for t in ps.get('cards_transformed') or []:
                o, f = t.get('original_card') or {}, t.get('final_card') or {}
                _remove(deck, cid(o), upg(o)); deck[(cid(f), upg(f))] += 1
            for c in ps.get('cards_removed') or []: _remove(deck, cid(c), upg(c))
            for u in ps.get('upgraded_cards') or []:
                u = cid(u)
                if deck[(u, False)] > 0: deck[(u, False)] -= 1; deck[(u, True)] += 1
            for u in ps.get('downgraded_cards') or []:
                u = cid(u)
                if deck[(u, True)] > 0: deck[(u, True)] -= 1; deck[(u, False)] += 1
            for x in ps.get('potion_choices') or []:
                if x.get('was_picked'): pots.append(pid(x.get('choice')))
            for x in ps.get('bought_potions') or []: pots.append(pid(x))
            for x in (ps.get('potion_used') or []) + (ps.get('potion_discarded') or []):
                x = pid(x)
                if x in pots: pots.remove(x)
            if len(pots) > 5: pots = pots[-5:]
            if p.get('map_point_type') == 'elite': elites += 1; elites_act += 1
            deck = +deck
            rt = [r.get('room_type') for r in p.get('rooms') or []]; tt = sum(r.get('turns_taken') or 0 for r in p.get('rooms') or [])
            k3 = min(ai, 2)
            if 'monster' in rt: hist['n_m'] += 1; hist['dmg_m'] += (ps.get('damage_taken') or 0) - MU_DMG_M[k3]; hist['turns_m'] += tt - MU_TURNS_M[k3]
            if 'elite' in rt: hist['n_e'] += 1; hist['dmg_e'] += (ps.get('damage_taken') or 0) - MU_DMG_E[k3]
            if p.get('map_point_type') == 'rest_site':
                hist['n_rest'] += 1; hist['n_smith'] += 1 if 'SMITH' in (ps.get('rest_site_choices') or []) else 0
            hist['n_rm'] += len(ps.get('cards_removed') or [])
            ch = ps.get('card_choices') or []
            if p.get('map_point_type') in ('monster', 'elite', 'boss') and 2 <= len(ch) <= 4:     # 战后选牌（检验「拿哪张」用）
                picked = [i for i, x in enumerate(ch) if x.get('was_picked')]
                if len(picked) <= 1:
                    offered = [(cid(x.get('card')), upg(x.get('card'))) for x in ch]
                    dk = +deck
                    if picked: _remove(dk, *offered[picked[0]])
                    hist['n_rw'] += 1; hist['n_skip'] += 0 if picked else 1
                    picks.append({'act': ai + 1, 'done': fi + 1, 'hp': ps.get('current_hp', hp), 'max_hp': ps.get('max_hp', mhp) or mhp,
                                  'gold': ps.get('current_gold', gold), 'deck': dk, 'relics': sorted(relics.elements()), 'potions': list(pots),
                                  'offered': offered, 'picked': picked[0] if picked else -1})
            hp = ps.get('current_hp', hp); mhp = ps.get('max_hp', mhp) or mhp; gold = ps.get('current_gold', gold)
        if ai < len(mph) - 1 and g < n_total:                    # 本幕打完、进下一幕之前（和下一幕 done=0 同一个家底，按「本幕已打完」再记一次）
            snaps.append({'act': ai + 1, 'done': len(act), 'gfloor': g, 'hp': hp, 'max_hp': mhp, 'gold': gold,
                          'deck': +deck, 'relics': sorted(relics.elements()), 'potions': list(pots),
                          'elites': elites, 'elites_act': elites_act, 'next': None, 'hist': dict(hist)})
    info['final_deck'] = +deck; info['final_relics'] = sorted(relics.elements()); info['picks'] = picks
    return info, snaps


def _last_gain(mph, r, upto):
    g = 0; last = 1
    for act in mph:
        for p in act:
            g += 1
            if g > upto: return last
            ps = (p.get('player_stats') or [{}])[0]
            got = [rid(x.get('choice')) for x in ps.get('relic_choices') or [] if x.get('was_picked')] + [rid(x) for x in ps.get('bought_relics') or []]
            if r in got: last = g
    return last


def check_reconstruction(d, info):
    """正向还原的最终牌组 vs 结局牌组：返回 (一致?, 牌张数差, 升级状态差, 遗物一致?)"""
    real = collections.Counter((cid(c), upg(c)) for c in d['players'][0].get('deck') or [])
    mine = info['final_deck']
    ids_real = collections.Counter(c for (c, _), n in real.items() for _ in range(n))
    ids_mine = collections.Counter(c for (c, _), n in mine.items() for _ in range(n))
    card_diff = sum(((ids_real - ids_mine) + (ids_mine - ids_real)).values())
    up_diff = abs(sum(n for (c, u), n in real.items() if u) - sum(n for (c, u), n in mine.items() if u))
    rel_ok = collections.Counter(rid(r.get('id')) for r in d['players'][0].get('relics') or []) == collections.Counter(info['final_relics'])
    return real == mine, card_diff, up_diff, rel_ok
