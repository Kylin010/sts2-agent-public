"""药水：什么时候喝。阈值都在 params.json（potion_ 开头），可以按遭遇调（kb/encounter_params.json）。

按用途分类（kb/potions.json 的 uses）：
  回血类（emergency，不含 defense：鲜血药水、龙涎香）：血量低于 potion_heal_below 或这回合会死才喝——满血时喝等于浪费
  瓶中精灵：被动（死了自动复活），不主动喝
  防御类（defense：格挡、虚弱……）：这回合要掉很多血时喝
  增益 / 进攻 / 能量 / 其他：Boss 前几回合、精英第 1 回合就喝，越早喝收益越久
  这回合会死：所有能喝的都喝，防御和回血优先
10/2 之前的版本每回合最多喝 2 瓶，Boss 一开场按顺序全喝（包括血瓶）；战斗基准里 Boss 战死掉的 210 局有 52 局身上还有药。
现在改成每瓶药每回合只尝试一次（防止喝药失败时死循环），不限瓶数。
"""
from params import P
from policy import kb
from policy.knowledge import intent_damage


# 关键药水，按先喝的顺序：士兵炖汤（整场打击重放）→ 能力药水（免费能力牌）→ 欧洛巴斯之酸（攻击 + 技能 + 能力各一张，当回合免费）
KEY_RANK = {k: n for n, k in enumerate(P.get('potion_key_ids', ['SOLDIERS_STEW', 'POWER_POTION', 'OROBIC_ACID']))}


def pid(p):
    return str(p.get('id') or kb.id_by_name('potions', p.get('name')) or '').replace('POTION.', '')


def kind(p):
    u = kb.potion_uses(pid(p))
    if pid(p) == 'FAIRY_IN_A_BOTTLE': return 'passive'
    if 'emergency' in u and 'defense' not in u: return 'heal'
    if 'defense' in u: return 'defense'
    if 'permanent' in u: return 'permanent'
    return 'buff'          # setup / offense / energy_draw / utility


def decide(st, mem, need, hp, room, rnd, enemies):
    pl = st.get('player') or {}; mx = max(pl.get('max_hp', 1), 1)
    pots = [p for p in pl.get('potions') or [] if p and p.get('name')]
    if not pots or not enemies: return None
    key = ((st.get('context') or {}).get('floor'), rnd)
    tried = mem.setdefault('pot_tried', {})
    if tried.get('key') != key: tried.clear(); tried['key'] = key
    pots = [p for p in pots if kind(p) != 'passive' and (p['index'], p.get('name')) not in tried]
    if not pots: return None
    tgt = max(enemies, key=intent_damage)['index']
    # 滑溜（墨影幻灵开场 9 层）：每次掉血只算 1，伤害药水扔进去等于浪费（研究 10 号）→ 滑溜没磨完前不喝进攻类药水
    from policy import enemy_powers as EP
    if P.get('potion_skip_intangible', False) and any(EP.amt(e, 'intangible') > 0 for e in enemies if e['index'] == tgt):
        # 无形（灵魂异鱼「消逝」后那一回合）：每次掉血压到 1，伤害药水扔进去只掉 1 → 留到下回合
        pots = [p for p in pots if 'offense' not in kb.potion_uses(pid(p))]
        if not pots: return None
    if any(EP.amt(e, 'slippery') > 0 for e in enemies if e['index'] == tgt):
        pots = [p for p in pots if 'offense' not in kb.potion_uses(pid(p))]
        if not pots: return None

    def use(p):
        tried[(p['index'], p.get('name'))] = True
        a = {'potion_index': p['index']}
        if p.get('target_type') == 'AnyEnemy': a['target_index'] = tgt
        return ('use_potion', a)
    by = lambda *ks: [p for p in pots if kind(p) in ks]
    if need >= hp:                                   # 这回合会死：防御、回血优先，然后什么都喝
        return use((by('defense', 'heal') or pots)[0])
    if P.get('potion_key_on', False):
        # → 精英 / Boss 一开场就喝（Boss 睡着时等它醒，见下面 potion_wait_asleep）。
        # 普通战「也可以看情况喝」：这回合来伤 ≥ 血量 × potion_key_monster_need，或第 1 回合敌人总血 ≥ potion_key_monster_ehp 才喝，否则留着
        key = [p for p in pots if pid(p) in KEY_RANK]
        if room == 'Monster' and key:
            ehp = sum((e.get('hp') or 0) for e in enemies)
            if need >= P.get('potion_key_monster_need', 0.5) * hp or (rnd == 1 and ehp >= P.get('potion_key_monster_ehp', 120)):
                return use(min(key, key=lambda p: KEY_RANK[pid(p)]))
            pots = [p for p in pots if pid(p) not in KEY_RANK]
            if not pots: return None
            by = lambda *ks: [p for p in pots if kind(p) in ks]
        elif key and room in ('Elite', 'Boss'):
            from policy import enemy_powers as EPk
            if not any(EPk.amt(e, 'asleep') > 0 for e in enemies) or not P.get('potion_wait_asleep', False):
                return use(min(key, key=lambda p: KEY_RANK[pid(p)]))
    if P.get('crab_hold_potions', True) and any('rocket' in str(e.get('name', '')).lower() for e in enemies):
        # 帝皇蟹（高手录像研究 D1）：虚弱 / 格挡 / 易伤药水留给火箭的光束 / 激光回合（意图 ≥30），别第 1 回合就喝
        rk = next(e for e in enemies if 'rocket' in str(e.get('name', '')).lower())
        hold = lambda p: any(w in pid(p) for w in ('WEAK', 'BLOCK', 'VULNERAB'))
        if intent_damage(rk) >= 30:
            h = [p for p in pots if hold(p)]
            if h: return use(h[0])
        else:
            pots = [p for p in pots if not hold(p)]
            if not pots: return None
    if by('heal') and hp <= P['potion_heal_below'] * mx:
        return use(by('heal')[0])
    big = need >= P['potion_defense_need'] * hp      # 这回合要掉很多血
    act = (st.get('context') or {}).get('act', 1)
    a2 = (act == 2 and P.get('potion_save_a2', False)) or act in P.get('potion_save_acts', [])   # 高手录像研究 D2：人类带 ~2 瓶进第二幕 Boss、只用 0.7；我们 0.8~1.5 → 路上少喝
    # 10/4：potion_save_acts 指定哪几幕省药（第一幕死亡 85% 在 Boss，进场血量 72~90%，牌组弱——药留给 Boss）
    elite_need = P.get('potion_elite_need_a2', 0.7) if a2 else P['potion_elite_need']
    mon_need = P.get('potion_monster_need_a2', 1.0) if a2 else P['potion_monster_need']
    if room == 'Boss':
        r0 = 1
        if P.get('potion_wait_asleep', False):
            # 10/4：乐加维林族母开局睡 3 回合，程序第 1 回合对着睡着的它喝屈伸药水（只加当回合力量）= 白喝。
            # 有敌人睡着时增益 / 进攻药先留着，「Boss 前几回合」从它醒的那回合算起
            from policy import enemy_powers as EP2
            if any(EP2.amt(e, 'asleep') > 0 for e in enemies): return None if not big else (use(by('defense')[0]) if by('defense') else None)
            aw = mem.setdefault('boss_awake', {})
            if aw.get('key') != (st.get('context') or {}).get('floor'): aw.clear(); aw['key'] = (st.get('context') or {}).get('floor'); aw['r'] = rnd
            r0 = aw['r']
        if rnd - r0 + 1 <= P['potion_boss_rounds'] and by('buff'): return use(by('buff')[0])
        if big and by('defense'): return use(by('defense')[0])
    elif room == 'Elite':
        if rnd == 1 and P['potion_elite_r1'] and by('buff') and not a2: return use(by('buff')[0])
        if need >= elite_need * hp and by('defense', 'buff'): return use(by('defense', 'buff')[0])
    elif room == 'Monster' and need >= mon_need * hp and by('defense', 'buff'):
        return use(by('defense', 'buff')[0])   # 普通战：要掉很多血才喝
    return None
