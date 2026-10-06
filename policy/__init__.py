"""决策入口：decide(状态, 记忆, 引擎) → (动作, 参数)。每种决定交给对应的模块，方便单独改、单独测。"""
from params import P
from policy import combat, rewards, pathing, route, rest, shop, events, select, elites


def decide(st, mem, sim):
    """战斗房间里的所有决定（出牌、用药、战斗中的选牌如知识恶魔的诅咒）都先换上这个遭遇的专属参数（kb/encounter_params.json）"""
    import params
    ctx = st.get('context') or {}
    enc = ctx.get('encounter') if ctx.get('room_type') in ('Monster', 'Elite', 'Boss') else None
    with params.scoped(params.for_encounter(enc)):
        return _decide(st, mem, sim)


def _decide(st, mem, sim):
    d = st.get('decision', '')
    if d == 'crystal_sphere':
        from policy import crystal
        return crystal.choose(st)
    route.resolve_unknown(mem, st)                 # 刚进的问号房开出了什么（更新问号概率）
    fw = mem.get('follow')                          # 照着人类赢家的整局决定打（policy/follow.py）；照不了的退回自己的决定
    if fw is not None and d != 'combat_play':
        r = _follow(fw, st, mem, sim, d)
        if r is not None: return r
    if d == 'combat_play':
        elites.note(mem, st)                         # 记下这一幕打过哪个精英（路线 / 选牌预测下一个精英用）
        return combat.decide(st, mem, sim)
    if d == 'event_choice':
        i = events.choose(st, mem)
        if i is None:
            from sim import SimError
            raise SimError(f'No supported player choice in unfinished event: {st.get("event_name") or "unknown"}')
        return 'choose_option', {'option_index': i}
    if d == 'map_select':
        m = sim.get_map()
        c = route.choose(m, st, mem) if P.get('route_mode') == 'ev' else pathing.choose(m, st)
        n = next((n for row in m.get('rows') or [] for n in row if n['col'] == c['col'] and n['row'] == c['row']), {})
        mem['next_is_boss'] = next_is_boss(m, n)
        route.note_room(mem, st, n.get('type'))
        # Public-model search starts from visible inputs in a separate model.
        # Ordinary route selection must never checkpoint the real game.
        return 'select_map_node', {'col': c['col'], 'row': c['row']}
    if d == 'card_reward':
        i = rewards.choose(st, mem)
        return ('skip_card_reward', {}) if i is None else ('select_card_reward', {'card_index': i})
    if d == 'card_select':
        return 'select_cards', {'indices': select.choose(st, mem)}
    if d == 'shop':
        return shop.decide(st, mem)
    if d == 'rest_site':
        return 'choose_option', {'option_index': rest.choose(st, mem)}
    if d == 'bundle_select':
        return 'select_bundle', {'bundle_index': 0}
    return 'proceed', {}


def next_is_boss(m, n):
    """选的这个节点之后是不是 Boss。引擎的地图把 Boss 单独放在 m['boss']（不在 rows 里），
    Boss 前最后一个篝火的 children 指向 Boss 坐标——不是空的。原来用 `not children` 判断，永远是 False，
    篝火的 heal_below_before_boss 从没生效（Codex 发现，梳理表 C03）"""
    kids = n.get('children') or []
    if not kids: return True
    b = m.get('boss') or {}
    types = {(x.get('col'), x.get('row')): x.get('type') for row in m.get('rows') or [] for x in row}
    return all((k.get('col'), k.get('row')) == (b.get('col'), b.get('row')) or types.get((k.get('col'), k.get('row'))) == 'Boss'
               for k in kids)


def _follow(fw, st, mem, sim, d):
    ctx = st.get('context') or {}
    if d == 'map_select':
        m = sim.get_map(); c = fw.route(m, st)
        if c is None: return None
        n = next((n for row in m.get('rows') or [] for n in row if n['col'] == c['col'] and n['row'] == c['row']), {})
        mem['next_is_boss'] = next_is_boss(m, n); route.note_room(mem, st, n.get('type'))
        return 'select_map_node', {'col': c['col'], 'row': c['row']}
    if d == 'card_reward' and ctx.get('room_type') != 'Shop':
        return fw.card_reward(st)
    if d == 'rest_site':
        r = fw.rest(st)
        if r is None: return None
        if r[1] == 'SMITH': mem['select_purpose'] = 'upgrade'
        return 'choose_option', {'option_index': r[0]}
    if d == 'card_select' and ctx.get('room_type') not in ('Monster', 'Elite', 'Boss'):
        purpose = mem.get('select_purpose')
        if purpose in ('upgrade', 'remove'):
            idx = fw.select(st, purpose)
            if idx is not None:
                mem.pop('select_purpose', None); return 'select_cards', {'indices': idx}
        return None
    if d == 'event_choice':
        i = fw.event(st)
        return None if i is None else ('choose_option', {'option_index': i})
    if d == 'shop':
        return fw.shop(st, mem)
    return None
