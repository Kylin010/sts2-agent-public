"""按地图 / 本幕 Boss 提前准备牌组。
第一幕开局地图上就能看到 Boss；暗港第一幕死亡 3/4 在三个 Boss（乐加维林族母、瀑布巨兽、灵魂异鱼）。选牌时按 Boss 给对路的牌加分（logit），
缺多少补多少（牌组里已经够了就不再加）。总权重 mapprep_w，默认 0 = 不起作用。

要点：
- 花园幽灵鳗（暗港精英，4 只）一般要准备群伤，没有群伤很难打 → 暗港第一幕群伤牌加分
- 乐加维林族母：先看是否抓了对应牌组；睡着时上能力、上易伤（痛击打不穿它的格挡，不会让它醒）→ 能力 / 成长牌、易伤牌加分
- 灵魂异鱼：选择烧牌（消耗），烧掉它塞进来的烂牌；它的掉血牌可以故意掉血触发浴火 → 消耗类牌、狱火/ 撕裂加分
- 花园幽灵鳗（10/4 补充）：狱火、药水的伤害不触发胆小的护盾 → 狱火本来就有群伤标签，暗港这里一起加分
- 瀑布巨兽：保留足够的血和防御去打（爆炸伤害 = 蒸汽层数，拖得越久越大）→ 非基础格挡牌、力量 / 成长（打得快）加分
"""
from params import P
from policy import kb

BASIC = {'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'ASCENDERS_BANE'}


def _deck(st):
    return [str(x.get('id', '')).replace('CARD.', '') for x in (st.get('player') or {}).get('deck') or []]


def _n(deck, tag, exclude_basic=True):
    return sum(1 for d in deck if tag in kb.tags(d) and not (exclude_basic and d in BASIC))


def bonus(card, st):
    ctx = st.get('context') or {}
    act = ctx.get('act') or 1
    if act != 1: return 0.0
    c = str(card or '').replace('CARD.', '').rstrip('+')
    t = kb.tags(c)
    deck = _deck(st)
    boss = (ctx.get('boss') or {}).get('id') or ''
    b = 0.0
    if ctx.get('act_name') == 'Underdocks' and 'aoe' in t and _n(deck, 'aoe') < 2:
        b += P.get('mapprep_aoe', 0.4)
    if boss == 'LAGAVULIN_MATRIARCH_BOSS':
        if ('power' in t or 'scaling' in t) and (_n(deck, 'power') + _n(deck, 'scaling')) < 3: b += P.get('mapprep_laga_power', 0.4)
        if 'vuln' in t and _n(deck, 'vuln', exclude_basic=False) < 3: b += P.get('mapprep_laga_vuln', 0.3)
    elif boss == 'SOUL_FYSH_BOSS':
        if 'exhaust_fuel' in t and _n(deck, 'exhaust_fuel') < 2: b += P.get('mapprep_fysh_exhaust', 0.4)
        if c in ('INFERNO', 'RUPTURE'): b += P.get('mapprep_fysh_rupture', 0.3)     # 呼唤回合末掉 6：触发狱火（全体伤害）/ 撕裂（+力量）
    elif boss == 'WATERFALL_GIANT_BOSS':
        e = kb.card(c)
        if (e.get('block') or 0) > 0 and e.get('type') != 'Power' and c not in BASIC and _n(deck, 'block') < 4: b += P.get('mapprep_giant_block', 0.3)
        if ('strength' in t or 'scaling' in t) and (_n(deck, 'strength') + _n(deck, 'scaling')) < 2: b += P.get('mapprep_giant_scale', 0.2)
    return b
