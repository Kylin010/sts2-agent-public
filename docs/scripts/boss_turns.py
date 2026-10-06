"""第二幕 Boss 研究 · 逐回合还原：人类录像和我们程序的 Boss 战，统一成同一种逐回合记录，方便直接对比。

人类：boss_data.load_fights()（v0.111.0 录像，每场取最后一次尝试；之前放弃重来的尝试单独标 result='retry'）。
我们：agent/results/bdla2-g3-0615.jsonl 里第二幕 Boss 的逐出牌记录（trace 里 d='combat'）。

每场一条记录（dict）：
    src 'human'/'ours'，boss 'crab'/'kd'，result 'win'/'loss'/'retry'，key（录像哈希 / 我们的种子+任务）
    hp_in, maxhp, deck（牌 id，升级加 '+'），relics, potions_in（药水 id）
    turns: 每个「我的回合 + 紧接着的敌方回合」一条：
        n            第几回合
        dmg          我这回合打出的伤害（打在敌人身上的 dmg + 被格挡吃掉的，不含溢出）；dmg_t = 按目标分（CRUSHER / ROCKET / KNOWLEDGE_DEMON）
        dmg_rf       敌方回合里我打出的伤害（火焰屏障、荆棘反伤等）
        blk          我这回合获得的格挡（人类：所有来源；我们：只看得到出牌之间的变化 + 回合开始时已有的）
        blk_card     其中卡牌给的（人类录像 block 事件带 card 的）
        loss         这一整轮实际掉的血（我的回合自伤 + 敌方回合挨打），self_loss = 我自己回合里掉的
        inc          敌方回合打过来的总伤害（被格挡吃掉的也算）；inc_t 按敌人分
        plays        [(牌 id, 升级, 目标)]；pots [(药水 id, 目标)]（我们的记录里药水没有目标）
        hand         人类：这回合抽到的牌；我们：回合开始时的手牌（hand_all = 这回合在手里出现过的所有牌，blk_end = 点结束回合时的格挡）。
                     en = 回合开始的能量（人类只有新版录像有）。plays 的第 4 项 = 是否自动打出（人类录像才有）
        face         回合结束时面朝谁（帝皇蟹；最后一张带目标的牌 / 对敌人用的药水决定；初始面朝火箭）
        alive        回合开始时活着的敌人 → 血量
        moves        敌方回合各敌人的招式 id（只有人类录像有）
    kills      {敌人: 第几回合死的}
    curses     知识恶魔：[(回合, 诅咒 id)]（DISINTEGRATION / MIND_ROT / SLOTH / WASTE_AWAY）
    card_dmg / card_blk / card_n   每张牌（id，不含升级）打出的伤害 / 格挡 / 次数
用法：from boss_turns import load_all；python3 boss_turns.py 自检（打印几场样例）
缓存：BOSS_TURNS_CACHE（默认 /tmp/sts2-boss-turns.pkl）
"""
import json, os, sys, collections, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boss_data

ROOT = '/opt/slay-the-spire-2'
OURS = os.environ.get('OURS_RESULTS', f'{ROOT}/agent/results/bdla2-g3-0615.jsonl')
ENG = f'{ROOT}/sources/spire-codex/data-beta/v0.111.0/eng'
CACHE = os.environ.get('BOSS_TURNS_CACHE', '/tmp/sts2-boss-turns.pkl')
BOSS_KEY = {'KAISER_CRAB_BOSS': 'crab', 'KNOWLEDGE_DEMON_BOSS': 'kd'}
CURSES = {'DISINTEGRATION_POWER': 'DISINTEGRATION', 'MIND_ROT_POWER': 'MIND_ROT', 'SLOTH_POWER': 'SLOTH', 'WASTE_AWAY_POWER': 'WASTE_AWAY'}
ENEMY_NAME = {'Crusher': 'CRUSHER', 'Rocket': 'ROCKET', 'Knowledge Demon': 'KNOWLEDGE_DEMON'}
CRAB = ('CRUSHER', 'ROCKET')


def _name_maps():
    cards = {}
    for c in json.load(open(f'{ENG}/cards.json')):
        if c['name'] not in cards or c.get('color') in ('ironclad',):
            cards[c['name']] = c['id']
    pots = {p['name']: p['id'] for p in json.load(open(f'{ENG}/potions.json'))}
    return cards, pots


CARD_ID, POT_ID = _name_maps()


def new_turn(n):
    return {'n': n, 'dmg': 0, 'dmg_t': collections.Counter(), 'dmg_rf': 0, 'blk': 0, 'blk_card': 0, 'loss': 0, 'self_loss': 0,
            'inc': 0, 'inc_t': collections.Counter(), 'plays': [], 'pots': [], 'face': None, 'alive': {}, 'moves': {}, 'hand': [], 'en': None}


# ———————————————————————— 人类录像 ————————————————————————

def human_record(f, result=None):
    ev = f['ev']
    rec = {'src': 'human', 'boss': BOSS_KEY[f['boss']], 'result': result or f['result'], 'key': f['run'], 'attempts': f.get('attempts', 1),
           'hp_in': f['hp'], 'maxhp': f['maxhp'], 'deck': f['deck'], 'relics': f['relics'], 'potions_in': f['potions'],
           'turns': [], 'kills': {}, 'curses': [], 'card_dmg': collections.Counter(), 'card_blk': collections.Counter(),
           'card_n': collections.Counter()}
    cs = next((e for e in ev if e['t'] == 'combat_start'), None)
    if cs is None: return None
    ehp = {x['id']: x['hp'] for x in cs.get('enemies') or []}
    emax = {x['id']: x.get('max_hp', x['hp']) for x in cs.get('enemies') or []}
    turns = {}
    phase, n = 'player', 1
    face = 'ROCKET'
    pend_tgt = {}
    kd_hp_events = any(e['t'] == 'hp' and e.get('dst') == 'KNOWLEDGE_DEMON' for e in ev)

    def T(k):
        if k not in turns:
            turns[k] = new_turn(k)
            turns[k]['alive'] = {e: h for e, h in ehp.items() if h > 0}
        return turns[k]
    T(1)
    for e in ev:
        t = e['t']
        if t == 'turn':
            phase = e.get('side'); n = e.get('n') or n
            if phase == 'player':
                T(n)['alive'] = {k: h for k, h in ehp.items() if h > 0}
            continue
        if t == 'end_turn' and e.get('side') == 'player':
            T(n)['face'] = face if rec['boss'] == 'crab' else None
            continue
        if t == 'end_turn' and e.get('side') == 'enemy':      # 敌方回合结束后、下一个「turn player」之前的事件（抽牌、回合开始的自动打牌 / 遗物）算下一回合
            phase = 'player'; n = (e.get('n') or n) + 1
            T(n)['alive'] = {k: h for k, h in ehp.items() if h > 0}
            continue
        cur = T(n)
        if t == 'hit':
            src, dst = e.get('src'), e.get('dst')
            amt = (e.get('dmg') or 0) + (e.get('blocked') or 0)
            if src == 'player' and dst not in ('player', None):
                if phase == 'player':
                    cur['dmg'] += amt; cur['dmg_t'][dst] += amt
                else:
                    cur['dmg_rf'] += amt
                rec['card_dmg'][e.get('card') or ('〔反伤〕' if phase != 'player' else '〔无牌来源〕')] += amt
                if dst in ehp: ehp[dst] -= e.get('dmg') or 0
                if e.get('killed') and dst not in rec['kills']:
                    rec['kills'][dst] = n
                    if rec['boss'] == 'crab':
                        other = [k for k in CRAB if k != dst]
                        face = other[0] if other else face
            elif dst == 'player' and src not in ('player', None):
                cur['inc'] += amt; cur['inc_t'][src] += amt
        elif t == 'death':
            tg = e.get('tgt')
            if tg in ehp and tg not in rec['kills']:
                rec['kills'][tg] = n; ehp[tg] = min(ehp[tg], 0)
        elif t == 'block' and e.get('src') == 'player':
            cur['blk'] += e.get('n') or 0
            if e.get('card'):
                cur['blk_card'] += e.get('n') or 0; rec['card_blk'][e['card']] += e.get('n') or 0
        elif t == 'hp' and e.get('dst') in (None, 'player'):
            d = e.get('d') or 0
            if d < 0:
                cur['loss'] -= d
                if phase == 'player': cur['self_loss'] -= d
        elif t == 'hp' and e.get('dst') in ehp:                  # 新版录像：敌人血量变化（回血）
            if (e.get('d') or 0) > 0: ehp[e['dst']] = e.get('hp', ehp[e['dst']])
        elif t == 'move':
            cur['moves'][e.get('src')] = e.get('id')
            if e.get('id') == 'PONDER_MOVE' and 'KNOWLEDGE_DEMON' in ehp and not kd_hp_events:     # 思考：回 30（老版录像没有敌人血量事件）
                ehp['KNOWLEDGE_DEMON'] = min(emax['KNOWLEDGE_DEMON'], ehp['KNOWLEDGE_DEMON'] + 30)
        elif t == 'draw':
            cur['hand'].append(e['id'])              # 人类：这回合抽到的牌（回合开始 + 回合中）
        elif t == 'energy' and e.get('src') == 'turn':
            cur['en'] = e.get('energy')
        elif t == 'play':
            tg = e.get('target')
            cur['plays'].append((e['id'], e.get('up', 0) or 0, tg, bool(e.get('auto'))))
            rec['card_n'][e['id']] += 1
            if rec['boss'] == 'crab' and tg in CRAB and ehp.get(tg, 0) > 0: face = tg
        elif t == 'potion_start':
            pend_tgt[e['id']] = e.get('target')
        elif t == 'potion_used':
            tg = e.get('target') or pend_tgt.pop(e['id'], None)
            cur['pots'].append((e['id'], tg))
            if rec['boss'] == 'crab' and tg in CRAB and ehp.get(tg, 0) > 0: face = tg
        elif t == 'power' and e.get('tgt') == 'IRONCLAD' and e.get('id') in CURSES and (e.get('n') or 0) > 0:
            rec['curses'].append((n, CURSES[e['id']]))
    rec['turns'] = [turns[k] for k in sorted(turns)]
    for tt in rec['turns']:
        if tt['face'] is None and rec['boss'] == 'crab': tt['face'] = face
    return rec


# ———————————————————————— 我们的程序 ————————————————————————

def _foes(x):
    return {ENEMY_NAME.get(f[0], f[0]): {'hp': f[1] or 0, 'blk': f[2] or 0, 'inc': f[3] or 0} for f in x.get('foes') or []}


def ours_records(path=OURS):
    out = []
    for line in open(path):
        r = json.loads(line)
        for cb in r['combats']:
            if cb['act'] != 2 or cb['room'] != 'Boss': continue
            names = set(cb['enemies'])
            boss = 'crab' if names & {'Crusher', 'Rocket'} else 'kd' if 'Knowledge Demon' in names else None
            if boss is None: continue
            fl = cb['floor']
            E = [x for x in r['trace'] if x.get('act') == 2 and x.get('floor') == fl and x.get('d') in ('combat', 'card_select', 'combat_select')]
            last_fight = cb is r['combats'][-1]
            result = 'win' if (not last_fight or r['win']) else 'loss'
            out.append(_our_fight(r, boss, E, result, cb))
    return out


def _our_fight(r, boss, E, result, cb):
    C = [x for x in E if x.get('d') == 'combat']
    rec = {'src': 'ours', 'boss': boss, 'result': result, 'key': f"{r.get('seed')}:{r.get('task')}:{r.get('cand')}", 'cand': r.get('cand'),
           'attempts': 1, 'hp_in': C[0]['hp'] if C else None, 'maxhp': next((x.get('max_hp') for x in E if x.get('max_hp')), None),
           'deck': tuple(r['deck']), 'relics': r['relics'], 'potions_in': [POT_ID.get(p, p) for p in (C[0].get('pots') or [])] if C else [],
           'turns': [], 'kills': {}, 'curses': [], 'card_dmg': collections.Counter(), 'card_blk': collections.Counter(),
           'card_n': collections.Counter(), 'cb': {k: cb.get(k) for k in ('dmg', 'hp', 'rounds', 'potions')}}
    # 知识恶魔的诅咒：card_select 的选项里有诅咒（每次出现两条：card_select 和 combat_select，取 card_select）
    rnd = 0
    for x in E:
        if x.get('d') == 'combat': rnd = x.get('r') or rnd
        if x.get('d') == 'card_select':
            opts = x.get('opts') or []
            if any(o in ('Disintegration', 'Mind Rot', 'Sloth', 'Waste Away') for o in opts):
                idx = int(str((x.get('args') or {}).get('indices', '0')).split(',')[0])
                rec['curses'].append((rnd, CARD_ID.get(opts[idx], opts[idx])))
    by_r = collections.OrderedDict()
    for x in C: by_r.setdefault(x['r'], []).append(x)
    rounds = list(by_r)
    face = 'ROCKET'
    for ri, rn in enumerate(rounds):
        xs = by_r[rn]; tt = new_turn(rn)
        f0 = _foes(xs[0])
        tt['alive'] = {k: v['hp'] for k, v in f0.items() if v['hp'] > 0}
        tt['blk'] = xs[0].get('blk') or 0
        tt['hand'] = [CARD_ID.get(h, h) for h in xs[0].get('hand') or []]; tt['en'] = xs[0].get('en')
        seen = collections.Counter()                          # 这回合在手里出现过的所有牌（含回合中抽到的）
        for x in xs: seen |= collections.Counter(CARD_ID.get(h, h) for h in x.get('hand') or [])
        tt['hand_all'] = list(seen.elements())
        tt['blk_end'] = xs[-1].get('blk') or 0
        for k, v in f0.items(): tt['inc_t'][k] = v['inc']
        tt['inc'] = sum(v['inc'] for v in f0.values())       # 回合开始时显示的意图（含当时朝向下的 ×1.5）
        nxt_first = by_r[rounds[ri + 1]][0] if ri + 1 < len(rounds) else None
        for j, x in enumerate(xs):
            a = x.get('a'); card = CARD_ID.get(x.get('card'), x.get('card'))
            tg = ENEMY_NAME.get(x.get('tgt'), x.get('tgt'))
            if a == 'play_card':
                tt['plays'].append((card, 0, tg)); rec['card_n'][card] += 1
                if boss == 'crab' and tg in CRAB: face = tg
            elif a == 'use_potion':
                tt['pots'].append((POT_ID.get(x.get('potion'), x.get('potion')), tg))
                if boss == 'crab' and tg in CRAB: face = tg
            y = xs[j + 1] if j + 1 < len(xs) else None
            if y is not None:
                fa, fb = _foes(x), _foes(y)
                d = 0
                for k, v in fa.items():
                    w = fb.get(k, {'hp': 0, 'blk': 0})
                    dd = max(0, v['hp'] - w['hp']) + max(0, v['blk'] - w['blk'])
                    d += dd; tt['dmg_t'][k] += dd
                    if w['hp'] <= 0 < v['hp'] and k not in rec['kills']:
                        rec['kills'][k] = rn
                        if boss == 'crab':
                            other = [o for o in CRAB if o != k]; face = other[0]
                tt['dmg'] += d
                if a == 'play_card': rec['card_dmg'][card] += d
                gain = max(0, (y.get('blk') or 0) - (x.get('blk') or 0))
                tt['blk'] += gain
                if a == 'play_card': rec['card_blk'][card] += gain
                if y.get('hp') is not None and x.get('hp') is not None and y['hp'] < x['hp']:
                    tt['self_loss'] += x['hp'] - y['hp']
        last = xs[-1]
        if nxt_first is not None:
            fa, fb = _foes(last), _foes(nxt_first)
            rf = sum(max(0, v['hp'] - fb.get(k, {'hp': 0})['hp']) for k, v in fa.items() if not (boss == 'kd' and rn % 4 == 0))
            tt['dmg_rf'] = rf
            for k, v in fa.items():
                if fb.get(k, {'hp': 0})['hp'] <= 0 < v['hp'] and k not in rec['kills']: rec['kills'][k] = rn
            tt['loss'] = max(0, (xs[0]['hp'] or 0) - (nxt_first['hp'] or 0))
        else:
            fa = _foes(last)
            if result == 'win':                      # 最后一张牌打死了剩下的
                d = sum(v['hp'] + v['blk'] for v in fa.values() if v['hp'] > 0)
                tt['dmg'] += d
                for k, v in fa.items():
                    if v['hp'] > 0: tt['dmg_t'][k] += v['hp'] + v['blk']
                if last.get('a') == 'play_card': rec['card_dmg'][CARD_ID.get(last.get('card'), last.get('card'))] += d
                for k, v in fa.items():
                    if v['hp'] > 0 and k not in rec['kills']: rec['kills'][k] = rn
                tt['loss'] = tt['self_loss']
            else:
                tt['loss'] = xs[0]['hp'] or 0         # 死在这一轮
        tt['face'] = face if boss == 'crab' else None
        rec['turns'].append(tt)
    return rec


def load_all(rebuild=False):
    src_m = max(os.path.getmtime(boss_data.CACHE) if os.path.exists(boss_data.CACHE) else 0, os.path.getmtime(OURS), os.path.getmtime(__file__),
                os.path.getmtime(boss_data.__file__))
    if not rebuild and os.path.exists(CACHE) and os.path.getmtime(CACHE) > src_m:
        with open(CACHE, 'rb') as fh: return pickle.load(fh)
    recs = []
    for f in boss_data.load_fights():
        r = human_record(f)
        if r: recs.append(r)
        for p in f.get('prev') or []:              # 放弃重来的尝试
            if any(e['t'] == 'turn' for e in p['ev']):
                p = dict(p, run=f['run'], attempts=f['attempts'])
                r = human_record(p, result='retry')
                if r: recs.append(r)
    recs += ours_records()
    with open(CACHE, 'wb') as fh: pickle.dump(recs, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return recs


if __name__ == '__main__':
    recs = load_all(rebuild=True)
    c = collections.Counter((r['src'], r['boss'], r['result']) for r in recs)
    for k in sorted(c): print(k, c[k])
    for src in ('human', 'ours'):
        for boss in ('crab', 'kd'):
            r = next(x for x in recs if x['src'] == src and x['boss'] == boss and x['result'] == 'win')
            print(f'== {src} {boss} {r["key"]} hp_in={r["hp_in"]} kills={r["kills"]} curses={r["curses"]}')
            for t in r['turns']:
                print('  ', t['n'], 'dmg', t['dmg'], dict(t['dmg_t']), 'rf', t['dmg_rf'], 'blk', t['blk'], 'loss', t['loss'], 'inc', t['inc'],
                      'face', t['face'], 'alive', t['alive'], 'moves', t['moves'], [p[0] for p in t['plays']], t['pots'])
