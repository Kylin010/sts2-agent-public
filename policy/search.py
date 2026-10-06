"""战斗推演：用真实游戏引擎把候选出牌方案实际打一遍，看真实结果再选。

所有卡牌 / 遗物 / 能力 / 怪物之间的联动都由引擎精确计算，不再靠手写规则近似。
每回合开始时：
  1. 规划器给出前 K 名候选方案（policy/combat.plan(topk=K)，外加「什么都不打」）
  2. 每个方案 × S 次：引擎读「进这场战斗前」的存档 → 重新进同一场战斗 → 重放到目前为止的所有动作（引擎是确定性的，
     会回到一模一样的局面）→ **把抽牌堆随机打乱**（不偷看真实的抽牌顺序）→ 按方案出牌（中途抽到的新牌交给规划器）
     → 结束回合 → 敌人回合 → 下一回合由规划器照常打 → 在下一次结束回合的时刻估值
  3. 打分 = −（这期间实际掉的血）−（战斗估值模型：从那一刻到战斗结束还要掉多少血）；赢了不再扣，死了重罚
  4. 推演完，同样「读档 + 重放」把引擎恢复到真实局面（不打乱），按最好的方案打
在下一次结束回合时估值，是因为战斗估值模型（data/combat_value.json）就是用「结束回合那一刻的局面」训练的，
而且这样下一手抽到什么、这回合打的能力牌 / 抽牌下回合值多少，都由引擎实打实算进去了。
用的是同一个引擎（不另开进程，省内存）；恢复后会核对局面，对不上就报错（宁可这局算崩溃，也不在错的局面上继续打）。
已知的信息泄露：随机出招的怪、随机生成的牌，推演里用的是真实的随机数（打乱的只有抽牌堆）。
"""
import json, copy, os, random, time
from params import P
from sim import SimError
from policy import combat, combatvalue as CV

DEBUG = os.environ.get('STS2_SEARCH_DEBUG') == '1'
_IN = {'on': False}
_LAST_ERR = ['']                     # 推演里面调规划器时不再嵌套推演


class _Mismatch(SimError):
    """影子引擎重放对不上真实局面"""
SELECTS = ('card_select', 'card_reward', 'bundle_select')


def save_path():
    return f'/tmp/sts2-search-{os.getpid()}.json'


def enabled(st, mem):
    if _IN['on'] or not P.get('search_on'): return False
    if not P.get('search_public', False): return False  # real-save replay is not a player action
    room = (st.get('context') or {}).get('room_type', '')
    if room in P.get('search_rooms', ['Elite', 'Boss']): return True
    pl = st.get('player') or {}                                   # 普通战：血量低于一半才推演（低血时普通战也会死）
    return room == 'Monster' and pl.get('hp', 0) < P.get('search_monster_hp', 0) * max(pl.get('max_hp', 1), 1)


def _reset(s, recipe, log):
    """引擎回到「这一刻」：读进战斗前的存档、重新进同一场战斗、重放 log"""
    st = s.send({'cmd': 'load_save', 'path': recipe['path']})
    if st.get('type') == 'error':
        _LAST_ERR[0] = f'读档出错：{st.get("message")}'; return None
    st = s.send(recipe['enter']) if recipe['kind'] == 'room' else s.act('select_map_node', **recipe['node'])
    for i, (a, args) in enumerate(log):
        st = s.act(a, **args)
        if st.get('type') == 'error':
            _LAST_ERR[0] = f'重放第 {i + 1}/{len(log)} 步 {a} {args} 出错：{st.get("message")}'
            return None
    return st


def _key(st):
    return (st.get('decision'), st.get('round'), (st.get('player') or {}).get('hp'), (st.get('player') or {}).get('block'), st.get('energy'),
            sorted((c.get('name', ''), bool(c.get('upgraded'))) for c in st.get('hand') or []),
            sorted((e.get('name'), e.get('hp'), e.get('block')) for e in st.get('enemies') or []))


def restore(s, mem, st):
    """把引擎恢复到真实局面 st；对不上就报错。引擎超时坏掉了就换新进程再恢复（真实局面完全可以由存档 + 动作记录重建）"""
    if s.broken: s.restart()
    try:
        st2 = _reset(s, mem['recipe'], mem['clog'])
    except SimError:
        s.restart(); st2 = _reset(s, mem['recipe'], mem['clog'])
    if st2 is None or _key(st2) != _key(st):
        raise SimError(f'推演后恢复局面失败（{(st2 or {}).get("decision")} 回合 {(st2 or {}).get("round")}；{_LAST_ERR[0]}）')
    return st2


def _find(hand, card):
    want = (card.get('id'), bool(card.get('upgraded')))
    return next((c for c in hand if (c.get('id'), bool(c.get('upgraded'))) == want and c.get('can_play')), None)


def tgt_ref_of(st, index):
    """目标记成「第几个叫这个名字的活着的敌人」，换了局面（有怪死了 / 召唤了）也能对上"""
    ens = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    e = next((x for x in ens if x.get('index') == index), None)
    if e is None: return (None, 0)
    return (e.get('name'), [x for x in ens if x.get('name') == e.get('name')].index(e))


def _target(st, tref):
    ens = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    if not ens: return None
    name, k = tref
    same = [e for e in ens if e.get('name') == name]
    if len(same) > k: return same[k]['index']
    if same: return same[0]['index']
    return min(ens, key=lambda e: e.get('hp') or 0)['index']


def _ck(c):
    return (c.get('id'), bool(c.get('upgraded')))


def make_plan(key, hand, seq):
    """这回合的方案：按顺序要打的牌 + 「留着不打」的牌（回合开始的手牌里、方案没选的那些）。
    方案打完后规划器只能打新抽到 / 新生成的牌——否则规划器会把留着的牌也打掉，所有候选方案最后都变成同一套打法"""
    import collections
    res = collections.Counter(_ck(c) for c in hand)
    for c, _ in seq: res[_ck(c)] -= 1
    # expect：按方案打下去、没有新牌进手时手里应该剩的牌（10/3 claude-value：search_replan_on_draw 用它发现「抽到 / 生成了新牌」）
    return {'key': key, 'seq': list(seq), 'reserved': +res, 'expect': collections.Counter(_ck(c) for c in hand)}


def reserve(st, mem):
    """方案打完、交回规划器时：把留着不打的牌标成打不出（按牌名计数，同名的新牌照样能打）"""
    tp = mem.get('turn_plan')
    if not tp or tp['key'] != mem.get('turn_key') or not tp['reserved']: return st
    from params import P as _P
    if not _P.get('search_reserve', True): return st   # 10/3：手牌回合末会弃掉，留着不打多半是浪费（实测：剩 1 能量、手里有防御、敌人要打 17，直接结束回合）
    left = dict(tp['reserved']); hand = []
    for c in st.get('hand') or []:
        k = _ck(c)
        if left.get(k, 0) > 0 and c.get('can_play'):
            left[k] -= 1; c = dict(c, can_play=False)
        hand.append(c)
    return dict(st, hand=hand)


def next_action(st, mem):
    """按这回合定好的方案出下一张牌；方案打完 / 对不上返回 None（交回规划器）"""
    tp = mem.get('turn_plan')
    if not tp or tp['key'] != mem.get('turn_key'): return None
    from params import P as _P
    if _P.get('search_replan_on_draw') and tp['seq'] and 'expect' in tp:
        # 10/3 claude-value（同牌组局面对照）：人类先打抽牌，看到新牌再决定能量花在哪；我们回合开始定好整串方案、抽到新牌也照打。
        # 手里出现方案外的新牌（抽到 / 生成）→ 放弃剩下的方案：1 = 交给规划器在完整手牌上重新规划；2 = 在当前局面重新推演（每回合最多 search_replan_max 次）
        import collections
        now = collections.Counter(_ck(c) for c in st.get('hand') or [])
        # 3 = 每打出一张就重新推演
        every = _P['search_replan_on_draw'] >= 3 and tp.get('played', 0) >= 1
        if every or any(n > tp['expect'].get(k, 0) for k, n in now.items()):
            tp['seq'] = []; tp['reserved'] = {}
            if _P['search_replan_on_draw'] >= 2 and mem.get('replans', (None, 0))[0] == tp['key'] and mem['replans'][1] >= _P.get('search_replan_max', 2):
                return None
            if _P['search_replan_on_draw'] >= 2:
                n = mem['replans'][1] + 1 if mem.get('replans', (None, 0))[0] == tp['key'] else 1
                mem['replans'] = (tp['key'], n); mem['searched_key'] = None      # decide() 下一步会在当前局面再推演一次
            return None
    while tp['seq']:
        card, tref = tp['seq'].pop(0)
        if card.get('_potion'):                     # 10/4 药水进推演（search_potions）：方案第一步是喝某瓶药
            pot = next((p for p in (st.get('player') or {}).get('potions') or [] if p and p.get('name') == card['name']), None)
            if pot is None: continue
            args = {'potion_index': pot['index']}
            if pot.get('target_type') == 'AnyEnemy':
                t = _target(st, tref)
                if t is None: continue
                args['target_index'] = t
            tp['played'] = tp.get('played', 0) + 1
            return ('use_potion', args)
        c = _find(st.get('hand') or [], card)
        if 'expect' in tp and c is not None: tp['expect'][_ck(c)] -= 1
        if c is None: continue
        args = {'card_index': c['index']}
        if c.get('target_type') == 'AnyEnemy':
            t = _target(st, tref)
            if t is None: return None
            args['target_index'] = t
        tp['played'] = tp.get('played', 0) + 1
        return ('play_card', args)
    return None


def _step(s, st, m2, decide):
    """推演里走一步（和 run.drive 一样：出牌报错就把这张牌记进 bad、换一张）"""
    a, ar = decide(st, m2, s)
    r = s.act(a, **ar)
    if r.get('type') != 'error': return r, a
    if st.get('decision') == 'combat_play' and m2.get('last_try'):
        m2.setdefault('bad', set()).add(m2.pop('last_try')); return st, None
    raise SimError(f'推演里动作出错：{a} {r.get("message")}')


def _play_turn(s, st, seq, m2, decide):
    """在引擎上按方案出牌，打完再交给规划器打完这回合，结束回合。返回结束回合后的状态"""
    rnd = st.get('round')
    m2['turn_plan'] = make_plan(m2.get('turn_key'), st.get('hand') or [], seq)
    for _ in range(60):
        d = st.get('decision')
        if d == 'combat_play' and st.get('round') != rnd: return st
        if d != 'combat_play' and d not in SELECTS: return st
        if d == 'card_reward': return st          # 10/5：这回合打赢了就停在选卡奖励（_value 按打赢算）。以前交给规划器选掉 → 没有别的奖励时引擎自动「前进」，
                                                  # Boss 战会进下一幕（还回血）；快速搭场景复用这个影子局，两次以后到第三幕，之后推演里打死 Boss 全部报
                                                  # 「Cannot verify final boss completion」→ 打死 Boss 的打法被当成失败扔掉（Boss 战打得慢的一个原因）
        st, _a = _step(s, st, m2, decide)
    return None


def _ehp(st):
    """主要敌人（不算随从）的剩余血量 + 格挡"""
    return sum((e.get('hp') or 0) + (e.get('block') or 0) for e in st.get('enemies') or []
               if (e.get('hp') or 0) > 0 and not any('minion' in str(p.get('name', '')).lower() for p in e.get('powers') or []))


_RLRNG = random.Random()          # 推演模拟记录抽样用（单独的随机数，不影响推演本身）
_RL_END = [None]


def _compact(st):
    """大网络训练用的紧凑局面：逐张牌、每只怪的血 / 格挡 / 意图 / 能力、遗物计数、药水，不带描述文字（原记录一条 13 KB）"""
    from policy import potions as PO
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    return {'c': [ctx.get('act'), ctx.get('floor'), ctx.get('room_type'), str(ctx.get('encounter') or '').replace('ENCOUNTER.', '')],
            'r': st.get('round'), 'e': st.get('energy'), 'p': [pl.get('hp'), pl.get('max_hp'), pl.get('block')],
            'pp': [[q.get('id'), q.get('amount')] for q in st.get('player_powers') or []],
            'h': [_cardstr(c) for c in st.get('hand') or []], 'd': list(st.get('draw_pile') or []),
            'x': list(st.get('discard_pile') or []), 'z': list(st.get('exhaust_pile') or []),
            'rl': [[str(r.get('id') or '').replace('RELIC.', ''), r.get('counter')] for r in pl.get('relics') or []],
            'po': [PO.pid(q) for q in pl.get('potions') or [] if q and q.get('name')],
            'en': [[e.get('monster_id'), e.get('hp'), e.get('max_hp'), e.get('block'),
                    [[str(i.get('type', '')).lower(), i.get('damage'), i.get('hits', 1)] for i in e.get('intents') or []],
                    [[q.get('id'), q.get('amount')] for q in e.get('powers') or []]] for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]}


def _value(hp0, st, m2, decide, s):
    """推演一次模拟往后打（_value_core）。search_rollout_log 开着时按 search_rollout_log_p 抽样，把这次模拟每个回合开始的局面
    和这次模拟最后的结局（之后还掉多少血 / 死没死 / 打赢没）存下来——推演本来就要打，这些数据不另花算力"""
    snaps = [] if P.get('search_rollout_log') and _RLRNG.random() < P.get('search_rollout_log_p', 0.05) else None
    _RL_END[0] = None
    v = _value_core(hp0, st, m2, decide, s, snaps)
    if snaps and _RL_END[0]:
        try:
            kind, hp_end = _RL_END[0]
            with open(f"{P['search_rollout_log']}.{os.getpid()}", 'a') as f:
                f.write(json.dumps({'snaps': snaps, 'end': kind, 'hp_end': hp_end}, ensure_ascii=False, separators=(',', ':')) + '\n')
        except Exception:
            pass
    return v


def _value_core(hp0, st, m2, decide, s, snaps=None):
    """结束这回合后，规划器接着打 search_depth 个回合，在那次结束回合时估值（打到战斗结束就用真实结果）。
    选牌界面（战斗里的选牌，或者打赢后的选卡奖励）都交给规划器选掉再往下走；走出战斗 = 赢了"""
    rnd = st.get('round'); hp = hp0; ends = 0; left = 1.0; snap_rnd = None
    for _ in range(60 * P['search_depth']):
        d = st.get('decision')
        if d == 'card_reward':                                     # 10/3 Codex 审查：打赢后引擎先自动领遗物再弹选牌奖励——
            _RL_END[0] = ('win', hp)
            return -(hp0 - hp) + P['search_win_bonus']            # 遗物来自真实存档里还没公开的遗物袋（梨会加血），不能算进来：在这之前截断
        if d == 'combat_play' and (st.get('player') or {}).get('hp') is not None: hp = st['player']['hp']   # 只用出牌界面的血量（战后流程里的回血 / 加上限都不算）
        if d == 'combat_play': left = _ehp(st) / max(m2['_ehp0'], 1)
        if snaps is not None and d == 'combat_play' and st.get('round') != snap_rnd:   # 每个回合开始记一次局面
            snap_rnd = st.get('round'); snaps.append(_compact(st))
        if d == 'game_over':
            _PUB_DIRTY[0] = True                                   # 影子局结束了：下次快速搭场景不能复用它
            _RL_END[0] = ('win', hp) if st.get('victory') else ('death', 0)
            if st.get('victory'): return -(hp0 - hp) + P['search_win_bonus']
            # 死了：敌人剩的血越少罚得越轻——所有方案都会死时，选「离打死它最近」的，赢面最大
            return -(hp0 + P['search_death'] * (P['search_death_floor'] + (1 - P['search_death_floor']) * min(1.0, left)))
        if d in SELECTS:
            st, _a = _step(s, st, m2, decide); continue
        if d != 'combat_play' or not [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]:
            _RL_END[0] = ('win', hp)
            return -(hp0 - hp) + P['search_win_bonus']            # 打赢了
        if st.get('round') != rnd:                                # 规划器这回合打完、敌人也打完了（一般不会走到这）
            rnd = st.get('round')
        a, ar = decide(st, m2, s)
        if a == 'end_turn': ends += 1
        if a == 'end_turn' and P.get('cvnet_cutoff') and ends >= P.get('cvnet_depth', 2):
            # 大版战斗价值网络收尾（AlphaGo 式）：打完 cvnet_depth 个回合、敌方回合结束、新回合开始时，
            # 价值 = 到这里掉的血 + 网络估计「从这个回合开始到战斗结束还掉多少」。网络就是用这种回合开始的局面训的
            from policy import cvnet
            if cvnet.available():
                r = s.act(a, **ar)
                if r.get('type') == 'error': return None
                pl_r = r.get('player') or {}
                if r.get('decision') == 'combat_play' and pl_r.get('hp') is not None and [e for e in r.get('enemies') or [] if (e.get('hp') or 0) > 0]:
                    fut = cvnet.predict(r)
                    _RL_END[0] = None                                # 截断的模拟没有真实结局，不进训练记录
                    return -(hp0 - pl_r['hp']) - P.get('cvnet_weight', 1.0) * fut
                st = r; continue                                      # 敌方回合里打完 / 死了：照常按真实结局收尾
        if a == 'end_turn' and ends >= P['search_depth']:
            sit = CV.situation_from_state(st, m2.get('last_my_dpt'))
            fut = CV.unblocked_now(sit) + (CV.predict(sit) if CV.available() else 0)
            if DEBUG: print(f"      R{st.get('round')} 血{hp} 挡{sit['block']} 敌{[(e['ehp'], e['intent']) for e in sit['enemies']]} 立即{CV.unblocked_now(sit)} 之后{CV.predict(sit):.1f}")
            return -(hp0 - hp) - P['search_future_weight'] * fut
        r = s.act(a, **ar)
        if r.get('type') == 'error':
            if m2.get('last_try'): m2.setdefault('bad', set()).add(m2.pop('last_try')); continue
            return None
        st = r
    return None


def _pw(ps):
    return tuple(sorted((str(p.get('id')), p.get('amount')) for p in ps or []))


def _vis(st):
    """局面里玩家看得见的部分（用来核对新引擎摆出来的战斗和真局一致）。
    B-113（Codex）：原来不比能力、手牌只比 id + 升级 → 免费 / 降费、附魔、能力层数摆错了也查不出；现在手牌按规格串（附魔 + 当前费用）、双方能力、手牌显示费用都比"""
    pl = st.get('player') or {}
    return (st.get('round'), st.get('energy'), pl.get('hp'), pl.get('block'),
            tuple(sorted(_cardstr(c) for c in st.get('hand') or [])), tuple(sorted((_cardstr(c), None if _xcost(c) else c.get('cost')) for c in st.get('hand') or [])),
            tuple(st.get('draw_pile') or []), tuple(sorted(st.get('discard_pile') or [])), tuple(sorted(st.get('exhaust_pile') or [])),
            _pw(st.get('player_powers')),
            tuple(sorted((str(x.get('id')), x.get('counter')) for x in pl.get('relics') or [] if x.get('counter') is not None
                         and str(x.get('id') or '').replace('RELIC.', '') not in RELIC_NOCOMBAT)),   # 补丁 24：遗物计数也要对上
            tuple((e.get('monster_id'), e.get('hp'), e.get('block'), tuple((str(i.get('type', '')).lower(), i.get('damage'), i.get('hits', 1)) for i in e.get('intents') or []), _pw(e.get('powers'))) for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0))   # 只比活着的（已死的敌人新引擎里移除，claude-value p23cv）)


# 计数只在战斗外起作用的遗物：核对时不比（10/5 整步摆不出来里占一大半）。银坩埚 = 还剩几次选卡奖励升级（TryModifyCardRewardOptionsLate），
# 用完计数消失；佩尔之牙 = 存着几张被拿走的牌（AfterCombatEnd 才还一张）。推演停在选卡奖励之前，这两个计数不影响战斗
RELIC_NOCOMBAT = {'SILVER_CRUCIBLE', 'PAELS_TOOTH'}

# X 费牌（源码 HasEnergyCostX）：手牌里显示的「费用」不是真费用（打出时用掉全部能量），真局和新引擎显示不同 → 核对时不比它（能量另外比）
XCOST = {'CASCADE', 'DIRGE', 'HEAVENLY_DRILL', 'MULTI_CAST', 'MALAISE', 'SKEWER', 'TEMPEST', 'ERADICATE', 'WHIRLWIND', 'VOLLEY'}


def _xcost(c):
    return str(c.get('id') or '').replace('CARD.', '').rstrip('+') in XCOST


def _cardstr(c):
    if c.get('spec'): return str(c['spec'])                     # 补丁 23：ID[+][#附魔=层数][@当前费用]
    return str(c.get('id') or '').replace('CARD.', '') + ('+' if c.get('upgraded') else '')


def build_public(s, st, seed, force_fresh=False, public_history=None, _moves=None):
    """新引擎（推演只能用看得见的——牌、怪物、怪物默认出招、抽牌堆 / 弃牌堆 / 消耗牌堆、抽牌概率、怪物伤害；
    看不到下一张牌真正是什么）：在影子引擎里开一局和本局无关的新种子，只按看得见的局面摆出这场战斗（补丁 22 的 set_combat），
    抽牌堆按 seed 随机排；之后怪物按它的出招表走（固定循环照走，随机分支按游戏自己的概率，用的是新种子的随机数）。
    摆出来和真局看得见的部分对不上就返回 None（这回合不推演）"""
    from policy import potions as PO
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    if not ctx.get('encounter') or st.get('draw_pile') is None: return None
    from policy.public_move_beliefs import unique_move
    from policy.public_stun_history import followup
    public_next = followup(st, public_history)
    is_stun = lambda e: any(str(it.get('type', '')).lower() == 'stun' for it in e.get('intents') or [])
    if any(is_stun(e) for e in st.get('enemies') or [] if e.get('hp', 0) > 0) and public_next is None:
        _LAST_ERR[0] = 'Stun follow-up is not proved by completed public history'
        return None
    public_moves = _moves or {e.get('index'): 'STUNNED' if is_stun(e) else unique_move(st, e, public_history) for e in st.get('enemies') or [] if e.get('hp', 0) > 0}
    if _moves is None and any(move is None for move in public_moves.values()):
        # 10/5 主线：当前招看意图分不出来（同样的意图形状对应几招）时，人类也只能「几种都想一遍」——
        # 按这次模拟的种子打乱候选顺序逐个试摆；摆出来的意图（类型 / 显示伤害 / 段数）和真局对不上的候选会被核对挡掉，
        # 对得上的里面取第一个。不同种子轮到不同候选 = 按可能性平均，不读真实招式
        from policy.public_move_beliefs import candidates, _prior
        import itertools
        opts = []
        for e in st.get('enemies') or []:
            if e.get('hp', 0) <= 0: continue
            i = e.get('index')
            if public_moves.get(i) is not None: opts.append([(i, public_moves[i])]); continue
            c = candidates(e)
            pr = _prior(st, e, public_history)
            if c and pr: c = tuple(sorted(set(c) & set(pr))) or c
            if not c:
                _LAST_ERR[0] = 'Current move is ambiguous from public intents/history'
                return None
            c = list(c); random.Random(f'{seed}-{i}').shuffle(c); opts.append([(i, m) for m in c])
        # 10/5 claude-value 报帝皇蟹 23% 摆不出：原来按组合依次试、最多 4 组，两只怪都有歧义时前几组都卡在第一只的错误候选上。
        # 改成按「哪只怪的意图对不上」只把那只换成下一个候选（每只独立），最多试到每只候选都用完
        choice = [0] * len(opts)
        for _ in range(sum(len(o) for o in opts) + 1):
            moves = {o[k][0]: o[k][1] for o, k in zip(opts, choice)}
            _ENEMY_BAD[0] = None
            r0 = build_public(s, st, seed, force_fresh=force_fresh, public_history=public_history, _moves=moves)
            if r0 is not None: return r0
            bad_idx = _ENEMY_BAD[0]
            if not bad_idx: break                                   # 不是敌人意图对不上（别的原因摆不出）：换候选也没用
            moved = False
            for j, o in enumerate(opts):
                if o[0][0] in bad_idx and choice[j] + 1 < len(o): choice[j] += 1; moved = True
            if not moved: break
        last = _LAST_ERR[0]
        _LAST_ERR[0] = 'Current move is ambiguous from public intents/history（候选都对不上）' + (f' 最后：{last}' if P.get('search_public_why') == 'detail' else '')
        return None
    from policy.public_relic_lifecycle import model_flags
    lifecycle = model_flags(pl.get('relics') or [])
    if lifecycle is None:
        _LAST_ERR[0] = 'Relic lifecycle missing from public UI or active ToyBox lifetime unknown'
        return None
    # 快速搭场景（search_public_fast，claude-value 10/4）：开新局（start_run）每次约 170 ms，占推演时间的 80%；
    # 影子引擎里已经有一局时直接重设牌组 / 遗物 / 药水、进房间、摆战斗，最后按种子重置战斗随机流（reseed_rng：
    # 洗牌、生成牌、目标、怪物 AI 等全部战斗随机流；玩家随机流只管奖励 / 商店 / 变牌）→ 每个种子的结果和开新局一样确定。
    # 这是影子局自己的随机数，和真实对局无关。force_fresh 用于校验
    fast = P.get('search_public_fast', False) and not force_fresh and getattr(s, '_pub_pid', None) == _pid(s) and not _PUB_DIRTY[0]
    if not fast:
        r = s.send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'PUB{seed}'})
        if r.get('type') == 'error': return None
        s._pub_pid = _pid(s); _PUB_DIRTY[0] = False
    s.send({'cmd': 'set_player', 'hp': pl.get('hp'), 'max_hp': pl.get('max_hp'), 'gold': pl.get('gold', 0),
            'deck': [_cardstr(c) for c in pl.get('deck') or []],
            'relics': [str(x.get('id') or '').replace('RELIC.', '') for x in pl.get('relics') or [] if x.get('id')],
            'potions': [PO.pid(p) if p and p.get('name') else None for p in pl.get('potions') or []]})
    rc = {str(x.get('id') or '').replace('RELIC.', ''): x['counter'] for x in pl.get('relics') or [] if x.get('id') and x.get('counter') is not None}
    r = s.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': str(ctx['encounter']).replace('ENCOUNTER.', '')})
    if r.get('type') == 'error':
        if fast: s._pub_pid = None; return build_public(s, st, seed, force_fresh=True, public_history=public_history, _moves=_moves)      # 复用的局进不了房间：退回开新局
        return None
    rs = {str(x.get('id') or '').replace('RELIC.', ''): x['status'] for x in pl.get('relics') or [] if x.get('id') and x.get('status') not in (None, 'Normal')}   # 引擎 p27cv：遗物状态（Active / Disabled），界面看得见
    st0 = s.send({'cmd': 'set_combat', 'seed': seed, 'relic_counters': rc, 'relic_status': rs, 'relic_lifecycle': lifecycle, 'round': st.get('round'), 'energy': st.get('energy'), 'hp': pl.get('hp'), 'block': pl.get('block', 0),
                  'powers': [{'id': p['id'], 'amount': p.get('amount', 1), **({'facing': p['facing']} if p.get('facing') else {})} for p in st.get('player_powers') or [] if p.get('id')],   # 引擎 p29：帝皇蟹战人物朝向
                  'hand': [_cardstr(c) for c in st.get('hand') or []], 'draw': st.get('draw_pile') or [],
                  'discard': st.get('discard_pile') or [], 'exhaust': st.get('exhaust_pile') or [],
                  'enemies': [{'monster_id': e.get('monster_id'), 'slot': e.get('slot'), 'hp': e.get('hp'), 'max_hp': e.get('max_hp'), 'block': e.get('block', 0),
                               'move': public_moves[e.get('index')], 'move_next': public_next if is_stun(e) else None, 'powers': [{'id': p['id'], 'amount': p.get('amount', 1)} for p in e.get('powers') or [] if p.get('id')]}
                              for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]})
    s.ctx_override = {k: ctx.get(k) for k in ('act', 'act_name', 'boss', 'floor', 'room_type', 'encounter') if ctx.get(k) is not None}
    if isinstance(st0.get('context'), dict): st0['context'].update(s.ctx_override)
    if st0.get('decision') != 'combat_play':
        _LAST_ERR[0] = f"摆战斗失败：{st0.get('decision')} {str(st0.get('message') or st0.get('error') or '')[:120]}"
        return None
    model_lifecycle = model_flags((st0.get('player') or {}).get('relics') or [])
    if model_lifecycle != lifecycle:
        _LAST_ERR[0] = 'Independent model did not restore public wax/melted flags'
        return None
    a, b = _vis(st0), _vis(st)
    if a != b:
        bad = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        det = ''
        if 10 in bad:                                   # 遗物计数：写出是哪个遗物（真局 → 新引擎）
            da, db = dict(a[10]), dict(b[10])
            det += ' 遗物' + str([(k, db.get(k), da.get(k)) for k in sorted(set(da) | set(db)) if da.get(k) != db.get(k)][:3])
        if 5 in bad:                                    # 手牌显示费用：写出是哪张牌
            import collections as _co
            det += ' 手牌' + str(list((_co.Counter(b[5]) - _co.Counter(a[5])).elements())[:3]) + '→' + str(list((_co.Counter(a[5]) - _co.Counter(b[5])).elements())[:3])
        _LAST_ERR[0] = f'新引擎摆出来对不上：{bad}{det}'
        if P.get('search_public_why') == 'detail':          # 体检用：记下第一处不一致的两边（真局 / 新引擎）
            i = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
            _LAST_ERR[0] += f' 真={str(b[i])[:300]} 新={str(a[i])[:300]}'
        if _moves is not None and bad == [11]:                   # 只有敌人对不上 = 有候选招不对：记下是哪几只，换下一个候选（不必开新局重试）
            alive = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
            if len(a[11]) == len(b[11]) == len(alive):
                _ENEMY_BAD[0] = {alive[j].get('index') for j in range(len(alive)) if a[11][j] != b[11][j]}
            return None
        if fast: s._pub_pid = None; return build_public(s, st, seed, force_fresh=True, public_history=public_history, _moves=_moves)
        return None
    if P.get('search_public_fast', False):
        r = s.send({'cmd': 'reseed_rng', 'seed': seed})
        if r.get('type') != 'ok': return None
    return st0


_PUB_DIRTY = [False]
_ENEMY_BAD = [None]     # 最近一次试候选招时，意图对不上的敌人 index 集合


def _pid(s):
    p = getattr(s, 'p', None)
    return getattr(p, 'pid', None) if p is not None else None


def _counters(s):
    """引擎里所有随机数对象已经用了几次（补丁 22 的 rng_counters，只读）"""
    r = s.send({'cmd': 'rng_counters'})
    if r.get('type') != 'ok': return None
    return (tuple(sorted((r.get('run') or {}).items())), tuple(sorted((r.get('player') or {}).items())), r.get('monsters'))


def _play_turn_surface(s, st, seq, m2, decide):
    """表面推演：
    不洗抽牌堆、不换随机数；按方案出牌、规划器补完这回合，但**不结束回合**（敌人这回合做什么看它显示的意图）。
    - 这一步用到了随机数（随机目标、随机生成牌、洗牌……）→ 停在这一步**之前**（结果是真实随机数决定的，不能看）；
    - 这一步抽了牌 → 停在这一步**之后**，估值不看手牌（战斗估值模型本来就不用手牌内容）。
    返回 (停下时的局面, 原因)"""
    import collections
    rnd = st.get('round')
    m2['turn_plan'] = make_plan(m2.get('turn_key'), st.get('hand') or [], seq)
    c0 = _counters(s)
    if c0 is None: return None, 'no_counters'
    for _ in range(60):
        d = st.get('decision')
        if d != 'combat_play' and d not in SELECTS: return st, 'left'
        if d == 'combat_play' and st.get('round') != rnd: return st, 'turn'
        a, ar = decide(st, m2, s)
        if a == 'end_turn': return st, 'end'
        hand0 = collections.Counter(_ck(c) for c in st.get('hand') or [])
        dp0 = st.get('draw_pile_count')
        r = s.act(a, **ar)
        if r.get('type') == 'error':
            if st.get('decision') == 'combat_play' and m2.get('last_try'):
                m2.setdefault('bad', set()).add(m2.pop('last_try')); continue
            raise SimError(f'表面推演里动作出错：{a} {r.get("message")}')
        if _counters(s) != c0: return st, 'rng'
        if r.get('decision') == 'combat_play':
            dp1 = r.get('draw_pile_count')
            new = collections.Counter(_ck(c) for c in r.get('hand') or []) - hand0
            if (isinstance(dp0, int) and isinstance(dp1, int) and dp1 < dp0) or new:
                return r, 'draw'
        st = r
    return st, 'cap'


def _value_surface(hp0, st, m2, last_hp):
    """表面推演的估值：这回合到停下为止掉的血 + 战斗估值模型（看得见的局面：血、格挡、能力、敌人血量 / 意图 / 公开出招表）"""
    d = st.get('decision')
    if d == 'game_over':
        return -(hp0 + P['search_death']) if not st.get('victory') else -(hp0 - last_hp) + P['search_win_bonus']
    if d != 'combat_play' and d not in SELECTS:
        return -(hp0 - last_hp) + P['search_win_bonus']          # 打赢了（奖励界面之后的东西不看）
    if not [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]:
        return -(hp0 - last_hp) + P['search_win_bonus']
    hp = (st.get('player') or {}).get('hp', last_hp)
    sit = CV.situation_from_state(st, m2.get('last_my_dpt'))
    fut = CV.unblocked_now(sit) + (CV.predict(sit) if CV.available() else 0)
    if hp - CV.unblocked_now(sit) <= 0: fut += P['search_death']   # 挡不住意图就会死
    return -(hp0 - hp) - P['search_future_weight'] * fut


def potion_cands(st, top_score):
    """药水进推演：
    每瓶能主动喝的药各出一个候选方案「先喝它，这回合剩下的交给规划器」，和不喝的方案一起在引擎里实打比较——
    药和手牌 / 遗物的联动（力量药 + 多段、能量药 + 大牌……）由引擎精确算。喝掉的药按 potion_cost 扣分（以后还能用）"""
    from policy import potions as PO
    from policy.knowledge import intent_damage
    enemies = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
    if not enemies: return []
    pl = st.get('player') or {}; hp, mx = pl.get('hp', 1), max(pl.get('max_hp', 1), 1)
    room = (st.get('context') or {}).get('room_type', '')
    need = max(0, sum(intent_damage(e) for e in enemies) - pl.get('block', 0))
    out, seen = [], set()
    for p in (st.get('player') or {}).get('potions') or []:
        if not p or not p.get('name') or p['name'] in seen or PO.kind(p) in ('passive', 'permanent'): continue
        hmin = P.get('search_potion_heal_min_hpf')            # 默认 None = 不限制；建议 0.4
        if (hmin is not None and PO.kind(p) == 'heal' and room in ('Monster', 'Elite')
                and hp >= hmin * mx and need < hp):
            continue   # 纯回血药（鲜血药水、龙涎香……）：普通战 / 精英里血还够、这回合也不会死就不考虑——推演里「战斗结束多十几血 > 代价 12」就会喝，
                       # 可这瓶药留到 Boss 战能决定生死（iter-pub：第一幕普通战喝药 70 次，32 次在血 ≥50、来伤 ≤15 时，鲜血药水最多）
        seen.add(p['name'])
        t = max(enemies, key=intent_damage)['index'] if p.get('target_type') == 'AnyEnemy' else None
        out.append((top_score - 0.001, [({'_potion': True, 'name': p['name'], 'id': 'POTION:' + p['name']}, t)]))
    return out


def potion_cost(st):
    """喝掉一瓶药的代价（≈ 以后它能省多少血）：普通战贵、精英中、Boss 便宜；快到 Boss 时普通战 / 精英再贵一点（看未来：药留给 Boss）"""
    ctx = st.get('context') or {}; room = ctx.get('room_type', '')
    c = {'Boss': P.get('search_potion_cost_boss', 1.0), 'Elite': P.get('search_potion_cost_elite', 6.0)}.get(room, P.get('search_potion_cost_monster', 12.0))
    if room != 'Boss' and (ctx.get('floor') or 0) >= P.get('search_potion_boss_floor', 12): c += P.get('search_potion_cost_near_boss', 4.0)
    return c


def search_turn(st, mem, real_sim=None):
    """这回合要打的方案 [(牌, 目标引用)]；候选只有一个时返回 None（交回规划器）。
    推演在影子引擎上做（sim.aux，每个进程第二个引擎），真实对局的引擎完全不碰，所以不需要恢复；
    影子重放对不上真实局面（比如问号房读档重进开出的东西不一样）→ 这场战斗不再推演，交回规划器"""
    if not P.get('search_public', False):
        raise SimError('真实存档重放推演已停用；只允许公开输入的独立模型')
    import policy
    from sim import aux
    t0 = time.time()
    # 按房间加强推演：search_room_over = {"Boss": {"k": 10, "samples": 4, ...}}
    # 死得最多的是 Boss / 精英战，每局只有几场；普通战照旧，整局时间不至于翻倍。没写的项沿用全局 search_*
    over = (P.get('search_room_over') or {}).get((st.get('context') or {}).get('room_type', ''), {})
    S = lambda k: over.get(k, P[f'search_{k}'])
    cands = combat.plan(st, mem, set(mem.get('bad') or ()), topk=S('k')) or []
    if P.get('search_potions', False) and cands:
        cands = list(cands) + potion_cands(st, cands[0][0])
    if not cands or len(cands) < 2: return None
    hp0 = (st.get('player') or {}).get('hp', 0)
    base = {k: v for k, v in mem.items() if k not in ('recipe', 'clog', 'turn_plan', 'search_last', 'search_stats', 'follow', 'decisions', 'trace', 'simeval_log', '_sl_snap', 'sl_events')}   # 大的、和战斗无关的不复制
    results = []
    import params as _pm
    _scope = _pm.scoped({'simeval_pick': False, 'simeval_route': False})   # 10/2：推演打赢后会走到选卡奖励，模拟实打选牌会在同一个影子引擎上开打，把推演的局面冲掉
    n1 = S('samples'); n2 = S('refine_samples')
    if P.get('search_surface', False): n1, n2 = 1, 0             # 表面推演没有随机性，打一次就够
    ctx = st.get('context') or {}                                 # 随机数按「种子 + 位置」固定：同一份代码打同一个种子，结果完全一样
    if P.get('search_public', False):
        # 模拟用的种子只由看得见的局面算出来（同一局面同一批种子，结果可重放），完全不碰原始种子
        rng = random.Random(str((_vis(st), ctx.get('act'), ctx.get('floor'), mem.setdefault('_pub_calls', [0]).__setitem__(0, mem['_pub_calls'][0] + 1) or mem['_pub_calls'][0])))
    else:
        rng = random.Random(str((ctx.get('seed'), ctx.get('act'), ctx.get('floor'), st.get('round'), len(mem.get('clog') or []))))
    seeds = [rng.randrange(1 << 30) for _ in range(n1 + n2)]     # 各方案用同一批打乱方式比较（配对，差别更准）

    def rollout(seq_ref, seed):
        """打一次；失败（引擎超时、动作出错）返回 None，这一次不计入平均（以前记 -999，会冤枉这个方案）"""
        try:
            if P.get('search_public', False):         # 新引擎推演：只用看得见的局面摆战斗，抽牌和怪物随机按概率
                if sim.broken: sim.restart()
                _t = time.time()
                st0p = build_public(sim, st, seed, public_history=mem)
                mem['pub_build_sec'] = mem.get('pub_build_sec', 0.0) + time.time() - _t; mem['pub_rollouts'] = mem.get('pub_rollouts', 0) + 1
                ssx = mem.setdefault('search_stats', {'turns': 0, 'changed': 0, 'sec': 0.0}); ssx['pub_n'] = ssx.get('pub_n', 0) + 1   # 10/4：整局记录里也要看得到每场战斗摆不出来的比例
                if st0p is None:
                    mem['public_build_fail'] = mem.get('public_build_fail', 0) + 1; ssx['pub_fail'] = ssx.get('pub_fail', 0) + 1
                    if P.get('search_public_why'):
                        w = mem.setdefault('pub_fail_why', {}); k = str(_LAST_ERR[0])[:90 if P.get('search_public_why') != 'detail' else 800]; w[k] = w.get(k, 0) + 1
                        wx = ssx.setdefault('why', {}); wx[k] = wx.get(k, 0) + 1
                    return None
                m2 = copy.deepcopy(base); m2['_ehp0'] = _ehp(st)
                # 新引擎是另开的一局，层数和真局不同：方案 / 回合 / 战斗的记号改成新引擎里的，否则方案认不出来（10/4 冒烟：所有方案推演分一模一样）
                c0 = st0p.get('context') or {}; k0 = (c0.get('floor'), st0p.get('round') or 1)
                for kk in ('turn_key', 'plays_key', 'searched_key'):
                    if m2.get(kk) == mem.get('turn_key'): m2[kk] = k0
                m2['turn_key'] = k0; m2['combat_key'] = (c0.get('act'), c0.get('floor'))
                st1 = _play_turn(sim, st0p, seq_ref, m2, policy.decide)
                v = None if st1 is None else _value(hp0, st1, m2, policy.decide, sim)
                if P.get('search_public_verify') and P.get('search_public_fast'):
                    # 校验快速搭场景：同一种子开新局再打一遍，结果必须完全一样（不一样 = 复用的局有残留状态）
                    st0f = build_public(sim, st, seed, force_fresh=True, public_history=mem)
                    m3 = copy.deepcopy(base); m3['_ehp0'] = _ehp(st)
                    st1f = None if st0f is None else _play_turn(sim, st0f, seq_ref, m3, policy.decide)
                    vf = None if st1f is None else _value(hp0, st1f, m3, policy.decide, sim)
                    pv = mem.setdefault('pub_verify', [0, 0]); pv[0] += 1; pv[1] += (v != vf)
                return v
            if sim.broken: sim.restart()
            st0 = _reset(sim, mem['recipe'], mem['clog'])
            if st0 is None or _key(st0) != _key(st):
                mem['search_mismatch'] = mem.get('search_mismatch', 0) + 1
                raise _Mismatch(f'推演重放对不上真实局面（回合 {st.get("round")}；{_LAST_ERR[0]}）')
            if P.get('search_surface', False):        # 表面推演：不洗牌、不换随机数，只推到这回合结束 / 碰到隐藏信息为止
                m2 = copy.deepcopy(base); m2['_ehp0'] = _ehp(st)
                st1, why = _play_turn_surface(sim, st0, seq_ref, m2, policy.decide)
                if st1 is None: return None
                mem.setdefault('surface_stops', {}); mem['surface_stops'][why] = mem['surface_stops'].get(why, 0) + 1
                last_hp = (st1.get('player') or {}).get('hp', hp0) if st1.get('decision') == 'combat_play' else (st0.get('player') or {}).get('hp', hp0)
                return _value_surface(hp0, st1, m2, last_hp)
            r1 = sim.send({'cmd': 'shuffle_draw', 'seed': seed})
            draw_count = r1.get('draw_pile_count')
            if r1.get('type') != 'ok' or type(draw_count) is not int or draw_count < 0:
                raise _Mismatch(f'打乱抽牌堆失败：{str(r1.get("message"))[:80]}')
            if P.get('search_reseed', True):         # 10/3：其他随机数也重置（敌人随机出招 / 目标、随机生成的牌、洗牌）——推演不能看到真实对局未来的随机结果；固定出招不受影响
                r2 = sim.send({'cmd': 'reseed_rng', 'seed': seed})
                run_count = r2.get('run_rngs')
                monster_count = r2.get('monster_rngs')
                live_monsters = sum((e.get('hp') or 0) > 0 for e in st0.get('enemies') or [])
                if (r2.get('type') != 'ok' or type(run_count) is not int or run_count <= 0
                        or type(monster_count) is not int or monster_count < live_monsters):
                    raise _Mismatch(f'重置随机数失败：{str(r2)[:80]}')
            m2 = copy.deepcopy(base); m2['_ehp0'] = _ehp(st)
            st1 = _play_turn(sim, st0, seq_ref, m2, policy.decide)
            return None if st1 is None else _value(hp0, st1, m2, policy.decide, sim)
        except _Mismatch:
            raise
        except SimError as e:
            mem['search_errors'] = mem.get('search_errors', 0) + 1; _LAST_ERR[0] = str(e)[:200]
            if sim.broken: sim.restart()
            return None

    _IN['on'] = True; _scope.__enter__()                         # 都放进 try/finally：出任何错都会恢复（以前 aux() 失败会让 _IN 一直开着，这个进程以后再也不推演）
    try:
        sim = aux(); sim.rec = None
        # 第一轮：每个方案打 n1 次；第二轮：前几名再各打 n2 次（好钢用在刀刃上）
        for sc, seq in cands:
            seq_ref = [(c, tgt_ref_of(st, ti)) for c, ti in seq]
            pc = potion_cost(st) if any(c.get('_potion') for c, _ in seq_ref) else 0.0
            results.append([[v - pc for v in (rollout(seq_ref, sd) for sd in seeds[:n1]) if v is not None], sc, seq_ref])
            if time.time() - t0 > S('time_cap'): break
        results = [r for r in results if r[0]]                     # 一次都没打成的方案不参加比较
        if not results:
            ssx = mem.setdefault('search_stats', {'turns': 0, 'changed': 0, 'sec': 0.0}); ssx['none'] = ssx.get('none', 0) + 1   # 这一步一个模拟都没打成 → 退回规划器
            if P.get('search_teach_log') and P.get('search_public_why') and ssx['none'] <= 3:      # 整步摆不出来的局面存下来（每场最多 3 个），离线查原因
                try:
                    with open(f"{P['search_teach_log']}.fail.{os.getpid()}", 'a') as f:
                        f.write(json.dumps({'why': _LAST_ERR[0], 'enc': str(ctx.get('encounter') or ''), 'state': {k: st.get(k) for k in ('hand', 'energy', 'enemies', 'player', 'player_powers', 'round', 'context', 'draw_pile', 'discard_pile', 'exhaust_pile')}}, ensure_ascii=False) + '\n')
                except Exception: pass
            return None
        avg = lambda r: sum(r[0]) / len(r[0])
        top = sorted(results, key=lambda r: (-avg(r), -r[1]))[:S('refine_top')]
        if n2:
            for r in top:
                if time.time() - t0 > S('time_cap'): break
                pc = potion_cost(st) if any(c.get('_potion') for c, _ in r[2]) else 0.0
                r[0] += [v - pc for v in (rollout(r[2], sd) for sd in seeds[n1:n1 + n2]) if v is not None]
            if DEBUG:
                for r in results: print(f"    方案 {[c.get('name') for c, _ in r[2]]} 规划分 {r[1]:.1f} → 推演 {[round(v, 1) for v in r[0]]}")
        refined = {id(r) for r in top}
        allres = [(avg(r), len(r[0]), r[1], r[2]) for r in results]              # 老师记录用：全部候选（含只打了第一轮的）
        results = [r for r in results if id(r) in refined] if n2 else results     # 只在打了第二轮的方案里选
        results = [(avg(r), r[1], r[2]) for r in results]
    except _Mismatch:
        mem['recipe'] = None                                        # 这场战斗重放不可靠：不再推演
        return None
    finally:
        _IN['on'] = False
        _scope.__exit__(None, None, None)
        try: sim.ctx_override = None              # 影子引擎还要给选牌实打用，别把真局的幕 / 层数带过去
        except Exception: pass
    results.sort(key=lambda t: (-t[0], -t[1]))
    ss = mem.setdefault('search_stats', {'turns': 0, 'changed': 0, 'sec': 0.0})
    ss['turns'] += 1; ss['sec'] += time.time() - t0; ss['changed'] += results[0][1] != cands[0][0]
    mem['search_last'] = [(round(v, 1), round(sc, 1), [c.get('name') for c, _ in sq]) for v, sc, sq in results[:4]]
    if P.get('search_teach_log'):
        # 推演当老师：记下真实局面和推演选中的出法，
        # 离线在同一局面上让规划器列出全部组合，学权重让它自己选中老师那组（tools/train_from_teacher.py）
        try:
            ctx = st.get('context') or {}
            rec = {'enc': str(ctx.get('encounter') or '').replace('ENCOUNTER.', ''), 'room': ctx.get('room_type'), 'act': ctx.get('act'),
                   'round': st.get('round'), 'floor': ctx.get('floor'), 'seed': ctx.get('seed'),     # seed + floor：离线接上这场战斗的结果（只用于训练，不进决策）
                   'state': {k: st.get(k) for k in ('hand', 'energy', 'enemies', 'player', 'player_powers', 'round', 'context', 'draw_pile', 'discard_pile', 'exhaust_pile')},
                   'chosen': [str(c.get('id') or c.get('name')) for c, _ in results[0][2]],
                   'cands': [{'v': round(v, 2), 'sc': round(sc, 2), 'cards': [str(c.get('id') or c.get('name')) for c, _ in sq]} for v, sc, sq in results[:8]],
                   # 全部候选（重排函数训练用）：n = 推演打了几遍；喝药的候选带 potion
                   'all': [{'v': round(v, 2), 'n': n, 'sc': round(sc, 2), 'cards': [str(c.get('id') or c.get('name')) for c, _ in sq if not c.get('_potion')],
                            'potion': next((str(c.get('id') or c.get('name')) for c, _ in sq if c.get('_potion')), None)} for v, n, sc, sq in allres]}
            with open(f"{P['search_teach_log']}.{os.getpid()}", 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')   # 每个进程一个文件，长行不会写串
        except Exception:
            pass
        if P.get('search_teach_only'):
            # 只当老师（DAgger）：推演打分、记录，但这回合照样交给不推演的规划器打——记下的是我们自己下场会遇到的局面
            return None
    return results[0][2]
