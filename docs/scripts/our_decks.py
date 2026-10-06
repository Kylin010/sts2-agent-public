"""输出核心研究 · 我们的牌组 vs 人类：死的时候有没有核心、拿了什么代替。

我们的对局：agent/results/v16h-hp80.jsonl、fresh300-hp80.jsonl（每行一局，deck 是死时 / 通关时的最终牌组，+ 表示升级）。
人类对照：
- 人类在同一幕死掉的局的「死前牌组」（进那个节点时的牌组）；
- 人类打到第二幕 Boss 的局，进 Boss 前的牌组（c2），分赢家 / 全部。
用法：CORE_CACHE=缓存路径 python3 our_decks.py [结果文件 ...]
"""
import sys, os, json, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import load_all, name, counts, BASIC
from cores import CORES, which, has_good_core, EXH_ENGINE, EXH_SRC, EXH_PAY, kinds

AGENT = '/opt/slay-the-spire-2/agent'
FILES = sys.argv[1:] or [f'{AGENT}/results/v16h-hp80.jsonl', f'{AGENT}/results/fresh300-hp80.jsonl']
PARTS = EXH_ENGINE | EXH_SRC | EXH_PAY | {'BODY_SLAM', 'JUGGERNAUT', 'BARRICADE', 'UNMOVABLE'}


def ours():
    out = []
    for fn in FILES:
        for l in open(fn):
            r = json.loads(l)
            deck = [c for c in r['deck']]
            k = counts(deck)
            out.append({'file': os.path.basename(fn), 'act': r['act'], 'room': r['room'], 'win': r['win'], 'deck': deck, 'k': k,
                        'relics': len(r.get('relics') or []), 'ups': sum(1 for c in deck if c.endswith('+')),
                        'combats': r.get('combats') or [], 'seed': r.get('seed')})
    return out


def desc(group, lab):
    n = len(group)
    if not n: return
    cores = [set(which(g['k'])) for g in group]
    good = np.mean([bool(has_good_core(g['k'])) for g in group])
    anyc = np.mean([bool(s) for s in cores])
    cc = collections.Counter(c for s in cores for c in s)
    size = np.mean([sum(g['k'].values()) for g in group])
    st = np.mean([g['k'].get('STRIKE_IRONCLAD', 0) for g in group])
    df = np.mean([g['k'].get('DEFEND_IRONCLAD', 0) for g in group])
    parts = np.mean([kinds(g['k'], PARTS) for g in group])
    rel = np.mean([g['relics'] for g in group]); ups = np.mean([g['ups'] for g in group])
    print(f'| {lab} | {n} | {good:.0%} | {anyc:.0%} | ' + '、'.join(f'{c} {v / n:.0%}' for c, v in cc.most_common()) +
          f' | {size:.1f} | {st:.1f} / {df:.1f} | {parts:.1f} | {rel:.1f} | {ups:.1f} |')


def main():
    O = ours()
    H = load_all()
    print(f'我们的对局：{len(O)} 局（{", ".join(os.path.basename(f) for f in FILES)}），赢 {sum(o["win"] for o in O)}；'
          f'死在：' + '，'.join(f'第{a}幕 {k} {v}' for (a, k), v in sorted(collections.Counter((o['act'], o['room']) for o in O).items())) + '\n')

    # 人类：同一幕死掉的局，取死的那个节点进场时的牌组
    def human_death(act):
        out = []
        for r in H:
            if r['win'] or r['acts'] != act: continue
            p = r['points'][-1]
            out.append({'k': counts(p['deck']), 'relics': p['relics'], 'ups': p['ups']})
        return out

    def human_c2(win=None):
        out = []
        for r in H:
            if r['c2'] is None or (win is not None and r['win'] != win): continue
            p = r['points'][r['c2_idx']]
            out.append({'k': counts(r['c2']), 'relics': p['relics'], 'ups': p['ups']})
        return out

    print('## 牌组画像\n')
    print('| 组 | 局数 | 有消耗/格挡核心 | 有任何核心 | 各核心占比 | 张数 | 打击 / 防御 | 消耗零件种类 | 遗物 | 升级 |\n|---|---|---|---|---|---|---|---|---|---|')
    for a in (1, 2, 3):
        desc([o for o in O if o['act'] == a and not o['win']], f'我们·死在第{a}幕')
        desc(human_death(a), f'人类·死在第{a}幕')
    desc(human_c2(True), '人类赢家·第二幕 Boss 前')
    desc(human_c2(), '人类全部·第二幕 Boss 前')
    print()

    # 牌的出现率：我们死在第二幕的 vs 人类第二幕 Boss 前（赢家）
    o2 = [o for o in O if o['act'] == 2 and not o['win']]
    hw = human_c2(True); ha = human_c2()
    def pres(g):
        c = collections.Counter(x for d in g for x in d['k'] if x not in BASIC)
        return {k: v / len(g) for k, v in c.items()}
    po, pw, pa = pres(o2), pres(hw), pres(ha)
    allc = set(po) | set(pw)
    diff = sorted(allc, key=lambda c: po.get(c, 0) - pw.get(c, 0))
    print(f'## 牌的出现率：我们死在第二幕的 {len(o2)} 局 vs 人类赢家第二幕 Boss 前 {len(hw)} 局（人类全部 {len(ha)} 局）\n')
    print('我们明显更少（差 ≥5 个百分点）：' + '，'.join(f'{name(c)} {po.get(c, 0):.0%}/{pw.get(c, 0):.0%}' for c in diff if pw.get(c, 0) - po.get(c, 0) >= 0.05))
    print()
    print('我们明显更多（差 ≥5 个百分点）：' + '，'.join(f'{name(c)} {po.get(c, 0):.0%}/{pw.get(c, 0):.0%}' for c in diff[::-1] if po.get(c, 0) - pw.get(c, 0) >= 0.05))
    print()
    # 第二幕死的局：逐局列核心 / 消耗零件
    print('## 我们死在第二幕的局：核心与关键牌（逐局）\n')
    for o in o2:
        cs = which(o['k'])
        key = [c for c in o['deck'] if c.rstrip('+') not in BASIC]
        print(f'- {o["seed"]} {o["room"]} 核心：{"、".join(cs) or "无"}；非基础牌：' + '、'.join(name(c) for c in key))
    print()
    # 我们的第二幕战斗掉血
    dm = collections.defaultdict(list)
    for o in O:
        for c in o['combats']:
            if c.get('act') == 2: dm[c.get('room')].append(c.get('dmg') or 0)
    print('## 我们第二幕每场掉血：' + '，'.join(f'{k} {np.mean(v):.1f}（{len(v)} 场）' for k, v in dm.items()))


if __name__ == '__main__':
    main()
