"""从社区对局统计每个事件、每个选项：多少人选、选了以后最终胜率、当场掉血 / 加减最大生命 / 金币 / 加牌删牌。
输出 data/event_stats.json，给 policy/events.py 选选项用。
数据：sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz（A10 铁甲战士、测试版 v0.111.0，没有修改器）
用法：python3 tools/event_stats.py
"""
import collections, gzip, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'

stats = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
seen = collections.Counter()
for line in gzip.open(SRC, 'rt'):
    d = json.loads(line)
    if d.get('was_abandoned') or d.get('modifiers') or len(d.get('players') or []) != 1: continue
    win = bool(d.get('win'))
    for ai, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            rooms = p.get('rooms') or []
            ev = next((r.get('model_id') for r in rooms if str(r.get('model_id', '')).startswith('EVENT.')), None)
            if not ev or ev == 'EVENT.NEOW': continue
            ev = ev.replace('EVENT.', '')
            ps = (p.get('player_stats') or [{}])[0]
            seen[ev] += 1
            for ch in ps.get('event_choices') or []:
                key = str((ch.get('title') or {}).get('key', '')).replace('.title', '')
                if not key: continue
                c = stats[ev][key]
                c['n'] += 1; c['win'] += win; c[f'act{ai + 1}'] += 1
                c['dmg'] += ps.get('damage_taken') or 0; c['heal'] += ps.get('hp_healed') or 0
                c['maxhp'] += (ps.get('max_hp_gained') or 0) - (ps.get('max_hp_lost') or 0)
                c['gold'] += (ps.get('gold_gained') or 0) - (ps.get('gold_lost') or 0) - (ps.get('gold_spent') or 0)
                c['cards_gained'] += len(ps.get('cards_gained') or []); c['cards_removed'] += len(ps.get('cards_removed') or [])
                c['relics'] += len([r for r in ps.get('relic_choices') or [] if r.get('was_picked')])
                c['curse'] += sum(1 for x in ps.get('cards_gained') or [] if any(w in str(x.get('id')) for w in
                                  ('DOUBT', 'REGRET', 'INJURY', 'DECAY', 'SHAME', 'WRITHE', 'NORMALITY', 'PAIN', 'CLUMSY', 'POOR_SLEEP', 'GUILTY', 'FOLLY', 'GREED', 'DEBT', 'SPORE_MIND', 'BAD_LUCK', 'ENTHRALLED', 'ASCENDERS_BANE')))
out = {}
for ev, opts in stats.items():
    tot = sum(c['n'] for c in opts.values())
    out[ev] = {'n': seen[ev], 'options': {}}
    for k, c in sorted(opts.items(), key=lambda t: -t[1]['n']):
        n = c['n']
        out[ev]['options'][k] = {'n': n, 'pick': round(n / max(tot, 1), 3), 'win': round(c['win'] / n, 3),
                                 **{f: round(c[f] / n, 2) for f in ('dmg', 'heal', 'maxhp', 'gold', 'cards_gained', 'cards_removed', 'relics', 'curse')}}
json.dump(out, open(f'{HERE}/data/event_stats.json', 'w'), ensure_ascii=False, indent=1)
print(f'{len(out)} 个事件，{sum(len(v["options"]) for v in out.values())} 个选项 → data/event_stats.json')
