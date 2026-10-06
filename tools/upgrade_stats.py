"""从社区赢家的篝火升级统计升级优先级：每张牌「在牌组里且还没升级时，被选中升级的比例」。
输出 data/upgrade_stats.json，policy/knowledge.best_upgrade 用它排序。
用法：python3 tools/upgrade_stats.py
"""
import collections, gzip, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH']
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
present = collections.Counter(); chosen = collections.Counter(); n_dec = 0
by_act = collections.defaultdict(collections.Counter); pres_act = collections.defaultdict(collections.Counter)
for line in gzip.open(SRC, 'rt'):
    d = json.loads(line)
    if not d.get('win') or d.get('modifiers') or 'BaseLib' in line: continue
    plain = collections.Counter(START)                 # 还没升级的
    for ai, act in enumerate(d.get('map_point_history') or []):
        for p in act:
            ps = (p.get('player_stats') or [{}])[0]
            ups = [cid(x) for x in ps.get('upgraded_cards') or []]
            if p.get('map_point_type') == 'rest_site' and len(ups) == 1 and ups[0] in plain:
                n_dec += 1
                for c in plain:
                    if plain[c] > 0: present[c] += 1; pres_act[min(ai + 1, 3)][c] += 1
                chosen[ups[0]] += 1; by_act[min(ai + 1, 3)][ups[0]] += 1
            for c in ps.get('cards_gained') or []:
                if not (isinstance(c, dict) and c.get('current_upgrade_level')): plain[cid(c)] += 1
            for c in ps.get('cards_removed') or []:
                if plain[cid(c)] > 0: plain[cid(c)] -= 1
            for u in ups:
                if plain[u] > 0: plain[u] -= 1
            plain += collections.Counter()
out = {'_说明': '赢家在篝火升级时：rate = 这张牌在牌组里（未升级）时被选中升级的比例；by_act 分幕', '_decisions': n_dec}
for c, n in present.items():
    if n < 15: continue
    out[c] = {'n': n, 'rate': round(chosen[c] / n, 3),
              'by_act': {a: round(by_act[a][c] / pres_act[a][c], 3) for a in (1, 2, 3) if pres_act[a][c] >= 10}}
json.dump(out, open(f'{HERE}/data/upgrade_stats.json', 'w'), ensure_ascii=False, indent=1)
top = sorted((k for k in out if not k.startswith('_')), key=lambda k: -out[k]['rate'])
print(f'{n_dec} 次篝火升级，{len(top)} 张牌')
print('最常升级：', [(k, out[k]['rate']) for k in top[:15]])
print('最少升级：', [(k, out[k]['rate']) for k in top[-6:]])
