"""人类回放 → 每个玩家回合结束时的战斗局面 + 之后到战斗结束掉了多少血 / 死没死（战斗价值网络用别人的对局训练）。


数据：sources/community-runs/replays/ironclad-a10/*.ndjson.gz（spire-codex 社区录像，逐事件）。
只取 v0.111.0 / v0.107.1、单人、标准模式、无修改器、无模组、回放格式 v4 以上。

局面字段和 policy/combatvalue.situation_from_state 一一对应，还原方法：
- 取局面的时刻：玩家 end_turn 事件那一刻（回合结束触发——覆甲 / 金属化格挡、灼伤 / 感染扣血、虚无消耗——已经发生；
  我们自己的数据取在按「结束回合」之前，差别只在有这些触发的回合，量级是几点格挡 / 血）
- 我方血量：hp 事件（绝对值）；读档恢复看 resume 事件的 hp
- 血量上限：整局记录（ironclad-a10*.jsonl.gz，同一种子、这一层之前那一格的 max_hp）；查不到就用开局上限 + max_hp 事件 + 存档退出时 end 事件里的上限
- 格挡：本回合 block 事件累加、挨打时减掉被挡的部分、敌方回合结束清零（有壁垒不清）；v6 以上 block 事件带 left（当前格挡），直接以它为准
- 力量 / 敏捷 / 虚弱 / 易伤 / 脆弱 / 能力数：power 事件按增量累计（带 amount 的以 amount 为准），power_lost 清掉
- 牌组张数：开局牌组 + 获得 − 删除（v5 以上有整副快照就以快照为准，读档时以 resume 的 deck_size 为准）；
  每回合伤害 my_dpt 用同一副牌调 policy.deckeval（和运行时一样）
- 抽牌堆 / 弃牌堆张数：逐张牌记账（开场 = 牌组张数；抽牌 −1；洗牌 = 弃牌堆全部回到抽牌堆；打出进弃牌堆 / 消耗 / 能力牌消失；
  回合结束手牌进弃牌堆）。战斗中生成的牌放到哪一堆看它下一次出现：先被抽到且中间没洗牌 = 抽牌堆，直接被打出 = 手牌，否则当弃牌堆
- 敌人血量：开场血量 − 命中掉血（dmg − overkill），hp / max_hp 事件给绝对值时以它为准；killed / death 事件记死亡，死后又出招 = 复活（按满血）；
  同名敌人没有实例编号（v4–v6）时：出招按顺序对应活着的同名敌人，挨打给「上次打的那只」，打死时找血量刚好等于伤害的那只
- 敌人格挡：block 事件累加、被挡掉的减掉、敌方回合开始清零（埋地不清）
- 敌人意图伤害：这个玩家回合之后的敌方回合里，该敌人打到我身上的总伤害（掉血 + 被挡）——就是玩家这回合看到的意图（已含力量 / 虚弱 / 易伤）；
  没出攻击招 = 0。v7 有 intent 事件，用来核对
- fut（接下来 3 回合平均伤害）：用这回合实际出的招（move 事件）调 policy.foresight.future，和运行时一样的出招表推算
- 随从：开场能力取 kb/monsters.json 的 start_powers（开场能力回放里不记），战斗中召唤的按 power 事件
- 中途召唤的敌人（v4–v6 没有 spawn 事件）：第一次在出招 / 挨打里出现时加入，血量用出招表 A10 区间中值
标签：future = 局面时的血 − 战斗结束时的血（死了按 0），died = 死在这场战斗里（没有 combat_end 而整局以死亡结束，或 combat_end 是 loss）。
读档重打（存档退出后整场战斗重来）：被放弃的那一遍没有结果，丢掉；只留打完的那一遍（这会偏向人类打得好的那遍，见报告）。

输出：results/human-turns.jsonl（每行一场战斗：{replay, seed, build, ver, enc, act, floor, attempt, reloaded, turns: [{s, future, died, ...}]}，
格式和 STS2_LOG_TURNS 记的一样，tools/train_combat_value.py 也能直接读）。同时打印各字段的核对结果。
用法：python3 tools/replay_situations.py [--max-files N] [--out results/human-turns.jsonl]
"""
import argparse, collections, glob, gzip, json, os, re, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy.combatvalue import deck_dpt
from policy import kb, foresight
from params import P

SRC = '/opt/slay-the-spire-2/sources/community-runs'
REPLAYS = f'{SRC}/replays/ironclad-a10'
BUILDS = ('v0.111.0', 'v0.107.1')
MON = json.load(open(f'{HERE}/kb/monsters.json'))
PLAYER = 'IRONCLAD'
DEBUFF_P = ('WEAK_POWER', 'VULNERABLE_POWER', 'FRAIL_POWER')
NO_CLEAR_P = ('BARRICADE_POWER', 'BLUR_POWER')            # 有这些能力时玩家格挡不在回合开始清零
NO_CLEAR_E = ('BURROWED_POWER', 'BARRICADE_POWER')


def snake(s):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', s).upper()


def mon_hp(mid):
    h = ((MON.get(mid) or {}).get('hp') or {}).get('a10') or [30, 30]
    return int(round(sum(h) / len(h)))


def mon_start_powers(mid):
    out = collections.Counter()
    for p in (MON.get(mid) or {}).get('start_powers') or []:
        a = p.get('amount')
        a = (a.get('a10', a.get('a0', 1)) if isinstance(a, dict) else a) or 1
        out[snake(str(p.get('power')))] += a if isinstance(a, (int, float)) else 1
    return out


HEAL_MOVES = {'PONDER_MOVE': 30, 'SIPHON_MOVE': 15}
INF_HP = 999999999
RESPAWN_MAX = {1: 212, 2: 313}
REVIVE_POWERS = {'IllusionPower', 'ReattachPower', 'AdaptablePower'}


def RESPAWNS_ON_DEATH(mid):
    return 'RESPAWN_MOVE' in ((MON.get(mid) or {}).get('moves') or {})


def can_revive(mid):
    m = MON.get(mid) or {}
    return bool({str(p.get('power')) for p in m.get('start_powers') or []} & REVIVE_POWERS) or 'RESPAWN_MOVE' in (m.get('moves') or {})


def fut_of(mid, move, strength, intent, public_player_powers=None):
    """foresight：从这一招往后 3 个敌方回合的平均伤害（和运行时 situation_from_state 一样）；认不出来就用这回合意图"""
    m = MON.get(mid)
    if not m or not move or move not in (m.get('moves') or {}): return intent, False
    try:
        f3 = foresight.future({'name': m.get('name'), 'powers': [{'name': 'Strength', 'amount': strength}]}, move, 3, public_player_powers=public_player_powers)
    except Exception:
        f3 = None
    return (sum(f3) / len(f3), True) if f3 else (intent, False)


# ---------------------------------------------------------------- 整局记录：每层的血量上限
def runrec_maxhp(seeds, cache):
    if os.path.exists(cache):
        d = json.load(open(cache))
        if set(seeds) <= set(d['seeds']): return {s: {int(k): v for k, v in fl.items()} for s, fl in d['by'].items()}
    by = {}
    for name in ('ironclad-a10-v0.111.0.jsonl.gz', 'ironclad-a10-all.jsonl.gz'):
        for l in gzip.open(f'{SRC}/{name}', 'rt'):
            i = l.rfind('"seed"')
            if i < 0: continue
            m = re.match(r'"seed"\s*:\s*"([^"]+)"', l[i:i + 60])
            if not m or m.group(1) not in seeds or m.group(1) in by: continue
            r = json.loads(l)
            if r.get('ascension') != 10: continue
            fl = {}; f = 0
            for act in r.get('map_point_history') or []:
                for mp in act:
                    f += 1
                    ps = (mp.get('player_stats') or [{}])[0]
                    rooms = [rm.get('model_id', '').replace('ENCOUNTER.', '') for rm in mp.get('rooms') or []]
                    fl[f] = (ps.get('max_hp'), ps.get('current_hp'), rooms)
            by[r['seed']] = fl
    json.dump({'seeds': sorted(seeds), 'by': by}, open(cache, 'w'))
    return by


# ---------------------------------------------------------------- 单个回放
class Combat:
    def __init__(self, x, deck, hp, max_hp, ver):
        self.enc = x.get('encounter') or ''; self.act = x.get('act') or 1; self.floor = x.get('floor') or 0
        self.attempt = x.get('attempt_id') or 0; self.cid = x.get('combat_id')
        self.enemies = []                        # 按槽位顺序；每个 {key, id, hp, max, block, pw, alive}
        for e in x.get('enemies') or []:
            self.add_enemy(e['id'], e.get('hp'), e.get('max_hp'), cid=e.get('cid'), start_pw=True)
        self.deck = deck; self.deck_n = len(deck)
        self.my_dpt = deck_dpt([{'id': d[0], 'upgraded': bool(d[1])} for d in deck])
        self.hp = hp; self.max_hp = max_hp; self.block = 0; self.ppw = collections.Counter()
        self.draw_n = self.deck_n; self.disc_n = 0; self.hand = set(); self.loc = {}
        self.side = None; self.round = 0; self.snaps = []; self.pending = None
        self.last_hit = {}                       # 同名敌人：玩家上次打的是哪只
        self.actor = {}; self.moves_seen = collections.Counter(); self.last_play_target = None; self.v7_int = {}; self.flushed = False
        self.seg = []; self.first_seg = True; self.deck_err = 0             # 这一段（上次洗牌以来）的局面；第一段的抽牌堆误差
        self.ver = ver

    def add_enemy(self, mid, hp=None, mx=None, cid=None, start_pw=False):
        e = {'key': len(self.enemies), 'id': mid, 'cid': cid, 'hp': hp if hp is not None else mon_hp(mid), 'max': mx or hp or mon_hp(mid),
             'block': 0, 'pw': mon_start_powers(mid) if start_pw else collections.Counter(), 'alive': True}
        self.enemies.append(e)
        return e

    def find(self, mid, cid=None, prefer=None, for_kill=None, create=True):
        """找一个敌人：有实例编号按编号（开场没给编号的，第一次见到时绑到一只还没绑定的同名敌人上）；
        否则同名里按 prefer → 活着的第一只；打死时优先血量刚好等于伤害的那只"""
        if mid in (None, 'player', PLAYER, 'effect'): return None
        ok_new = mid in MON and (MON[mid].get('category') != 'pet')
        if cid is not None:
            for e in self.enemies:
                if e['cid'] == cid: return e
            unbound = [e for e in self.enemies if e['id'] == mid and e['cid'] is None]
            if unbound:
                e = self._pick(unbound, prefer, for_kill); e['cid'] = cid
                return e
            return self.add_enemy(mid, cid=cid) if (create and ok_new) else None
        cands = [e for e in self.enemies if e['id'] == mid]
        if not cands:
            return self.add_enemy(mid) if (create and ok_new) else None
        return self._pick(cands, prefer, for_kill)

    @staticmethod
    def _pick(cands, prefer, for_kill):
        alive = [e for e in cands if e['alive']] or cands
        if for_kill is not None:
            exact = [e for e in alive if e['hp'] == for_kill]
            if exact: return exact[0]
        if prefer is not None and prefer in alive: return prefer
        return alive[0]


def accept(h):
    """v0.111.0（"0.1.0" 是同一个提交 41cef1ea 的另一种版本号）/ v0.107.1、单人、标准模式、A10 铁甲、无修改器、没有影响玩法的模组"""
    build_ok = h.get('build_id') in BUILDS or '41cef1ea' in str(h.get('build_id_full') or '')
    mods_ok = not any(m.get('affects_gameplay') for m in h.get('mods') or [] if isinstance(m, dict))
    return (build_ok and h.get('player_count') == 1 and h.get('game_mode') == 'standard' and not h.get('modifiers') and mods_ok
            and (h.get('replay_version') or 0) >= 4 and h.get('character') == 'IRONCLAD' and h.get('ascension') == 10)


def process(path, runrec, V):
    """一个回放 → [战斗记录]。V：核对计数器"""
    lines = []
    for l in gzip.open(path, 'rt'):
        try: lines.append(json.loads(l))
        except Exception: pass
    if not lines or not accept(lines[0]): return None
    hdr = lines[0]; ver = hdr.get('replay_version'); seed = hdr.get('seed'); rr = runrec.get(seed) or {}
    # 生成的牌放到哪一堆：看它下一次出现（先算好）
    gen_dest = {}
    for i, x in enumerate(lines):
        if x.get('t') != 'generate': continue
        c = x.get('c'); shuffled = False; dest = 'discard'
        for y in lines[i + 1:i + 4000]:
            t = y.get('t')
            if t in ('combat_end', 'combat_start', 'end'): break
            if t == 'shuffle': shuffled = True
            if y.get('c') == c and t in ('draw', 'play', 'exhaust', 'discard'):
                dest = ('discard' if shuffled else 'draw') if t == 'draw' else 'hand'
                break
        gen_dest[i] = dest
    deck = [[d['id'], d.get('up', 0)] for d in hdr.get('starting_deck') or []]; pend = collections.Counter()
    hp = hdr.get('starting_max_hp') or 80; max_hp = hp; out = []; cb = None
    starts = {}; restarted = set()                                     # 每场战斗第一次进场时的牌组 / 血量；重来过的战斗
    for i, x in enumerate(lines):
        t = x.get('t')
        # ---- 战斗外：牌组 / 血量上限
        if t == 'header' and i > 0:
            if cb is not None: V['drop_left'] += 1; cb = None
            continue
        if t == 'resume':
            if x.get('hp') is not None: hp = x['hp']
            if cb is not None: V['drop_left'] += 1; cb = None
            ds = x.get('deck_size')
            if ds and ds != len(deck): V['deck_resume_fix'] += 1
            continue
        if t == 'end':
            if cb is not None:
                if x.get('terminal_reason') == 'death':
                    finish(cb, 0, True, out, V, hdr, path)
                else:
                    V['drop_left'] += 1
                cb = None
            if x.get('max_hp'): max_hp = x['max_hp']
            if x.get('final_deck'):                                   # 存档退出时的整副牌：以它为准（读档会回滚获得的牌）
                fd = [[d['id'], d.get('up', 0)] for d in x['final_deck']]
                V['deck_sync_n'] += 1; V['deck_sync_ok'] += len(fd) == len(deck)
                deck = fd
            continue
        if t == 'deck' and x.get('cards'): deck = [[d['id'], d.get('up', 0)] for d in x['cards']]
        elif t == 'acquire' and cb is None: deck.append([x['id'], x.get('up', 0) + pend.pop(x.get('c'), 0)])
        elif t == 'remove' and cb is None: take(deck, x.get('id'))
        elif t == 'transform' and cb is None:
            if x.get('from_id'): take(deck, x.get('from_id'))
            deck.append([x.get('to_id'), x.get('to_up', 0)])
        elif t == 'upgrade' and cb is None:
            d = take(deck, x.get('id'), up=0)
            if d is not None: deck.append([d[0], d[1] + 1])
            elif x.get('c') is not None: pend[x['c']] += 1
        if t == 'hp' and 'hp' in x and x.get('dst') in (None, 'player', PLAYER):
            hp = x['hp']
            if cb is not None: cb.hp = hp
        if t == 'max_hp' and x.get('dst') in ('player', PLAYER) and x.get('max_hp'):
            max_hp = x['max_hp']
            if cb is not None: cb.max_hp = max_hp
        if t == 'combat_start':
            if cb is not None: V['drop_left'] += 1
            base = (x.get('combat_id') or '').split('#')[0]
            if base in starts:                                         # 同一场战斗重来（读档 / 重开）：牌组、血量回到第一次进场时
                deck = [list(d) for d in starts[base][0]]; hp = starts[base][1]; restarted.add(base)
            else:
                starts[base] = ([list(d) for d in deck], hp)
            mx = max_hp
            f = x.get('floor') or 0
            if (f - 1) in rr and rr[f - 1][0]:
                mx = rr[f - 1][0]; V['maxhp_runrec'] += 1
                if rr[f - 1][1] is not None:
                    V['hp_check_n'] += 1; V['hp_check_ok'] += abs(rr[f - 1][1] - hp) <= 0
                if f in rr and x.get('encounter') in rr[f][2]: V['floor_align_ok'] += 1
                V['floor_align_n'] += 1
            else:
                V['maxhp_fallback'] += 1
            cb = Combat(x, [list(d) for d in deck], hp, max(mx, hp), ver)
            continue
        if cb is None: continue
        if t == 'combat_end':
            if x.get('result') == 'victory': finish(cb, cb.hp, False, out, V, hdr, path)
            elif x.get('result') == 'loss': finish(cb, 0, True, out, V, hdr, path)
            else: V['drop_noresult'] += 1
            cb = None; continue
        step(cb, x, i, gen_dest, V)
    if cb is not None: V['drop_truncated'] += 1
    frac = len(restarted) / max(len(starts), 1)
    for r in out:
        r['restarted'] = r['cid'] in restarted; r['file_restart_frac'] = round(frac, 3)
    return out


def take(deck, cid, up=None):
    cands = [i for i, d in enumerate(deck) if d[0] == cid]
    if up is not None: cands = [i for i in cands if bool(deck[i][1]) == bool(up)] or cands
    return deck.pop(cands[0]) if cands else None


def situation(cb):
    ens = []
    for e in cb.enemies:
        if not e['alive'] or e['hp'] <= 0: continue
        pw = e['pw']
        ens.append({'key': e['key'], 'id': e['id'], 'fut': 0, 'ehp': max(0, e['hp']) + max(0, e['block']), 'intent': 0,
                    'str': pw.get('STRENGTH_POWER', 0), 'minion': 1 if pw.get('MINION_POWER', 0) > 0 else 0,
                    'vuln': 1 if pw.get('VULNERABLE_POWER', 0) > 0 else 0, 'weak': 1 if pw.get('WEAK_POWER', 0) > 0 else 0})
    p = cb.ppw
    public_curses = ({'public_player_powers': [{'id': key, 'amount': val} for key, val in p.items() if val > 0]}
                     if P.get('foresight_public_kd_loop', False) else {})
    return {**public_curses, 'enc': cb.enc, 'act': cb.act, 'round': cb.round, 'hp': cb.hp, 'max_hp': max(cb.max_hp, cb.hp), 'block': max(0, cb.block),
            'str': p.get('STRENGTH_POWER', 0), 'dex': p.get('DEXTERITY_POWER', 0), 'n_pw': sum(1 for v in p.values() if v),
            'p_weak': 1 if p.get('WEAK_POWER', 0) > 0 else 0, 'p_vuln': 1 if p.get('VULNERABLE_POWER', 0) > 0 else 0,
            'p_frail': 1 if p.get('FRAIL_POWER', 0) > 0 else 0, 'deck': cb.deck_n, 'draw': max(0, cb.draw_n), 'discard': max(0, cb.disc_n),
            'my_dpt': cb.my_dpt, 'enemies': ens}


def close_pending(cb, V):
    """敌方回合结束：把这回合各敌人实际打出的伤害填成上一个局面的意图"""
    sn = cb.pending
    if sn is None: return
    cb.pending = None
    acc = sn.pop('_acc'); moves = sn.pop('_moves')
    s = sn['s']; keys = {e['key'] for e in s['enemies']}
    for k in list(acc) + list(moves):
        if k not in keys:                                   # 局面里没有、敌方回合却出手了：之前没记到的召唤物
            e = cb.enemies[k]
            s['enemies'].append({'key': k, 'id': e['id'], 'fut': 0, 'ehp': max(0, e['hp']) + max(0, e['block']), 'intent': 0,
                                 'str': e['pw'].get('STRENGTH_POWER', 0), 'minion': 1 if e['pw'].get('MINION_POWER', 0) > 0 else 0,
                                 'vuln': 0, 'weak': 0, '_late': 1})
            keys.add(k); V['late_enemy'] += 1
    v7 = sn.get('_v7', {})
    for e in s['enemies']:
        e['intent'] = acc.get(e['key'], 0)
        if e['key'] in v7 and not e.get('_late'): e['_shown'] = v7[e['key']]
        if '_shown' in e:                                   # v7：玩家这回合最后显示的意图——核对，并直接用它（就是运行时看到的）
            V['intent_check_n'] += 1; V['intent_check_ok'] += abs(e['_shown'] - e['intent']) <= 0
            e['intent'] = e.pop('_shown')
        f, ok = fut_of(e['id'], moves.get(e['key']), e['str'], e['intent'], s.get('public_player_powers'))
        e['fut'] = round(f, 2); V['fut_ok' if ok else 'fut_fallback'] += 1
    sn.pop('_v7', None)


def step(cb, x, i, gen_dest, V):
    t = x.get('t')
    if t == 'turn':
        if x.get('side') == 'player':
            close_pending(cb, V)
            cb.side = 'player'; cb.round = x.get('n') or cb.round + 1; cb.last_play_target = None
        else:
            cb.side = 'enemy'; cb.moves_seen = collections.Counter(); cb.actor = {}
            for e in cb.enemies:                            # 敌人格挡在它的回合开始清零
                if not any(e['pw'].get(p, 0) for p in NO_CLEAR_E): e['block'] = 0
        return
    if t == 'end_turn':
        if x.get('side') == 'player' and cb.side == 'player':
            sn = {'s': situation(cb), 'hp': cb.hp, '_acc': collections.Counter(), '_moves': {}, '_v7': getattr(cb, 'v7_int', {}), 'enemy_hits': 0}
            cb.snaps.append(sn); cb.seg.append(sn); cb.pending = sn; cb.v7_int = {}
            # 手牌进弃牌堆（v6 以上有 flush 事件，已经处理过）
            if not getattr(cb, 'flushed', False):
                cb.disc_n += len(cb.hand); cb.hand = set()
            cb.flushed = False
        elif x.get('side') == 'enemy':
            close_pending(cb, V)
            if not any(cb.ppw.get(p, 0) for p in NO_CLEAR_P): cb.block = 0      # 玩家格挡在自己回合开始前清零
        return
    if t == 'flush':
        ret = set(x.get('retained_c') or [])
        if x.get('mine') is False: return
        moved = [c for c in cb.hand if c not in ret]
        cb.disc_n += len(moved); cb.hand = {c for c in cb.hand if c in ret}; cb.flushed = True
        return
    # ---- 牌堆记账
    if t == 'draw':
        c = x.get('c'); cb.draw_n -= 1; cb.hand.add(c); cb.loc[c] = 'hand'
        if cb.draw_n < 0:                                            # 记少了：这一段里之前的局面都补 1
            V['draw_negative'] += 1; cb.draw_n = 0
            for sn in cb.seg: sn['s']['draw'] += 1
        return
    if t == 'shuffle':
        V['shuffle_n'] += 1; V['shuffle_pre_draw_zero'] += cb.draw_n == 0
        if cb.draw_n > 0:                                            # 洗牌时抽牌堆应该是空的：记多了，这一段里之前的局面都减掉
            V['draw_fix'] += 1
            for sn in cb.seg: sn['s']['draw'] = max(0, sn['s']['draw'] - cb.draw_n)
            if cb.first_seg: cb.deck_err = cb.draw_n                  # 第一段多出来的多半是牌组张数记多了
            cb.draw_n = 0
        cb.seg = []; cb.first_seg = False
        if x.get('n_draw') is not None:
            V['ndraw_check_n'] += 1; V['ndraw_check_ok'] += abs(x['n_draw'] - (cb.draw_n + cb.disc_n)) <= 1
            cb.draw_n = x['n_draw']
        else:
            cb.draw_n += cb.disc_n
        cb.disc_n = 0
        return
    if t == 'generate':
        c = x.get('c'); d = gen_dest.get(i, 'discard'); cb.loc[c] = d
        if d == 'draw': cb.draw_n += 1
        elif d == 'hand': cb.hand.add(c)
        else: cb.disc_n += 1
        return
    if t == 'play':
        c = x.get('c'); auto = x.get('auto')
        if c in cb.hand: cb.hand.discard(c)
        elif cb.loc.get(c) == 'discard': cb.disc_n -= 1
        elif cb.loc.get(c) in (None, 'draw') and auto: cb.draw_n -= 1                  # 自动打出抽牌堆顶的牌（破灭等）
        elif cb.loc.get(c) in ('played', 'exhaust', 'gone'): return                       # 同一张牌第二次打出（回响等），不重复记账
        rp = x.get('result_pile')
        typ = kb.card(x.get('id') or '').get('type')
        dest = rp if rp else ('gone' if typ == 'Power' else 'discard')
        if dest == 'discard': cb.disc_n += 1; cb.loc[c] = 'discard'
        elif dest == 'hand': cb.hand.add(c); cb.loc[c] = 'hand'
        elif dest == 'draw': cb.draw_n += 1; cb.loc[c] = 'draw'
        elif dest == 'exhaust': cb.loc[c] = 'exhaust'
        else: cb.loc[c] = 'gone'
        if x.get('target') and cb.side == 'player':
            cb.last_play_target = cb.find(x['target'], x.get('target_cid'), prefer=cb.last_hit.get(x['target']), create=False)
        return
    if t == 'exhaust':
        c = x.get('c'); l = cb.loc.get(c)
        if c in cb.hand: cb.hand.discard(c)
        elif l == 'discard': cb.disc_n -= 1
        elif l in (None, 'draw'): cb.draw_n -= 1
        cb.loc[c] = 'exhaust'
        return
    if t == 'discard':
        c = x.get('c')
        if c in cb.hand: cb.hand.discard(c)
        else: cb.draw_n -= 1
        cb.disc_n += 1; cb.loc[c] = 'discard'
        return
    # ---- 敌人出招 / 召唤 / 死亡
    if t == 'spawn':
        if x.get('side') == 'enemy':
            cb.add_enemy(x.get('id'), x.get('hp'), x.get('max_hp'), cid=x.get('cid'))
        return
    if t == 'move':
        mid = x.get('src')
        if mid in (None, 'player', PLAYER): return
        e = None
        if x.get('src_cid') is not None: e = cb.find(mid, x['src_cid'])
        else:
            same = [q for q in cb.enemies if q['id'] == mid and q['alive']]
            k = cb.moves_seen[mid]; cb.moves_seen[mid] += 1
            if k < len(same): e = same[k]
            else:                                               # 活着的同名敌人不够：复活一只能复活的，否则是新召唤的
                dead = [q for q in cb.enemies if q['id'] == mid and not q['alive']]
                e = dead[0] if (dead and can_revive(mid)) else (cb.add_enemy(mid) if mid in MON else None)
                if e is not None and e in dead: e['alive'] = True; e['hp'] = e['max']; V['revive'] += 1
        if e is None: return
        if not e['alive']: e['alive'] = True; e['hp'] = e['max']; V['revive'] += 1              # 死了又出招 = 复活
        mv = x.get('id')
        if mv in HEAL_MOVES: e['hp'] = min(e['max'], e['hp'] + HEAL_MOVES[mv])               # 知识恶魔沉思 / 瀑布巨兽虹吸回血
        elif mv == 'HATCH_MOVE' and x.get('src_cid') is None: e['max'] = e['hp'] = 21               # 硬蛋孵化（v7 有 max_hp 事件给准确值）
        cb.actor[mid] = e
        if cb.pending is not None and cb.side == 'enemy': cb.pending['_moves'][e['key']] = mv
        return
    if t == 'intent' and x.get('at') in ('turn_start', 'turn_end') and cb.side == 'player':      # v7：显示的意图（回合中途变了会再记一条 turn_end）
        e = cb.find(x.get('src'), x.get('src_cid'), create=False)
        if e is not None and 'attack' in (x.get('intents') or []):
            cb.v7_int = getattr(cb, 'v7_int', {}); cb.v7_int[e['key']] = (x.get('dmg') or 0) * (x.get('hits') or 1)
        elif e is not None:
            cb.v7_int = getattr(cb, 'v7_int', {}); cb.v7_int[e['key']] = 0
        return
    if t == 'death':
        e = cb.find(x.get('tgt'), x.get('tgt_cid'), create=False)
        if e is not None and x.get('tgt') not in ('player', PLAYER) and e['hp'] != INF_HP: e['alive'] = False
        return
    # ---- 命中
    if t == 'hit':
        src, dst = x.get('src'), x.get('dst'); dmg = x.get('dmg') or 0; blk = x.get('blocked') or 0
        if dst in ('player', PLAYER):
            if 'left' not in x: cb.block = max(0, cb.block - blk)
            if src not in ('player', PLAYER, 'effect') and cb.side == 'enemy' and cb.pending is not None:
                e = cb.find(src, x.get('src_cid'), prefer=cb.actor.get(src))
                if e is not None:
                    cb.pending['_acc'][e['key']] += dmg + blk
            if cb.pending is not None and cb.side == 'enemy': cb.pending['enemy_hits'] += dmg
            return
        lost = dmg - (x.get('overkill') or 0)
        prefer = cb.last_play_target if (cb.last_play_target or {}).get('id') == dst else cb.last_hit.get(dst)
        e = cb.find(dst, x.get('dst_cid'), prefer=prefer, for_kill=lost if x.get('killed') else None)
        if e is None: return
        if not e['alive'] and x.get('dst_cid') is None:
            if can_revive(dst) or MON.get(dst, {}).get('category') == 'summon':
                e = cb.add_enemy(dst); V['spawn_on_hit'] += 1          # 打到的同名敌人全死了：新召唤的
        others = [q for q in cb.enemies if q['id'] == dst and q['alive'] and q is not e] if x.get('dst_cid') is None else []
        if x.get('killed') and dst == 'WATERFALL_GIANT':                # 瀑布巨兽被打死：变成无限血（运行时状态里血量 999999999），两回合后自爆
            V['kill_n'] += 1; V['kill_hp_ok'] += abs(e['hp'] - lost) <= 1
            e['hp'] = INF_HP; e['block'] = 0
            return
        if x.get('killed') and RESPAWNS_ON_DEATH(dst) and e.get('respawns', 0) < 2:   # 实验体：打死立刻进入下一阶段（上限 212 → 313，回满）
            V['kill_n'] += 1; V['kill_hp_ok'] += abs(e['hp'] - lost) <= 1
            e['respawns'] = e.get('respawns', 0) + 1; e['max'] = RESPAWN_MAX[e['respawns']]; e['hp'] = e['max']; e['block'] = 0
            return
        if x.get('killed'):
            V['kill_n'] += 1; V['kill_hp_ok'] += abs(e['hp'] - lost) <= 1
            if others and e['hp'] != lost:                             # 同名敌人分不清：总血量守恒，差额挪给另一只
                q = prefer if prefer in others else others[0]
                q['hp'] = max(1, q['hp'] + e['hp'] - lost); V['kill_pool_fix'] += 1
            e['alive'] = False; e['hp'] = 0
        else:
            if e['hp'] - lost <= 0 and others:                         # 这一下没打死却会打到 ≤0：其实打的是另一只
                q = max(others, key=lambda q: q['hp'])
                if q['hp'] - lost > 0: e = q; V['hit_reassign'] += 1
            e['hp'] -= lost
            if e['hp'] <= 0: V['hp_nonpos'] += 1; e['hp'] = 1
        e['block'] = max(0, e['block'] - blk)
        if src in ('player', PLAYER): cb.last_hit[dst] = e
        return
    if t == 'block':
        src = x.get('src'); n = x.get('n') or 0
        if src in ('player', PLAYER):
            if x.get('mine') is False: return
            if 'left' in x:
                pred = max(0, cb.block + n) if x.get('reason') == 'gained' else None
                if pred is not None: V['block_check_n'] += 1; V['block_check_ok'] += pred == x['left']
                cb.block = x['left']
            else:
                cb.block = max(0, cb.block + n)
            return
        e = cb.find(src, x.get('src_cid'), prefer=cb.actor.get(src) if cb.side == 'enemy' else cb.last_hit.get(src), create=False)
        if e is None: return
        e['block'] = x['left'] if 'left' in x else max(0, e['block'] + n)
        return
    if t == 'hp' and x.get('dst') not in (None, 'player', PLAYER):
        e = cb.find(x.get('dst'), x.get('dst_cid'), create=False)
        if e is not None and x.get('hp') is not None: e['hp'] = x['hp']; e['alive'] = x['hp'] > 0
        return
    if t == 'max_hp' and x.get('dst') not in (None, 'player', PLAYER):
        e = cb.find(x.get('dst'), x.get('dst_cid'), create=False)
        if e is not None:
            if x.get('max_hp'): e['max'] = x['max_hp']
            if x.get('hp') is not None: e['hp'] = x['hp']; e['alive'] = x['hp'] > 0
        return
    # ---- 能力
    if t in ('power', 'power_lost'):
        tgt = x.get('tgt'); pid = x.get('id')
        if x.get('mine') is False: return
        if tgt in ('player', PLAYER):
            pw = cb.ppw
        else:
            pref = cb.actor.get(tgt) if cb.side == 'enemy' else (cb.last_play_target if (cb.last_play_target or {}).get('id') == tgt else cb.last_hit.get(tgt))
            e = cb.find(tgt, x.get('tgt_cid'), prefer=pref, create=False)
            if e is None: return
            pw = e['pw']
        if 'amount' in x and x['amount'] is not None: pw[pid] = x['amount']
        elif t == 'power_lost': pw[pid] = 0
        else: pw[pid] += x.get('n') or 0
        return


def finish(cb, end_hp, died, out, V, hdr, path):
    close_pending(cb, V)
    turns = []
    if 0 < cb.deck_err <= 8:
        V['deck_fix_combats'] += 1
        for sn in cb.snaps: sn['s']['deck'] = max(1, sn['s']['deck'] - cb.deck_err)
    for sn in cb.snaps:
        if not [e for e in sn['s']['enemies'] if not e['minion']]:
            V['drop_nomain'] += 1; continue
        sn['s'].pop('_late', None)
        for e in sn['s']['enemies']: e.pop('_late', None)
        turns.append({'s': sn['s'], 'future': sn['hp'] - end_hp, 'died': died, 'enemy_turn_loss': sn['enemy_hits']})
    V['combats'] += 1; V['died'] += died; V['turns'] += len(turns)
    out.append({'replay': os.path.basename(path), 'seed': hdr.get('seed'), 'build': hdr.get('build_id'), 'ver': hdr.get('replay_version'),
                'enc': cb.enc, 'act': cb.act, 'floor': cb.floor, 'attempt': cb.attempt, 'cid': (cb.cid or '').split('#')[0], 'hp0': cb.snaps[0]['hp'] if cb.snaps else cb.hp,
                'end_hp': end_hp, 'died': died, 'turns': turns})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--max-files', type=int, default=0)
    ap.add_argument('--out', default=f'{HERE}/results/human-turns.jsonl')
    ap.add_argument('--runrec-cache', default=f'{HERE}/results/human-runrec-maxhp.json')
    ap.add_argument('--public-kd-loop', action='store_true', help='Use proved public curse effects for Knowledge Demon future features')
    a = ap.parse_args()
    if a.public_kd_loop: P['foresight_public_kd_loop'] = True
    files = sorted(glob.glob(f'{REPLAYS}/*.ndjson.gz'))
    if a.max_files: files = files[:a.max_files]
    hdrs = {}
    for f in files:
        with gzip.open(f, 'rt') as fh:
            try: hdrs[f] = json.loads(fh.readline())
            except Exception: pass
    ok = [f for f in files if f in hdrs and accept(hdrs[f])]
    print(f'回放 {len(files)} 个，符合条件（{"/".join(BUILDS)}、单人、标准、无修改器 / 影响玩法的模组、回放格式 v4+）{len(ok)} 个', flush=True)
    seeds = {hdrs[f].get('seed') for f in ok}
    os.makedirs(os.path.dirname(a.runrec_cache), exist_ok=True)
    runrec = runrec_maxhp(seeds, a.runrec_cache)
    print(f'整局记录里找到 {len(set(runrec) & seeds)} / {len(seeds)} 个种子（用来取每层血量上限）', flush=True)
    V = collections.Counter(); n = 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fo:
        for k, f in enumerate(ok):
            recs = process(f, runrec, V)
            for r in recs or []:
                if not r['turns']: continue
                fo.write(json.dumps(r, ensure_ascii=False) + '\n'); n += 1
            if k % 100 == 99: print(f'  {k + 1}/{len(ok)}', flush=True)
    pct = lambda a_, b_: f'{V[a_] / max(V[b_], 1):.1%}（{V[a_]}/{V[b_]}）'
    print(f'写入 {a.out}：{V["combats"]} 场战斗（死亡 {V["died"]}），{V["turns"]} 个回合局面')
    print(f'丢掉：读档 / 重开放弃的那一遍 {V["drop_left"]}、截断 {V["drop_truncated"]}、无结果 {V["drop_noresult"]}；局面里没有活着的主怪 {V["drop_nomain"]}')
    print('核对：')
    print(f'  上限来自整局记录 {V["maxhp_runrec"]}，回退 {V["maxhp_fallback"]}；层号对齐（这一层的遭遇对得上）{pct("floor_align_ok", "floor_align_n")}；'
          f'进场血量 = 整局记录上一层血量 {pct("hp_check_ok", "hp_check_n")}')
    print(f'  格挡（v6+ 的 left 字段）：累加结果一致 {pct("block_check_ok", "block_check_n")}')
    print(f'  意图：v7 回合结束时显示的意图 = 敌方回合实际打出 {pct("intent_check_ok", "intent_check_n")}（v7 用显示值，v4–v6 用实际打出）')
    print(f'  牌组：存档退出时整副牌张数 = 记账 {pct("deck_sync_ok", "deck_sync_n")}（之后以它为准）；按第一次洗牌修正牌组张数的战斗 {V["deck_fix_combats"]}')
    print(f'  抽牌堆：洗牌前抽牌堆记账为 0 {pct("shuffle_pre_draw_zero", "shuffle_n")}（不为 0 的倒推修正这一段的局面）；v7 洗牌后张数 ±1 {pct("ndraw_check_ok", "ndraw_check_n")}；'
          f'记账出现负数 {V["draw_negative"]}')
    print(f'  敌人血量：打死时记账血量 = 这一下掉的血（±1）{pct("kill_hp_ok", "kill_n")}（同名分不清、按总血量守恒修正 {V["kill_pool_fix"]}）；'
          f'没打死却记到 ≤0 {V["hp_nonpos"]}（改记到另一只 {V["hit_reassign"]}）；复活 {V["revive"]}；挨打时补召唤物 {V["spawn_on_hit"]}；补进局面的召唤物 {V["late_enemy"]}')
    print(f'  fut：按实际出招推算 {V["fut_ok"]}，退回意图 {V["fut_fallback"]}')


if __name__ == '__main__':
    main()
