"""读取知识库 kb/（卡牌、遗物、药水、敌人、联动规则），给各个策略模块用。改知识只改 kb/ 里的 JSON，不用动代码。"""
import json, os, collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = f'{HERE}/kb'
CARDS = json.load(open(f'{KB}/cards.json'))
RELICS = json.load(open(f'{KB}/relics.json'))
POTIONS = json.load(open(f'{KB}/potions.json'))
_EN = json.load(open(f'{KB}/enemies.json'))
ENEMIES = {k: v for k, v in _EN.items() if not k.startswith('_')}
ACT_ELITES = _EN.get('_act_elites', {})
SYNERGIES = json.load(open(f'{KB}/synergies.json'))['rules']
NAMES = json.load(open(f'{KB}/names_en.json'))     # 英文名 → id（商店里的牌和遗物只给名字）

norm = lambda x: str(x or '').replace('CARD.', '').replace('RELIC.', '').replace('POTION.', '').rstrip('+')


def card(cid): return CARDS.get(norm(cid), {})
def id_by_name(kind, name):
    """kind = cards / relics / potions；升级过的牌名字后面带 +"""
    return NAMES.get(kind, {}).get(str(name or '').rstrip('+'))
def tags(cid): return set(card(cid).get('tags') or [])
def relic(rid): return RELICS.get(norm(rid), {})
def potion_uses(pid): return set(POTIONS.get(norm(pid), {}).get('uses') or ['utility'])
def ids_with(tag): return {k for k, v in CARDS.items() if tag in (v.get('tags') or [])}


def deck_tag_counts(deck_ids):
    c = collections.Counter()
    for i in deck_ids:
        for t in tags(i): c[t] += 1
    return c


def synergy_bonus(card_id, deck_ids, relic_ids=(), potion_ids=(), act=1):
    """这张牌和现有牌组 / 遗物 / 药水的联动加分（kb/synergies.json + 遗物的 boost_tags）"""
    t = tags(card_id); cnt = deck_tag_counts(deck_ids); deckset = set(map(norm, deck_ids)); b = 0.0
    for r in SYNERGIES:
        w = r.get('when', {})
        if any(cnt[k] < v for k, v in (w.get('deck_tags') or {}).items()): continue
        if any(cnt[k] > v for k, v in (w.get('deck_tags_max') or {}).items()): continue
        if any(c not in deckset for c in w.get('deck_cards') or []): continue
        if any(norm(x) not in set(map(norm, relic_ids)) for x in w.get('relics') or []): continue
        if any(norm(x) not in set(map(norm, potion_ids)) for x in w.get('potions') or []): continue
        if 'act_max' in w and act > w['act_max']: continue
        for key, v in r.get('boost', {}).items():
            kind, name = key.split(':', 1)
            if (kind == 'tag' and name in t) or (kind == 'card' and name == norm(card_id)): b += v
    for rid in relic_ids:
        for tg, v in (relic(rid).get('boost_tags') or {}).items():
            if tg in t: b += v
    return b


def enemy_rules(encounter_id=None, names=()):
    """这场战斗的敌人特殊机制（按遭遇 id，或按怪物英文名）"""
    out = dict(ENEMIES.get(norm(encounter_id), {})) if encounter_id else {}
    for n in names:
        out.update(ENEMIES.get(n, {}))
    return out


def counter_bonus(card_id, act, boss_id):
    """应对本幕 Boss（权重 1）和本幕常见精英（平均后权重 0.5）需要的牌型，给这张牌加分"""
    t = tags(card_id); b = 0.0
    for tg, v in (ENEMIES.get(norm(boss_id), {}).get('counter_tags') or {}).items():
        if tg in t: b += v
    el = ACT_ELITES.get(str(act), [])
    for e in el:
        for tg, v in (ENEMIES.get(e, {}).get('counter_tags') or {}).items():
            if tg in t: b += 0.5 * v / max(len(el), 1)
    return b
