"""生成 kb/ 里的知识库（卡牌、遗物、药水），手写修正放在 kb/overrides/，优先级更高。

在 agent/ 目录运行：python3 build_knowledge.py
- 卡牌标签从游戏数据的结构化字段来（伤害、段数、格挡、抽牌、加能量、自伤、施加的能力、关键词），再加描述里的关键字
- 遗物、药水按描述自动分组；分组只是初稿，重要的条目都在 overrides 里手写
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/opt/slay-the-spire-2/sources/spire-codex/data-beta/v0.111.0'
OUT = f'{HERE}/kb'
clean = lambda t: re.sub(r'\[/?[a-z]+(:[^\]]*)?\]', '', t or '').replace('\n', ' ')


def load(name, lang='eng'):
    return {x['id']: x for x in json.load(open(f'{SRC}/{lang}/{name}.json'))}


def card_entry(c, zh):
    d = clean(c.get('description')); tags = set()
    pw = {str(p.get('power') or p.get('id') or p.get('name') or '').upper(): p.get('amount') for p in c.get('powers_applied') or []} \
        if isinstance(c.get('powers_applied'), list) else {}
    dmg, blk = c.get('damage') or 0, c.get('block') or 0
    if dmg: tags.add('damage')
    if 'ALL enemies' in d or c.get('target') == 'AllEnemies': tags.add('aoe')
    if (c.get('hit_count') or 1) > 1: tags.add('multi_hit')
    if blk: tags.add('block')
    if c.get('cards_draw'): tags.add('draw')
    if c.get('energy_gain'): tags.add('energy')
    if c.get('hp_loss') or re.search(r'Lose \d+ HP|lose \d+ HP', d): tags.add('self_damage')
    if any('VULNERABLE' in k for k in pw) or 'Vulnerable' in d: tags.add('vuln')
    if any('WEAK' in k for k in pw) or 'Weak' in d: tags.add('weak')
    if any('STRENGTH' in k for k in pw) or 'Strength' in d: tags.add('strength')
    if 'Exhaust' in d and c.get('type') != 'Power' and ('Exhaust all' in d or 'Exhaust 1' in d or 'Exhaust a' in d or 'non-Attack' in d):
        tags.add('exhaust_fuel')
    if 'whenever a card is Exhausted' in d.lower() or 'Exhausted' in d and c.get('type') == 'Power': tags.add('exhaust_engine')
    if 'equal to your Block' in d or 'gain Block, deal' in d.lower(): tags.add('block_payoff')
    if c.get('type') == 'Power': tags.add('power')
    if re.search(r'permanently|this run|raise your Max HP', d, re.I): tags.add('permanent_growth')
    kws = [str(k) for k in c.get('keywords') or []]
    return {'name': zh.get(c['id'], {}).get('name', c.get('name')), 'type': c.get('type'), 'cost': c.get('cost'),
            'x_cost': bool(c.get('is_x_cost')), 'rarity': c.get('rarity'), 'color': c.get('color'), 'target': c.get('target'),
            'damage': dmg, 'hits': c.get('hit_count') or 1, 'block': blk, 'draw': c.get('cards_draw') or 0,
            'energy': c.get('energy_gain') or 0, 'self_hp': c.get('hp_loss') or 0, 'powers': pw, 'keywords': kws,
            'tags': sorted(tags), 'text': clean(zh.get(c['id'], {}).get('description'))}


RELIC_GROUPS = [   # (分组, 英文描述里的关键字)
    ('counter', r'[Ee]very \d+|(\d+)(st|nd|rd|th) ', ),
    ('turn_end', r'end of your turn|at the end of turn|end your turn', ),
    ('combat_start', r'[Ss]tart (of )?each combat|start of combat|beginning of each combat|first turn', ),
    ('energy', r'Energy', ),
    ('turn_start', r'start of your turn|start of each turn', ),
    ('deck_add', r'add a card|added to your Deck|card to your Deck', ),
    ('rest', r'Rest Site|rest', ),
    ('shop', r'[Mm]erchant|[Ss]hop', ),
    ('pathing', r'paths|map|room', ),
    ('on_exhaust', r'Exhaust', ),
    ('on_attack', r'Attack', ),
    ('on_power', r'Power', ),
    ('hp', r'Max HP|[Hh]eal', ),
]


def relic_entry(r, zh):
    d = clean(r.get('description'))
    groups = [g for g, pat in RELIC_GROUPS if re.search(pat, d)]
    return {'name': zh.get(r['id'], {}).get('name', r.get('name')), 'rarity': r.get('rarity'), 'pool': r.get('pool'),
            'groups': groups, 'text': clean(zh.get(r['id'], {}).get('description'))}


POTION_USE = [  # (用途, 英文描述关键字)
    ('permanent', r'(raise|gain|increase).{0,20}Max HP|permanently'), ('emergency', r'Heal|revive|Fairy|extra turn'),
    ('defense', r'Block|Weak|Intangible|Plated|Buffer|Dexterity'), ('setup', r'Strength|Ritual|Power|Duplicate|Vulnerable'),
    ('energy_draw', r'[Ee]nergy|[Dd]raw'), ('offense', r'[Dd]amage|Poison'),
]


def potion_entry(p, zh):
    d = clean(p.get('description'))
    uses = [u for u, pat in POTION_USE if re.search(pat, d)] or ['utility']
    return {'name': zh.get(p['id'], {}).get('name', p.get('name')), 'rarity': p.get('rarity'), 'uses': uses,
            'text': clean(zh.get(p['id'], {}).get('description'))}


def merge(base, override_file):
    path = f'{OUT}/overrides/{override_file}'
    if not os.path.exists(path): return base
    for k, v in json.load(open(path)).items():
        if k.startswith('_'): continue
        base.setdefault(k, {}).update(v)
    return base


if __name__ == '__main__':
    os.makedirs(f'{OUT}/overrides', exist_ok=True)
    ce, cz = load('cards'), load('cards', 'zhs')
    cards = {k: card_entry(v, cz) for k, v in ce.items() if str(v.get('color', '')).lower() in ('ironclad', 'colorless', 'curse', 'status', 'event', 'token')}
    re_, rz = load('relics'), load('relics', 'zhs')
    # 铁甲战士只会遇到通用遗物和铁甲战士专属遗物；其他角色专属的 36 件不收（避免选牌 / 路线时误以为能拿到）
    relics = {k: relic_entry(v, rz) for k, v in re_.items() if str(v.get('pool', 'shared')).lower() in ('shared', 'ironclad', '')}
    pe, pz = load('potions'), load('potions', 'zhs')
    potions = {k: potion_entry(v, pz) for k, v in pe.items()}
    for name, data, ov in (('cards', cards, 'cards.json'), ('relics', relics, 'relics.json'), ('potions', potions, 'potions.json')):
        data = merge(data, ov)
        json.dump(data, open(f'{OUT}/{name}.json', 'w'), ensure_ascii=False, indent=1, sort_keys=True)
        print(f'{name}: {len(data)} 条')
