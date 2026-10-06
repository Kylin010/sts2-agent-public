"""回合结束时的手牌和遗物效果：有时候「少出牌 / 不出牌 / 留能量」反而更好。

规划时每种出牌组合打完后，看：剩多少能量、手里还剩哪些牌、这回合打没打攻击、最后有多少格挡，
再按遗物和手里的坏牌修正格挡、伤害、掉血和额外分数。分值都在 params.json（hand_ 开头）。
"""
from params import P

cid = lambda c: str(c.get('id') or '').replace('CARD.', '')

# 回合结束时还在手里会造成的损失：(伤害可被格挡, 直接失去生命)
END_TURN_PENALTY = {'BURN': (2, 0), 'WITHER': (3, 0), 'INFECTION': (3, 0), 'TOXIC': (5, 0), 'DECAY': (2, 0),
                    'BECKON': (0, 6), 'BAD_LUCK': (0, 13), 'DOUBT': (0, 0), 'SHAME': (0, 0)}
SOFT_PENALTY = {'DOUBT': 3, 'SHAME': 3, 'DEBT': 2}          # 虚弱 / 脆弱 / 丢金币，折成分数
EXHAUST_ALL = {'FIEND_FIRE', 'STOKE'}
EXHAUST_ONE = {'BURNING_PACT', 'TRUE_GRIT', 'BRAND'}


def left_in_hand(combo, hand):
    """这组牌打完后，手里还剩哪些牌（考虑消耗手牌的牌）"""
    ids = [cid(c) for c in combo]
    rest = [c for c in hand if c not in combo]
    if any(i in EXHAUST_ALL for i in ids): return []
    if 'SECOND_WIND' in ids: rest = [c for c in rest if c.get('type') == 'Attack']
    for _ in range(sum(1 for i in ids if i in EXHAUST_ONE)):           # 消耗一张：挑最坏的（有罚的坏牌优先）
        bad = [c for c in rest if cid(c) in END_TURN_PENALTY or c.get('type') in ('Curse', 'Status')]
        if bad: rest.remove(max(bad, key=lambda c: sum(END_TURN_PENALTY.get(cid(c), (1, 0)))))
    return rest


def turn_end(combo, ctx, block, unspent):
    """返回 (格挡修正, 额外伤害, 额外受到的可格挡伤害, 额外直接失血, 额外分数)"""
    rel = ctx['relics']; ids = [cid(c) for c in combo]
    rest = left_in_hand(combo, ctx['hand'])
    attacks = sum(1 for c in combo if c.get('type') == 'Attack')
    blk = 0; dealt = 0; dmg_in = 0; hp_loss = 0; bonus = 0
    for c in rest:
        a, b = END_TURN_PENALTY.get(cid(c), (0, 0))
        if a: a = (c.get('stats') or {}).get('damage') or a       # 升级过的灼伤 / 凋萎伤害更高（凋萎每被升级一次 +3），读牌面
        dmg_in += a; hp_loss += b; bonus -= SOFT_PENALTY.get(cid(c), 0)
        if cid(c) == 'REGRET': hp_loss += len(rest)
    # 冰淇淋：多余能量留到下回合。只算这组牌让存量多 / 少了多少（unspent − 现有能量），不给已经存下的能量记分——
    # 否则战斗一结束存量就作废，「打死最后一只」反而比「再防一回合」少几百分，会一直囤能量不收尾（Codex 卡 40 回合的局）
    if 'ICE_CREAM' in rel: bonus += P['hand_saved_energy'] * (unspent - ctx['energy'])
    # 回合末遗物 / 能力（源码核对，Codex 发现，梳理表 C12）：
    # ① 奥利哈钢 / 假奥利哈钢在回合末「最早」阶段先看出完牌的格挡是不是 0（BeforeSideTurnEndVeryEarly），
    #    镀层、涟漪盆、斗篷扣的格挡都在它之后，压不掉它；两件可以同时有（原来先加了别的再判断，且只算一件）
    ori = ((6 if 'ORICHALCUM' in rel else 0) + (3 if 'FAKE_ORICHALCUM' in rel else 0)) if block == 0 else 0
    # ② 涟漪盆 / 孙子兵法看的是「整回合」有没有打过攻击：遗物状态 Active = 本回合还没打过（回合开始置 Active、打出攻击后置 Normal）。
    #    原来只看这一组牌，本回合早些时候已经打过攻击也照给
    quiet = lambda rid: rel[rid][1] in (None, 'Active')
    if attacks == 0:
        if 'ART_OF_WAR' in rel and quiet('ART_OF_WAR'): bonus += P['hand_art_of_war']        # 下回合 +1 能量
        if 'RIPPLE_BASIN' in rel and quiet('RIPPLE_BASIN'): blk += 4
    if 'CLOAK_CLASP' in rel: blk += len(rest)
    # ③ 镀层（石肤给的 Plating）：回合末给等于层数的格挡（下个己方回合开始才 −1），原来完全没算；这组牌里新打的石肤当回合就生效
    plating = sum((p.get('amount') or 0) for p in ctx.get('player_powers') or [] if 'plating' in str(p.get('name', '')).lower())
    plating += sum(((c.get('stats') or {}).get('platingpower') or 4) for c in combo if cid(c) == 'STONE_ARMOR')
    blk += plating + ori
    total = block + blk
    if 'PARRYING_SHIELD' in rel and total >= 10: dealt += 6
    if 'STURDY_CLAMP' in rel: bonus += 0.5 * min(10, max(0, total - ctx['incoming']))
    if 'SCREAMING_FLAGON' in rel and not rest: dealt += 20 * len(ctx['enemies'])
    if ctx.get('stampede') and any(c.get('type') == 'Attack' for c in rest): dealt += 6
    return blk, dealt, dmg_in, hp_loss, bonus


def hand_is_junk(hand):
    bad = [c for c in hand if c.get('type') in ('Curse', 'Status') or not c.get('can_play')]
    return len(hand) > 0 and len(bad) >= len(hand) / 2
