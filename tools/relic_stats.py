"""从社区对局统计每件遗物：拿到它的对局最终胜率比同阶段平均高多少（lift），赢家在商店见到时买的比例。
输出 data/relic_stats.json，给商店（policy/shop.py）和以后的遗物选择用。
注意：lift 混着「强玩家 / 顺风局更容易拿到好遗物」的影响，只当排序参考。
用法：python3 tools/relic_stats.py
"""
import collections, gzip, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
have = collections.defaultdict(lambda: [0, 0]); base = [0, 0]
shop = collections.defaultdict(lambda: [0, 0])          # 赢家：见到次数、买的次数
rid = lambda x: str(x).replace('RELIC.', '')
for line in gzip.open(SRC, 'rt'):
    d = json.loads(line)
    if d.get('was_abandoned') or d.get('modifiers') or 'BaseLib' in line: continue
    win = bool(d.get('win')); acts = d.get('map_point_history') or []
    if len(acts) < 2: continue                           # 只看活到第二幕的（拿到遗物以后还有路要走）
    got = set()
    for ai, act in enumerate(acts[:2]):
        for p in act:
            ps = (p.get('player_stats') or [{}])[0]
            for r in ps.get('relic_choices') or []:
                if r.get('was_picked'): got.add(rid(r.get('choice')))
            if p.get('map_point_type') == 'shop' and win:
                gold = ps.get('current_gold', 0) + ps.get('gold_spent', 0)
                for r in ps.get('relic_choices') or []:
                    k = rid(r.get('choice')); shop[k][0] += 1; shop[k][1] += bool(r.get('was_picked'))
    base[0] += 1; base[1] += win
    for k in got: have[k][0] += 1; have[k][1] += win
b = base[1] / base[0]
out = {'_说明': f'lift = 拿到这件遗物（前两幕）的对局最终胜率 − 活到第二幕的平均胜率 {b:.3f}；shop_buy = 赢家在商店见到它时买的比例',
       '_baseline': round(b, 3)}
for k, (n, w) in have.items():
    if n < 20: continue
    s = shop.get(k, [0, 0])
    out[k] = {'n': n, 'win': round(w / n, 3), 'lift': round(w / n - b, 3), 'shop_seen': s[0], 'shop_buy': round(s[1] / s[0], 3) if s[0] >= 10 else None}
json.dump(out, open(f'{HERE}/data/relic_stats.json', 'w'), ensure_ascii=False, indent=1)
top = sorted((k for k in out if not k.startswith('_')), key=lambda k: -out[k]['lift'])
print(f'{len(top)} 件遗物；平均胜率 {b:.1%}')
print('lift 最高：', [(k, out[k]['lift']) for k in top[:12]])
print('lift 最低：', [(k, out[k]['lift']) for k in top[-8:]])
