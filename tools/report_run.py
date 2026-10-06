"""把一批整局结果（results/*.jsonl）做成一页中文报告，方便逐局翻看。

用法：python3 tools/report_run.py results/fresh300-hp80.jsonl --title "新种子测试（301~400）" [--out reports/xxx.html]
内容：总览（过第一 / 二幕、赢、死在哪、死在谁手里）+ 每局一行（点开看牌组、遗物、每场战斗掉血）。
注意：每局的 combats 只记打赢的战斗，最后输掉的那一场在 act / floor / room / enemies 里。
"""
import argparse, collections, html, json, os, re
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
CARDS = json.load(open(f'{HERE}/kb/cards.json'))
RELICS = json.load(open(f'{HERE}/kb/relics.json'))
MON = {m['id']: m['name'] for m in json.load(open(f'{ROOT}/sources/spire-codex/data-beta/v0.111.0/zhs/monsters.json'))}
MON_FIX = {'Decimillipede': 'DECIMILLIPEDE_SEGMENT', 'Battle Friend V3.0': 'BATTLE_FRIEND_V3', 'Battle Friend V2.0': 'BATTLE_FRIEND_V2',
           'Battle Friend V1.0': 'BATTLE_FRIEND_V1'}
ROOM = {'Monster': '普通战', 'Elite': '精英', 'Boss': 'Boss'}


def mon(n):
    i = MON_FIX.get(n) or re.sub(r'[^A-Z0-9]+', '_', n.upper()).strip('_')
    if i not in MON and n.endswith('Raider'): i = n.split()[0].upper() + '_RUBY_RAIDER'
    return MON.get(i, n)


def enemies(es):
    c = collections.Counter(mon(e) for e in es or [])
    return ' + '.join(f'{k}×{v}' if v > 1 else k for k, v in c.items()) or '—'


def card(c):
    up = c.endswith('+'); b = c.rstrip('+')
    return (CARDS.get(b, {}).get('name') or b) + ('+' if up else '')


def deck(d):
    c = collections.Counter(card(x) for x in d or [])
    return '、'.join(f'{k}×{v}' if v > 1 else k for k, v in sorted(c.items(), key=lambda t: (-t[1], t[0])))


def relic(r):
    return RELICS.get(r, {}).get('name') or r


def outcome(r):
    if 'crash' in r: return '崩溃', 'crash'
    if r.get('win'): return '通关', 'win'
    a, f = r.get('act') or 1, r.get('floor') or 0
    return f'死在第 {a} 幕第 {f} 层（{ROOM.get(r.get("room"), r.get("room") or "?")}）', f'a{a}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path'); ap.add_argument('--title', default='对局报告'); ap.add_argument('--out', default=None)
    ap.add_argument('--note', default='')
    a = ap.parse_args()
    rs = [json.loads(l) for l in open(a.path)]
    ok = [r for r in rs if 'crash' not in r]; n = len(ok)
    a1 = sum(1 for r in ok if r.get('win') or (r.get('act') or 1) >= 2)
    a2 = sum(1 for r in ok if r.get('win') or (r.get('act') or 1) >= 3)
    w = sum(bool(r.get('win')) for r in ok)
    dead = [r for r in ok if not r.get('win')]
    by_room = collections.Counter((r.get('act'), r.get('room')) for r in dead)
    by_who = collections.Counter(enemies(r.get('enemies')) for r in dead)
    el1 = [sum(1 for c in r.get('combats') or [] if c['act'] == 1 and c['room'] == 'Elite') for r in ok]

    def stat(label, v, sub=''):
        return f'<div class="stat"><div class="v">{v}</div><div class="l">{label}</div><div class="s">{sub}</div></div>'

    out = [f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(a.title)}</title><style>
:root{{--bg:#f7f6f3;--card:#fff;--ink:#1f1f1d;--mute:#6b6a66;--line:#e4e2dc;--a1:#c2410c;--a2:#b45309;--a3:#4d7c0f;--win:#15803d;--accent:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161615;--card:#1f1f1d;--ink:#ecebe7;--mute:#a3a29d;--line:#34332f;--a1:#fb923c;--a2:#fbbf24;--a3:#a3e635;--win:#4ade80;--accent:#93c5fd}}}}
:root[data-theme="dark"]{{--bg:#161615;--card:#1f1f1d;--ink:#ecebe7;--mute:#a3a29d;--line:#34332f;--a1:#fb923c;--a2:#fbbf24;--a3:#a3e635;--win:#4ade80;--accent:#93c5fd}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"PingFang SC","Noto Sans SC",system-ui,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:20px 16px 60px}}h1{{font-size:22px;margin:4px 0 4px}}h2{{font-size:17px;margin:28px 0 10px}}
.note{{color:var(--mute);font-size:13px}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:16px 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}.stat .v{{font-size:26px;font-weight:650}}.stat .l{{font-size:13px}}.stat .s{{font-size:12px;color:var(--mute)}}
table{{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:14px}}
td,th{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--mute);font-weight:500;font-size:13px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media (max-width:640px){{.two{{grid-template-columns:1fr}}}}
details{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:6px 0}}summary{{cursor:pointer;padding:10px 12px;list-style:none;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}}
summary::-webkit-details-marker{{display:none}}.seed{{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--mute)}}
.badge{{font-weight:600}}.badge.a1{{color:var(--a1)}}.badge.a2{{color:var(--a2)}}.badge.a3{{color:var(--a3)}}.badge.win{{color:var(--win)}}
.who{{flex:1 1 200px}}.meta{{color:var(--mute);font-size:13px}}.body{{padding:0 12px 12px;font-size:14px}}.body p{{margin:6px 0}}
.k{{color:var(--mute)}}.fights td:nth-child(n+4){{text-align:right;white-space:nowrap}}.fights{{font-size:13px}}.hl td{{background:color-mix(in srgb,var(--a1) 12%,transparent)}}
.filter{{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}}.filter button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:4px 12px;font:inherit;font-size:13px;cursor:pointer}}
.filter button.on{{border-color:var(--accent);color:var(--accent)}}
</style></head><body><main>
<h1>{html.escape(a.title)}</h1><div class="note">{html.escape(a.note)}　共 {len(rs)} 局（崩溃 {len(rs) - n}）。每局的战斗记录只有打赢的场次，最后输掉的那场写在标题里。</div>
<div class="stats">{stat('过第一幕', f'{a1 / max(n, 1):.0%}', f'{a1}/{n}')}{stat('过第二幕', f'{a2 / max(n, 1):.0%}', f'{a2}/{n}')}{stat('通关', w, f'{w}/{n}')}
{stat('第一幕平均精英', f'{sum(el1) / max(len(el1), 1):.2f}', '人类赢家 2.57')}</div>
<div class="two"><div><h2>死在哪</h2><table><tr><th>位置</th><th>局数</th></tr>''']
    for (act, room), v in sorted(by_room.items(), key=lambda t: (t[0][0] or 0, -t[1])):
        out.append(f'<tr><td>第 {act} 幕 {ROOM.get(room, room)}</td><td>{v}</td></tr>')
    out.append('</table></div><div><h2>死在谁手里</h2><table><tr><th>敌人</th><th>局数</th></tr>')
    for k, v in by_who.most_common(12):
        out.append(f'<tr><td>{html.escape(k)}</td><td>{v}</td></tr>')
    out.append('</table></div></div><h2>逐局（点开看牌组、遗物、每场战斗）</h2><div class="filter">'
               '<button class="on" data-f="all">全部</button><button data-f="a1">死在第一幕</button><button data-f="a2">死在第二幕</button>'
               '<button data-f="a3">死在第三幕</button><button data-f="win">通关</button></div><div id="list">')
    key = lambda r: (-(r.get('win') and 99 or 0), -((r.get('act') or 1) * 100 + (r.get('floor') or 0)))
    for r in sorted(rs, key=key):
        oc, cls = outcome(r)
        cs = r.get('combats') or []
        e1 = sum(1 for c in cs if c['act'] == 1 and c['room'] == 'Elite')
        meta = f'第一幕精英 {e1} · 遗物 {len(r.get("relics") or [])} · 牌 {len(r.get("deck") or [])} · 升级 {sum(1 for c in r.get("deck") or [] if c.endswith("+"))} · {int(r.get("sec") or 0) // 60} 分钟'
        who = '' if r.get('win') or 'crash' in r else enemies(r.get('enemies'))
        out.append(f'<details data-c="{cls}"><summary><span class="badge {cls}">{oc}</span><span class="who">{html.escape(who)}</span>'
                   f'<span class="meta">{meta}</span><span class="seed">{html.escape(str(r.get("seed")))}</span></summary><div class="body">')
        if 'crash' in r: out.append(f'<p class="k">{html.escape(r["crash"][:300])}</p>')
        out.append(f'<p><span class="k">牌组：</span>{html.escape(deck(r.get("deck")))}</p>')
        out.append(f'<p><span class="k">遗物：</span>{html.escape("、".join(relic(x) for x in r.get("relics") or []))}</p>')
        out.append('<table class="fights"><tr><th>幕-层</th><th>类型</th><th>敌人</th><th>掉血</th><th>剩血</th><th>回合</th></tr>')
        for c in cs:
            hl = ' class="hl"' if c['room'] in ('Elite', 'Boss') else ''
            out.append(f'<tr{hl}><td>{c["act"]}-{c["floor"]}</td><td>{ROOM.get(c["room"], c["room"])}</td><td>{html.escape(enemies(c["enemies"]))}</td>'
                       f'<td>{c.get("dmg", "")}</td><td>{c.get("hp", "")}</td><td>{c.get("rounds", "")}</td></tr>')
        if not r.get('win') and 'crash' not in r:
            out.append(f'<tr class="hl"><td>{r.get("act")}-{r.get("floor")}</td><td>{ROOM.get(r.get("room"), r.get("room"))}</td>'
                       f'<td>{html.escape(enemies(r.get("enemies")))}</td><td colspan="3">输在这一场</td></tr>')
        out.append('</table></div></details>')
    out.append('''</div></main><script>
document.querySelectorAll('.filter button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.filter button').forEach(x=>x.classList.toggle('on',x===b));
const f=b.dataset.f;document.querySelectorAll('#list details').forEach(d=>d.style.display=(f==='all'||d.dataset.c===f)?'':'none')});
</script></body></html>''')
    path = a.out or f'{HERE}/reports/{os.path.basename(a.path).replace(".jsonl", "")}.html'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w').write('\n'.join(out))
    print(path)


if __name__ == '__main__':
    main()
