"""用模拟实打来评估整局决策。

问题：选牌 / 打不打精英 / 休息还是升级，原来靠模型和经验值估「这副牌够不够强」，估不准（种子 1 第二幕连燃烧都跳过）。
做法：每个选项变成一副具体的牌组，在另一个引擎进程里拿它实打这一幕的 Boss（地图上公开显示）和这一幕的精英池，
      看平均掉多少血、死几次，选最好的。
公平：用和本局无关的随机种子开新局（不偷看本局真实的后续），所有选项用同一批种子（配对比较，差别更准）。
用法：eval_decks(st, [牌组1, 牌组2, ...]) → 每副牌的分（越大越好，单位≈每场少掉的血）
"""
import json, os, random, time
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = json.load(open(f'{HERE}/kb/rules.json'))['acts']
ACT_KEY = {1: 'OVERGROWTH', 2: 'HIVE', 3: 'GLORY'}           # sts2-cli 第一幕永远是密林
STATS = {'calls': 0, 'fights': 0, 'sec': 0.0}
_BASE = {}                                   # 底档缓存：(种子, 遗物, 血量) → 存档文件
DEBUG = os.environ.get('STS2_SIMEVAL_DEBUG') == '1'


def _engine():
    from sim import aux
    return aux()                    # 和推演共用每个进程的第二个引擎（sim.aux），真实对局的引擎不碰


def path(k):
    return f'/tmp/sts2-eval-{os.getpid()}-{k}.json'


def deck_ids(st):
    return [str(c.get('id', '')).replace('CARD.', '') + ('+' if c.get('upgraded') else '') for c in (st.get('player') or {}).get('deck') or []]


def encounters(st):
    """要实打的遭遇和权重：这一幕的 Boss（地图上公开）+ 精英池；不是最后一幕时再加下一幕的 Boss 池和精英池（「战未来」，
    下一幕的 Boss 还没公开，三个都算、平分权重）。权重比例见 simeval_boss_w / simeval_next_w"""
    ctx = st.get('context') or {}; act = min(max(int(ctx.get('act') or 1), 1), 3)
    key = ACT_KEY[act]
    if P.get('simeval_act_fix', False) and str(ctx.get('act_name') or '').upper() in RULES:
        # 10/4：补丁 17 起第一幕可能是暗港，原来写死「第一幕 = 密林」——暗港局的选牌一直在拿密林的精英实打（Boss 用的是对的）
        key = str(ctx['act_name']).upper()
    a = RULES[key]; bw = P['simeval_boss_w']; nw = P['simeval_next_w'] if act < 3 else 0.0
    boss = (ctx.get('boss') or {}).get('id')
    out = [(boss, (1 - nw) * bw)] if boss else []
    els = [x['encounter'] for x in a.get('elites') or []]
    out += [(e, (1 - nw) * (1 - bw) / len(els)) for e in els]
    if nw:
        b = RULES[ACT_KEY[act + 1]]
        bs = [x['encounter'] if isinstance(x, dict) else x for x in b.get('bosses') or []]
        ne = [x['encounter'] for x in b.get('elites') or []]
        out += [(e, nw * bw / len(bs)) for e in bs] + [(e, nw * (1 - bw) / len(ne)) for e in ne]
    return out


def _fight(s, enc, mem_sets):
    import run
    st = s.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': enc})
    for _ in range(5):                                        # 开战时的选牌（遗物触发）照常处理
        if st.get('decision') in ('card_select', 'card_reward'):
            import policy
            a, ar = policy.decide(st, {}, s); st = s.act(a, **ar)
    if st.get('decision') != 'combat_play': return None
    hp0 = (st.get('player') or {}).get('hp', 0)
    r = run.drive(s, st, {}, combat_only=True, max_steps=2500, max_sec=P['simeval_fight_sec'])
    c = (r.get('combats') or [{}])[0]
    died = not r.get('win')
    return min(hp0, c.get('dmg') or 0) + (P['simeval_death'] if died else 0)


def eval_decks(st, decks, tag=''):
    """每副牌在同一批种子、同一批遭遇上实打，返回分数列表（−加权平均掉血，死了另加罚分）"""
    import params
    from sim import SimError
    t0 = time.time(); STATS['calls'] += 1
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    encs = encounters(st)
    # 同一幕里的所有评估用同一批种子：底档可以缓存，各次决定之间也可比。
    # 种子只由看得见的信息（第几幕、章节、本幕 Boss）算，不碰原始种子
    rng = random.Random(str((ctx.get('act'), ctx.get('act_name'), (ctx.get('boss') or {}).get('id'))))
    seeds = [f'EV{rng.randrange(10 ** 9)}' for _ in range(P['simeval_samples'])]
    hp = mx = P['simeval_hp'] or pl.get('max_hp', 80)            # 用足够高的血量比「打赢要掉多少血」（按当前血量比，大家都会死，看不出差别）
    relics = [str(r.get('id', '')).replace('RELIC.', '') for r in pl.get('relics') or []]
    potions = [str(p.get('id', '')).replace('POTION.', '') for p in pl.get('potions') or [] if p and p.get('id')]
    tot = [0.0] * len(decks); wsum = [0.0] * len(decks)
    with params.scoped({'search_on': False, 'learn_explore': False, 'simeval_pick': False, 'simeval_route': False}):   # 实打里面不再嵌套实打 / 推演
        s = _engine()
        for k, sd in enumerate(seeds):                          # 每个种子一个底档（遗物 / 血量），存档读档让遗物完整初始化；按「种子 + 遗物」缓存
            bkey = (sd, tuple(relics), hp, mx)
            if bkey not in _BASE or not os.path.exists(_BASE[bkey]):
                try:
                    s.start(sd, ascension=10)
                    s.send({'cmd': 'set_player', 'hp': hp, 'max_hp': mx, 'relics': relics, 'deck': decks[0]})
                    fp = path(f'{k}-{len(_BASE)}'); s.send({'cmd': 'write_continue_save', 'path': fp})
                    if len(_BASE) > 50:
                        for v in _BASE.values():
                            try: os.remove(v)
                            except OSError: pass
                        _BASE.clear()
                    _BASE[bkey] = fp
                except SimError:
                    s.broken = True; s = _engine(); continue
            for i, d in enumerate(decks):
                for enc, w in encs:
                    if not enc: continue
                    try:
                        s.send({'cmd': 'load_save', 'path': _BASE[bkey]})
                        sp = {'cmd': 'set_player', 'deck': d}
                        if potions: sp['potions'] = potions
                        s.send(sp)
                        v = _fight(s, enc, None)
                    except SimError:
                        s.broken = True; s = _engine(); v = None
                    if v is None: continue
                    STATS['fights'] += 1
                    if DEBUG: print(f'      {tag} 牌组{i} 种子{k} {enc}: {v}')
                    tot[i] += w * v; wsum[i] += w
    STATS['sec'] += time.time() - t0
    return [-(t / ws) if ws else -1e9 for t, ws in zip(tot, wsum)]


_DD = {}


def deck_damage(st):
    """当前牌组打这一幕精英池 / Boss 平均掉多少血（实打，按牌组 + 遗物缓存，牌组没变就不重算）。给路线算风险用"""
    pl = st.get('player') or {}; ctx = st.get('context') or {}; act = min(max(int(ctx.get('act') or 1), 1), 3)
    deck = deck_ids(st)
    key = (act, tuple(sorted(deck)), tuple(sorted(str(r.get('id')) for r in pl.get('relics') or [])))
    if key in _DD: return _DD[key]
    a = RULES[ACT_KEY[act]]; boss = (ctx.get('boss') or {}).get('id')
    out = {}
    with __import__('params').scoped({'simeval_next_w': 0.0}):
        for kind, encs in (('elite', [x['encounter'] for x in a.get('elites') or []]), ('boss', [boss] if boss else [])):
            if not encs: continue
            vals = []
            for e in encs:
                st2 = dict(st, context=dict(ctx, boss={'id': e}))
                with __import__('params').scoped({'simeval_boss_w': 1.0}):
                    vals.append(-eval_decks(st2, [deck], tag=f'dd-{kind}')[0])
            out[kind] = sum(vals) / len(vals)
    _DD.clear() if len(_DD) > 200 else None
    _DD[key] = out
    return out


def boss_losses(st, deck, n=None, tag='boss'):
    """这副牌打本幕 Boss（地图上公开）各种子的掉血列表（用 simeval_hp 的高血量量「打赢要掉多少血」，死了另加罚分）。
    种子只由看得见的信息算（第几幕、章节、Boss），和 eval_decks 同一套；篝火 Boss 账（rest_boss_sim）用"""
    import params
    from sim import SimError
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    boss = (ctx.get('boss') or {}).get('id')
    if not boss: return []
    n = n or P.get('rest_sim_samples', 6)
    rng = random.Random(str((ctx.get('act'), ctx.get('act_name'), boss, 'rest')))
    seeds = [f'RB{rng.randrange(10 ** 9)}' for _ in range(n)]
    hp = mx = P['simeval_hp'] or pl.get('max_hp', 80)
    relics = [str(r.get('id', '')).replace('RELIC.', '') for r in pl.get('relics') or []]
    potions = [str(p.get('id', '')).replace('POTION.', '') for p in pl.get('potions') or [] if p and p.get('id')]
    out = []; t0 = time.time()
    with params.scoped({'search_on': False, 'learn_explore': False, 'simeval_pick': False, 'simeval_route': False}):
        s = _engine()
        for k, sd in enumerate(seeds):
            try:
                s.start(sd, ascension=10)
                sp = {'cmd': 'set_player', 'hp': hp, 'max_hp': mx, 'relics': relics, 'deck': deck}
                if potions: sp['potions'] = potions
                s.send(sp)
                v = _fight(s, boss, None)
            except SimError:
                s.broken = True; s = _engine(); v = None
            if v is not None: out.append(v); STATS['fights'] += 1
    STATS['sec'] += time.time() - t0
    return out


def boss_runs(st, deck, hp, n=None, tag='boss'):
    """这副牌带 hp 血（上限照真实的）打本幕 Boss，各种子的 (赢没赢, 剩多少血)。按真实血量打——
    用 200 血量掉血不行：血多时规划器不防守，掉血被高估成 80~180（篝火 Boss 账第一版的冒烟发现）"""
    import params, run
    from sim import SimError
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    boss = (ctx.get('boss') or {}).get('id')
    if not boss or hp <= 0: return []
    n = n or P.get('rest_sim_samples', 6)
    rng = random.Random(str((ctx.get('act'), ctx.get('act_name'), boss, 'rest')))
    seeds = [f'RB{rng.randrange(10 ** 9)}' for _ in range(n)]
    mx = pl.get('max_hp', 80)
    relics = [str(r.get('id', '')).replace('RELIC.', '') for r in pl.get('relics') or []]
    potions = [str(p.get('id', '')).replace('POTION.', '') for p in pl.get('potions') or [] if p and p.get('id')]
    out = []; t0 = time.time()
    with params.scoped({'search_on': False, 'learn_explore': False, 'simeval_pick': False, 'simeval_route': False}):
        s = _engine()
        for sd in seeds:
            try:
                s.start(sd, ascension=10)
                sp = {'cmd': 'set_player', 'hp': int(hp), 'max_hp': mx, 'relics': relics, 'deck': deck}
                if potions: sp['potions'] = potions
                s.send(sp)
                st0 = s.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': boss})
                for _ in range(5):
                    if st0.get('decision') in ('card_select', 'card_reward'):
                        import policy
                        a, ar = policy.decide(st0, {}, s); st0 = s.act(a, **ar)
                if st0.get('decision') != 'combat_play': continue
                r = run.drive(s, st0, {}, combat_only=True, max_steps=2500, max_sec=P['simeval_fight_sec'])
                c = (r.get('combats') or [{}])[0]
                out.append((bool(r.get('win')), max(0, int(hp) - (c.get('dmg') or 0)) if r.get('win') else 0)); STATS['fights'] += 1
            except SimError:
                s.broken = True; s = _engine()
    STATS['sec'] += time.time() - t0
    return out
