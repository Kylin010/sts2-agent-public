"""局面级对照（10/3 claude-value，主线 22:34 布置的 ②：人类当老师）：
在人类回放的每个回合开始局面上调 combat.plan（离线、不推演），和人类实际打的牌比较。

还原的局面（第二幕三个 Boss，同牌组案例 data/bench_*_replay.json 里的回放）：
- 手牌：上一次玩家结束回合之后、本回合第一个动作之前抽到的牌；升级看这张牌后来打出时的 up，没打出的按牌组里是否只有升级版判断
- 卡牌数值：data/engine_card_dicts.json（p15 引擎里每种牌、升级 / 不升级各进一次战斗读到的牌面），
  再按当时的力量 / 敏捷 / 虚弱 / 脆弱、敌人易伤换算 damage_by_target 和 block（引擎预览也是这么算的）
- 能量：我们同一例同一回合 trace 的回合开始能量（遗物相同）；没有就 3
- 玩家：血量（hp 事件）、能力（power 事件按增量累计）；回合开始格挡按 0
- 敌人：血量 = 开场 − 玩家命中 + 知识恶魔 Ponder 回 30；格挡 = 上一个敌方回合获得的；能力按增量累计；
  意图 = 这一回合敌方实际出的招（源码出招表 + 力量，×0.75 敌人虚弱，×1.5 玩家易伤；帝皇蟹背后那只 ×1.5，朝向按上回合最后一个目标）
- 读档重打的回合只留最后一遍
比较：人类本回合从起手手牌里打出的牌（不含自动打出、回合中途抽到的） vs 规划器的最佳组合；
另外查人类那组牌在规划器全部组合里排第几（推演只看前 5 名 + 格挡最多 + 伤害最多）。

用法：python3 tools/replay_turns.py [--boss crab|kd|insat] [--n 例子数] [--json 输出]
"""
import argparse, collections, copy, gzip, json, math, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy import combat
from policy.knowledge import cid
from params import P

R = '/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10/'
CD = json.load(open(f'{HERE}/data/engine_card_dicts.json'))
BOSSES = {
    'crab': ('KAISER_CRAB_BOSS', 'bench_crab_replay.json', 'cv-crab-replay.jsonl'),
    'kd': ('KNOWLEDGE_DEMON_BOSS', 'bench_knowledge_demon_replay.json', 'cv-kd-replay.jsonl'),
    'insat': ('THE_INSATIABLE_BOSS', 'bench_the_insatiable_replay.json', 'cv-insat-replay.jsonl'),
}
NAMES = {'CRUSHER': 'Crusher', 'ROCKET': 'Rocket', 'KNOWLEDGE_DEMON': 'Knowledge Demon', 'THE_INSATIABLE': 'The Insatiable'}
# 出招表（A10，源码）：招式 → (每段伤害, 段数)
MOVES = {'THRASH_MOVE': (14, 1), 'ENLARGING_STRIKE_MOVE': (4, 1), 'BUG_STING_MOVE': (7, 2), 'ADAPT_MOVE': (0, 0), 'GUARDED_STRIKE_MOVE': (14, 1),
         'TARGETING_RETICLE_MOVE': (4, 1), 'PRECISION_BEAM_MOVE': (20, 1), 'CHARGE_UP_MOVE': (0, 0), 'LASER_MOVE': (35, 1), 'RECHARGE_MOVE': (0, 0),
         'CURSE_OF_KNOWLEDGE_MOVE': (0, 0), 'SLAP_MOVE': (18, 1), 'KNOWLEDGE_OVERWHELMING_MOVE': (9, 3), 'PONDER_MOVE': (13, 1),
         'LIQUIFY_GROUND_MOVE': (0, 0), 'LUNGING_BITE_MOVE': (31, 1), 'SALIVATE_MOVE': (0, 0), 'THRASH_MOVE_2': (9, 2)}
INSAT_THRASH = (9, 2)        # 无厌沙虫的 THRASH_MOVE 和帝皇蟹碾碎爪同名，按遭遇区分
POWER_NAME = {'BACK_ATTACK_LEFT_POWER': 'Back Attack', 'BACK_ATTACK_RIGHT_POWER': 'Back Attack', 'CRAB_RAGE_POWER': 'Crab Rage',
              'NO_DRAW_POWER': 'No Draw'}


def pname(pid):
    return POWER_NAME.get(pid) or pid.replace('_POWER', '').replace('_', ' ').title()


def card(cid_up, idx, pw, enemies, epw):
    d = copy.deepcopy(CD.get(cid_up) or CD.get(cid_up.rstrip('+')) or {'id': 'CARD.' + cid_up.rstrip('+'), 'name': cid_up, 'cost': 1,
                                                                          'type': 'Status', 'can_play': False, 'stats': {}})
    d['index'] = idx
    if cid_up.endswith('+'): d['upgraded'] = True
    st = d['stats'] = dict(d.get('stats') or {})
    if d.get('type') == 'Attack' and st.get('damage') is not None:
        per = st['damage'] + pw.get('Strength', 0)
        if pw.get('Weak', 0) > 0: per *= 0.75
        st['damage'] = int(per)
        d['damage_by_target'] = [{'target_index': e['index'], 'name': e['name'],
                                  'damage': int(per * (1.5 if epw[e['_id']].get('Vulnerable', 0) > 0 else 1))} for e in enemies]
    if st.get('block'):
        b = st['block'] + pw.get('Dexterity', 0)
        if pw.get('Frail', 0) > 0: b *= 0.75
        st['block'] = max(0, int(b))
    return d


def our_energy(trace_rows):
    """我们同一例的 trace：每回合开始的能量（取所有场次的众数）"""
    by = collections.defaultdict(collections.Counter)
    for tr in trace_rows:
        first = {}
        for x in tr:
            if x.get('d') == 'combat' and x.get('r') and x['r'] not in first: first[x['r']] = x.get('en')
        for k, v in first.items():
            if v is not None: by[k][v] += 1
    return {k: v.most_common(1)[0][0] for k, v in by.items()}


def turns(path, enc, deck, energy_by_round, hp0=None):
    """逐个玩家回合产出局面（读档重打的回合以最后一遍为准）"""
    ev = [json.loads(l) for l in gzip.open(path, 'rt')]
    i0 = next(i for i, x in enumerate(ev) if x.get('t') == 'combat_start' and x.get('encounter') == enc)
    up_of = {}                                     # 卡牌实例 c → 打出时的 up
    for x in ev[i0:]:
        if x.get('t') == 'combat_end': break
        if x.get('t') == 'play' and x.get('c') is not None: up_of[x['c']] = x.get('up', 0)
    only_up = {d.rstrip('+') for d in deck if d.endswith('+')} - {d for d in deck if not d.endswith('+')}
    out = {}
    enemies = {}; pw = collections.Counter(); epw = collections.defaultdict(collections.Counter); hp = hp0
    hand = {}; cur = None; side = 'player'; rnd = 1; eblock = collections.Counter(); facing = 'ROCKET'; last_tgt = None
    base = None
    for x in ev[i0:]:
        t = x.get('t')
        if t == 'combat_start' and x.get('encounter') == enc:
            b = (x.get('combat_id') or '').split('#')[0]
            if base is None or b != base:
                base = b; enemies = {e['id']: {'hp': e['hp'], 'max': e['max_hp']} for e in x.get('enemies') or []}
            continue
        if t == 'combat_end': break
        if t == 'hp' and 'hp' in x and not x.get('dst'): hp = x['hp']
        elif t == 'power' and x.get('id'):
            if x.get('tgt') == 'IRONCLAD': pw[pname(x['id'])] += x.get('n') or 0
            elif x.get('tgt') in enemies: epw[x['tgt']][pname(x['id'])] += x.get('n') or 0
        elif t == 'hit' and x.get('src') == 'player' and x.get('dst') in enemies: enemies[x['dst']]['hp'] -= x.get('dmg') or 0
        elif t == 'block' and x.get('src') in enemies: eblock[x['src']] += x.get('n') or 0
        elif t == 'draw': hand[x.get('c')] = x['id']
        elif t == 'exhaust' or t == 'discard': hand.pop(x.get('c'), None)
        elif t == 'turn':
            side = x.get('side'); rnd = x.get('n') or rnd
            if side == 'player':
                if cur is not None and cur['round'] < rnd: pass
                live = {k: dict(v) for k, v in enemies.items() if v['hp'] > 0}
                cur = {'round': rnd, 'hp': hp, 'hand': dict(hand), 'pw': dict(pw), 'epw': {k: dict(v) for k, v in epw.items()},
                       'enemies': live, 'eblock': {k: eblock.get(k, 0) for k in live}, 'facing': facing, 'played': [], 'targets': [], 'moves': {}}
                out[rnd] = cur                    # 读档重打：同一回合再来一遍会覆盖
            else:
                eblock = collections.Counter()   # 敌人回合开始格挡清零（之后这回合获得的留到玩家下回合）
        elif t == 'play' and side == 'player' and cur is not None and not x.get('auto'):
            if x.get('c') in cur['hand'] and x.get('c') not in cur.setdefault('_seen', set()):     # 同一张牌被打两次（回响形态等）只算一次
                cur['_seen'].add(x.get('c')); cur['played'].append(x['id'] + ('+' if x.get('up') else '')); cur['targets'].append(x.get('target'))
            if x.get('target') in ('CRUSHER', 'ROCKET'): facing = x['target']
            hand.pop(x.get('c'), None)
        elif t == 'play': hand.pop(x.get('c'), None)
        elif t == 'end_turn' and x.get('side') == 'player': hand = {}
        elif t == 'move' and side == 'enemy' and cur is not None:
            cur['moves'][x.get('src')] = x.get('id')
            if x.get('id') == 'PONDER_MOVE' and x.get('src') in enemies: enemies[x['src']]['hp'] += 30
    for rnd, tr in out.items():
        tr['energy'] = energy_by_round.get(rnd, energy_by_round.get(2, 3))
        tr['cards'] = {c: (cid_ + ('+' if (up_of.get(c) or cid_ in only_up) else '')) for c, cid_ in tr['hand'].items()}
    return [out[k] for k in sorted(out)]


def state(tr, enc):
    order = list(tr['enemies'])
    ens = []
    for n, eid in enumerate(order):
        mv = tr['moves'].get(eid)
        dmg, hits = (INSAT_THRASH if (enc == 'THE_INSATIABLE_BOSS' and mv == 'THRASH_MOVE') else MOVES.get(mv, (0, 0)))
        ep = tr['epw'].get(eid, {})
        intents = []
        if hits:
            per = dmg + ep.get('Strength', 0)
            if ep.get('Weak', 0) > 0: per *= 0.75
            if tr['pw'].get('Vulnerable', 0) > 0: per *= 1.5
            if enc == 'KAISER_CRAB_BOSS' and len(order) == 2 and eid != tr['facing']: per *= 1.5
            intents = [{'type': 'Attack', 'damage': int(per), 'hits': hits}]
        else:
            intents = [{'type': 'Buff'}]
        ens.append({'index': n, '_id': eid, 'name': NAMES.get(eid, eid), 'hp': tr['enemies'][eid]['hp'], 'max_hp': tr['enemies'][eid]['max'],
                    'block': tr['eblock'].get(eid, 0), 'intents': intents,
                    'powers': [{'name': k, 'amount': v} for k, v in ep.items() if v]})
    epw = {e['_id']: tr['epw'].get(e['_id'], {}) for e in ens}
    hand = [card(c_up, k, tr['pw'], ens, epw) for k, c_up in enumerate(tr['cards'].values())]
    return {'decision': 'combat_play', 'round': tr['round'], 'energy': tr['energy'], 'hand': hand, 'enemies': ens,
            'player': {'hp': tr['hp'] or 50, 'max_hp': 80, 'block': 0, 'potions': []},
            'player_powers': [{'name': k, 'amount': v} for k, v in tr['pw'].items() if v],
            'context': {'encounter': enc, 'act': 2, 'floor': 33, 'room_type': 'Boss', 'seed': 'REPLAY'}}


def stats_of(cards_):
    s = collections.Counter()
    for c in cards_:
        d = CD.get(c) or CD.get(c.rstrip('+')) or {}
        st_ = d.get('stats') or {}
        s['blk'] += st_.get('block') or 0
        if d.get('type') == 'Attack': s['dmg'] += (st_.get('damage') or 0) * max(st_.get('hits') or 1, 1)
        s['power'] += d.get('type') == 'Power'
        s['draw'] += bool(st_.get('cards') or st_.get('draw'))
        s['n'] += 1
    return s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--boss', default='crab,kd,insat'); ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--json'); a = ap.parse_args()
    rows = []
    for b in a.boss.split(','):
        enc, cf, rf = BOSSES[b]
        cases = json.load(open(f'{HERE}/data/{cf}'))
        ours = collections.defaultdict(list)
        if os.path.exists(f'{HERE}/results/{rf}'):
            for l in open(f'{HERE}/results/{rf}'):
                r = json.loads(l)
                if r.get('trace'): ours[r['case']].append(r['trace'])
        for k, c in enumerate(cases):
            en = our_energy(ours.get(k, []))
            for tr in turns(R + c['replay'], enc, c['deck'], en, c.get('hp')):
                if not tr['cards'] or not tr['enemies']: continue
                st = state(tr, enc)
                mem = {'crab_facing': 'rocket' if tr['facing'] == 'ROCKET' else 'crusher'}
                try:
                    pool = combat.plan(copy.deepcopy(st), mem, set(), topk=-1)
                    best = combat.plan(copy.deepcopy(st), dict(mem), set(), topk=5)
                except Exception as e:
                    rows.append({'boss': b, 'case': k, 'round': tr['round'], 'error': str(e)[:120]}); continue
                cands = sorted([(sc, tuple(sorted(cid(x) for x in combo))) for sc, combo in pool['pool']], key=lambda t: -t[0])
                ours_best = max(best, key=lambda t: t[0]) if best else (0, [])
                ours_ids = sorted(cid(x) for x, _ in ours_best[1])
                hum_ids = sorted(x.rstrip('+') for x in tr['played'])
                rank = next((i for i, (_, k_) in enumerate(cands) if list(k_) == hum_ids), None)
                in_top = any(sorted(cid(x) for x, _ in seq) == hum_ids for _, seq in best)
                hs, os_ = stats_of(tr['played']), stats_of([cid(x) + ('+' if x.get('upgraded') else '') for x, _ in ours_best[1]])
                inc = sum(combat.intent_damage(e) for e in st['enemies'])
                rows.append({'boss': b, 'case': k, 'round': tr['round'], 'hp': tr['hp'], 'energy': tr['energy'], 'incoming': inc,
                             'hand': list(tr['cards'].values()), 'human': tr['played'], 'ours': [cid(x) for x, _ in ours_best[1]],
                             'same': hum_ids == ours_ids, 'rank': rank, 'n_cands': len(cands), 'in_top': in_top,
                             'h': dict(hs), 'o': dict(os_), 'targets': tr['targets'],
                             'our_targets': [st['enemies'][t]['_id'] if t is not None and t < len(st['enemies']) else None for _, t in ours_best[1]]})
    if a.json: json.dump(rows, open(a.json, 'w'), ensure_ascii=False)
    ok = [r for r in rows if 'error' not in r]
    print(f'回合 {len(rows)}（出错 {len(rows) - len(ok)}）')
    for b in a.boss.split(','):
        v = [r for r in ok if r['boss'] == b]
        if not v: continue
        same = sum(r['same'] for r in v); top = sum(r['in_top'] for r in v); unk = sum(r['rank'] is None for r in v)
        print(f"{b}：{len(v)} 回合；整组一致 {same / len(v):.0%}；人类那组在推演候选里 {top / len(v):.0%}；规划器根本没枚举到 {unk / len(v):.0%}")
        d = lambda k: sum(r['h'].get(k, 0) - r['o'].get(k, 0) for r in v if not r['same']) / max(1, sum(not r['same'] for r in v))
        print(f"   不一致的回合里，人类 − 我们：格挡 {d('blk'):+.1f}  伤害 {d('dmg'):+.1f}  能力牌 {d('power'):+.2f}  张数 {d('n'):+.2f}")


if __name__ == '__main__':
    main()
