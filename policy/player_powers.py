"""玩家身上已有的能力 → 规划这一回合出牌时的联动（消耗引擎、格挡转伤害……）。
能力名用引擎给的英文标题（小写匹配）。说明来自游戏本地化文本（v0.111.0）：
  Feel No Pain 无惧疼痛 N   每消耗一张牌，得 N 格挡
  Dark Embrace 黑暗之拥 N   每消耗一张牌，抽 N 张
  Corruption 腐化           技能 0 费，打出后消耗（费用引擎已经算好；这里只算「技能也算消耗」）
  Juggernaut 主宰 N         每次获得格挡，对随机敌人造成 N 伤害
  Barricade 壁垒            格挡不会在回合开始时消失：多出来的格挡下回合还有用
  Unmovable 岿然不动        每回合第一次从牌获得格挡时翻倍
  Inferno 地狱之火 N        自己回合每次掉血，对全体敌人造成 N 伤害
  Rupture 破裂 N            自己回合每次掉血，+N 力量（长期收益）
「消耗」的来源：带 Exhaust 词条的牌、腐化下的技能、燃烧契约 / 坚毅（消耗一张手牌）、重振精神（消耗所有非攻击手牌）、
恶魔之焰（消耗所有手牌）、回合结束时留在手里的虚无牌（Ethereal，如升天者之咒）。
"""
from params import P

cid = lambda c: str(c.get('id') or '').replace('CARD.', '')
EXHAUST_ONE = {'BURNING_PACT', 'TRUE_GRIT'}          # 消耗一张手牌
SELF_HP_HITS = {'BLOODLETTING': 1, 'OFFERING': 1, 'HEMOKINESIS': 1, 'BREAKTHROUGH': 1, 'BLOOD_WALL': 1, 'CRIMSON_MANTLE': 0,
                'FORGOTTEN_RITUAL': 1, 'PACTS_END': 0}


def amt(powers, word):
    for p in powers or []:
        if word in str(p.get('name', '')).lower(): return p.get('amount') or 1
    return 0


def keywords(c):
    k = c.get('keywords') or []
    if isinstance(k, str): k = [k]
    return {str(x.get('name') if isinstance(x, dict) else x).lower() for x in k}


def exhaust_count(combo, ids, ctx):
    pw = ctx.get('player_powers') or []
    corr = amt(pw, 'corruption') > 0
    n = 0
    for c, i in zip(combo, ids):
        if 'exhaust' in keywords(c) or (corr and c.get('type') == 'Skill'): n += 1
        if i in EXHAUST_ONE: n += 1
    rest = [c for c in ctx['hand'] if c not in combo]
    if 'SECOND_WIND' in ids: n += sum(1 for c in rest if c.get('type') != 'Attack')
    if 'FIEND_FIRE' in ids: n += len(rest)
    elif 'SECOND_WIND' not in ids:
        n += sum(1 for c in rest if 'ethereal' in keywords(c))       # 回合结束留在手里的虚无牌
    return n


def effects(combo, ids, ctx):
    """返回 {'block': 多得的格挡, 'draw': 多抽的牌, 'dealt': 多打的伤害, 'value': 长期价值, 'barricade': 是否有壁垒}"""
    pw = ctx.get('player_powers') or []
    out = {'block': 0.0, 'draw': 0.0, 'dealt': 0.0, 'value': 0.0, 'barricade': amt(pw, 'barricade') > 0}
    if not pw: return out
    ex = exhaust_count(combo, ids, ctx) if (amt(pw, 'feel no pain') or amt(pw, 'dark embrace')) else 0
    out['block'] += amt(pw, 'feel no pain') * ex
    out['draw'] += amt(pw, 'dark embrace') * ex
    fnp_block = out['block']
    blockers = [c for c in combo if ((c.get('stats') or {}).get('block') or 0) > 0]
    um = amt(pw, 'unmovable')
    if um and blockers:
        # 岿然不动（源码 UnmovablePower.ModifyBlockMultiplicative）：本回合「从牌获得格挡」的前 N 次翻倍。手牌的格挡预览已经含这个翻倍——
        # 本回合还不到 N 次时每张格挡牌都显示翻倍，但实际只有先打的 N 张翻倍，其余按一半算（假设大的先吃到）。
        # 原来在预览之上又加了一份最大格挡（Codex 发现，梳理表 C13）。重振精神同一次出牌里的多次格挡都翻倍，不参与这个修正
        left = max(0, um - ctx.get('card_blocks', 0))
        if left > 0:
            bl = sorted(((c.get('stats') or {}).get('block') or 0) for c in blockers if cid(c) != 'SECOND_WIND')
            out['block'] -= sum(v / 2 for v in bl[:max(0, len(bl) - left)])
    jug = amt(pw, 'juggernaut')
    if jug: out['dealt'] += jug * (len(blockers) + (1 if fnp_block > 0 else 0))
    hp_hits = sum(SELF_HP_HITS.get(i, 0) for i in ids)
    if hp_hits:
        inf = amt(pw, 'inferno')
        if inf: out['dealt'] += inf * hp_hits * len(ctx['enemies'])
        rup = amt(pw, 'rupture')
        if rup: out['value'] += P['rupture_str_value'] * rup * hp_hits * ctx['long']
    return out
