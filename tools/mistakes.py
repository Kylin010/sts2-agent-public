"""自动查失误：读带 trace 的对局（results/*.jsonl 或 lab/trace*/种子.json），赢的局和输的局分开统计每类失误，并列出例子。

用法：python3 tools/mistakes.py results/某批.jsonl [lab/trace-10/*.json ...] [--out reports/失误.md] [--examples 8]


失误类型（规则判断，不一定每条都错，但值得看）：
  战斗：剩能量还有能打的牌就结束回合 / 敌人要打很多、手里有防御牌却没挡（能量全用在攻击上）/ 死的时候药没喝完
  路线：有钱（≥150）有商店却不去 / 血量高（≥70%）有精英却绕开 / 幕末还攒着很多钱
  商店：带着很多钱出店、牌组还有打击防御却不删牌
  篝火：血量高还回血（浪费升级）/ 血量低进 Boss 前还升级
  事件：血量低（<50%）还花血换东西
  选牌：一张不拿（跳过）的次数，别家角色的牌全跳过
"""
import argparse, collections, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zh
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = json.load(open(f'{HERE}/kb/cards.json'))
EN2ID = json.load(open(f'{HERE}/kb/names_en.json'))['cards']
BASIC = {'Strike', 'Defend'}


def kb_card(name):
    i = EN2ID.get(str(name).rstrip('+'))
    return KB.get(i, {}) if i else {}


def is_block(name):
    c = kb_card(name); return (c.get('block') or 0) > 0 and c.get('type') != 'Power'


def is_junk(name):
    c = kb_card(name); return c.get('type') in ('Curse', 'Status') or not c


def load(paths):
    rs = []
    for p in paths:
        for f in sorted(glob.glob(p)):
            if f.endswith('.jsonl'):
                rs += [json.loads(l) for l in open(f)]
            else:
                rs.append(json.load(open(f)))
    return [r for r in rs if r.get('trace')]


def check(r):
    """一局 → [(类型, 说明)]"""
    out = []; t = r['trace']; won = bool(r.get('win'))
    deck_basic = 4
    # —— 战斗 ——
    for i, x in enumerate(t):
        if x['d'] != 'combat' or x.get('a') != 'end_turn': continue
        en = x.get('en') or 0; hand = x.get('hand') or []; np_ = set(x.get('np') or [])
        cost = x.get('cost') or [kb_card(h).get('cost') for h in hand]      # 旧记录没有费用：按知识库的基础费用
        inc = sum(max(0, f[3] or 0) for f in x.get('foes') or []); blk = x.get('blk') or 0
        playable = [(h, c) for j, (h, c) in enumerate(zip(hand, cost)) if j not in np_ and c is not None and 0 <= c <= en and not is_junk(h)]
        where = f"{x['act']}-{x['floor']} 第{x.get('r')}回合"
        if en > 0 and playable:
            blk_left = [h for h, _ in playable if is_block(h)]
            if blk_left and inc > blk:
                out.append(('战斗：敌人要打、剩能量和防御牌却结束回合', f"{where}：要挨 {inc}、挡 {blk}、剩 {en} 能量，没打 {'、'.join(zh.card(h) for h in blk_left)}"))
            else:
                out.append(('战斗：剩能量还有能打的牌就结束回合', f"{where}：剩 {en} 能量，没打 {'、'.join(zh.card(h) for h, _ in playable)}"))
        if inc >= 12 and blk < inc * 0.5:
            # 这回合开始时手里有没有防御牌（同一回合第一条记录）
            first = next((y for y in t[max(0, i - 12):i + 1] if y['d'] == 'combat' and (y['act'], y['floor'], y.get('r')) == (x['act'], x['floor'], x.get('r'))), x)
            had = [h for h in first.get('hand') or [] if is_block(h)]
            if had:
                out.append(('战斗：挨重击只挡不到一半（手里有防御牌）', f"{where}：要挨 {inc}、只挡 {blk}；回合开始手里有 {'、'.join(zh.card(h) for h in had)}"))
    if not won:
        last = next((x for x in reversed(t) if x['d'] == 'combat'), None)
        if last and last.get('pots'):
            out.append(('战斗：死的时候药没喝完', f"{last['act']}-{last['floor']}：还剩 {'、'.join(zh.potion(p) for p in last['pots'])}"))
    # —— 路线 / 商店 / 篝火 / 事件 / 选牌 ——
    for i, x in enumerate(t):
        d = x['d']; hp, mx, gold = x.get('hp') or 0, x.get('max_hp') or 1, x.get('gold') or 0
        hpf = hp / mx; where = f"{x['act']}-{x['floor']}"
        if d == 'map_select':
            opts = x.get('opts') or []; a = x.get('args') or {}
            ch = next((o[0] for o in opts if o[1] == a.get('col') and o[2] == a.get('row')), None)
            types = {o[0] for o in opts}
            if 'Shop' in types and ch != 'Shop' and gold >= 150:
                out.append(('路线：有钱（≥150）有商店却不去', f"{where}：带 {gold} 金，去了 {zh_room(ch)}"))
            rd = x.get('ready')
            if 'Elite' in types and ch != 'Elite' and (rd[0] >= rd[1] if rd else hpf >= 0.7):
                out.append(('路线：分数够（或血 ≥70%）有精英却绕开', f"{where}：血 {hp}/{mx}{f'，准备度 {rd[0]:.0f}/精英线 {rd[1]}' if rd else ''}，去了 {zh_room(ch)}"))
            if rd and ch == 'Elite' and rd[0] < rd[1]:
                out.append(('路线：分数不够还去打精英', f"{where}：血 {hp}/{mx}，准备度 {rd[0]:.0f}/精英线 {rd[1]}"))
            if ch == 'Boss' and gold >= 250:
                out.append(('路线：带着很多钱进 Boss（没花掉）', f"{where}：{gold} 金"))
        elif d == 'shop' and x.get('a') == 'leave_room' and gold >= 150:
            out.append(('商店：带着 ≥150 金出店', f"{where}：剩 {gold} 金（删牌 {x.get('remove_cost')}）"))
        elif d == 'rest_site':
            opts = x.get('opts') or []; k = (x.get('args') or {}).get('option_index', 0); ch = opts[k] if k < len(opts) else ''
            if ch == 'HealRestSiteOption' and hpf >= 0.7:
                out.append(('篝火：血量 ≥70% 还回血（少一次升级）', f"{where}：血 {hp}/{mx}"))
        elif d == 'event_choice':
            name, zo = zh.event(x.get('opts') or [])
            k = (x.get('args') or {}).get('option_index', 0); txt = zo[k] if k < len(zo) else ''
            m = re.search(r'失去(\d+)点生命|受到(\d+)点伤害', txt)
            if m and hpf < 0.5:
                out.append(('事件：血量 <50% 还花血换东西', f"{where} {name}：血 {hp}/{mx}，选了「{txt[:30]}」"))
        elif d == 'card_reward' and x.get('a') != 'select_card_reward':
            opts = x.get('opts') or []
            off = [o for o in opts if not kb_card(o) or kb_card(o).get('color') not in ('ironclad', 'colorless', 'event')]   # 知识库里没有的 = 别家角色的牌
            kind = '选牌：别家角色的牌全跳过' if opts and len(off) == len(opts) else '选牌：跳过'
            out.append((kind, f"{where}：{'、'.join(zh.card(o) for o in opts)}"))
    return out


def zh_room(t):
    return {'Monster': '普通战', 'Elite': '精英', 'RestSite': '篝火', 'Shop': '商店', 'Unknown': '问号', 'Treasure': '宝箱', 'Boss': 'Boss'}.get(t, t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+'); ap.add_argument('--out', default=None); ap.add_argument('--examples', type=int, default=6)
    a = ap.parse_args()
    rs = load(a.paths)
    groups = {'赢（打完目标幕）': [r for r in rs if r.get('win')], '输': [r for r in rs if not r.get('win')]}
    lines = [f'# 失误统计（{len(rs)} 局带记录：赢 {len(groups["赢（打完目标幕）"])}，输 {len(groups["输"])}）', '']
    allk = collections.OrderedDict()
    per = {}
    for g, grp in groups.items():
        c = collections.Counter(); ex = collections.defaultdict(list)
        for r in grp:
            for k, s in check(r):
                c[k] += 1; allk[k] = 1
                if len(ex[k]) < a.examples: ex[k].append(f"{r.get('seed')} {s}")
        per[g] = (c, ex, len(grp))
    lines.append('| 失误 | ' + ' | '.join(f'{g}（每局几次）' for g in groups) + ' |')
    lines.append('|---|' + '---|' * len(groups))
    for k in sorted(allk, key=lambda k: -sum(per[g][0][k] for g in groups)):
        lines.append(f'| {k} | ' + ' | '.join(f"{per[g][0][k]}（{per[g][0][k] / max(per[g][2], 1):.1f}）" for g in groups) + ' |')
    for g in groups:
        c, ex, n = per[g]
        lines += ['', f'## {g}：例子']
        for k, _ in c.most_common():
            lines.append(f'- **{k}**（{c[k]} 次）')
            lines += [f'  - {e}' for e in ex[k]]
    text = '\n'.join(lines)
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True); open(a.out, 'w').write(text)
    print(text)


if __name__ == '__main__':
    main()
