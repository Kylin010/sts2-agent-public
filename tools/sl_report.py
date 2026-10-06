"""读档学习的报告。
1. 总览：每局读档几次、哪些战斗最常要读档、老实打 vs 老师（看随机数的推演）掉血、老师救回几次死亡、哪些老师也救不了（问题在更早的决定）
2. 第一次分歧：同一场战斗老实打和老师从同一个局面开始，找两边第一次出牌不同的地方，归类老师「多挡 / 多打 / 用药 / 换目标 / 提前结束回合」

用法：python3 tools/sl_report.py results/sl1.jsonl [lab/iter/seed_acts.json]
"""
import collections, json, os, statistics as S, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy import kb


def ctype(name):
    base = str(name or '').rstrip('+')
    i = {'Strike': 'STRIKE_IRONCLAD', 'Defend': 'DEFEND_IRONCLAD'}.get(base) or kb.id_by_name('cards', name)   # 按名字会查到别的角色的打击 / 防御
    c = kb.card(i) if i else {}
    if not c: return '?'
    if c.get('type') == 'Power': return '能力'
    if (c.get('block') or 0) > 0 and c.get('type') != 'Attack': return '格挡'
    if c.get('type') == 'Attack': return '攻击'
    return '技能'


def act_of(it):
    a = it.get('a')
    if a == 'play_card': return ('出牌', it.get('card'), it.get('tgt'))
    if a == 'use_potion': return ('用药', str(it.get('potion')), None)
    return (a, None, None)


def first_divergence(trace, act, floor):
    """同一场战斗：读档标记之前那段是老实打的，标记之后、下一个标记之前 sl=1 的那段是老师（第一次读档）打的。
    返回 (局面, 老实动作, 老师动作) 或 None"""
    is_fight = lambda t: t.get('d') in ('combat', 'combat_select') and t['act'] == act and t['floor'] == floor
    first_t = next((i for i, t in enumerate(trace) if t.get('sl') and is_fight(t)), None)
    if first_t is None: return None
    idx = max((i for i in range(first_t) if trace[i].get('d') == 'SL'), default=None)
    if idx is None: return None
    honest = [t for t in trace[:idx] if is_fight(t) and not t.get('sl')]
    nxt = next((i for i in range(idx + 1, len(trace)) if trace[i].get('d') == 'SL'), len(trace))
    teacher = [t for t in trace[idx:nxt] if is_fight(t) and t.get('sl')]
    for h, o in zip(honest, teacher):
        if act_of(h) != act_of(o): return h, act_of(h), act_of(o)
    return None


def classify(st, ha, oa):
    if oa[0] == '用药' and ha[0] != '用药': return '老师先用药'
    if ha[0] == '用药' and oa[0] != '用药': return '老实先用药（老师不用）'
    if oa[0] == 'end_turn' and ha[0] != 'end_turn': return '老师提前结束回合（少打一张）'
    if ha[0] == 'end_turn' and oa[0] != 'end_turn': return '老师多打一张'
    if ha[0] == oa[0] == '出牌':
        th, to = ctype(ha[1]), ctype(oa[1])
        if ha[1] == oa[1]: return '同一张牌换目标'
        if to == '格挡' and th == '攻击': return '老师挡（老实打）'
        if to == '攻击' and th == '格挡': return '老师打（老实挡）'
        if to == '能力' and th != '能力': return '老师先出能力'
        return f'换牌：{th} → {to}'
    return f'{ha[0]} → {oa[0]}'


def main(path, acts_path=None):
    rs = [json.loads(l) for l in open(path)]
    acts = json.load(open(acts_path)) if acts_path and os.path.exists(acts_path) else {}
    ok = [r for r in rs if 'crash' not in r]
    print(f'{os.path.basename(path)}：{len(rs)} 局（技术故障 {len(rs) - len(ok)}）')
    for name, zh in (('Overgrowth', '密林'), ('Underdocks', '暗港'), (None, '全部')):
        xs = [r for r in ok if name is None or acts.get(r.get('seed')) == name]
        if not xs: continue
        n_sl = [len(r.get('sl') or []) for r in xs]
        print(f'  {zh}：{len(xs)} 局，过第一幕 {sum(1 for r in xs if r.get("win"))}（读档辅助，不是诚实胜率），'
              f'每局读档 {S.mean(n_sl):.2f} 次，一次都不用读档 {sum(1 for x in n_sl if x == 0)} 局')
    evs = [(r, e) for r in ok for e in r.get('sl') or []]
    print(f'\n读档 {len(evs)} 次：原因', dict(collections.Counter(e['why'] for _, e in evs)))
    saved = sum(1 for _, e in evs if e['honest_died'] and e.get('oracle') and not e['oracle'][-1]['died'])
    died = sum(1 for _, e in evs if e['honest_died'])
    print(f'老实打会死 {died} 次，老师救回 {saved} 次；老师也死 {sum(1 for _, e in evs if e.get("oracle") and e["oracle"][-1]["died"])} 次')
    by = collections.defaultdict(list)
    for _, e in evs: by[(e['room'], ' + '.join(e['enemies']))].append(e)
    print('\n最常要读档的战斗（次数 / 老实平均掉血 → 老师 / 老实会死 → 老师救回）：')
    for k, xs in sorted(by.items(), key=lambda t: -len(t[1]))[:15]:
        hd = S.mean(e['honest_dmg'] for e in xs); od = S.mean(e['oracle'][-1]['dmg'] for e in xs if e.get('oracle')) if any(e.get('oracle') for e in xs) else float('nan')
        dd = sum(e['honest_died'] for e in xs); sv = sum(1 for e in xs if e['honest_died'] and e.get('oracle') and not e['oracle'][-1]['died'])
        print(f'  {k[0]:7} {k[1][:50]:50} {len(xs):3} 次  {hd:5.1f} → {od:5.1f}  死 {dd} → 救 {sv}')
    # 老师能挽回多少：按「老师比老实少掉血」分
    gain = [e['honest_dmg'] - e['oracle'][-1]['dmg'] for _, e in evs if e.get('oracle') and not e['honest_died'] and not e['oracle'][-1]['died']]
    if gain:
        print(f'\n没死的读档战斗：老师平均少掉 {S.mean(gain):.1f} 血；少掉 ≥10 的 {sum(1 for g in gain if g >= 10)} / {len(gain)}，几乎一样（±3）{sum(1 for g in gain if abs(g) <= 3)}')
    # 第一次分歧
    kinds = collections.Counter(); examples = collections.defaultdict(list)
    for r, e in evs:
        dv = first_divergence(r.get('trace') or [], e['act'], e['floor'])
        if not dv: kinds['（老师和老实整场一样，或没对上记录）'] += 1; continue
        st, ha, oa = dv; k = classify(st, ha, oa); kinds[k] += 1
        if len(examples[k]) < 3:
            examples[k].append(f"R{st.get('r')} 血{st.get('hp')} 挡{st.get('blk')} 能{st.get('en')} 手{st.get('hand')} 敌{[(f[0], f[1], f[3]) for f in st.get('foes') or []]} | 老实 {ha} / 老师 {oa}")
    print('\n第一次分歧（老师怎么打得不一样）：')
    for k, n in kinds.most_common():
        print(f'  {k}：{n}')
        for x in examples.get(k, []): print('      ', x[:260])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else f'{HERE}/lab/iter/seed_acts.json')
