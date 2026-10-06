"""每场精英 / Boss 的「阶段打法」。
从人类回放统计：同一遭遇里，按敌人这回合出的招（玩家回合之后的敌方回合实际出招 = 玩家回合看到的意图）分阶段，
人类把能量花在 攻击 / 格挡 / 能力 / 功能（抽牌、能量、减益……）上各占多少。
输出 data/phase_profiles.json：{遭遇: {"_all": {类: 占比}, "招1|招2": {类: 占比, "n": 回合数}}}
用法：python3 tools/phase_profiles.py
"""
import collections, glob, gzip, json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = '/opt/slay-the-spire-2/sources/community-runs/replays/ironclad-a10'
K = json.load(open(f'{HERE}/kb/cards.json'))
CATS = ('atk', 'blk', 'pow', 'util')


def cat(cid):
    k = K.get(cid) or {}
    t = k.get('type')
    if t == 'Attack': return 'atk'
    if t == 'Power': return 'pow'
    if t == 'Skill': return 'blk' if (k.get('block') or 0) > 0 else 'util'
    return None


def fights(path):
    """一份回放里每场精英 / Boss 战（只取第一次打，attempt 0）：[(遭遇, [(招式键, {类: 能量})])]"""
    out = []; cur = None; enc = None; turn = None; spend = None; moves = None
    for line in gzip.open(path, 'rt'):
        try: x = json.loads(line)
        except Exception: continue
        t = x.get('t')
        if t == 'header':
            if not (x.get('build_id') == 'v0.111.0' and x.get('player_count') == 1 and x.get('ascension') == 10 and not x.get('modifiers')): return []
        elif t == 'combat_start':
            e = x.get('encounter') or ''
            if (e.endswith('_ELITE') or e.endswith('_BOSS')) and not x.get('attempt_id'):
                enc = e; cur = []; spend = None; moves = None
            else:
                enc = None
        elif enc is None:
            continue
        elif t == 'turn':
            if x.get('side') == 'player':
                spend = collections.Counter(); moves = []
            elif x.get('side') == 'enemy' and spend is not None:
                pass
        elif t == 'play' and spend is not None and not x.get('auto'):
            c = cat(x.get('id'))
            if c: spend[c] += max(x.get('cost_paid') or 0, 0.5)
        elif t == 'move' and moves is not None:
            moves.append(f"{x.get('src')}:{x.get('id')}")
        elif t == 'end_turn' and x.get('side') == 'enemy' and spend is not None:
            cur.append(('|'.join(sorted(moves)) or 'NONE', spend)); spend = None; moves = None
        elif t == 'combat_end':
            if cur: out.append((enc, cur))
            enc = None
    return out


def main():
    agg = collections.defaultdict(lambda: collections.defaultdict(collections.Counter)); n = collections.defaultdict(collections.Counter)
    for p in sorted(glob.glob(f'{SRC}/*.ndjson.gz')):
        for enc, turns in fights(p):
            for key, sp in turns:
                agg[enc][key].update(sp); agg[enc]['_all'].update(sp); n[enc][key] += 1; n[enc]['_all'] += 1
    out = {}
    for enc, d in agg.items():
        out[enc] = {}
        for key, c in d.items():
            tot = sum(c.values()) or 1
            out[enc][key] = {**{k: round(c[k] / tot, 3) for k in CATS}, 'n': n[enc][key], 'energy': round(tot / max(n[enc][key], 1), 2)}
    json.dump(out, open(f'{HERE}/data/phase_profiles.json', 'w'), ensure_ascii=False, indent=0)
    for enc in sorted(out, key=lambda e: -out[e]['_all']['n']):
        a = out[enc]['_all']
        print(f"{enc}: {a['n']} 回合 攻 {a['atk']:.2f} 挡 {a['blk']:.2f} 能 {a['pow']:.2f} 功 {a['util']:.2f}；阶段 {len(out[enc]) - 1} 个")


if __name__ == '__main__':
    main()
