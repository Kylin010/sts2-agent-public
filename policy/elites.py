"""精英预测：打过哪些精英 → 接下来可能是哪个 → 群伤要多重要。

规则（源码，research/游戏规则-地图遭遇与概率.md 第 47、57 行，社区 5323 局验证）：每幕精英队列 3 个一袋、不放回，
袋与袋之间第一个不等于上一个。所以：第 1 个 3 选 1，第 2 个在另外 2 个里，第 3 个必定是剩下那个，第 4 个不等于第 3 个。
每幕恰好一个多怪精英（群伤最有用）：第一幕异蛙寄生虫（召扭动虫）、第二幕残杀千足虫（3 节）、第三幕骑士团伙（3 个骑士）。
注意：sts2-cli 第一幕永远是密林（Overgrowth），所以第一幕的池子按密林算。
"""
from policy import kb

POOL = {1: ['BYGONE_EFFIGY_ELITE', 'BYRDONIS_ELITE', 'PHROG_PARASITE_ELITE'],
        2: ['DECIMILLIPEDE_ELITE', 'ENTOMANCER_ELITE', 'INFESTED_PRISMS_ELITE'],
        3: ['KNIGHTS_ELITE', 'MECHA_KNIGHT_ELITE', 'SOUL_NEXUS_ELITE']}
MULTI = {'PHROG_PARASITE_ELITE', 'DECIMILLIPEDE_ELITE', 'KNIGHTS_ELITE'}
ZH = {'BYGONE_EFFIGY_ELITE': '旧日雕像', 'BYRDONIS_ELITE': '多尼斯异鸟', 'PHROG_PARASITE_ELITE': '异蛙寄生虫',
      'DECIMILLIPEDE_ELITE': '残杀千足虫', 'ENTOMANCER_ELITE': '蜂群术士', 'INFESTED_PRISMS_ELITE': '感染棱柱',
      'KNIGHTS_ELITE': '骑士团伙', 'MECHA_KNIGHT_ELITE': '机甲骑士', 'SOUL_NEXUS_ELITE': '灵魂枢纽'}
# 敌人名字（引擎给的英文）里的关键词 → 精英
_KEYS = [('phrog', 'PHROG_PARASITE_ELITE'), ('wriggler', 'PHROG_PARASITE_ELITE'), ('effigy', 'BYGONE_EFFIGY_ELITE'), ('byrdonis', 'BYRDONIS_ELITE'),
         ('decimillipede', 'DECIMILLIPEDE_ELITE'), ('entomancer', 'ENTOMANCER_ELITE'), ('prism', 'INFESTED_PRISMS_ELITE'),
         ('mecha knight', 'MECHA_KNIGHT_ELITE'), ('flail knight', 'KNIGHTS_ELITE'), ('magi knight', 'KNIGHTS_ELITE'),
         ('spectral knight', 'KNIGHTS_ELITE'), ('soul nexus', 'SOUL_NEXUS_ELITE')]
AOE_POTIONS = {'EXPLOSIVE_AMPOULE'}                    # 对所有敌人造成伤害的药水


def identify(enemy_names):
    for n in enemy_names or []:
        low = str(n).lower()
        for k, e in _KEYS:
            if k in low: return e
    return None


def note(mem, st):
    """进精英战时调用：记下这一幕打过哪个精英（每层只记一次）"""
    ctx = st.get('context') or {}
    if ctx.get('room_type') != 'Elite': return
    act, floor = ctx.get('act', 1), ctx.get('floor')
    done = mem.setdefault('elite_floors', set())
    if (act, floor) in done: return
    e = identify([x.get('name') for x in st.get('enemies') or []])
    if not e: return
    done.add((act, floor)); mem.setdefault('elites_seen', {}).setdefault(act, []).append(e)


def dist(act, seen, j=0):
    """这一幕已经打过 seen（按顺序）之后，再往后第 j 个精英（j=0 = 下一个）是谁的概率 {精英: 概率}"""
    pool = POOL.get(act) or []
    if not pool: return {}
    out = {}

    def walk(seq, prob, k):
        pos = len(seq) % 3; bag_start = len(seq) - pos
        if pos == 0:   # 新的一袋：不等于上一个
            cand = [e for e in pool if not seq or e != seq[-1]]
        else:
            cand = [e for e in pool if e not in seq[bag_start:]]
        if not cand: cand = list(pool)
        for e in cand:
            p = prob / len(cand)
            if k == 0: out[e] = out.get(e, 0) + p
            else: walk(seq + [e], p, k - 1)
    walk(list(seen), 1.0, j)
    return out


def p_multi(act, seen, j=0):
    return sum(p for e, p in dist(act, seen, j).items() if e in MULTI)


def aoe_capacity(st):
    """0~1：这副牌（加药水）打多个敌人的能力。群伤牌 1 张算 0.5、多段 0.25；狱火 + 自伤牌（放血等）算强群伤；群伤药水 0.25"""
    pl = st.get('player') or {}
    ids = [str(c.get('id', '')).replace('CARD.', '') for c in pl.get('deck') or []]
    aoe = sum(0.5 for i in ids if 'aoe' in kb.tags(i)) + sum(0.25 for i in ids if 'multi_hit' in kb.tags(i) and 'aoe' not in kb.tags(i))
    if 'INFERNO' in ids:                              # 狱火：回合内每次掉血对所有敌人 6 伤害；有自伤牌就是持续群伤
        selfd = sum(1 for i in ids if 'self_damage' in kb.tags(i))
        aoe += 0.5 * min(selfd, 2)
    pots = [str(p.get('id') or kb.id_by_name('potions', p.get('name')) or '').replace('POTION.', '') for p in pl.get('potions') or [] if p and p.get('name')]
    aoe += 0.25 * sum(1 for p in pots if p in AOE_POTIONS)
    from policy import combos
    aoe += combos.aoe_extra(st)                        # 联动表里凑齐的群伤联动
    return min(1.0, aoe / 1.5)
