"""第二幕 Boss 备战选牌（docs/高手怎么打第二幕Boss.md 规则 S1 / S2）。第二幕开局地图上就能看到 Boss。

S1「每回合产能」：人类赢家进第二幕 Boss 时非基础格挡牌 3.7~4.1 张、过牌牌 3.0~3.3 张；我们 2.6~2.9、1.9~2.4。
   不够时，补格挡 / 过牌的牌加分（logit，加在模拟实打之后，系数 boss_prep_w）。
S2 按 Boss 多拿 / 少拿（社区大样本：有这张牌时打这个 Boss 的胜率差，相关不是因果；+13 个百分点 ≈ +0.5 logit）。
"""
from params import P
from policy import kb

BASIC = {'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH'}
BOSS = {
    'KAISER_CRAB_BOSS': {'UNMOVABLE': .5, 'FEEL_NO_PAIN': .45, 'STOKE': .35, 'PYRE': .35, 'BATTLE_TRANCE': .3, 'TAUNT': .3,
                         'EXTERMINATE': -.2, 'INFERNO': -.2, 'SPITE': -.2, 'STAMPEDE': -.6},
    'KNOWLEDGE_DEMON_BOSS': {'BATTLE_TRANCE': .3, 'CASCADE': .3, 'DEMON_FORM': .3, 'SHOCKWAVE': .3, 'CRIMSON_MANTLE': .3,
                             'CRUELTY': .25, 'SECOND_WIND': .25, 'PERFECTED_STRIKE': -.3, 'BREAKTHROUGH': -.2, 'SPITE': -.35},
}


def bonus(card, st):
    ctx = st.get('context') or {}
    if (ctx.get('act') or 1) != 2: return 0.0
    c = card.rstrip('+'); e = kb.card(c)
    deck = [str(x.get('id', '')).replace('CARD.', '') for x in (st.get('player') or {}).get('deck') or []]
    b = BOSS.get((ctx.get('boss') or {}).get('id'), {}).get(c, 0.0)
    blk = sum(1 for d in deck if d not in BASIC and (kb.card(d).get('block') or 0) > 0 and kb.card(d).get('type') != 'Power')
    drw = sum(1 for d in deck if 'draw' in kb.tags(d))
    if c not in BASIC and (e.get('block') or 0) > 0 and e.get('type') != 'Power' and blk < 4: b += P.get('boss_prep_blk', 0.3)
    if 'draw' in kb.tags(c) and drw < 3: b += P.get('boss_prep_draw', 0.3)
    return b
