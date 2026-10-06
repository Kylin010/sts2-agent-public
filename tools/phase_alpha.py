"""每个精英 / Boss 的专属打法参数：
从人类回放的分阶段统计（data/phase_profiles.json，tools/phase_profiles.py 生成）算出 phase_alpha：
同一场战斗里，敌人出某一招的回合，人类把能量花在攻击上的比例 ÷ 这场战斗平均的攻击比例 = 这一招时伤害估值的倍数
（夹在 0.6~1.6；样本少于 15 回合的不要）。几只敌人组合出招的条目，按每只敌人的招拆开、按回合数加权平均。
输出 data/phase_alpha.json：{遭遇: {招式 id: 倍数}}；规划器按敌人当前的招（局面里的 move_id）查。
用法：python3 tools/phase_alpha.py
"""
import collections, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prof = json.load(open(f'{HERE}/data/phase_profiles.json'))
out = {}
for enc, v in prof.items():
    base = (v.get('_all') or {}).get('atk')
    if not base: continue
    acc = collections.defaultdict(lambda: [0.0, 0])
    for key, st in v.items():
        if key in ('_all', 'NONE') or not isinstance(st, dict) or (st.get('n') or 0) < 15: continue
        for part in key.split('|'):
            mv = part.split(':', 1)[-1]
            acc[mv][0] += st['atk'] * st['n']; acc[mv][1] += st['n']
    m = {mv: round(min(1.6, max(0.6, (s / n) / base)), 2) for mv, (s, n) in acc.items() if n >= 15}
    m = {k: x for k, x in m.items() if abs(x - 1) >= 0.05}
    if m: out[enc] = m
json.dump(out, open(f'{HERE}/data/phase_alpha.json', 'w'), ensure_ascii=False, indent=1)
print(len(out), '个遭遇')
for enc in ('LAGAVULIN_MATRIARCH_BOSS', 'WATERFALL_GIANT_BOSS', 'KAISER_CRAB_BOSS', 'SOUL_FYSH_BOSS', 'THE_INSATIABLE_BOSS', 'KNOWLEDGE_DEMON_BOSS'):
    print(enc, out.get(enc))
