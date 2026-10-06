"""选牌界面（card_select）：要选几张、选来干什么（消耗 / 删除 / 升级 / 拿牌 / 知识恶魔的诅咒），从上下文推断。"""
from params import P
from policy.knowledge import cid, card_score, worst_first, best_upgrade, EXHAUST_PICKERS


def choose(st, mem):
    cards = st.get('cards') or []
    ids = [cid(c) for c in cards]
    ctx = st.get('context') or {}
    if any(i in P['curse_order'] for i in ids):      # 知识恶魔的「知识诅咒」
        smart = kd_curse(st, ids) if P.get('kd_curse_smart', True) else None
        if smart is not None: return str(next(c['index'] for c in cards if cid(c) == smart))
        rank = {k: n for n, k in enumerate(P['curse_order'])}
        return str(min(cards, key=lambda c: rank.get(cid(c), 99))['index'])
    n = min(max(st.get('min_select') or 1, 1), len(cards))
    purpose = mem.pop('select_purpose', None)
    if purpose is None:
        if ctx.get('room_type') in ('Monster', 'Elite', 'Boss'):
            last = mem.get('last_card')
            if mem.get('plays_this_turn', 0) == 0: last = 'BURNING_PACT'      # 回合开始的选牌（烘焙手套）：消耗最差的
            purpose = 'exhaust' if last in EXHAUST_PICKERS else 'upgrade' if last == 'ARMAMENTS' else 'best'
        else:
            t = mem.get('event_text', '')
            purpose = ('remove' if any(w in t for w in ('Remove', 'Transform', 'remove', 'transform'))
                       else 'upgrade' if ('pgrade' in t or 'nchant' in t) else 'best')
    if purpose in ('exhaust', 'remove'): order = worst_first(cards)
    elif purpose == 'upgrade':
        order = best_upgrade(cards, ctx.get('act', 2))
        if n == 1 and ctx.get('room_type') not in ('Monster', 'Elite', 'Boss') and order:     # 篝火升级哪张：交给学习层（底分按原来的排序）
            from policy import learn
            base = [-k for k in range(len(order[:6]))]
            if P.get('simeval_upgrade') and len(order) > 1 and st.get('player'):
                # 模拟实打选升级（10/3）：前几名候选各升级一张，拿去打本幕 / 下一幕的 Boss 和精英，比掉血
                from policy import simeval
                cands = order[:P.get('simeval_upgrade_k', 4)]
                deck0 = simeval.deck_ids(st); decks = []
                for c in cands:
                    d = list(deck0); i = cid(c)
                    if i in d: d[d.index(i)] = i + '+'
                    decks.append(d)
                sc = simeval.eval_decks(st, decks, tag='upg')
                base = [v / P['simeval_pick_scale'] + P['simeval_prior_w'] * b for v, b in zip(sc, base[:len(cands)])] + base[len(cands):]
            c = learn.pick('upg', [(c, base[k], learn.feats('upg', cid(c), st)) for k, c in enumerate(order[:6])], st, mem)
            return str(c['index'])
    else: order = sorted(cards, key=lambda c: -card_score(cid(c), ctx.get('act', 1)))
    return ','.join(str(c['index']) for c in order[:n])


AUTO_PLAY = {'HELLRAISER', 'STAMPEDE', 'HAVOC'}
EXTRA_ENERGY = {'PYRE', 'OFFERING', 'BLOODLETTING'}


def kd_curse(st, ids):
    """知识恶魔三次二选一（研究 12 号 2.3）：按牌组挑。返回要选的诅咒 id；不认识的组合返回 None
    ① 瓦解 6 / 心灵腐化：靠过牌和 0 费连打的牌组选瓦解，否则心灵腐化
    ② 瓦解 7 / 懒惰（每回合最多 3 张）：3 能量、没有 0 费 / 自动打牌 / 额外能量的牌组懒惰几乎免费，否则瓦解
    ③ 瓦解 8 / 衰朽（能量 −1）：能量多（薪火之源等）选衰朽，否则瓦解
    有撕裂 / 狱火：瓦解（每回合末掉血还触发它们）"""
    from policy import kb
    deck = [str(c.get('id', '')).replace('CARD.', '') for c in (st.get('player') or {}).get('deck') or []]
    real = [d for d in deck if kb.card(d).get('type') not in ('Curse', 'Status')]
    zero = sum(1 for d in real if kb.card(d).get('cost') == 0)
    draw = sum(1 for d in real if 'draw' in kb.tags(d))
    auto = sum(1 for d in real if d in AUTO_PLAY); energy = sum(1 for d in real if d in EXTRA_ENERGY)
    opts = set(ids)
    if 'DISINTEGRATION' in opts and ({'RUPTURE', 'INFERNO'} & set(real)): return 'DISINTEGRATION'
    if opts >= {'DISINTEGRATION', 'MIND_ROT'}:
        return 'DISINTEGRATION' if zero >= 2 or draw >= 3 else 'MIND_ROT'
    if opts >= {'DISINTEGRATION', 'SLOTH'}:
        return 'DISINTEGRATION' if zero >= 1 or auto or energy else 'SLOTH'
    if opts >= {'DISINTEGRATION', 'WASTE_AWAY'}:
        return 'WASTE_AWAY' if energy >= 2 or 'PYRE' in real else 'DISINTEGRATION'
    return None
