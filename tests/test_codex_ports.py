"""移植 Codex 发现的 bug 的离线测试（docs/Codex发现梳理.md 表一的编号）。

不起引擎，直接拿手写的公开状态喂给策略函数，核对数值。运行：
    cd <仓库根目录> && python3 tests/test_codex_ports.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._gamedata import require_kb; require_kb(__name__)  # noqa: E402

from params import P  # noqa: E402
P['cv_weight'] = 0.0          # 战斗估值模型会叠一层学出来的修正，测试只看规则本身
P['imit_w'] = 0.0
from policy import combat, longterm  # noqa: E402


# ---------- 造局面的小工具 ----------
def card(cid, idx, typ='Attack', cost=1, dmg=None, block=None, target='AnyEnemy', n_enemies=1, stats=None, by_target=None, **kw):
    c = {'id': f'CARD.{cid}', 'index': idx, 'name': cid, 'type': typ, 'cost': cost, 'can_play': True, 'target_type': target}
    st = dict(stats or {})
    if dmg is not None: st['damage'] = dmg
    if block is not None: st['block'] = block
    c['stats'] = st or None
    if typ == 'Attack' and dmg is not None:
        c['damage_by_target'] = by_target or [{'target_index': i, 'damage': dmg} for i in range(n_enemies)]
    c.update(kw)
    return c


def enemy(idx, hp, atk=0, hits=1, powers=None, name='Test Dummy', block=0):
    intents = [{'type': 'Attack', 'damage': atk, **({'hits': hits} if hits > 1 else {})}] if atk else [{'type': 'Buff'}]
    return {'index': idx, 'name': name, 'hp': hp, 'max_hp': hp, 'block': block, 'intents': intents,
            'powers': [{'name': n, 'amount': a} for n, a in (powers or {}).items()] or None}


def state(hand, enemies, energy=3, hp=60, max_hp=80, block=0, relics=None, potions=None, player_powers=None, rnd=1):
    return {'decision': 'combat_play', 'round': rnd, 'energy': energy, 'hand': hand, 'enemies': enemies,
            'context': {'act': 1, 'floor': 3, 'room_type': 'Monster'},
            'player': {'hp': hp, 'max_hp': max_hp, 'block': block, 'deck': [],
                       'relics': [{'id': k, 'counter': v[0], 'status': v[1]} for k, v in (relics or {}).items()],
                       'potions': potions or []},
            'player_powers': [{'name': n, 'amount': a} for n, a in (player_powers or {}).items()] or None}


def ctx_of(st, mem=None):
    """拿到 plan() 里建好的 ctx（topk=-1 会把 ctx 原样返回）"""
    return combat.plan(st, mem if mem is not None else {}, set(), topk=-1)['ctx']


def foe_loss(combo, st):
    """这组牌让每个敌人掉多少血（规划器自己的估算，取最优的那种目标分配）"""
    d = {}
    combat.evaluate(tuple(combo), ctx_of(st), detail=d)
    return d['lost']


# ---------- C01 甲虫汁不是永久药水 ----------
def test_c01_beetle_juice_not_permanent():
    st = state([], [enemy(0, 30, 6), enemy(1, 30, 6)], potions=[{'index': 0, 'name': 'Beetle Juice', 'target_type': 'AnyEnemy'}])
    assert longterm.permanent_potion(st) is None
    st['player']['potions'] = [None, {'index': 1, 'name': 'Fruit Juice', 'target_type': 'Self'}]
    assert longterm.permanent_potion(st)['index'] == 1
    st['player']['potions'] = [{'index': 0, 'name': 'Potion of Capacity', 'target_type': 'Self'}]
    assert longterm.permanent_potion(st)['index'] == 0


def test_c01_beetle_juice_turn_plays_cards():
    """多个敌人、手里有打击、身上有甲虫汁：不该一开局就（不带目标）喝甲虫汁"""
    hand = [card('STRIKE_IRONCLAD', 0, dmg=6, n_enemies=2), card('DEFEND_IRONCLAD', 1, typ='Skill', block=5, target='Self')]
    st = state(hand, [enemy(0, 30, 6), enemy(1, 30, 6)], potions=[{'index': 0, 'name': 'Beetle Juice', 'target_type': 'AnyEnemy'}])
    a, args = combat.decide(st, {})
    assert not (a == 'use_potion' and 'target_index' not in args), (a, args)


# ---------- C02 痛击类自己吃不到自己上的易伤 ----------
def test_c02_bash_alone_no_self_vuln():
    bash = card('BASH', 0, cost=2, dmg=8)
    st = state([bash], [enemy(0, 40, 10)])
    assert foe_loss([bash], st)[0] == 8


def test_c02_bash_then_strike_gets_vuln():
    bash = card('BASH', 0, cost=2, dmg=8); strike = card('STRIKE_IRONCLAD', 1, dmg=6)
    st = state([bash, strike], [enemy(0, 40, 10)])
    assert foe_loss([bash, strike], st)[0] == 8 + 9


def test_c02_thunderclap_aoe():
    tc = card('THUNDERCLAP', 0, dmg=4, target='AllEnemies', n_enemies=2)
    st = state([tc], [enemy(0, 30, 5), enemy(1, 30, 5)])
    assert foe_loss([tc], st) == {0: 4, 1: 4}


def test_c02_already_vulnerable_uses_preview():
    """敌人已经有易伤：引擎预览已含 ×1.5（8 → 12），不再乘"""
    bash = card('BASH', 0, cost=2, dmg=12)
    st = state([bash], [enemy(0, 40, 10, powers={'Vulnerable': 1})])
    assert foe_loss([bash], st)[0] == 12


def test_c02_no_false_kill():
    """敌人 10 血：痛击只打 8，打不死，它的 10 点攻击要算进来（原来算成 12 伤「打死了」）"""
    bash = card('BASH', 0, cost=2, dmg=8)
    st = state([bash], [enemy(0, 10, 10)])
    assert foe_loss([bash], st)[0] == 8


# ---------- C03 Boss 前篝火 ----------
def _map():
    """三层小地图：第 0 层两个怪物房 → 第 1 层篝火（指向 Boss）和问号（指向第 2 层商店）；Boss 在 m['boss']，不在 rows 里"""
    rows = [[{'col': 0, 'row': 0, 'type': 'Monster', 'children': [{'col': 0, 'row': 1}]},
             {'col': 1, 'row': 0, 'type': 'Monster', 'children': [{'col': 1, 'row': 1}]}],
            [{'col': 0, 'row': 1, 'type': 'RestSite', 'children': [{'col': 3, 'row': 3}]},
             {'col': 1, 'row': 1, 'type': 'Unknown', 'children': [{'col': 1, 'row': 2}]}],
            [{'col': 1, 'row': 2, 'type': 'Shop', 'children': [{'col': 3, 'row': 3}]}]]
    return {'rows': rows, 'boss': {'col': 3, 'row': 3, 'type': 'Boss'}}


def test_c03_next_is_boss():
    import policy
    m = _map(); n = {(x['col'], x['row']): x for row in m['rows'] for x in row}
    assert policy.next_is_boss(m, n[(0, 1)]) is True          # 篝火 → Boss
    assert policy.next_is_boss(m, n[(1, 1)]) is False         # 问号 → 商店
    assert policy.next_is_boss(m, n[(0, 0)]) is False


def test_c03_rest_heals_before_boss():
    """Boss 前篝火、血 70%（< heal_below_before_boss 0.75）：规则应选回血"""
    from policy import rest
    st = {'decision': 'rest_site', 'context': {'act': 1, 'floor': 15},
          'player': {'hp': 56, 'max_hp': 80, 'deck': []},
          'options': [{'index': 0, 'option_id': 'HEAL', 'is_enabled': True}, {'index': 1, 'option_id': 'SMITH', 'is_enabled': True}]}
    assert rest._rule(st, {'next_is_boss': True}) == 0
    assert rest._rule(st, {'next_is_boss': False}) == 1


# ---------- C04 X 费最后打 ----------
def test_c04_whirlwind_after_strike():
    """旋风斩在手牌第一个、打击第二个，3 能量：应该先打打击（再用剩下 2 能量旋风斩），而不是旋风斩先把能量花光"""
    ww = card('WHIRLWIND', 0, cost=0, dmg=5, target='AllEnemies', by_target=[{'target_index': 0, 'damage': 5, 'repeat': 3, 'total_damage': 15}])
    sk = card('STRIKE_IRONCLAD', 1, dmg=6)
    st = state([ww, sk], [enemy(0, 60, 5)])
    assert foe_loss([ww, sk], st)[0] == 6 + 5 * 2
    c, _ = combat.plan(st, {}, set())
    assert combat.cid(c) == 'STRIKE_IRONCLAD', combat.cid(c)


def test_c04_volley_is_x_cost():
    """齐射是 X 费（引擎报 0）：和打击一起打，段数 = 打击之后剩下的 2 能量"""
    vo = card('VOLLEY', 0, cost=0, dmg=10, target='RandomEnemy')
    sk = card('STRIKE_IRONCLAD', 1, dmg=6)
    st = state([vo, sk], [enemy(0, 60, 5)])
    assert foe_loss([vo, sk], st)[0] == 6 + 10 * 2
    assert foe_loss([vo], st)[0] == 10 * 3
    assert combat.ORDER(vo) > combat.ORDER(sk)


# ---------- C05 力量攻击 / 无情猛攻先打 ----------
def test_c05_setup_strike_first():
    sk = card('STRIKE_IRONCLAD', 0, dmg=6); ss = card('SETUP_STRIKE', 1, dmg=7)
    st = state([sk, ss], [enemy(0, 60, 5)], energy=2)
    assert foe_loss([sk, ss], st)[0] == 7 + 6 + 3
    c, _ = combat.plan(st, {}, set())
    assert combat.cid(c) == 'SETUP_STRIKE', combat.cid(c)


def test_c05_bash_before_setup_strike_no_strength():
    """痛击（易伤，排在前面）先打：吃不到整顿打击的 +3；整顿打击吃到痛击的易伤"""
    bash = card('BASH', 0, cost=2, dmg=8); ss = card('SETUP_STRIKE', 1, dmg=7)
    st = state([bash, ss], [enemy(0, 60, 5)], energy=3)
    assert abs(foe_loss([bash, ss], st)[0] - (8 + 7 * 1.5)) < 1e-6


def test_c05_unrelenting_first():
    sk = card('STRIKE_IRONCLAD', 0, dmg=6); un = card('UNRELENTING', 1, cost=2, dmg=14)
    st = state([sk, un], [enemy(0, 60, 5)], energy=2)
    c, _ = combat.plan(st, {}, set())
    assert combat.cid(c) == 'UNRELENTING', combat.cid(c)


# ---------- C06 恶魔之焰段数 ----------
def test_c06_fiend_fire_hits_rest_of_hand():
    ff = card('FIEND_FIRE', 0, cost=2, dmg=7)
    sk = card('STRIKE_IRONCLAD', 1, dmg=6)
    d1 = card('DEFEND_IRONCLAD', 2, typ='Skill', block=5, target='Self')
    d2 = card('DEFEND_IRONCLAD', 3, typ='Skill', block=5, target='Self')
    st = state([ff, sk, d1, d2], [enemy(0, 80, 5)], energy=3)
    assert foe_loss([ff], st)[0] == 7 * 3                 # 剩 3 张
    assert foe_loss([ff, sk], st)[0] == 6 + 7 * 2         # 打击先打，剩 2 张
    assert combat.ORDER(ff) > combat.ORDER(sk) and combat.ORDER(ff) > combat.ORDER(d1)


# ---------- C07 动态段数 ----------
def test_c07_tear_asunder_calculated_hits():
    ta = card('TEAR_ASUNDER', 0, cost=2, dmg=5, stats={'calculatedhits': 4, 'repeat': 1})
    st = state([ta], [enemy(0, 80, 5)])
    assert foe_loss([ta], st)[0] == 5 * 4


def test_c07_dismantle_vulnerable_two_hits():
    """目标已有易伤：引擎给 repeat=2、单段 12"""
    dm = card('DISMANTLE', 0, dmg=12, by_target=[{'target_index': 0, 'damage': 12, 'repeat': 2, 'total_damage': 24}])
    st = state([dm], [enemy(0, 80, 5, powers={'Vulnerable': 2})])
    assert foe_loss([dm], st)[0] == 24


def test_c07_bash_then_dismantle():
    """同组先痛击上易伤，拆解吃到易伤也变 2 段：8 + 12×2"""
    bash = card('BASH', 0, cost=2, dmg=8); dm = card('DISMANTLE', 1, dmg=8)
    st = state([bash, dm], [enemy(0, 80, 5)])
    assert foe_loss([bash, dm], st)[0] == 8 + 12 * 2


# ---------- C08 契约终结不抽牌 ----------
def test_c08_pacts_end_no_draw():
    from policy import knowledge
    assert 'PACTS_END' not in knowledge.DRAW
    assert knowledge.DRAW.get('POMMEL_STRIKE') == 1


# ---------- C09 能量时机 ----------
def test_c09_drum_no_immediate_energy():
    from policy import knowledge
    for k in ('DRUM_OF_BATTLE', 'PYRE', 'OUTMANEUVER', 'RELAX'): assert k not in knowledge.ENERGY, k
    assert knowledge.ENERGY.get('BLOODLETTING') == 2
    drum = card('DRUM_OF_BATTLE', 0, typ='Skill', cost=1, target='Self', stats={'cards': 2, 'energy': 2})
    s1 = card('STRIKE_IRONCLAD', 1, dmg=6); s2 = card('STRIKE_IRONCLAD', 2, dmg=6)
    st = state([drum, s1, s2], [enemy(0, 80, 5)], energy=2)
    assert combat.evaluate((drum, s1, s2), ctx_of(st)) is None          # 2 能量付不起 3 张
    st = state([drum, s1, s2], [enemy(0, 80, 5)], energy=2, player_powers={'Corruption': 1})
    drum['cost'] = 0
    assert combat.evaluate((drum, s1, s2), ctx_of(st)) is not None      # 腐化：战鼓 0 费、打出即消耗 +2


# ---------- C10 战斗已结束的组合不算「以后」的分 ----------
def test_c10_no_offering_on_kill_turn():
    sk = card('STRIKE_IRONCLAD', 0, dmg=6)
    of = card('OFFERING', 1, typ='Skill', cost=0, target='Self', keywords=['Exhaust'])
    st = state([sk, of], [enemy(0, 5, 10)], energy=1)
    ctx = ctx_of(st)
    assert combat.evaluate((sk,), ctx) > combat.evaluate((sk, of), ctx)
    c, _ = combat.plan(st, {}, set())
    assert combat.cid(c) == 'STRIKE_IRONCLAD'


def test_c10_burn_ignored_when_fight_ends():
    sk = card('STRIKE_IRONCLAD', 0, dmg=6)
    burn = card('BURN', 1, typ='Status', cost=0, target='Self', stats={'damage': 2}); burn['can_play'] = False
    a = state([sk], [enemy(0, 5, 10)]); b = state([sk, burn], [enemy(0, 5, 10)])
    assert abs(combat.evaluate((sk,), ctx_of(a)) - combat.evaluate((sk,), ctx_of(b))) < 1e-6


def test_c10_ice_cream_finishes_fight():
    """冰淇淋存了 84 能量、最后一只史莱姆 1 血：先打头槌收尾，不再防御囤能量"""
    hb = card('HEADBUTT', 0, dmg=9); df = card('DEFEND_IRONCLAD', 1, typ='Skill', block=5, target='Self')
    st = state([df, hb], [enemy(0, 1, 3)], energy=84, relics={'ICE_CREAM': (None, 'Normal')})
    c, _ = combat.plan(st, {}, set())
    assert combat.cid(c) == 'HEADBUTT', combat.cid(c)


# ---------- C11 力量数值读牌面 ----------
def test_c11_upgraded_inflame_from_stats():
    inf = card('INFLAME', 0, typ='Power', target='Self', stats={'strengthpower': 3})
    sk = card('STRIKE_IRONCLAD', 1, dmg=6)
    st = state([inf, sk], [enemy(0, 60, 5)], energy=2)
    assert foe_loss([inf, sk], st)[0] == 6 + 3
    assert combat.str_now(card('INFLAME', 2, typ='Power', target='Self')) == 2      # 没有牌面数值时用默认


def test_c11_demon_form_three_per_turn():
    df = card('DEMON_FORM', 0, typ='Power', target='Self', cost=3, stats={'strengthpower': 3})
    assert combat.str_amount(df, combat.STR_POWERS['DEMON_FORM'][1]) == 3
    assert combat.STR_POWERS['DEMON_FORM'][1] == 3


# ---------- C12 回合末遗物 / 能力 ----------
def _turn_end(combo, st, block):
    from policy import handrules
    if not any(c.get('can_play') for c in st['hand']):      # plan() 要至少一张能打的牌才建 ctx
        st['hand'] = st['hand'] + [card('STRIKE_IRONCLAD', 9, dmg=6)]
    ctx = ctx_of(st)
    return handrules.turn_end(tuple(combo), ctx, block, 0)


def test_c12_orichalcum_with_ripple():
    """没出格挡牌、没打攻击：涟漪盆 4 + 奥利哈钢 6 = 10（原来涟漪盆的 4 把奥利哈钢压掉）"""
    st = state([], [enemy(0, 30, 12)], relics={'ORICHALCUM': (None, 'Normal'), 'RIPPLE_BASIN': (None, 'Active')})
    assert _turn_end([], st, 0)[0] == 10
    assert _turn_end([], st, 5)[0] == 4          # 出牌已经有格挡：奥利哈钢不触发


def test_c12_ripple_after_attack_this_turn():
    """本回合早些时候已经打过攻击（遗物状态 Normal）：这一组没攻击也不给涟漪盆"""
    st = state([], [enemy(0, 30, 12)], relics={'RIPPLE_BASIN': (None, 'Normal'), 'ART_OF_WAR': (None, 'Normal')})
    blk, _, _, _, bonus = _turn_end([], st, 3)
    assert blk == 0 and bonus == 0


def test_c12_plating():
    st = state([], [enemy(0, 30, 12)], player_powers={'Plating': 3})
    assert _turn_end([], st, 0)[0] == 3
    sa = card('STONE_ARMOR', 0, typ='Power', target='Self', stats={'platingpower': 4})
    st = state([sa], [enemy(0, 30, 12)])
    assert _turn_end([sa], st, 0)[0] == 4


def test_c12_upgraded_wither_damage():
    w = card('WITHER', 0, typ='Status', cost=0, target='Self', stats={'damage': 9}); w['can_play'] = False
    st = state([w], [enemy(0, 30, 12)])
    assert _turn_end([], st, 0)[2] == 9


# ---------- C13 岿然不动 / 重振精神格挡 ----------
def _block_of(combo, st, mem=None):
    from policy import player_powers as PP
    ctx = ctx_of(st, mem)
    ids = [combat.cid(c) for c in combo]
    base = sum((c.get('stats') or {}).get('block') or 0 for c in combo)
    return base + PP.effects(tuple(combo), ids, ctx)['block']


def test_c13_unmovable_preview_already_doubled():
    """岿然不动、本回合还没从牌拿过格挡：手牌预览防御 10（已翻倍）、耸肩 16（已翻倍）。
    两张一起打：实际只有一张翻倍 → 16 + 5 = 21（原来 10 + 16 + 再加 16 = 42）"""
    d = card('DEFEND_IRONCLAD', 0, typ='Skill', block=10, target='Self')
    sh = card('SHRUG_IT_OFF', 1, typ='Skill', block=16, target='Self')
    st = state([d, sh], [enemy(0, 30, 20)], player_powers={'Unmovable': 1})
    assert _block_of([d], st) == 10
    assert _block_of([d, sh], st) == 21


def test_c13_unmovable_used_up():
    """本回合已经打过一张格挡牌：预览恢复正常，不再加"""
    d = card('DEFEND_IRONCLAD', 0, typ='Skill', block=5, target='Self')
    st = state([d], [enemy(0, 30, 20)], player_powers={'Unmovable': 1})
    mem = {'plays_key': (st['context']['floor'], st['round']), 'card_blocks_this_turn': 1}
    assert _block_of([d], st, mem) == 5


def test_c13_second_wind_block():
    """重振精神（预览每张 7，升级）+ 手里 2 张非攻击 + 1 张攻击：7 × 2 = 14（原来 7 + 5×2 = 17）"""
    sw = card('SECOND_WIND', 0, typ='Skill', block=7, target='Self')
    d1 = card('DEFEND_IRONCLAD', 1, typ='Skill', block=5, target='Self'); d2 = card('DEFEND_IRONCLAD', 2, typ='Skill', block=5, target='Self')
    sk = card('STRIKE_IRONCLAD', 3, dmg=6)
    st = state([sw, d1, d2, sk], [enemy(0, 30, 20)])
    d = {}
    combat.evaluate((sw,), ctx_of(st), detail=d)
    assert d['block'] == 14, d


# ---------- C14 钢笔尖计数 9 ----------
def test_c14_pen_nib_nine_only_first_doubled():
    """计数 9：两张打击预览都是 12（已翻倍），实际 12 + 6 = 18（原来按 24 算，再加一次翻倍分）"""
    s1 = card('STRIKE_IRONCLAD', 0, dmg=12); s2 = card('STRIKE_IRONCLAD', 1, dmg=12)
    st = state([s1, s2], [enemy(0, 80, 5)], relics={'PEN_NIB': (9, 'Active')})
    assert foe_loss([s1, s2], st)[0] == 18
    assert foe_loss([s1], st)[0] == 12
    ctx = ctx_of(st)
    assert longterm.combat_bonus((s1, s2), ctx, {'dmg_by_card': {id(s1): 12, id(s2): 6}, 'ends_fight': False,
                                               'self_hp': 0, 'killed_focus': False}) == 0


def test_c14_pen_nib_eight_unchanged():
    s1 = card('STRIKE_IRONCLAD', 0, dmg=6); s2 = card('STRIKE_IRONCLAD', 1, dmg=6)
    st = state([s1, s2], [enemy(0, 80, 5)], relics={'PEN_NIB': (8, 'Normal')})
    assert foe_loss([s1, s2], st)[0] == 12      # 预览不含翻倍；第 10 张的翻倍由 longterm 近似加分


# ---------- C15 战斗专注之后不能抽牌 ----------
def test_c15_battle_trance_blocks_other_draw():
    bt = card('BATTLE_TRANCE', 0, typ='Skill', cost=0, target='Self', stats={'cards': 3})
    pm = card('POMMEL_STRIKE', 1, dmg=9)
    st = state([bt, pm], [enemy(0, 80, 5)], energy=1)
    ctx = ctx_of(st)
    with_bt = combat.evaluate((bt, pm), ctx) - combat.evaluate((bt,), ctx)
    st2 = state([pm], [enemy(0, 80, 5)], energy=1)
    ctx2 = ctx_of(st2)
    alone = combat.evaluate((pm,), ctx2) - combat.evaluate((), ctx2)
    from params import P as PP_
    assert abs((alone - with_bt) - PP_['draw_value'] * 1) < 1e-6, (alone, with_bt)   # 战斗专注之后拳柄击的抽 1 不算


def test_c15_no_draw_power():
    pm = card('POMMEL_STRIKE', 0, dmg=9)
    a = state([pm], [enemy(0, 80, 5)], energy=1)
    b = state([pm], [enemy(0, 80, 5)], energy=1, player_powers={'No Draw': 1})
    from params import P as PP_
    da = combat.evaluate((pm,), ctx_of(a)); db = combat.evaluate((pm,), ctx_of(b))
    assert abs((da - db) - PP_['draw_value']) < 1e-6


# ---------- C16 商店买遗物的假报错 ----------
def test_c16_buy_relic_null_log_is_success():
    import run
    shop = {'decision': 'shop'}
    err = {'type': 'error', 'message': 'Buy relic failed: Object reference not set to an instance of an object.'}
    assert run.bought_but_logged_null(shop, err)
    assert not run.bought_but_logged_null(shop, {'type': 'error', 'message': 'Not enough gold'})
    assert not run.bought_but_logged_null({'decision': 'combat_play'}, err)


# ---------- 运行 ----------
if __name__ == '__main__':
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    bad = 0
    for k, f in tests:
        try:
            f(); print('通过', k)
        except Exception:
            bad += 1; print('失败', k); traceback.print_exc()
    print(f'{len(tests) - bad}/{len(tests)} 通过')
    sys.exit(1 if bad else 0)
