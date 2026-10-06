"""篝火「升级还是休息」：社区 A10 铁甲赢家怎么选。
每个篝火点：选之前的血量比例（current_hp − hp_healed）、牌组里最值得升级那张的分数（data/upgrade_stats.json 的分幕升级比例，
= 赢家手里有这张牌时篝火选它升级的比例）、下一步是不是 Boss、最后选了 HEAL 还是 SMITH。按「血量档 × 最佳升级分数档」统计选升级的比例，
输出 data/rest_stats.json，policy/rest.py 的 rest_mode = imitate 查这张表。
用法：python3 tools/rest_stats.py
"""
import collections, gzip, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH']
UP = {k: v for k, v in json.load(open(f'{HERE}/data/upgrade_stats.json')).items() if isinstance(v, dict)}
cid = lambda x: str((x or {}).get('id') if isinstance(x, dict) else x).replace('CARD.', '')
HP_BINS = [0.3, 0.45, 0.6, 0.75, 0.9]                 # 选之前的血量比例分档上界
UP_BINS = [0.05, 0.15, 0.3, 0.5]                     # 牌组里最好升级的分数分档上界


def band(x, bins):
    return next((i for i, b in enumerate(bins) if x < b), len(bins))


def up_score(c, act):
    u = UP.get(c)
    if not u or u['n'] < 15: return 0.05             # 没数据的按中下
    return u.get('by_act', {}).get(str(act), u['rate'])


def main():
    tab = collections.defaultdict(lambda: [0, 0])     # (幕, 下一个是 Boss, 血量档, 升级分数档) → [升级次数, 总次数]
    n = 0
    for line in gzip.open(SRC, 'rt'):
        d = json.loads(line)
        if not d.get('win') or d.get('modifiers') or 'BaseLib' in line: continue
        plain = collections.Counter(START)
        for ai, act in enumerate(d.get('map_point_history') or []):
            a = min(ai + 1, 3)
            for pi, p in enumerate(act):
                ps = (p.get('player_stats') or [{}])[0]
                ups = [cid(x) for x in ps.get('upgraded_cards') or []]
                ch = ps.get('rest_site_choices') or []
                if p.get('map_point_type') == 'rest_site' and len(ch) == 1 and ch[0] in ('HEAL', 'SMITH') and ps.get('max_hp'):
                    hp0 = (ps.get('current_hp', 0) - (ps.get('hp_healed') or 0)) / ps['max_hp']
                    best = max((up_score(c, a) for c in plain if plain[c] > 0), default=0.0)
                    boss = pi + 1 < len(act) and act[pi + 1].get('map_point_type') == 'boss'
                    k = (a, boss, band(hp0, HP_BINS), band(best, UP_BINS))
                    tab[k][0] += ch[0] == 'SMITH'; tab[k][1] += 1; n += 1
                for c in ps.get('cards_gained') or []:
                    if not (isinstance(c, dict) and c.get('current_upgrade_level')): plain[cid(c)] += 1
                for c in ps.get('cards_removed') or []:
                    if plain[cid(c)] > 0: plain[cid(c)] -= 1
                for u in ups:
                    if plain[u] > 0: plain[u] -= 1
                plain += collections.Counter()
    out = {'_说明': '赢家篝火选升级的比例。键 = 幕|下一个是Boss|血量档|最佳升级分数档；值 = [选升级次数, 总次数]',
           '_hp_bins': HP_BINS, '_up_bins': UP_BINS, '_n': n,
           **{f'{a}|{int(b)}|{h}|{u}': v for (a, b, h, u), v in tab.items()}}
    json.dump(out, open(f'{HERE}/data/rest_stats.json', 'w'), ensure_ascii=False, indent=0)
    print(f'{n} 个篝火决定')
    hl = ['<30%', '30-45', '45-60', '60-75', '75-90', '≥90']; ul = ['<.05', '.05-.15', '.15-.3', '.3-.5', '≥.5']
    for a in (1, 2):
        for boss in (False, True):
            print(f'\n第{a}幕{"（下一个是 Boss）" if boss else ""}：选升级的比例（样本）  行 = 血量，列 = 牌组里最好的升级分数')
            print('        ' + ''.join(f'{x:>13}' for x in ul))
            for h in range(len(hl)):
                row = [tab.get((a, boss, h, u)) for u in range(len(ul))]
                print(f'{hl[h]:>7} ' + ''.join(f'{(f"{r[0] / r[1]:.0%}（{r[1]}）" if r and r[1] >= 5 else "—"):>13}' for r in row))


if __name__ == '__main__':
    main()
