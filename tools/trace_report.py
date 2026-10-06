"""把 tools/trace_game.py 记下的一局做成中文页面：每一层做了什么（地图、事件、选牌、商店、篝火、战斗逐回合），最后的牌组和遗物。

用法：python3 tools/trace_report.py lab/trace/种子.json [更多…] --out reports/两局.html
"""
import argparse, collections, html, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zh
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOM = {'Monster': '普通战', 'Elite': '精英', 'RestSite': '篝火', 'Shop': '商店', 'Unknown': '问号', 'Treasure': '宝箱', 'Boss': 'Boss'}
REST = {'HealRestSiteOption': '休息（回 30% 血）', 'SmithRestSiteOption': '锻造（升级一张牌）', 'LiftRestSiteOption': '举重（+力量）',
        'DigRestSiteOption': '挖掘（拿遗物）', 'TokeRestSiteOption': '删牌', 'RecallRestSiteOption': '回忆'}
E = html.escape
CARD_TYPE = {'Attack': '攻击', 'Skill': '技能', 'Power': '能力', 'Curse': '诅咒', 'Status': '状态'}


def cards_zh(ns):
    return '、'.join(zh.card(n) for n in ns)


def fight_block(items, info, fatal):
    """一场战斗：逐回合（回合开始的状态 + 这回合打了什么）"""
    first = items[0]
    foes0 = first.get('foes') or []
    name = ' + '.join(f'{k}×{v}' if v > 1 else k for k, v in collections.Counter(zh.monster(f[0]) for f in foes0).items())
    hp0 = first.get('hp')
    if info: head = f"{name}：血 {hp0} → {info['hp']}（掉 {info['dmg']}），{info['rounds']} 回合"
    else: head = f"{name}：血 {hp0} 进场，<b>死在这一场</b>"
    pots = [it.get('potion') for it in items if it.get('a') == 'use_potion']
    if pots: head += f"，喝药：{E('、'.join(zh.potion(p) if isinstance(p, str) else str(p) for p in pots))}"
    rows = []; cur_r = None; plays = []; start = None

    def flush():
        if start is None: return
        foes = '；'.join(f"{zh.monster(f[0])} {f[1]}{f'+挡{f[2]}' if f[2] else ''}，意图 {f[3]}" for f in start.get('foes') or [])
        rows.append(f"<tr><td>{start.get('r')}</td><td>{start.get('hp')}{f'（挡 {start.get('blk')}）' if start.get('blk') else ''}</td>"
                    f"<td>{E(foes)}</td><td>{E(cards_zh(start.get('hand') or []))}</td><td>{E(' → '.join(plays))}</td></tr>")
    for it in items:
        if it['d'] == 'combat' and it.get('r') != cur_r:
            flush(); cur_r = it.get('r'); start = it; plays = []
        a = it.get('a')
        if a == 'play_card':
            plays.append(zh.card(it.get('card')) + (f"（打{zh.monster(it['tgt'])}）" if it.get('tgt') and len(it.get('foes') or []) > 1 else ''))
        elif a == 'use_potion':
            plays.append('喝 ' + (zh.potion(it['potion']) if isinstance(it.get('potion'), str) else '药水'))
        elif a == 'end_turn':
            plays.append('结束回合')
        elif it['d'] == 'combat_select':
            ch = [it['opts'][int(i)] for i in str((it.get('args') or {}).get('indices', '')).split(',') if i.strip().isdigit() and int(i) < len(it.get('opts') or [])]
            plays.append(f"（从 {cards_zh(it.get('opts') or [])} 里选了 {cards_zh(ch) or '无'}）")
    flush()
    return (f"<details class='fight{' fatal' if fatal else ''}'{' open' if fatal else ''}><summary>⚔ {head}</summary>"
            f"<table class='turns'><tr><th>回合</th><th>我的血</th><th>敌人（血 / 挡 / 这回合要打多少）</th><th>手牌</th><th>这回合打了</th></tr>{''.join(rows)}</table></details>")


def floor_html(items, combats, room, fatal_floor):
    out = []; i = 0
    while i < len(items):
        it = items[i]; d = it['d']
        if d in ('combat', 'combat_select'):
            j = i
            while j < len(items) and items[j]['d'] in ('combat', 'combat_select'): j += 1
            info = combats.get((it['act'], it['floor']))
            out.append(fight_block(items[i:j], info, fatal_floor and info is None)); i = j; continue
        if d == 'event_choice':
            opts = it.get('opts') or []
            name, zo = zh.event(opts)
            k = (it.get('args') or {}).get('option_index', 0)
            out.append(f"<div class='ev'>❓ <b>{E(name)}</b>：选了「{E(zo[k] if k < len(zo) else str(k))}」"
                       f"<div class='opts'>可选：{'<br>'.join(E(x) for x in zo)}</div></div>")
            while i + 1 < len(items) and items[i + 1]['d'] == 'event_choice' and items[i + 1].get('opts') == opts and items[i + 1].get('args') == it.get('args'):
                i += 1                                       # 同一页面重复点击（多步事件）只显示一次
        elif d == 'card_reward':
            opts = it.get('opts') or []
            if it['a'] == 'select_card_reward':
                k = (it.get('args') or {}).get('card_index', 0)
                out.append(f"<div>🃏 选牌：{E(cards_zh(opts))} → <b>拿了 {E(zh.card(opts[k]) if k < len(opts) else '?')}</b></div>")
            else:
                out.append(f"<div>🃏 选牌：{E(cards_zh(opts))} → <b>跳过</b></div>")
        elif d == 'card_select':
            opts = it.get('opts') or []
            ch = [opts[int(x)] for x in str((it.get('args') or {}).get('indices', '')).split(',') if x.strip().isdigit() and int(x) < len(opts)]
            prev = items[i - 1]['d'] if i else ''
            why = {'rest_site': '升级', 'shop': '删牌'}.get(prev, '选牌（事件 / 遗物效果）')
            out.append(f"<div>✂ {why}：<b>{E(cards_zh(ch) or '无')}</b><span class='mute'>（可选 {len(opts)} 张）</span></div>")
        elif d == 'rest_site':
            opts = it.get('opts') or []; k = (it.get('args') or {}).get('option_index', 0)
            out.append(f"<div>🔥 篝火：<b>{E(REST.get(opts[k], opts[k]) if k < len(opts) else '?')}</b>"
                       f"<span class='mute'>（血 {it.get('hp')}/{it.get('max_hp')}）</span></div>")
        elif d == 'shop':
            j = i
            while j < len(items) and items[j]['d'] in ('shop', 'card_select'): j += 1
            seq = items[i:j]; shelf = seq[0].get('opts') or {}
            after_all = items[j] if j < len(items) else None          # 商店之后的第一条记录（算最后一次购买花了多少钱）
            acts = []
            for x, nxt in zip(seq, seq[1:] + [after_all]):
                a = x.get('a')
                if a in ('buy_card', 'buy_relic', 'buy_potion'):
                    k = {'buy_card': 'cards', 'buy_relic': 'relics', 'buy_potion': 'potions'}[a]
                    f = {'cards': zh.card, 'relics': zh.relic, 'potions': zh.potion}[k]
                    have = (x.get('opts') or {}).get(k, [])
                    spent = (x.get('gold') or 0) - (nxt.get('gold') or 0) if nxt and nxt.get('gold') is not None else None
                    idx = (x.get('args') or {}).get({'cards': 'card_index', 'relics': 'relic_index', 'potions': 'potion_index'}[k])
                    got = [have[idx]] if isinstance(idx, int) and idx < len(have) else []     # 先按下标
                    if spent is not None and (not got or got[0][1] != spent):                # 下标对不上价钱（货架有卖空的格子）→ 按花掉的金币找
                        got = [y for y in have if y[1] == spent][:1] or got
                    acts.append('买了 ' + ('、'.join(f'{f(n)}（{c}）' for n, c in got) or '?'))
                elif a == 'remove_card':
                    acts.append(f"删牌（{x.get('remove_cost')} 金）")
                elif x['d'] == 'card_select':
                    o = x.get('opts') or []
                    ch = [o[int(q)] for q in str((x.get('args') or {}).get('indices', '')).split(',') if q.strip().isdigit() and int(q) < len(o)]
                    acts.append(f"删掉 {cards_zh(ch)}")
            sh = []
            for k, f, lab in (('cards', zh.card, '牌'), ('relics', zh.relic, '遗物'), ('potions', zh.potion, '药水')):
                if shelf.get(k): sh.append(f"{lab}：" + '、'.join(f'{f(n)} {c}' for n, c in shelf[k]))
            if seq[0].get('remove_cost'): sh.append(f"删牌 {seq[0]['remove_cost']}")
            out.append(f"<div class='ev'>🛒 <b>商店</b>（带着 {seq[0].get('gold')} 金）：<b>{E('；'.join(acts) or '什么都没买')}</b>"
                       f"<div class='opts'>{'<br>'.join(E(x) for x in sh)}</div></div>")
            i = j; continue
        elif d == 'map_select':
            opts = it.get('opts') or []; a = it.get('args') or {}
            ch = next((o[0] for o in opts if o[1] == a.get('col') and o[2] == a.get('row')), '?')
            alt = sorted({ROOM.get(o[0], o[0]) for o in opts})
            rd = it.get('ready')
            sc = f"（准备度 {rd[0]:.0f} 分；精英线 {rd[1]}、战斗线 {rd[2]}" if rd else ''
            if rd and len(rd) > 3 and rd[3]: sc += '；下一个精英 ' + '、'.join(f'{k} {v:.0%}' for k, v in rd[3].items())
            if rd and len(rd) > 4: sc += f'；群伤能力 {rd[4]:.2f}'
            if it.get('combos'): sc += '；联动：' + '、'.join(it['combos'])
            if rd: sc += '）'
            out.append(f"<div class='mute'>🗺 下一步：{'、'.join(alt)} → 去 <b>{ROOM.get(ch, ch)}</b>{sc}</div>")
        i += 1
    return '\n'.join(out)


def game_html(r):
    tr = r.get('trace') or []
    combats = {(c['act'], c['floor']): c for c in r.get('combats') or []}
    floors = collections.OrderedDict()
    for it in tr: floors.setdefault((it['act'], it['floor']), []).append(it)
    room_of = {}; prev = None
    for (a, f), items in floors.items():           # 这一层是什么房间：上一层的地图选择决定
        if prev:
            m = [x for x in floors[prev] if x['d'] == 'map_select']
            if m:
                o = m[-1]; ch = next((q[0] for q in o.get('opts') or [] if q[1] == o['args'].get('col') and q[2] == o['args'].get('row')), None)
                room_of[(a, f)] = ROOM.get(ch, ch)
        prev = (a, f)
    last = list(floors)[-1] if floors else None
    if r.get('win'): res = '通关' if not r.get('cleared') else f"打完第 {r['cleared']} 幕"
    elif 'crash' in r: res = '崩溃：' + r['crash'][:100]
    else: res = f"死在第 {r.get('act')} 幕第 {r.get('floor')} 层（{ROOM.get(r.get('room'), r.get('room'))}：{' + '.join(zh.monster(x) for x in r.get('enemies') or [])}）"
    deck = r.get('deck') or []
    groups = collections.defaultdict(collections.Counter)
    for c in sorted(deck, key=lambda c: ['攻击', '技能', '能力', '诅咒', '状态', '其他'].index(zh.card_type_id(c)) if zh.card_type_id(c) in ('攻击', '技能', '能力', '诅咒', '状态', '其他') else 9):
        groups[zh.card_type_id(c)][zh.card_id(c)] += 1
    deck_html = ''.join(f"<div><b>{t}</b>（{sum(g.values())}）：{E('、'.join(f'{k}×{v}' if v > 1 else k for k, v in g.most_common()))}</div>" for t, g in groups.items())
    rel_html = ''.join(f"<li><b>{E(zh.relic_id(x))}</b>：{E(zh.relic_id_text(x))}</li>" for x in r.get('relics') or [])
    body = []; mx = g = None
    for (a, f), items in floors.items():
        hp = items[0].get('hp')                       # 战斗层的第一条是战斗记录，没有上限血和金币：沿用上一层的
        mx = items[0].get('max_hp') or mx; g = items[0]['gold'] if items[0].get('gold') is not None else g
        rm = room_of.get((a, f)) or ('开局' if f <= 1 and a == 1 else '')
        body.append(f"<section{' class=fatal-floor' if (a, f) == last and not r.get('win') else ''}><h3>第 {a} 幕 第 {f} 层 <span class='room'>{E(rm)}</span>"
                    f"<span class='mute'>　血 {hp}/{mx} · 金 {g}</span></h3>{floor_html(items, combats, rm, (a, f) == last and not r.get('win'))}</section>")
    return (f"<article><h2>种子 {E(str(r.get('seed')))}：{E(res)}</h2>"
            f"<details open><summary><b>最后的牌组（{len(deck)} 张，升级 {sum(1 for c in deck if c.endswith('+'))}）和遗物（{len(r.get('relics') or [])} 个）</b></summary>"
            f"<div class='deck'>{deck_html}</div><ul class='relics'>{rel_html}</ul></details>{''.join(body)}</article>")


CSS = """:root{--bg:#f7f6f3;--card:#fff;--ink:#1f1f1d;--mute:#6b6a66;--line:#e4e2dc;--bad:#c2410c;--accent:#1d4ed8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--card:#1f1f1d;--ink:#ecebe7;--mute:#a3a29d;--line:#34332f;--bad:#fb923c;--accent:#93c5fd}}
:root[data-theme="dark"]{--bg:#161615;--card:#1f1f1d;--ink:#ecebe7;--mute:#a3a29d;--line:#34332f;--bad:#fb923c;--accent:#93c5fd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans SC",system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px}h2{font-size:18px;margin:36px 0 10px;padding-top:12px;border-top:2px solid var(--line)}
h3{font-size:15px;margin:0 0 6px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0}
section.fatal-floor{border-color:var(--bad)}.room{color:var(--accent);margin-left:6px}.mute,.opts{color:var(--mute);font-size:13px}.opts{margin:2px 0 4px 20px}
details{margin:4px 0}summary{cursor:pointer}.fight.fatal>summary{color:var(--bad);font-weight:600}
.turns{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0;display:block;overflow-x:auto}.turns td,.turns th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.turns th{color:var(--mute);font-weight:500;white-space:nowrap}.turns td:first-child,.turns td:nth-child(2){white-space:nowrap}.deck div{margin:3px 0}.relics{margin:6px 0;padding-left:20px;font-size:14px}
.ev{margin:3px 0}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+'); ap.add_argument('--out', default=f'{HERE}/reports/单局.html'); ap.add_argument('--title', default='单局详细记录')
    ap.add_argument('--note', default='')
    a = ap.parse_args()
    games = [json.load(open(p)) for p in a.paths]
    page = (f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{E(a.title)}</title><style>{CSS}</style></head><body><main><h1>{E(a.title)}</h1><p class='mute'>{E(a.note)}</p>"
            + ''.join(game_html(r) for r in games) + '</main></body></html>')
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w').write(page); print(a.out)


if __name__ == '__main__':
    main()
