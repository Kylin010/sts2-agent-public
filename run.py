"""批量自动打牌、统计。三种评估方式（可以分段优化）：

  完整对局：  python3 run.py 40 --tag v2                  # 种子 s0~s39，4 个进程并行；看胜率、死在哪
  只打前几幕：python3 run.py 100 --stop-act 1 --tag a1    # 打完第一幕就停，看第一幕通过率和剩余血量
  练习模式：  python3 run.py 40 --god 999 --tag d2        # 血量 999 不会死，记录每场战斗比人类赢家多掉多少血
  单场演练：  python3 run.py 50 --scenario a2-decimillipede  # 固定牌组直接进某个战斗（scenarios.json），重复 50 个种子
  战斗基准：  python3 run.py 0 --bench                    # 用真人当时的牌组 / 遗物 / 血量打同一场战斗（data/bench.json），和人比掉血
  调参数：    python3 run.py 40 --set alpha_max=1.2 --set reward_skip_below=0.3
  看一局：    python3 run.py 1 --verbose --god 999
  种子：      默认用 data/dev_seeds.txt（游戏自己生成的 1000 个种子，固定下来方便比较版本）；
              --seeds game 每局现场让游戏生成新种子（最终的「连胜」测试用这个）
"""
import argparse, collections, copy, json, os, sys, time
from multiprocessing import Pool
import params
from sim import Sim, SimError, acquire, release
LOG_TURNS = os.environ.get('STS2_LOG_TURNS') == '1'      # 采集战斗局面（训练战斗估值模型用）
LOG_PLAYS = os.environ.get('STS2_LOG_PLAYS') == '1'      # 统计每张牌「在手里时打出的比例」（出牌偏好校准用）

HERE = os.path.dirname(os.path.abspath(__file__))
COMBAT_ROOMS = ('Monster', 'Elite', 'Boss')


def note_public_combat_hp(fight, state, *, final=False):
    """Optional additive metrics; legacy dmg/hp and training labels stay intact.

    Sampled positive HP drops are not gross engine damage: a single observed
    transition can include both damage and healing. Net loss uses the first
    combat-play observation and the first public observation after combat.
    """
    if not params.P.get('combat_hp_metrics', False):
        return
    hp = (state.get('player') or {}).get('hp')
    valid = isinstance(hp, int) and not isinstance(hp, bool) and hp >= 0
    metrics = fight.get('hp_metrics')
    if final and metrics is None:
        return          # An endpoint alone cannot establish a combat start HP.
    if valid:
        if metrics is None:
            metrics = fight['hp_metrics'] = {
                'start': hp, 'last': hp, 'observations': 0, 'sampled_loss': 0}
        metrics['sampled_loss'] += max(0, metrics['last'] - hp)
        metrics['last'] = hp
        metrics['observations'] += 1
    if final and metrics is not None:
        metrics.update(end=hp if valid else None,
                       net_loss=metrics['start'] - hp if valid else None,
                       end_decision=state.get('decision'),
                       complete=valid)


def describe(st, a, args):
    pl = st.get('player') or {}
    if st.get('decision') != 'combat_play':
        return f"[{(st.get('context') or {}).get('act')}-{(st.get('context') or {}).get('floor')}] hp={pl.get('hp')} {st.get('decision')} → {a} {args}"
    from policy.knowledge import intent_damage
    en = '; '.join(f"{e['name']}#{e['index']} {e['hp']}+{e.get('block', 0)} 意图{intent_damage(e)}"
                   for e in st.get('enemies') or [] if e.get('hp', 0) > 0)
    hd = ', '.join(f"{c['name']}({c.get('cost')}){'×' if not c.get('can_play') else ''}" for c in st.get('hand') or [])
    return f"[R{st.get('round')}] 血{pl.get('hp')} 挡{pl.get('block')} 能{st.get('energy')} | {en} | 手：{hd} → {a} {args}"


# ---- 读档学习----
# sl_on 时：每次选地图节点前存一个档、记下记忆；一场战斗打完如果死了 / 大掉血，就读回这场战斗之前，重选同一个节点，
# 让「老师」重打：推演开着、而且允许看真实随机数（search_reseed=False）、推演更多。老师打完就关掉，接着正常打。
# 每次读档记进 sl_events（哪场、老实打掉多少、老师掉多少），老师那场的逐回合记录标 sl=1，给后面「学老师」用。
# **读档辅助的成绩不是诚实胜率**，只当学习过程的指标（每局要读几次档）。
SL_KEEP = ('trace', 'sl_events', 'decisions')       # 读档时保留的记录；其余记忆回到存档那一刻
_SL_SCOPE = {}                                      # 老师的参数作用域（按 id(mem)）：不能放进 mem——推演会深拷贝 mem，生成器拷不了


def _sl_copy(mem):
    """记忆的深拷贝（读档用）。有的值拷不了（比如推演的参数作用域是生成器）就留原引用"""
    out = {}
    for k, v in mem.items():
        if k in SL_KEEP or k.startswith('_sl'): continue
        try: out[k] = copy.deepcopy(v)
        except Exception: out[k] = v
    return out


def _sl_path():
    return f'/tmp/sts2-sl-{os.getpid()}.json'


def _sl_trigger(fight, st, d):
    """读档条件：死了；或掉血 ≥ sl_dmg_frac × 最大血量；或 ≥ sl_human_mult × 人类赢家同一场的平均掉血（且 ≥ sl_min_dmg）"""
    P = params.P
    if d == 'game_over' and not st.get('victory'): return 'died'
    mx = (st.get('player') or {}).get('max_hp') or 80
    dmg = fight.get('dmg') or 0
    if dmg >= P.get('sl_dmg_frac', 0.3) * mx: return 'big'
    b = BASE.get(match_baseline(fight)) or {}
    if b.get('win_avg') and dmg >= max(P.get('sl_min_dmg', 15), P.get('sl_human_mult', 1.5) * b['win_avg']): return 'vs_human'
    return None


def _sl_end(mem):
    """关掉老师（恢复参数）。drive 正常 / 异常退出时都要调"""
    if mem.get('_sl_active'):
        sc = _SL_SCOPE.pop(id(mem), None)
        if sc is not None: sc.__exit__(None, None, None)
        mem['_sl_active'] = False


def _sl_after_fight(sim, st, d, mem, combats):
    """一场战斗刚打完（还在奖励界面 / 死亡界面）：要不要读档重打。要读就返回重进这场战斗后的新状态，不读返回 None"""
    P = params.P
    snap = mem.get('_sl_snap'); fight = combats[-1]
    died = d == 'game_over' and not st.get('victory')
    if mem.get('_sl_active'):                         # 老师刚打完这场：记结果
        _sl_end(mem)
        ev = mem['sl_events'][-1]
        ev.setdefault('oracle', []).append({'dmg': fight['dmg'], 'died': died})
        if not (_sl_trigger(fight, st, d) and snap and snap['tries'] < P.get('sl_max_tries', 2)): return None
        why = 'oracle_' + (_sl_trigger(fight, st, d) or '')          # 老师也死 / 大掉血：再读一次，推演加倍
    else:
        why = _sl_trigger(fight, st, d)
        if not why or not snap or snap.get('node') is None or snap['act'] != fight['act']: return None
        mem.setdefault('sl_events', []).append({'act': fight['act'], 'floor': fight['floor'], 'room': fight['room'], 'enemies': fight['enemies'],
                                                'why': why, 'honest_dmg': fight['dmg'], 'honest_died': died})
    r = sim.send({'cmd': 'load_save', 'path': _sl_path()})
    if r.get('type') == 'error':
        mem['sl_events'][-1]['error'] = str(r.get('message'))[:100]; return None
    snap['tries'] += 1
    keep = {k: mem[k] for k in SL_KEEP if k in mem}
    mem.clear(); mem.update(_sl_copy(snap['mem'])); mem.update(keep); mem['_sl_snap'] = snap
    del combats[snap['combats']:]
    if mem.get('trace') is not None:
        mem['trace'].append({'act': snap['act'], 'floor': snap['floor'], 'd': 'SL', 'a': 'load', 'why': why, 'try': snap['tries']})
    k = snap['tries']
    sc = params.scoped({'search_on': True, 'search_reseed': False, 'search_rooms': ['Monster', 'Elite', 'Boss'],
                        'search_samples': P.get('sl_search_samples', 3) * k, 'search_refine_samples': P.get('sl_search_refine', 6) * k})
    sc.__enter__(); _SL_SCOPE[id(mem)] = sc; mem['_sl_active'] = True
    st = sim.act('select_map_node', **snap['node'])
    mem['recipe'] = {'kind': 'node', 'path': _sl_path(), 'node': snap['node']}; mem['clog'] = sim.rec = []
    return st


def drive(sim, st, mem, verbose=False, stop_act=None, combat_only=False, max_steps=8000, max_sec=None):
    try:
        return _drive(sim, st, mem, verbose, stop_act, combat_only, max_steps, max_sec)
    finally:
        _sl_end(mem)                                   # 读档学习：不管怎么退出，都把老师的参数恢复


def _drive(sim, st, mem, verbose=False, stop_act=None, combat_only=False, max_steps=8000, max_sec=None):
    """从当前状态一直打下去，直到游戏结束（或打完 stop_act 幕 / 单场战斗结束）。返回结果字典"""
    import policy
    if params.P.get('sl_on') or mem.get('save_dir'):
        raise SimError('普通对局禁止原生存读档；研究只能使用公开输入的独立模型')
    t0 = time.time(); max_sec = max_sec or (90 if combat_only else 120 if stop_act == 1 else 300)
    if params.P.get('search_on'): max_sec *= params.P.get('search_sec_mult', 10)      # 推演很费时间
    if params.P.get('simeval_pick') or params.P.get('simeval_route'): max_sec *= 2           # 模拟实打选牌 / 路线也很费时间
    if not combat_only and not params.P.get('search_on'): max_sec = max(max_sec, 1800)    # 10/3：不推演但开着模拟选牌，机器忙时 600 秒打不完（第八代不推演组 2 局超时）
    if params.P.get('sl_on'): max_sec *= params.P.get('sl_sec_mult', 3)                 # 读档学习：重打的战斗推演更多
    steps = errors = 0; last_state = None; last_enemies = None; last_room = None; floor = 0; act = 1
    combats = []; cur = None
    while steps < max_steps:
        steps += 1
        if time.time() - t0 > max_sec: raise SimError(f'超时：{max_sec} 秒还没打完（{act}-{floor}，{last_enemies}）')
        if st.get('type') == 'error':
            errors += 1
            if verbose: print('  错误：', st.get('message'))
            if errors > 60: raise SimError('错误太多：' + str(st.get('message')))
            if (last_state or {}).get('decision') == 'combat_play' and mem.get('last_try'):
                mem['bad'].add(mem.pop('last_try')); st = last_state          # 记下这张牌打不出，换一张
            elif bought_but_logged_null(last_state, st):
                st = sim.act('skip_select')       # 遗物其实已经买到：取回当前商店状态接着买，不再直接离店（梳理表 C16）
            else:
                st = fallback(sim, last_state)
            continue
        last_state = st
        d = st.get('decision', ''); ctx = st.get('context') or {}
        floor = ctx.get('floor', floor); act = ctx.get('act', act)
        in_combat = d == 'combat_play' or (d == 'card_select' and ctx.get('room_type') in COMBAT_ROOMS)
        if mem.get('recipe') and d == 'map_select':
            # 回到地图才停止记录（10/2：以前看到任何非战斗界面就停，事件里打起来的战斗——比如神秘骑士——就没有记录、推演不了）
            mem.pop('recipe'); mem.pop('clog', None); mem.pop('turn_plan', None); sim.rec = None
        if not in_combat and cur is not None:
            note_public_combat_hp(cur, st, final=True)
            if LOG_TURNS and cur.get('snaps'):            # 补上结果：从那个回合结束到战斗结束又掉了多少血、死没死
                died = d == 'game_over' and not st.get('victory')
                end_hp = 0 if died else cur['hp']
                cur['turns'] = [{'s': s0, 'future': h0 - end_hp, 'died': died} for s0, h0 in cur.pop('snaps')]
            cur.pop('_pr', None); cur.pop('_hand', None); cur.pop('_pre', None)
            if mem.get('search_stats'): cur['search'] = mem.pop('search_stats')      # 这场战斗推演了几个回合、改了几次、花了多久
            combats.append(cur); cur = None
            if combat_only: break
            if params.P.get('sl_on'):                     # 读档学习：死了 / 大掉血就读回这场战斗之前，让老师重打
                st2 = _sl_after_fight(sim, st, d, mem, combats)
                if st2 is not None:
                    st = st2; last_state = None; continue
        result = dict(combats=combats, act=act, floor=floor, room=last_room, enemies=last_enemies, steps=steps, errors=errors)
        if d == 'game_over':
            from terminal import victory_evidence
            evidence = victory_evidence(st, combats)
            pl_ = (st.get('player') or {}) if (st.get('player') or {}).get('relics') else ((last_state or {}).get('player') or {})
            return dict(result, win=evidence['verified'], victory_evidence=evidence,
                        terminal_victory_reported=bool(st.get('victory')),
                        act=st.get('act', act), floor=st.get('floor', floor),
                        deck=[str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '') for c in (st.get('player') or {}).get('deck') or []],
                        relics=[str(r.get('id') or r.get('name') or '').replace('RELIC.', '') for r in pl_.get('relics') or []])   # 10/2：和人类比遗物数量用
        if stop_act and act > stop_act:
            pl_ = st.get('player') or {}
            return dict(result, win=True, cleared=stop_act, hp=pl_.get('hp'), max_hp=pl_.get('max_hp'),
                        deck=[str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '') for c in pl_.get('deck') or []],
                        relics=[str(r.get('id') or r.get('name') or '').replace('RELIC.', '') for r in pl_.get('relics') or []])
        if d == 'combat_play':
            last_enemies = [e.get('name') for e in st.get('enemies') or []]; last_room = ctx.get('room_type')
            hp = (st.get('player') or {}).get('hp', 0)
            if cur is None or cur['floor'] != floor or cur['act'] != act:
                if cur is not None: combats.append(cur)
                cur = {'act': act, 'floor': floor, 'room': last_room, 'enemies': sorted(set(last_enemies)), 'dmg': 0, 'hp': hp, 'rounds': 0}
            cur['dmg'] += max(0, cur['hp'] - hp); cur['hp'] = hp; cur['rounds'] = max(cur['rounds'], st.get('round') or 0)
            if cur['rounds'] > 40: raise SimError(f'卡死：{act}-{floor} 打了 40 回合以上（{cur["enemies"]}）')
        if in_combat and cur is not None:
            note_public_combat_hp(cur, st)
        if LOG_PLAYS and d == 'combat_play' and cur is not None:
            rk = st.get('round')
            if cur.get('_pr') != rk:                      # 新回合：记下回合开始时的手牌
                cur['_pr'] = rk; cur['_hand'] = collections.Counter(str(c.get('id', '')).replace('CARD.', '') for c in st.get('hand') or [])
                ps = cur.setdefault('play_stats', {})
                for k, n in cur['_hand'].items(): ps.setdefault(k, [0, 0]); ps[k][0] += n
        a, args = policy.decide(st, mem, sim)
        if d == 'map_select' and a == 'select_map_node' and mem.get('_sl_snap') is not None and mem['_sl_snap']['floor'] == floor:
            mem['_sl_snap']['node'] = dict(args)
        if mem.get('trace') is not None and d != 'combat_play':
            mem['trace'].append(trace_item(st, a, args, act, floor))
            if d == 'map_select' and mem.get('route_ready'):
                mem['trace'][-1]['ready'] = mem['route_ready']                 # 准备度分数、精英线、战斗线、下一个精英概率、群伤能力
                if mem.get('route_combos'): mem['trace'][-1]['combos'] = mem['route_combos']   # 当时凑齐的联动
        if mem.get('trace_combat') and in_combat:          # 逐回合战斗记录（方便逐局查看）：手牌、能量、敌人血 / 挡 / 意图、打了什么
            mem['trace'].append(combat_item(st, a, args, act, floor))
            if mem.get('_sl_active'): mem['trace'][-1]['sl'] = 1        # 老师打的（读档学习的教材）
        if LOG_PLAYS and a == 'play_card' and cur is not None and cur.get('_hand') is not None:
            pc = next((str(c.get('id', '')).replace('CARD.', '') for c in st.get('hand') or [] if c.get('index') == args.get('card_index')), None)
            if pc and cur['_hand'].get(pc, 0) > 0:
                cur['_hand'][pc] -= 1; cur['play_stats'][pc][1] += 1
            cur['_pre'] = (pc, sum((e.get('hp') or 0) for e in st.get('enemies') or []))      # 出牌前敌人总血量（算这张牌打了多少）
            card = next((c for c in st.get('hand') or [] if c.get('index') == args.get('card_index')), {})
            if card.get('type') == 'Attack':                 # 这次攻击：目标有没有易伤、我有没有力量
                ens = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
                tg = next((e for e in ens if e.get('index') == args.get('target_index')), ens[0] if ens else {})
                ms = cur.setdefault('mod_stats', [0, 0, 0]); ms[0] += 1
                ms[1] += any('vulner' in str(p.get('name', '')).lower() for p in tg.get('powers') or [])
                ms[2] += any(str(p.get('name', '')).lower() == 'strength' and (p.get('amount') or 0) > 0 for p in st.get('player_powers') or [])
        if a == 'use_potion' and cur is not None: cur['potions'] = cur.get('potions', 0) + 1     # 这场战斗用了几瓶药（实验室要算药水成本）
        if LOG_TURNS and a == 'end_turn' and d == 'combat_play' and cur is not None:
            from policy import combatvalue
            cur.setdefault('snaps', []).append((combatvalue.situation_from_state(st, mem.get('last_my_dpt')), (st.get('player') or {}).get('hp', 0)))
        if verbose: print(describe(st, a, args))
        la = mem.setdefault('_last_acts', []); la.append(f"{d}:{a}:{args}"); del la[:-12]     # 卡死时报出最后几个动作
        if a == 'select_map_node': sim.rec = None
        before_move_observation = st
        st = sim.act(a, **args)
        from policy.public_move_beliefs import observe_completed
        observe_completed(before_move_observation, a, args, st, mem)
        from policy.public_stun_history import observe_completed as observe_stun
        observe_stun(before_move_observation, a, args, st, mem)
        if a == 'select_map_node' and mem.get('recipe_pending'):        # 进了要推演的房间：从这里开始记录每个动作
            mem['recipe'] = mem.pop('recipe_pending'); mem['clog'] = sim.rec = []
        if verbose and d == 'combat_play' and mem.get('search_last') and a == 'end_turn': print('   推演：', mem.pop('search_last'))
        if LOG_PLAYS and cur is not None and cur.get('_pre') and a == 'play_card':
            pc, pre = cur.pop('_pre')
            if pc and st.get('decision') == 'combat_play':
                post = sum((e.get('hp') or 0) for e in st.get('enemies') or [])
                ds = cur.setdefault('dmg_stats', {}); ds.setdefault(pc, [0, 0]); ds[pc][0] += 1; ds[pc][1] += max(0, pre - post)
    if combat_only:
        return dict(combats=combats, win=bool(combats) and (last_state or {}).get('decision') != 'game_over', steps=steps)
    raise SimError(f"步数超限：{act}-{floor} 卡在 {(last_state or {}).get('decision')}，最后的动作 {mem.get('_last_acts', [])[-8:]}")


def trace_item(st, a, args, act, floor):
    """非战斗决定的简要记录（逐种子研究用）：选了什么、当时有哪些选项"""
    pl = st.get('player') or {}; d = st.get('decision')
    it = {'act': act, 'floor': floor, 'd': d, 'a': a, 'args': args, 'hp': pl.get('hp'), 'max_hp': pl.get('max_hp'), 'gold': pl.get('gold')}
    nm = lambda xs: [x.get('name') or x.get('title') or x.get('id') for x in xs or []]
    if d == 'card_reward': it['opts'] = nm(st.get('cards'))
    elif d == 'card_select': it['opts'] = nm(st.get('cards'))
    elif d == 'event_choice': it['opts'] = [o.get('title') or o.get('text') for o in st.get('options') or []]; it['event'] = (st.get('context') or {}).get('event') or st.get('event_id') or st.get('title')
    elif d == 'rest_site': it['opts'] = [o.get('title') or o.get('id') or o.get('name') for o in st.get('options') or []]
    elif d == 'shop':
        it['opts'] = {k: [(x.get('name'), x.get('cost')) for x in st.get(k) or [] if x.get('is_stocked', True)] for k in ('cards', 'relics', 'potions') if st.get(k)}
        it['remove_cost'] = st.get('card_removal_cost')
    elif d == 'map_select': it['opts'] = [(c.get('type'), c.get('col'), c.get('row')) for c in st.get('choices') or []]
    return it


def combat_item(st, a, args, act, floor):
    from policy.knowledge import intent_damage
    pl = st.get('player') or {}; hand = st.get('hand') or []
    foes = [(e.get('name'), e.get('hp'), e.get('block', 0), intent_damage(e)) for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    it = {'act': act, 'floor': floor, 'd': 'combat' if st.get('decision') == 'combat_play' else 'combat_select', 'r': st.get('round'),
          'hp': pl.get('hp'), 'blk': pl.get('block', 0), 'en': st.get('energy'), 'hand': [c.get('name') for c in hand], 'foes': foes, 'a': a,
          'np': [i for i, c in enumerate(hand) if c.get('can_play') is False],           # 打不出的牌（下标）：区分「打不出」和「选择不打」
          'cost': [c.get('cost') for c in hand],
          'pots': [p.get('name') for p in pl.get('potions') or [] if p and p.get('name')]}
    if a == 'play_card':
        it['card'] = next((c.get('name') for c in hand if c.get('index') == args.get('card_index')), None)
        if args.get('target_index') is not None:
            it['tgt'] = next((e.get('name') for e in st.get('enemies') or [] if e.get('index') == args.get('target_index')), None)
    elif a == 'use_potion':
        it['potion'] = next((p.get('name') for p in (pl.get('potions') or []) if p and p.get('index') == args.get('potion_index')), args)
    elif a == 'end_turn':      # 10/3（claude-value 建议）：每回合记一次双方能力层数（沙坑、力量、易伤……），分得清「被吞」还是「被咬死」
        pw = lambda ps: {str(p.get('name')): p.get('amount') for p in ps or [] if p.get('name')}
        it['fpow'] = [pw(e.get('powers')) for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
        it['ppow'] = pw(st.get('player_powers') or pl.get('powers'))      # 玩家能力在局面顶层 player_powers（10/3 claude-value：原来读 player.powers，永远是空的）
    else:
        it['args'] = args
        if st.get('cards'): it['opts'] = [c.get('name') for c in st.get('cards')]
    return it


def bought_but_logged_null(last, err):
    """引擎 buy_relic 的已知假报错（Codex 发现，梳理表 C16）：OnTryPurchaseWrapper 已经买完，之后写日志读 entry.Model
    （买完已被清空）抛空引用，整条动作报「Buy relic failed: Object reference …」。原来按出错处理直接离店，
    同一家店计划好的买牌 / 删牌 / 买药全丢。没有待选牌时 skip_select 只是取回当前状态（DoSkipSelect → DetectDecisionPoint）"""
    msg = str((err or {}).get('message') or '')
    return (last or {}).get('decision') == 'shop' and msg.startswith('Buy relic failed') and 'Object reference' in msg


def fallback(sim, last):
    """动作出错时的退路"""
    d = (last or {}).get('decision', '')
    if d == 'combat_play': return sim.act('end_turn')
    if d == 'card_select': return sim.act('skip_select')
    if d == 'card_reward': return sim.act('skip_card_reward')
    if d == 'shop': return sim.act('leave_room')
    r = sim.act('proceed')
    return r if r.get('type') != 'error' else sim.act('leave_room')


def play_one(seed, god=0, stop_act=None, verbose=False, trace=False):
    if god or params.P.get('sl_on'):
        raise SimError('普通开局禁止改血量和真实存读档')
    sim = acquire()
    try:
        st = sim.start(seed, ascension=10) if seed else sim.send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10})
        seed = (st.get('context') or {}).get('seed') or seed
        if god:
            sim.send({'cmd': 'set_player', 'hp': god, 'max_hp': god})
            if st.get('player'): st['player']['hp'] = st['player']['max_hp'] = god
        mem = {'decisions': []} if params.P.get('learn_explore') else {}      # 强化学习训练：记下每个可学的决定
        if trace or params.P.get('trace_on', True):     # 10/3 起每局默认记录：非战斗决定全记，战斗逐回合只留最后一场（死的那场）；trace=True 全留
            mem['trace'] = []; mem['trace_combat'] = True
        if params.P.get('follow_human'):                  # 照着人类赢家在这个种子上的整局决定打（policy/follow.py），只有战斗自己打
            from policy import follow
            hr = follow.by_seed(seed)
            if hr: mem['follow'] = follow.Script(hr)
        act1 = (st.get('context') or {}).get('act_name')
        r = dict(drive(sim, st, mem, verbose=verbose, stop_act=stop_act), seed=seed)
        if act1: r['act1'] = act1                    # 10/4：第一幕是密林还是暗港（随机章节），报告分章节用
        if 'decisions' in mem: r['decisions'] = mem['decisions']
        if mem.get('sl_events'): r['sl'] = mem['sl_events']          # 读档学习：这局读了几次档、哪几场、老实 vs 老师
        if mem.get('rest_sim_log'): r['rest_sim_log'] = mem['rest_sim_log']   # 篝火 Boss 账（rest_boss_sim）
        if mem.get('simeval_log'): r['simeval_log'] = mem['simeval_log']   # 10/4 选牌实打当老师：存下每次实打评估，蒸馏成选牌模型
        if mem.get('trace') is not None:
            t = mem['trace']
            if not trace and not params.P.get('trace_full', True):   # 默认全留；关掉就只留最后一场
                last = next(((x['act'], x['floor']) for x in reversed(t) if x['d'] in ('combat', 'combat_select')), None)
                t = [x for x in t if x['d'] not in ('combat', 'combat_select') or (x['act'], x['floor']) == last]
            r['trace'] = t
        if mem.get('follow'): r['follow_div'] = mem['follow'].div[:40]; r['human_floors'] = [len(a) for a in mem['follow'].acts]
        return r
    finally:
        release(sim, ok=sys.exc_info()[0] is None)      # 出过异常的引擎关掉重开，正常的留给下一局复用


SCENARIOS = json.load(open(f'{HERE}/scenarios.json'))


def play_scenario(seed, name, verbose=False):
    """单场演练：固定牌组 / 遗物 / 血量，直接进某个战斗"""
    sc = SCENARIOS[name]; sim = acquire()
    try:
        sim.start(seed, ascension=10)
        # 注意：不指定遗物时别传 relics——用 set_player 写进去的遗物缺初始化，会让 enter_room 报空引用
        sp = {'cmd': 'set_player', 'hp': sc.get('hp', 80), 'max_hp': sc.get('max_hp', sc.get('hp', 80)), 'deck': sc['deck']}
        for k in ('relics', 'potions'):
            if sc.get(k): sp[k] = sc[k]
        sim.send(sp)
        st = sim.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': sc['encounter']})
        if st.get('decision') != 'combat_play': raise SimError(f'没能进入战斗：{st.get("message") or st.get("decision")}')
        r = drive(sim, st, {}, verbose=verbose, combat_only=True, max_steps=3000)
        c = (r.get('combats') or [{}])[0]
        return {'seed': seed, 'scenario': name, 'win': r.get('win', False), 'dmg': c.get('dmg'), 'rounds': c.get('rounds'),
                'combats': r.get('combats')}
    finally:
        release(sim, ok=sys.exc_info()[0] is None)      # 出过异常的引擎关掉重开，正常的留给下一局复用


_BF = os.environ.get('STS2_BENCH', 'bench.json')       # STS2_BENCH=bench_normals.json 换成普通战基准
BENCH = json.load(open(f'{HERE}/data/{_BF}')) if os.path.exists(f'{HERE}/data/{_BF}') else []


def play_case(i, case, verbose=False, rep=0):
    """战斗基准的一场：用真人当时的配置打同一个敌人（rep 不同 = 换一个随机种子再打一次）"""
    sim = acquire()
    try:
        sim.start(f'B{i}R{rep}', ascension=10)
        sp = {'cmd': 'set_player', 'hp': case['hp'], 'max_hp': case['max_hp'], 'deck': case['deck'], 'relics': case['relics']}
        if case.get('potions'): sp['potions'] = case['potions']
        sim.send(sp)
        enter = {'cmd': 'enter_room', 'type': 'combat', 'encounter': case['encounter']}
        mem = {}
        if params.P.get('trace_bench', True): mem['trace'] = []; mem['trace_combat'] = True    # 10/3：单场也逐回合记录（一关一关研究用）
        if params.P.get('bench_via_save'):              # 存档再读档进战斗：战斗推演要从这里重进同一场战斗（不推演也走这条路，结果才可比）
            from policy import search
            sim.send({'cmd': 'write_continue_save', 'path': search.save_path()})
            sim.send({'cmd': 'load_save', 'path': search.save_path()})
            mem.update({'recipe': {'kind': 'room', 'path': search.save_path(), 'enter': enter}, 'clog': []})
        st = sim.send(enter)
        if mem.get('clog') is not None: sim.rec = mem['clog']
        # 有些遗物开战先让你选牌（card_select / card_reward），交给 drive 正常处理
        if st.get('decision') not in ('combat_play', 'card_select', 'card_reward'):
            raise SimError(f'没能进入战斗：{st.get("message") or st.get("decision")}')
        r = drive(sim, st, mem, verbose=verbose, combat_only=True, max_steps=3000)
        c = (r.get('combats') or [{}])[0]
        if mem.get('search_stats'): c['search'] = mem.pop('search_stats')
        return {'case': i, 'encounter': case['encounter'], 'act': case['act'], 'room': case['room'], 'survived': r.get('win', False),
                'dmg': c.get('dmg'), 'rounds': c.get('rounds'), 'potions': c.get('potions', 0), **({'turns': c['turns']} if c.get('turns') else {}), **({'search': c['search']} if c.get('search') else {}),
                **({'play_stats': c['play_stats']} if c.get('play_stats') else {}), **({'dmg_stats': c['dmg_stats']} if c.get('dmg_stats') else {}), **({'mod_stats': c['mod_stats']} if c.get('mod_stats') else {}),
                'human_dmg': case['human_dmg'], 'human_survived': case['human_survived'], **({'trace': mem['trace']} if mem.get('trace') else {}),
                **({'hp_metrics': c['hp_metrics']} if c.get('hp_metrics') else {}),
                **({'nn': mem.pop('nn_stats')} if mem.get('nn_stats') else {}),
                **({'search_x': {k: mem.get(k) for k in ('public_build_fail', 'search_errors', 'search_mismatch', 'pub_build_sec', 'pub_rollouts', 'pub_verify', 'pub_fail_why') if mem.get(k)}} if mem.get('pub_rollouts') or mem.get('search_errors') or mem.get('search_mismatch') else {})}
    finally:
        release(sim, ok=sys.exc_info()[0] is None)      # 出过异常的引擎关掉重开，正常的留给下一局复用


def bench_report(rs):
    ok = [r for r in rs if 'crash' not in r and r.get('dmg') is not None]
    print(f'\n战斗基准：{len(ok)} 场（崩溃 {len(rs) - len(ok)}）')
    print(f'  脚本平均掉血 {sum(r["dmg"] for r in ok) / len(ok):.1f}，同样配置下的真人 {sum(r["human_dmg"] for r in ok) / len(ok):.1f}；'
          f'倍数 {sum(r["dmg"] for r in ok) / max(sum(r["human_dmg"] for r in ok), 1):.2f}')
    print(f'  撑过去的比例：脚本 {sum(r["survived"] for r in ok) / len(ok):.0%}，真人 {sum(r["human_survived"] for r in ok) / len(ok):.0%}')
    for room in ('elite', 'boss', 'monster'):
        x = [r for r in ok if r['room'] == room]
        if x: print(f'  {room}：脚本 {sum(r["dmg"] for r in x) / len(x):.1f} / 真人 {sum(r["human_dmg"] for r in x) / len(x):.1f}，撑过去 {sum(r["survived"] for r in x) / len(x):.0%} / {sum(r["human_survived"] for r in x) / len(x):.0%}')
    per = collections.defaultdict(list)
    for r in ok: per[r['encounter']].append(r)
    zh = {k: v['zh'] for k, v in BASE.items()}
    print('  比真人多掉血最多的遭遇：')
    for k, x in sorted(per.items(), key=lambda t: -sum(r['dmg'] - r['human_dmg'] for r in t[1]))[:12]:
        print(f'    {zh.get(k, k)}：{len(x)} 场，脚本 {sum(r["dmg"] for r in x) / len(x):.0f} / 真人 {sum(r["human_dmg"] for r in x) / len(x):.0f}，'
              f'撑过去 {sum(r["survived"] for r in x)}/{len(x)}')
    for r in rs:
        if 'crash' in r: print('  崩溃：', r['case'], r['encounter'], r['crash'][:120])


_LAB = {}


def lab_task(j, spec_path):
    """遭遇实验室的一个任务：spec 里第 j 个（哪个基准案例、第几个种子、用哪组参数）"""
    if spec_path not in _LAB:
        sp = json.load(open(spec_path)); benches = {}
        for b in {t['bench'] for t in sp['tasks'] if 'bench' in t}: benches[b] = json.load(open(f'{HERE}/data/{b}'))
        _LAB[spec_path] = (sp, benches)
    sp, benches = _LAB[spec_path]; t = sp['tasks'][j]
    if 'seed' in t:                               # 10/3 组合迭代：整局任务，每个任务带自己那组参数（所有组合共用一次分发，机器负载不叠加）
        with params.scoped(sp['candidates'][t['cand']]):
            r = play_one(t['seed'], stop_act=sp.get('stop_act'))
        r.update(cand=t['cand'], task=j)
        return r
    with params.scoped({**sp['candidates'][t['cand']], 'use_encounter_params': False}):
        r = play_case(t['case'], benches[t['bench']][t['case']], rep=t['rep'])
    r.update(cand=t['cand'], rep=t['rep'], bench=t['bench'], task=j)
    return r


def one_task(job):
    """一个任务 = 一局（或一场演练 / 一个基准战斗）。在子进程里执行"""
    kind, item, opts = job
    params.override(opts.get('set'))
    t = time.time()
    try:
        if kind == 'bench' and os.environ.get('STS2_PROFILE'):       # 性能剖析：每个工作进程各存一份 cProfile 结果
            import cProfile
            pr = cProfile.Profile(); pr.enable()
            try: r = play_case(item[0], BENCH[item[0]], rep=item[1])
            finally: pr.disable(); pr.dump_stats(f"{os.environ['STS2_PROFILE']}.{os.getpid()}")
        elif kind == 'bench': r = play_case(item[0], BENCH[item[0]], rep=item[1])
        elif kind == 'lab': r = lab_task(item, opts['lab'])
        elif opts.get('scenario'): r = play_scenario(item, opts['scenario'])
        else: r = play_one(item, god=opts.get('god', 0), stop_act=opts.get('stop_act'))
    except Exception as e:
        r = {'seed': item, 'case': item, 'win': False, 'crash': str(e)[:500]}
        if kind == 'bench': r['encounter'] = BENCH[item[0]]['encounter']
        if kind == 'lab': r['task'] = item
    r['sec'] = round(time.time() - t, 1)
    return r


def run_parallel(kind, items, opts, workers, idle_limit=None):
    """开 workers 个进程，任务一个一个领；某个任务卡住不影响别的。超过 idle_limit 秒没有任何任务完成就停下。
    10/2：看门狗要比单局时间上限长——开推演 / 模拟实打后一局要十几分钟，固定 900 秒会把正常跑着的整批杀掉（v16c 就是这么全军覆没的）"""
    if idle_limit is None:
        P = params.P
        idle_limit = 900
        if P.get('search_on'): idle_limit = 300 * P.get('search_sec_mult', 10) + 600
        if P.get('simeval_pick') or P.get('simeval_route'): idle_limit *= 2
    out = []; jobs = [(kind, it, opts) for it in items]
    with Pool(workers, maxtasksperchild=200) as p:    # 每个进程复用引擎，多做些任务再换进程
        it = p.imap_unordered(one_task, jobs, chunksize=1)
        for _ in jobs:
            try:
                out.append(it.next(timeout=idle_limit))
            except Exception as e:
                print(f'  看门狗：{idle_limit} 秒没有任务完成，停止（已完成 {len(out)}/{len(jobs)}）：{e!r}')
                p.terminate(); break
    return out


BASE = json.load(open(f'{HERE}/data/baselines.json'))
def match_baseline(c):
    """按怪物名字和房间类型，找人类数据里对应的遭遇"""
    names = set(c['enemies']); room = {'Monster': ('_WEAK', '_NORMAL'), 'Elite': ('_ELITE',), 'Boss': ('_BOSS',)}.get(c['room'], ())
    best, bk = 0, None
    for k, v in BASE.items():
        if not k.endswith(room): continue
        bn = set(v['names'].split(' + '))
        j = len(names & bn) / max(len(names | bn), 1)
        if j > best: best, bk = j, k
    return bk if best >= 0.3 else None


def summarize(rs, opts=None):
    opts = opts or {}
    n = len(rs); w = sum(bool(r.get('win')) for r in rs); crash = sum('crash' in r for r in rs)
    if not n:
        print('\n局数 0（这一批一局都没完成）'); return
    label = f"打完第 {opts['stop_act']} 幕的比例" if opts.get('stop_act') else '胜'
    print(f'\n局数 {n}，{label} {w}（{w / n:.0%}），崩溃 {crash}，平均每局 {sum(r.get("sec", 0) for r in rs) / n:.1f} 秒')
    unverified = sum(bool(r.get('terminal_victory_reported')) and not (r.get('victory_evidence') or {}).get('verified') for r in rs)
    if unverified: print(f'  引擎报告胜利但未通过完整终局核验：{unverified} 局（不计完整胜利）')
    if opts.get('scenario'):
        ds = [r['dmg'] for r in rs if r.get('dmg') is not None]
        rd = [r['rounds'] for r in rs if r.get('rounds') is not None]
        if ds: print(f'演练「{opts["scenario"]}」：平均掉血 {sum(ds) / len(ds):.1f}，平均回合 {sum(rd) / len(rd):.1f}，最多掉 {max(ds)}')
    if opts.get('stop_act'):
        hs = [r['hp'] / r['max_hp'] for r in rs if r.get('cleared')]
        if hs: print(f'通过的局，剩余血量平均 {sum(hs) / len(hs):.0%}')
    dead = [r for r in rs if not r.get('win') and 'crash' not in r]
    print('死在第几幕：', dict(sorted(collections.Counter(r.get('act') for r in dead).items(), key=lambda x: str(x[0]))))
    print('死在哪类房间：', dict(collections.Counter((r.get('act'), r.get('room')) for r in dead).most_common(8)))
    print('死在谁手里：', collections.Counter(' + '.join(sorted(set(r.get('enemies') or []))) for r in dead).most_common(8))
    tf = [((r.get('act') or 1) - 1) * 17 + (r.get('floor') or 0) for r in rs if 'crash' not in r and not opts.get('scenario')]
    if tf: print('平均走到第几层（全局，每幕按 17 层算）：', round(sum(tf) / len(tf), 1))
    combat_report(rs)
    for r in rs:
        if 'crash' in r: print('  崩溃：', r['seed'], r['crash'][:150])


def combat_report(rs):
    cs = [c for r in rs for c in r.get('combats') or []]
    if not cs: return
    agg = collections.defaultdict(lambda: [[], []]); per = collections.defaultdict(lambda: [[], []])
    for c in cs:
        k = match_baseline(c)
        if not k: continue
        agg[(c['act'], c['room'])][0].append(c['dmg']); agg[(c['act'], c['room'])][1].append(BASE[k]['win_avg'])
        per[k][0].append(c['dmg']); per[k][1].append(BASE[k]['win_avg'])
    print('\n每场战斗掉血：脚本 vs 人类赢家（同一个遭遇）')
    for (a, room), (x, y) in sorted(agg.items(), key=lambda t: (t[0][0] or 0, str(t[0][1]))):
        print(f'  第{a}幕 {room}：{len(x)} 场，脚本平均 {sum(x) / len(x):.1f}，人类赢家 {sum(y) / len(y):.1f}，倍数 {sum(x) / max(sum(y), 1):.2f}')
    worst = sorted(per.items(), key=lambda t: -(sum(t[1][0]) - sum(t[1][1])))[:10]
    print('  多掉血最多的遭遇：')
    for k, (x, y) in worst:
        print(f'    {BASE[k]["zh"]}：{len(x)} 场，脚本 {sum(x) / len(x):.0f} / 赢家 {y[0]:.0f}，共多掉 {sum(x) - sum(y):.0f}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('n', type=int); ap.add_argument('--tag', default='dev'); ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--verbose', action='store_true'); ap.add_argument('--start', type=int, default=0)
    ap.add_argument('--god', type=int, default=0, help='开局把血量调到这个数（练习模式，不会死）')
    ap.add_argument('--stop-act', type=int, default=None, help='打完第几幕就停（分段评估）')
    ap.add_argument('--scenario', default=None, help='单场演练，名字见 scenarios.json')
    ap.add_argument('--set', action='append', default=[], help='覆盖参数，例如 --set alpha_max=1.2')
    ap.add_argument('--bench', action='store_true', help='战斗基准：用真人当时的配置打同一场战斗（n=0 表示全部）')
    ap.add_argument('--part', default=None, help='分布式：只跑任务列表里的一部分，例如 "0/3" 或 "1,2/3"（按下标取模）')
    ap.add_argument('--only', default=None, help='战斗基准只测这些遭遇，逗号分隔，例如 BYGONE_EFFIGY_ELITE,BYRDONIS_ELITE')
    ap.add_argument('--no-hard-seeds', action='store_true', help='不把输掉的种子写进 seedlab（分布式时由汇总方写）')
    ap.add_argument('--reps', type=int, default=1, help='战斗基准：每个案例换几个随机种子各打一次（多打更准）')
    ap.add_argument('--seeds', default='dev', help='dev = data/dev_seeds.txt 里的固定种子；game = 每局让游戏现场生成')
    ap.add_argument('--seed-list', default=None, help='种子清单文件（一行一个，可重复；n=0 表示全部）——强化学习训练用')
    ap.add_argument('--lab', default=None, help='遭遇实验室：任务清单文件（lab.py 生成）')
    a = ap.parse_args()
    params.override(a.set)
    opts = {'god': a.god, 'stop_act': a.stop_act, 'scenario': a.scenario, 'set': a.set, 'lab': a.lab}
    if a.seeds == 'game':
        seeds = [None] * a.n
    else:
        dev = open(a.seed_list or f'{HERE}/data/dev_seeds.txt').read().split()
        seeds = dev[a.start:a.start + a.n] if a.n else dev
    if a.verbose:
        r = play_scenario(seeds[0], a.scenario, verbose=True) if a.scenario else play_one(seeds[0], god=a.god, stop_act=a.stop_act, verbose=True)
        r.pop('combats', None); print(r); sys.exit()
    def take(items):
        if not a.part: return items
        idx, k = a.part.split('/'); keep = {int(x) for x in idx.split(',')}; k = int(k)
        return [x for j, x in enumerate(items) if j % k in keep]
    t = time.time()
    if a.lab:
        n = len(json.load(open(a.lab))['tasks'])
        rs = run_parallel('lab', take(list(range(n))), opts, a.workers)
        os.makedirs(f'{HERE}/results', exist_ok=True)
        with open(f'{HERE}/results/{a.tag}.jsonl', 'w') as f:
            for r in rs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'实验室任务 {len(rs)} 个，用时 {time.time() - t:.0f} 秒'); sys.exit()
    if a.bench:
        only = set(a.only.split(',')) if a.only else None
        idx = [i for i in range(len(BENCH)) if not only or BENCH[i]['encounter'] in only][:a.n or None]
        rs = run_parallel('bench', take([(i, k) for i in idx for k in range(a.reps)]), opts, a.workers)
        os.makedirs(f'{HERE}/results', exist_ok=True)
        with open(f'{HERE}/results/{a.tag}.jsonl', 'w') as f:
            for r in rs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        bench_report(rs); print(f'总用时 {time.time() - t:.0f} 秒'); sys.exit()
    rs = run_parallel('run', take(seeds), opts, a.workers)
    os.makedirs(f'{HERE}/results', exist_ok=True)
    with open(f'{HERE}/results/{a.tag}.jsonl', 'w') as f:
        for r in rs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    if not a.god and not a.stop_act and not a.scenario and not a.no_hard_seeds:  # 完整对局输掉的种子收进种子研究
        with open(f'{HERE}/seedlab/hard_seeds.jsonl', 'a') as f:
            for r in rs:
                if not r.get('win') and r.get('seed') and 'crash' not in r:
                    f.write(json.dumps({'seed': r['seed'], 'tag': a.tag, 'act': r.get('act'), 'floor': r.get('floor'),
                                        'room': r.get('room'), 'enemies': r.get('enemies'), 'deck': r.get('deck')}, ensure_ascii=False) + '\n')
    summarize(rs, opts); print(f'总用时 {time.time() - t:.0f} 秒')
