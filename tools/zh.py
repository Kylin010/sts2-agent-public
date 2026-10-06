"""引擎给的是英文名，这里按 spire-codex 的中英两份数据（同一个 id）翻成中文。给报告用。"""
import json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = f'{ROOT}/sources/spire-codex/data-beta/v0.111.0'


def _pair(kind):
    eng = json.load(open(f'{D}/eng/{kind}.json')); zhs = {x['id']: x for x in json.load(open(f'{D}/zhs/{kind}.json'))}
    return {x['name']: zhs.get(x['id'], x) for x in eng if x.get('name')}, zhs


CARDS, CARDS_ID = _pair('cards')
RELICS, RELICS_ID = _pair('relics')
POTIONS, POTIONS_ID = _pair('potions')
MONSTERS, MONSTERS_ID = _pair('monsters')
_EV_ENG = json.load(open(f'{D}/eng/events.json')); _EV_ZH = {x['id']: x for x in json.load(open(f'{D}/zhs/events.json'))}


def _name(table, n):
    if n is None: return '?'
    up = n.endswith('+'); b = n.rstrip('+')
    x = table.get(b)
    return (x['name'] if x else b) + ('+' if up else '')


card = lambda n: _name(CARDS, n)
relic = lambda n: _name(RELICS, n)
potion = lambda n: _name(POTIONS, n)


def monster(n):
    if n in MONSTERS: return MONSTERS[n]['name']
    i = re.sub(r'[^A-Z0-9]+', '_', str(n).upper()).strip('_')
    for k in (i, i + '_SEGMENT', i.replace('_RAIDER', '_RUBY_RAIDER')):
        if k in MONSTERS_ID: return MONSTERS_ID[k]['name']
    return n


def _clean(t):
    return re.sub(r'\[/?\w+\]', '', t or '')


def card_text(n):
    x = CARDS.get(str(n).rstrip('+'))
    return re.sub(r'\[/?\w+\]', '', x.get('description') or '') if x else ''


def relic_text(n):
    x = RELICS.get(n)
    return re.sub(r'\[/?\w+\]', '', x.get('description') or '') if x else ''


def event(opts):
    """按选项的英文标题找是哪个事件；返回 (事件中文名, [选项中文标题 + 说明])。古神（开局）选项是遗物名"""
    opts = [o for o in opts or [] if o]
    if opts and all(o in RELICS for o in opts):
        return '古神的馈赠（开局选遗物）', [f'{relic(o)}：{relic_text(o)}' for o in opts]
    best = None
    for ev in _EV_ENG:
        titles = {}
        for o in ev.get('options') or []: titles[o.get('title')] = o.get('id')
        for pg in ev.get('pages') or []:
            for o in pg.get('options') or []: titles[o.get('title')] = o.get('id')
        hit = sum(1 for o in opts if o in titles)
        if hit and (best is None or hit > best[0]): best = (hit, ev, titles)
    if not best: return '事件', list(opts)
    _, ev, titles = best; zh = _EV_ZH.get(ev['id'], ev)
    zo = {o.get('id'): o for o in zh.get('options') or []}
    for pg in zh.get('pages') or []:
        for o in pg.get('options') or []: zo[o.get('id')] = o
    out = []
    for o in opts:
        z = zo.get(titles.get(o))
        out.append(z.get('title') + '：' + _clean(z.get('description')) if z else o)
    return zh.get('name', ev['id']), out


TYPE_ZH = {'Attack': '攻击', 'Skill': '技能', 'Power': '能力', 'Curse': '诅咒', 'Status': '状态'}


def card_id(c):
    """按 id（结果里的牌组，例如 TWIN_STRIKE+）翻译"""
    up = str(c).endswith('+'); x = CARDS_ID.get(str(c).rstrip('+'))
    return (x['name'] if x else str(c).rstrip('+')) + ('+' if up else '')


def card_type_id(c):
    x = CARDS_ID.get(str(c).rstrip('+')) or {}
    return TYPE_ZH.get(x.get('type'), x.get('type') or '其他')


def relic_id(r):
    x = RELICS_ID.get(r); return x['name'] if x else r


def relic_id_text(r):
    x = RELICS_ID.get(r); return _clean(x.get('description')) if x else ''
