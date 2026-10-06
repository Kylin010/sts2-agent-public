"""第二幕 Boss 研究 · 出表：帝皇蟹 / 知识恶魔，人类赢家 vs 人类没打过的 vs 我们程序，逐项对比。

数据层：boss_data.py（人类录像逐事件）→ boss_turns.py（统一成逐回合记录，含我们的 bdla2-g3-0615.jsonl）；
        boss_runs.py（社区整局大样本，进场状态和整场结果）。
用法：python3 boss_report.py > out/boss_report.md   （缓存都在 /tmp，第一次跑要 5~10 分钟，之后几十秒）
所有表都写明样本数。分组：
    人赢      人类录像里打赢的（每场取最后一次尝试）
    人没过    人类录像里输掉的 + 放弃重来的那几次尝试（输的太少，帝皇蟹 5 场、知识恶魔 8 场，合在一起看）
    我们赢 / 我们输   bdla2-g3-0615.jsonl
"""
import sys, os, json, collections, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boss_turns import load_all
from boss_runs import load_boss_runs
from core_data import name as zh
import cores

ENG = '/opt/slay-the-spire-2/sources/spire-codex/data-beta/v0.111.0/eng'
C = {x['id']: x for x in json.load(open(f'{ENG}/cards.json'))}
ZH_POT = {p['id']: p['name'] for p in json.load(open('/opt/slay-the-spire-2/sources/spire-codex/data-beta/v0.111.0/zhs/potions.json'))}
R = load_all()
RS = load_boss_runs()
GROUPS = {'人赢': ('human', ('win',)), '人没过': ('human', ('loss', 'retry')), '我们赢': ('ours', ('win',)), '我们输': ('ours', ('loss',))}
BOSS_ZH = {'crab': '帝皇蟹', 'kd': '知识恶魔'}
CR = {1: 'THRASH', 2: 'ENLARGING_STRIKE', 3: 'BUG_STING', 4: 'ADAPT', 0: 'GUARDED_STRIKE'}
RO = {1: 'TARGETING_RETICLE', 2: 'PRECISION_BEAM', 3: 'CHARGE_UP', 4: 'LASER', 0: 'RECHARGE'}
NONATK = {'ADAPT', 'CHARGE_UP', 'RECHARGE'}


def grp(src, boss, res):
    return [r for r in R if r['src'] == src and r['boss'] == boss and r['result'] in res]


def m(xs, f='{:.1f}'):
    xs = [x for x in xs if x is not None]
    return f.format(S.mean(xs)) if xs else '—'


def pct(a, b):
    return f'{a / b:.0%}' if b else '—'


def ctype(i): return C.get(i, {}).get('type')
def isblk(i): return (C.get(i, {}).get('block') or 0) > 0 and ctype(i) != 'Attack'
def isatk(i): return ctype(i) == 'Attack'
def isaoe(i): return C.get(i, {}).get('target') == 'AllEnemies' and isatk(i)
def isdraw(i): return (C.get(i, {}).get('cards_draw') or 0) > 0
def manual(p): return not (len(p) > 3 and p[3])
def seen(t, src): return t['hand_all'] if src == 'ours' else t['hand']


def deck_feats(deck):
    ids = [d.rstrip('+') for d in deck]; k = collections.Counter(ids)
    real = [i for i in ids if ctype(i) not in ('Curse', 'Status', None)]
    f = collections.OrderedDict()
    f['张数'] = len(ids); f['升级张数'] = sum(1 for d in deck if d.endswith('+'))
    f['基础打击+防御'] = k['STRIKE_IRONCLAD'] + k['DEFEND_IRONCLAD']
    f['非基础格挡牌'] = sum(1 for i in real if isblk(i) and i != 'DEFEND_IRONCLAD')
    f['过牌牌'] = sum(1 for i in real if isdraw(i))
    f['加能量牌'] = sum(1 for i in real if (C[i].get('energy_gain') or 0) > 0)
    f['0 费牌'] = sum(1 for i in real if C[i].get('cost') == 0)
    f['群伤攻击'] = sum(1 for i in real if isaoe(i))
    f['能力牌'] = sum(1 for i in real if ctype(i) == 'Power')
    f['诅咒/状态'] = sum(1 for i in ids if ctype(i) in ('Curse', 'Status'))
    for n in ('消耗引擎', '格挡转伤害'):
        f['有「' + n + '」核心'] = int(cores.CORES[n][0](k))
    return f


def table(head, rows):
    out = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    out += ['| ' + ' | '.join(str(x) for x in r) + ' |' for r in rows]
    return '\n'.join(out)


def section_samples():
    print('## 样本\n')
    c = collections.Counter((r['src'], r['boss'], r['result']) for r in R)
    rows = []
    for boss in ('crab', 'kd'):
        rows.append([BOSS_ZH[boss], c[('human', boss, 'win')], c[('human', boss, 'loss')], c[('human', boss, 'retry')],
                     c[('ours', boss, 'win')], c[('ours', boss, 'loss')],
                     sum(1 for r in RS if r['boss'] == boss and r['result'] == 'win'), sum(1 for r in RS if r['boss'] == boss and r['result'] == 'loss')])
    print(table(['Boss', '录像·人赢', '录像·人输', '录像·放弃重来的尝试', '我们赢', '我们输', '社区整局·赢', '社区整局·输'], rows))
    rt = collections.Counter((r['boss']) for r in R if r['src'] == 'human' and r['result'] == 'win' and r['attempts'] > 1)
    print(f"\n录像里打赢的局中用过「重开战斗 / 读档」的：帝皇蟹 {rt['crab']} 场、知识恶魔 {rt['kd']} 场（统计取最后那次）。\n")


def section_entry():
    print('## 一、进场状态\n')
    for boss in ('crab', 'kd'):
        print(f'### {BOSS_ZH[boss]}\n')
        cols = {}
        for g, (src, res) in GROUPS.items():
            rs = grp(src, boss, res)
            F = [deck_feats(r['deck']) for r in rs]
            d = collections.OrderedDict()
            d['场数'] = str(len(rs))
            d['进场血量'] = m([r['hp_in'] for r in rs])
            d['进场药水（瓶）'] = m([len(r['potions_in']) for r in rs], '{:.2f}')
            d['遗物数'] = m([len(r['relics']) for r in rs])
            for k in F[0]: d[k] = m([f[k] for f in F], '{:.2f}')
            cols[g] = d
        for res in ('win', 'loss'):
            rs = [r for r in RS if r['boss'] == boss and r['result'] == res]
            F = [deck_feats(r['deck']) for r in rs]
            d = collections.OrderedDict()
            d['场数'] = str(len(rs)); d['进场血量'] = m([r['hp_in'] for r in rs]); d['进场药水（瓶）'] = '—'
            d['遗物数'] = m([r['relics'] for r in rs])
            for k in F[0]: d[k] = m([f[k] for f in F], '{:.2f}')
            cols['社区' + ('赢' if res == 'win' else '输')] = d
        keys = list(next(iter(cols.values())).keys())
        print(table(['指标'] + list(cols), [[k] + [cols[g][k] for g in cols] for k in keys]))
        print()


def section_turns():
    print('## 二、逐回合：伤害 / 格挡 / 掉血\n')
    print('伤害 = 我的回合打出的（含打在敌人格挡上的）+ 敌方回合的反伤；格挡：人类 = 全部来源，我们 = 出牌之间看得到的变化（漏掉回合结束时的覆甲等，略偏低）；'
          '掉血 = 这一轮（我的回合 + 敌方回合）实际掉的血。括号里是活到这回合的场数。\n')
    for boss in ('crab', 'kd'):
        print(f'### {BOSS_ZH[boss]}\n')
        rows = []
        for n in range(1, 11):
            row = [n]
            for g, (src, res) in GROUPS.items():
                ts = [r['turns'][n - 1] for r in grp(src, boss, res) if len(r['turns']) >= n]
                if len(ts) < 3: row.append('—'); continue
                row.append(f"{m([t['dmg'] + t['dmg_rf'] for t in ts], '{:.0f}')} / {m([t['blk'] for t in ts], '{:.0f}')} / {m([t['loss'] for t in ts], '{:.1f}')}（{len(ts)}）")
            rows.append(row)
        print(table(['回合'] + [g + ' 伤/挡/掉' for g in GROUPS], rows))
        # 人类实际来伤
        hw = grp('human', boss, ('win',))
        inc = [m([r['turns'][n - 1]['inc'] for r in hw if len(r['turns']) >= n], '{:.0f}') for n in range(1, 11)]
        print(f"\n人赢每回合实际挨到的攻击（含被格挡吃掉的）：{' / '.join(inc)}（第 1~10 回合）\n")
        # 累计
        rows = []
        for g, (src, res) in GROUPS.items():
            rs = grp(src, boss, res)
            nt = [len(r['turns']) for r in rs]
            loss5 = [sum(t['loss'] for t in r['turns'][:5]) for r in rs if len(r['turns']) >= 5 or r['result'] == 'win']
            dmg3 = [sum(t['dmg'] + t['dmg_rf'] for t in r['turns'][:3]) for r in rs]
            npl = [sum(1 for p in t['plays'] if manual(p)) for r in rs for t in r['turns'] if t['n'] <= 5]
            nseen = [len(seen(t, src)) for r in rs for t in r['turns'] if t['n'] <= 5]
            rows.append([g, len(rs), m(nt), m(dmg3, '{:.0f}'), m(loss5, '{:.0f}'), m(npl), m(nseen)])
        print(table(['组', '场数', '打了几回合', '前 3 回合总伤害', '前 5 回合累计掉血', '前 5 回合每回合出牌', '前 5 回合每回合见到的牌'], rows))
        print()


def section_crab():
    print('## 三、帝皇蟹专项\n')
    print('### 3.1 先打死谁、第几回合、和另一只招式的关系\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'crab', res)
        killed = [r for r in rs if r['kills']]
        first = collections.Counter(min(r['kills'], key=lambda x: r['kills'][x]) for r in killed)
        ft = [min(r['kills'].values()) for r in killed]
        good = 0; rk4 = 0
        for r in killed:
            k = r['kills']; f = min(k, key=lambda x: k[x]); n = k[f]; sv = 'ROCKET' if f == 'CRUSHER' else 'CRUSHER'
            mv = (r['turns'][n - 1]['moves'].get(sv) or '').replace('_MOVE', '') if src == 'human' else (CR if sv == 'CRUSHER' else RO)[n % 5]
            good += mv in NONATK
            rk4 += f == 'ROCKET' and n in (4, 9)
        gap = [max(r['kills'].values()) - min(r['kills'].values()) for r in killed if len(r['kills']) == 2]
        rows.append([g, len(rs), f'{len(killed)}（{pct(len(killed), len(rs))}）', f"火箭 {first['ROCKET']} / 碾碎爪 {first['CRUSHER']}",
                     m(ft), pct(good, len(killed)), f'{rk4}（{pct(rk4, len(killed))}）', m(gap)])
    print(table(['组', '场数', '打死过至少一只', '先死的', '第一只死在第几回合（均）', '击杀那回合另一只不攻击的比例', '在第 4/9 回合（碾碎爪「适应」）打死火箭', '两只死亡间隔（回合）'], rows))
    print('\n（「另一只不攻击」= 碾碎爪的适应、火箭的蓄能 / 睡觉。随机击杀时，打死火箭碰上适应的基准概率约 20%，打死碾碎爪碰上蓄能 / 睡觉约 40%。）\n')
    hw = grp('human', 'crab', ('win',))
    dist = collections.Counter((min(r['kills'], key=lambda x: r['kills'][x]), min(r['kills'].values())) for r in hw if r['kills'])
    print('人赢第一只的击杀回合分布：' + '，'.join(f"{'火箭' if k[0] == 'ROCKET' else '碾碎爪'} T{k[1]}×{v}" for k, v in sorted(dist.items())) + '\n')

    print('### 3.2 第 4 回合（激光 38）怎么过\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = [r for r in grp(src, 'crab', res) if len(r['turns']) >= 4]
        dead = [r for r in rs if 'ROCKET' not in r['turns'][3]['alive']]
        k4 = [r for r in rs if r['kills'].get('ROCKET') == 4]
        alive = [r['turns'][3] for r in rs if r not in dead and r not in k4]
        hp4 = [r['turns'][3]['alive'].get('ROCKET', 0) for r in rs]
        pots = sum(1 for t in alive if t['pots'])
        rows.append([g, len(rs), m(hp4, '{:.0f}'), pct(sum(1 for x in hp4 if x <= 60), len(hp4)), len(dead), len(k4), len(alive),
                     m([t['blk'] for t in alive]), m([t['loss'] for t in alive]), f'{pots}/{len(alive)}'])
    print(table(['组', '活到第 4 回合', '第 4 回合开始火箭血量（均）', '火箭 ≤60 血的比例', '火箭已死', '本回合打死火箭', '火箭活着挨激光',
                 '挨激光时格挡', '挨激光时掉血', '挨激光时用药水'], rows))
    print()

    print('### 3.3 朝向：回合结束时面朝的是不是「这回合打得重的那只」\n')
    print('「该面朝」按出招表：第 2、4、7、9 回合面朝火箭，其余面朝碾碎爪；只统计回合结束时两只都活着的回合。\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'crab', res)
        byn = collections.defaultdict(lambda: [0, 0])
        for r in rs:
            for t in r['turns']:
                n = t['n']
                if not all(r['kills'].get(x, 99) > n for x in ('CRUSHER', 'ROCKET')): continue
                opt = 'ROCKET' if n % 5 in (2, 4) else 'CRUSHER'
                byn[n][0] += t['face'] == opt; byn[n][1] += 1
        tot = sum(v[0] for v in byn.values()); nn = sum(v[1] for v in byn.values())
        rows.append([g, f'{pct(tot, nn)}（{nn}）'] + [f'{pct(*byn[n])}（{byn[n][1]}）' if byn[n][1] else '—' for n in range(1, 7)])
    print(table(['组', '全部', 'T1 该朝碾碎爪', 'T2 该朝火箭', 'T3 该朝碾碎爪', 'T4 该朝火箭', 'T5 该朝碾碎爪', 'T6 该朝碾碎爪'], rows))
    print()

    print('### 3.4 集火还是平摊、群伤用了多少\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'crab', res)
        share = collections.defaultdict(list); main = []
        for r in rs:
            for t in r['turns'][:5]:
                s = t['dmg_t']['ROCKET'] + t['dmg_t']['CRUSHER']
                if s and len(t['alive']) == 2: share[t['n']].append(t['dmg_t']['ROCKET'] / s)
        aoe_n = sum(n for r in rs for c, n in r['card_n'].items() if isaoe(c))
        aoe_d = sum(d for r in rs for c, d in r['card_dmg'].items() if isaoe(c))
        tot = sum(sum(r['card_dmg'].values()) for r in rs)
        rows.append([g] + [f'{S.mean(share[n]):.0%}' if share[n] else '—' for n in range(1, 6)] + [f'{aoe_n / len(rs):.1f}', pct(aoe_d, tot)])
    print(table(['组', 'T1 打火箭占比', 'T2', 'T3', 'T4', 'T5', '每场群伤张数', '群伤占全部伤害'], rows))
    print()


def section_kd():
    print('## 四、知识恶魔专项\n')
    print('### 4.1 三次诅咒选了什么\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'kd', res)
        cs = [collections.Counter() for _ in range(3)]
        for r in rs:
            for i, (n, c) in enumerate(r['curses'][:3]): cs[i][c] += 1
        rows.append([g, len(rs)] + ['，'.join(f'{k} {v}' for k, v in c.most_common()) or '—' for c in cs])
    print(table(['组', '场数', '①（第 1 回合）', '②（第 5 回合）', '③（第 9 回合）'], rows))
    hum = [r for r in R if r['src'] == 'human' and r['boss'] == 'kd']
    print('\n人类录像（最后一次尝试 + 放弃重来的尝试）按诅咒选择分的结果：\n')
    rows = []
    for i in range(3):
        c = collections.defaultdict(collections.Counter)
        for r in hum:
            if len(r['curses']) > i: c[r['curses'][i][1]][r['result']] += 1
        for k, v in sorted(c.items()):
            tot = sum(v.values())
            rows.append([f'第 {i + 1} 次', k, tot, v['win'], v['loss'], v['retry'], pct(v['win'], tot)])
    print(table(['诅咒', '选了', '次数', '赢', '输', '放弃重来', '赢的比例'], rows))
    print('\n选了懒惰之后（第 6~9 回合）每回合出牌数：\n')
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'kd', res)
        a = [sum(1 for p in t['plays'] if manual(p)) for r in rs for t in r['turns'] if 6 <= t['n'] <= 9 and any(c == 'SLOTH' for _, c in r['curses'])]
        b = [sum(1 for p in t['plays'] if manual(p)) for r in rs for t in r['turns'] if 6 <= t['n'] <= 9 and not any(c == 'SLOTH' for _, c in r['curses'])]
        pre = [sum(1 for p in t['plays'] if manual(p)) for r in rs for t in r['turns'] if 2 <= t['n'] <= 5]
        pre_seen = [len(seen(t, src)) for r in rs for t in r['turns'] if 2 <= t['n'] <= 5]
        rows.append([g, m(pre), pct(sum(1 for x in pre if x > 3), len(pre)), m(pre_seen), f'{m(a)}（{len(a)}）', f'{m(b)}（{len(b)}）'])
    print(table(['组', '第 2~5 回合每回合出牌', '其中出牌 >3 张的回合', '第 2~5 回合每回合见到的牌', '第 6~9 回合·选了懒惰', '第 6~9 回合·没选懒惰'], rows))
    print()

    print('### 4.2 第几回合打完、伤害爆发在哪个回合\n')
    cat = {1: '诅咒', 2: '抽打', 3: '过载', 0: '思考'}
    rows = []
    for g, (src, res) in GROUPS.items():
        rs = grp(src, 'kd', res)
        kt = collections.Counter(r['kills'].get('KNOWLEDGE_DEMON') for r in rs if r['kills'].get('KNOWLEDGE_DEMON'))
        bt = collections.Counter(cat[max(r['turns'], key=lambda t: t['dmg'] + t['dmg_rf'])['n'] % 4] for r in rs)
        by = collections.defaultdict(list)
        for r in rs:
            for t in r['turns']:
                if t['n'] <= 8: by[cat[t['n'] % 4]].append(t)
        rows.append([g, len(rs), '，'.join(f'T{k}×{v}' for k, v in sorted(kt.items())) or '—',
                     '，'.join(f'{k}×{v}' for k, v in bt.most_common()),
                     ' / '.join(f"{k} {m([t['dmg'] + t['dmg_rf'] for t in by[k]], '{:.0f}')}·{m([t['blk'] for t in by[k]], '{:.0f}')}" for k in ('诅咒', '抽打', '过载', '思考'))])
    print(table(['组', '场数', '打完的回合', '伤害最高的回合是哪种招', '四种招的回合（前 8 回合）：伤害·格挡'], rows))
    print()


def section_bigturn():
    print('## 五、大招回合：是牌不够还是没打对\n')
    print('大招回合：帝皇蟹第 2、4 回合（两只都活着、火箭没在本回合死），知识恶魔第 2、3、6、7 回合。'
          '「手里格挡牌」：人类 = 这回合抽到的，我们 = 这回合在手里出现过的（都只数技能类格挡牌）。\n')
    for boss, big in (('crab', (2, 4)), ('kd', (2, 3, 6, 7))):
        print(f'### {BOSS_ZH[boss]}\n')
        rows = []
        for g, (src, res) in GROUPS.items():
            rs = grp(src, boss, res)
            if boss == 'crab':
                ts = [t for r in rs for t in r['turns'] if t['n'] in big and len(t['alive']) == 2 and r['kills'].get('ROCKET', 99) > t['n']]
            else:
                ts = [t for r in rs for t in r['turns'] if t['n'] in big]
            b = collections.defaultdict(list)
            chose_atk = 0
            for t in ts:
                hb = sum(1 for c in seen(t, src) if isblk(c)); pb = sum(1 for p in t['plays'] if isblk(p[0]))
                pa = sum(1 for p in t['plays'] if isatk(p[0]) and manual(p))
                b[min(hb, 3)].append(t)
                chose_atk += (hb - pb >= 1 and pa >= 1)
            rows.append([g, len(ts)] + [f"{m([t['blk'] for t in b[k]], '{:.0f}')} / {m([t['loss'] for t in b[k]])} / {m([t['dmg'] for t in b[k]], '{:.0f}')}（{len(b[k])}）" for k in range(4)]
                        + [pct(chose_atk, len(ts))])
        print(table(['组', '回合数', '格挡牌 0 张：挡/掉/伤', '1 张', '2 张', '3 张以上', '手里有格挡牌没打、却打了攻击'], rows))
        print()
    print('### 每张牌的质量\n')
    rows = []
    for boss in ('crab', 'kd'):
        for g, (src, res) in GROUPS.items():
            rs = grp(src, boss, res)
            cd = collections.Counter(); cb = collections.Counter(); cn = collections.Counter(); nt = 0
            for r in rs:
                cd.update(r['card_dmg']); cb.update(r['card_blk']); cn.update(r['card_n']); nt += len(r['turns'])
            atk = [k for k in cn if isatk(k)]; bl = [k for k in cn if isblk(k)]
            rows.append([BOSS_ZH[boss], g, f"{sum(cd[k] for k in atk) / max(1, sum(cn[k] for k in atk)):.1f}",
                         f"{sum(cb[k] for k in bl) / max(1, sum(cn[k] for k in bl)):.1f}", f'{sum(cn.values()) / max(1, nt):.1f}'])
    print(table(['Boss', '组', '每张攻击牌平均伤害', '每张格挡牌平均格挡（卡牌本身）', '每回合出牌'], rows))
    print('\n（人类的「卡牌格挡」取录像 block 事件里带 card 的；我们取打出这张牌前后格挡的变化，会把同时触发的无惧疼痛等算进去，略偏高。）\n')


def section_potions():
    print('## 六、药水\n')
    rows = []
    for boss in ('crab', 'kd'):
        for g, (src, res) in GROUPS.items():
            rs = grp(src, boss, res)
            used = [p for r in rs for t in r['turns'] for p, _ in t['pots']]
            byt = collections.Counter(min(t['n'], 6) for r in rs for t in r['turns'] for p in t['pots'])
            rows.append([BOSS_ZH[boss], g, len(rs), m([len(r['potions_in']) for r in rs], '{:.2f}'), f'{len(used) / max(1, len(rs)):.2f}',
                         '，'.join(f"T{k if k < 6 else '6+'}×{v}" for k, v in sorted(byt.items())),
                         '，'.join(f'{ZH_POT.get(k, k)}×{v}' for k, v in collections.Counter(used).most_common(6))])
    print(table(['Boss', '组', '场数', '进场带几瓶', '每场用几瓶', '在第几回合用', '用得最多的'], rows))
    print()
    rows = []
    for boss in ('crab', 'kd'):
        for res in ('win', 'loss'):
            rs = [r for r in RS if r['boss'] == boss and r['result'] == res]
            rows.append([BOSS_ZH[boss], '社区' + ('赢' if res == 'win' else '输'), len(rs), m([len(r['pots_used']) for r in rs], '{:.2f}'),
                         m([r['turns'] for r in rs]), m([r['dmg'] for r in rs]),
                         '，'.join(f'{ZH_POT.get(k, k)}×{v}' for k, v in collections.Counter(p for r in rs for p in r['pots_used']).most_common(6))])
    print(table(['Boss', '组', '场数', '每场用几瓶', '打了几回合', '掉血', '用得最多的'], rows))
    print()


def section_cards():
    print('## 七、打出的牌：谁在出伤害、谁在挡\n')
    for boss in ('crab', 'kd'):
        print(f'### {BOSS_ZH[boss]}\n')
        rows = []
        for g in ('人赢', '我们赢', '我们输'):
            src, res = GROUPS[g]; rs = grp(src, boss, res)
            cd = collections.Counter(); cb = collections.Counter(); cn = collections.Counter()
            for r in rs: cd.update(r['card_dmg']); cb.update(r['card_blk']); cn.update(r['card_n'])
            rows.append([g, '，'.join(f'{zh(k)} {v / len(rs):.0f}' for k, v in cd.most_common(8)),
                         '，'.join(f'{zh(k)} {v / len(rs):.0f}' for k, v in cb.most_common(6)),
                         '，'.join(f'{zh(k)} {v / len(rs):.1f}' for k, v in cn.most_common(10))])
        print(table(['组', '每场伤害前 8（点）', '每场格挡前 6（点）', '每场出牌前 10（张）'], rows))
        print()


def section_lift():
    print('## 八、选牌备战：社区大样本里「有这张牌」时的胜率（相关，不是因果）\n')
    for boss in ('crab', 'kd'):
        g = [r for r in RS if r['boss'] == boss]
        wins = sum(r['result'] == 'win' for r in g)
        pres = collections.defaultdict(lambda: [0, 0])
        for r in g:
            for c in set(x.rstrip('+') for x in r['deck']):
                pres[c][0] += 1; pres[c][1] += r['result'] == 'win'
        ours = [r for r in R if r['src'] == 'ours' and r['boss'] == boss]
        op = collections.Counter(c for r in ours for c in set(x.rstrip('+') for x in r['deck']))
        rows = []
        for c, (n, w) in pres.items():
            na = len(g) - n
            if n < 60 or na < 60: continue
            rows.append((w / n - (wins - w) / na, c, n, w / n, (wins - w) / na, op[c] / max(1, len(ours))))
        rows.sort(reverse=True)
        print(f'### {BOSS_ZH[boss]}（社区 {len(g)} 场，基准胜率 {wins / len(g):.0%}；我们 {len(ours)} 场）\n')
        fmt = lambda x: [zh(x[1]), x[2], f'{x[3]:.0%}', f'{x[4]:.0%}', f'{x[0] * 100:+.0f}', f'{x[2] / len(g):.0%}', f'{x[5]:.0%}']
        print(table(['牌', '有的场数', '有时胜率', '没有时胜率', '差（百分点）', '社区出现率', '我们出现率'], [fmt(x) for x in rows[:12]] + [['…'] * 7] + [fmt(x) for x in rows[-10:]]))
        print()


def section_extra():
    import glob, boss_data, boss_turns
    print('## 九、补充\n')
    print('### 9.1 帝皇蟹第 2/4 回合火箭实际打出多少（人类 = 录像里的受击；我们 = 点结束回合时火箭的意图）\n')
    print('基准：光束 20、激光 38（面朝火箭）；背后 ×1.5；虚弱 ×0.75；巨像 + 火箭易伤 ×0.5。\n')
    rows = []
    for T, base in ((2, 20), (4, 38)):
        for g, (src, res) in GROUPS.items():
            xs = []
            if src == 'human':
                for r in grp(src, 'crab', res):
                    if len(r['turns']) >= T and r['turns'][T - 1]['moves'].get('ROCKET') in ('PRECISION_BEAM_MOVE', 'LASER_MOVE'):
                        xs.append(r['turns'][T - 1]['inc_t'].get('ROCKET', 0))
            else:
                for line in open(boss_turns.OURS):
                    rr = json.loads(line)
                    for cb in rr['combats']:
                        if cb['act'] != 2 or cb['room'] != 'Boss' or not ({'Crusher', 'Rocket'} & set(cb['enemies'])): continue
                        res2 = 'win' if (cb is not rr['combats'][-1] or rr['win']) else 'loss'
                        if res2 not in res: continue
                        E = [x for x in rr['trace'] if x.get('d') == 'combat' and x['act'] == 2 and x['floor'] == cb['floor'] and x.get('r') == T]
                        if E:
                            ro = [f for f in E[-1]['foes'] if f[0] == 'Rocket']
                            if ro and ro[0][3]: xs.append(ro[0][3])
            if not xs: continue
            low = sum(1 for x in xs if x < base); half = sum(1 for x in xs if x <= base * 0.5); hi = sum(1 for x in xs if x > base)
            rows.append([f'T{T}（{base}）', g, len(xs), m(xs), f'{low}（{pct(low, len(xs))}）', half, hi])
    print(table(['回合', '组', '次数', '均值', '被压低（<基准）', '其中压到一半以下', '比基准高（背对 / 敌人力量）'], rows))
    print()

    print('### 9.2 人类录像：格挡从哪来、伤害为什么高（只看人赢）\n')
    F = boss_data.load_fights()
    rows = []
    for boss in ('KAISER_CRAB_BOSS', 'KNOWLEDGE_DEMON_BOSS'):
        fs = [f for f in F if f['boss'] == boss and f['result'] == 'win']
        turns = card = other = 0; strs = []; vul_d = tot_d = 0
        for f in fs:
            st = 0; vul = collections.Counter()
            for e in f['ev']:
                t = e['t']
                if t == 'turn' and e.get('side') == 'player': turns += 1
                if t == 'block' and e.get('src') == 'player':
                    n = e.get('n') or 0
                    if e.get('card'): card += n
                    else: other += n
                if t == 'power':
                    if e.get('tgt') == 'IRONCLAD' and e.get('id') == 'STRENGTH_POWER': st += e.get('n') or 0
                    elif e.get('id') == 'VULNERABLE_POWER' and e.get('tgt') not in ('IRONCLAD', None): vul[e['tgt']] += e.get('n') or 0
                if t == 'power_lost' and e.get('id') == 'VULNERABLE_POWER': vul[e.get('tgt')] = 0
                if t == 'hit' and e.get('src') == 'player' and e.get('dst') not in ('player', None) and e.get('card'):
                    a = (e.get('dmg') or 0) + (e.get('blocked') or 0); tot_d += a; strs.append(st)
                    if vul[e['dst']] > 0: vul_d += a
        rows.append([BOSS_ZH['crab' if 'CRAB' in boss else 'kd'], len(fs), f'{card / turns:.1f}', f'{other / turns:.1f}', m(strs), pct(vul_d, tot_d)])
    print(table(['Boss', '场数', '每回合卡牌格挡', '每回合非卡牌格挡（无惧疼痛、覆甲、遗物等）', '打出攻击时自身力量（均）', '打在易伤目标上的攻击伤害占比'], rows))
    print()

    print('### 9.3 知识恶魔诅咒的实际代价\n')
    hum = [r for r in R if r['src'] == 'human' and r['boss'] == 'kd']
    rows = []
    for i, ch in ((0, 'DISINTEGRATION'), (0, 'MIND_ROT'), (1, 'DISINTEGRATION'), (1, 'SLOTH')):
        g = [r for r in hum if len(r['curses']) > i and r['curses'][i][1] == ch]
        lo, hi = (2, 4) if i == 0 else (6, 9)
        ts = [t for r in g for t in r['turns'] if lo <= t['n'] <= hi]
        res = collections.Counter(r['result'] for r in g)
        rows.append([f'人类·第 {i + 1} 次', ch, len(g), f"{res['win']}/{res['loss']}/{res['retry']}", f'T{lo}~T{hi}', m([len(t['hand']) for t in ts]),
                     m([sum(1 for p in t['plays'] if manual(p)) for t in ts]), m([t['dmg'] for t in ts], '{:.0f}'), m([t['blk'] for t in ts], '{:.0f}'),
                     m([t['loss'] for t in ts]), m([t['self_loss'] for t in ts])])
    later = []
    for f in sorted(glob.glob('/opt/slay-the-spire-2/agent/results/bdla2-g[4-9]-*.jsonl')):
        try: later += boss_turns.ours_records(f)
        except Exception: pass
    for lab, recs in (('我们 g3（固定顺序）', [r for r in R if r['src'] == 'ours']), ('我们 g4~（按 12 号规则）', later)):
        kd = [r for r in recs if r['boss'] == 'kd']
        for i, ch in ((0, 'DISINTEGRATION'), (0, 'MIND_ROT')):
            g = [r for r in kd if len(r['curses']) > i and r['curses'][i][1] == ch]
            if not g: continue
            ts = [t for r in g for t in r['turns'] if 2 <= t['n'] <= 8]
            res = collections.Counter(r['result'] for r in g)
            rows.append([lab, ch + '（①）', len(g), f"{res['win']}/{res['loss']}/0", 'T2~T8', m([len(t['hand_all']) for t in ts]),
                         m([len(t['plays']) for t in ts]), m([t['dmg'] + t['dmg_rf'] for t in ts], '{:.0f}'), m([t['blk'] for t in ts], '{:.0f}'),
                         m([t['loss'] for t in ts]), m([t['self_loss'] for t in ts])])
    print(table(['来源', '选了', '场数', '赢/输/重来', '统计回合', '每回合见到的牌', '每回合出牌', '伤害', '格挡', '每轮掉血', '其中自己回合掉血'], rows))
    print('\n（我们的「自己回合掉血」只数出牌之间的掉血；瓦解在点结束回合后结算，算在「每轮掉血」里。g4~ 指 bdla2-g4/g5/g6 这几批，'
          '配置和 g3 不同（选牌、留牌等也改了），跨代比较只作参考。）\n')


def section_misc():
    import boss_data
    print('### 9.4 正文引用的零散数字\n')
    F = boss_data.load_fights()
    # 1) 打死第一只那回合往另一只 99 格挡里打的伤害（人类）
    ws = []
    for f in F:
        if f['boss'] != 'KAISER_CRAB_BOSS' or f['result'] != 'win': continue
        dead = None; w = 0
        for e in f['ev']:
            if e['t'] == 'turn' and e.get('side') == 'enemy' and dead: break
            if e['t'] == 'hit' and e.get('src') == 'player' and e.get('dst') in ('CRUSHER', 'ROCKET'):
                if dead and e['dst'] != dead: w += e.get('blocked') or 0
                if e.get('killed') and not dead: dead = e['dst']
        if dead: ws.append(w)
    print(f'- 帝皇蟹人赢：打死第一只那回合，之后打进另一只格挡（蟹之怒 99）的伤害 平均 {S.mean(ws):.1f}，{sum(1 for x in ws if x > 0)}/{len(ws)} 场有\n')
    # 2) 人赢第 4 回合（火箭活着、本回合没死）打的牌；本回合打死火箭时掉血
    hw = grp('human', 'crab', ('win',))
    alive4 = [r['turns'][3] for r in hw if len(r['turns']) >= 4 and 'ROCKET' in r['turns'][3]['alive'] and r['kills'].get('ROCKET') != 4]
    k4 = [r['turns'][3] for r in hw if r['kills'].get('ROCKET') == 4]
    cc = collections.Counter(p[0] for t in alive4 for p in t['plays'])
    print(f'- 帝皇蟹人赢第 4 回合火箭活着（{len(alive4)} 回合）打的牌：' + '，'.join(f'{zh(k)} {v}' for k, v in cc.most_common(8))
          + f'；第 4 回合打死火箭的 {len(k4)} 场这回合平均掉血 {m([t["loss"] for t in k4])}\n')
    # 3) 我们：防御类药水带了没有、第 4 回合前喝掉没有
    DEF = {'WEAK_POTION', 'BLOCK_POTION', 'DEXTERITY_POTION', 'VULNERABLE_POTION', 'LIQUID_BRONZE', 'FORTIFIER', 'GHOST_IN_A_JAR', 'STABLE_SERUM', 'SHACKLING_POTION'}
    for res in ('win', 'loss'):
        g = grp('ours', 'crab', (res,))
        had = [r for r in g if any(p in DEF for p in r['potions_in'])]
        early = [r for r in had if any(p in DEF for t in r['turns'] if t['n'] < 4 for p, _ in t['pots'])]
        print(f'- 帝皇蟹我们{"赢" if res == "win" else "输"} {len(g)} 局：进场带防御类药水 {len(had)} 局，其中第 4 回合前就喝掉 {len(early)} 局；'
              + '带的是 ' + '，'.join(f'{ZH_POT.get(k, k)}×{v}' for k, v in collections.Counter(p for r in had for p in r['potions_in'] if p in DEF).most_common()) + '\n')
    # 4) 第 1 回合手里有能力牌时当回合打出的比例
    for boss in ('crab', 'kd'):
        out = []
        for g, (src, res) in GROUPS.items():
            held = t1 = 0
            for r in grp(src, boss, res):
                t = r['turns'][0]
                if any(ctype(c) == 'Power' for c in seen(t, src)):
                    held += 1; t1 += any(ctype(p[0]) == 'Power' for p in t['plays'])
            out.append(f'{g} {t1}/{held}（{pct(t1, held)}）')
        print(f'- {BOSS_ZH[boss]}第 1 回合手里有能力牌、当回合就打出：' + '，'.join(out) + '\n')
    # 5) 我们第一只的击杀回合
    for res in ('win', 'loss'):
        g = [r for r in grp('ours', 'crab', (res,)) if r['kills']]
        d = collections.Counter((min(r['kills'], key=lambda x: r['kills'][x]), min(r['kills'].values())) for r in g)
        print(f'- 帝皇蟹我们{"赢" if res == "win" else "输"}第一只的击杀回合：' + '，'.join(f"{'火箭' if k[0] == 'ROCKET' else '碾碎爪'} T{k[1]}×{v}" for k, v in sorted(d.items())) + '\n')
    # 6) 人类选懒惰 / 瓦解（第 2 次）之前每回合出牌
    hum = [r for r in R if r['src'] == 'human' and r['boss'] == 'kd']
    for ch in ('DISINTEGRATION', 'SLOTH'):
        g = [r for r in hum if len(r['curses']) >= 2 and r['curses'][1][1] == ch]
        pre = [sum(1 for p in t['plays'] if manual(p)) for r in g for t in r['turns'] if 2 <= t['n'] <= 5]
        print(f'- 知识恶魔人类第 2 次选 {ch} 的 {len(g)} 场：选之前（第 2~5 回合）每回合出牌 {m(pre)}\n')
    # 7) 敌人出招时身上带虚弱的比例（人赢）
    for boss in ('KAISER_CRAB_BOSS', 'KNOWLEDGE_DEMON_BOSS'):
        wt = et = 0
        for f in F:
            if f['boss'] != boss or f['result'] != 'win': continue
            weak = collections.Counter()
            for e in f['ev']:
                if e['t'] == 'power' and e.get('id') == 'WEAK_POWER' and e.get('tgt') not in ('IRONCLAD', None): weak[e['tgt']] += e.get('n') or 0
                if e['t'] == 'power_lost' and e.get('id') == 'WEAK_POWER': weak[e.get('tgt')] = 0
                if e['t'] == 'move' and e.get('src') not in (None, 'player'):
                    et += 1; wt += weak[e['src']] > 0
        print(f'- {BOSS_ZH["crab" if "CRAB" in boss else "kd"]}人赢：敌人出招时身上带虚弱 {pct(wt, et)}（{et} 次出招）\n')
    # 8) 朝向推断核对：第 1 回合撕扯 / 瞄准的实际伤害
    c = collections.Counter()
    for r in R:
        if r['src'] == 'human' and r['boss'] == 'crab' and r['turns'] and r['turns'][0]['moves'].get('CRUSHER') == 'THRASH_MOVE':
            t = r['turns'][0]; c[(t['face'], t['inc_t'].get('CRUSHER'), t['inc_t'].get('ROCKET'))] += 1
    print('- 朝向推断核对（人类第 1 回合：推断的朝向，碾碎爪撕扯实际伤害，火箭瞄准实际伤害）：' + '，'.join(f'{k}×{v}' for k, v in c.most_common(6)) + '\n')


if __name__ == '__main__':
    print('# 第二幕 Boss 研究 · 数据表（boss_report.py 生成）\n')
    section_samples(); section_entry(); section_turns(); section_crab(); section_kd(); section_bigturn(); section_potions(); section_cards(); section_lift(); section_extra(); section_misc()
