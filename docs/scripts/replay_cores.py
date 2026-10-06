"""输出核心研究 · 录像：这场战斗里「打出过」某个核心的牌时，每回合输出、回合数、掉血是多少。

核心按这场战斗里实际打出过的牌判定（cores.py 的定义；只看打出过的牌，没抽到的不算）。
只用 v0.111.0、无玩法模组、没开控制台的录像；读档重打的战斗只取最后一次。
用法：python3 replay_cores.py
"""
import json, gzip, glob, sys, os, collections
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from core_data import ROOT, name
from cores import CORES
from replay_damage import DIR, idx, room_of


def parse(path):
    combats = []; cur = None
    for line in gzip.open(path, 'rt'):
        e = json.loads(line); t = e.get('t')
        if t == 'header' and ([m for m in e.get('mods') or [] if m.get('affects_gameplay')] or e.get('full_console')):
            return None
        if t == 'combat_start':
            if cur is not None: combats.append(cur)
            cur = {'id': e.get('combat_id'), 'act': e.get('act') or 0, 'room': room_of(e.get('encounter')), 'enc': e.get('encounter'),
                   'played': collections.Counter(), 'dealt': 0, 'turns': 0, 'hp_lost': None}
            continue
        if cur is None: continue
        if t == 'turn' and e.get('side') == 'player': cur['turns'] += 1
        elif t == 'play' and (e.get('play_index') or 0) == 0: cur['played'][e.get('id')] += 1
        elif t == 'hit' and e.get('src') == 'player' and e.get('dst') not in ('player', None):
            cur['dealt'] += (e.get('dmg') or 0) + (e.get('blocked') or 0)
        elif t == 'combat_end':
            cur['hp_lost'] = e.get('hp_lost_total'); cur['result'] = e.get('result'); combats.append(cur); cur = None
    if cur is not None: combats.append(cur)
    last = {c['id']: i for i, c in enumerate(combats)}
    return [c for i, c in enumerate(combats) if last[c['id']] == i and c.get('hp_lost') is not None and c['turns'] > 0]


def main():
    rows = []
    for path in sorted(glob.glob(f'{DIR}/*.ndjson.gz')):
        h = path.split('/')[-1].split('.')[0]
        r = idx.get(h)
        if r is None or r.get('build_id') != 'v0.111.0': continue
        cs = parse(path)
        if cs is None: continue
        for c in cs:
            c['win'] = bool(r.get('win')); rows.append(c)
    print(f'录像战斗 {len(rows)} 场（v0.111.0，干净）\n')
    for act_lab, sel in (('第二、三幕', lambda a: a >= 2), ('第一幕', lambda a: a == 1)):
        for room in ('monster', 'elite', 'boss'):
            R = [c for c in rows if sel(c['act']) and c['room'] == room and c.get('result') == 'victory']
            if not R: continue
            print(f'## {act_lab} {room}（打赢的 {len(R)} 场）\n')
            print('| 打出过的核心 | 场数 | 每回合输出 | 回合数 | 掉血 |\n|---|---|---|---|---|')
            groups = collections.OrderedDict()
            for n, (f, _) in CORES.items():
                groups[n] = [c for c in R if f(c['played'])]
            groups['消耗或格挡'] = [c for c in R if CORES['消耗引擎'][0](c['played']) or CORES['格挡转伤害'][0](c['played'])]
            groups['都没有'] = [c for c in R if not any(f(c['played']) for f, _ in CORES.values())]
            groups['全部'] = R
            for g, cs in groups.items():
                if len(cs) < 10: continue
                dpt = np.mean([c['dealt'] / c['turns'] for c in cs])
                print(f'| {g} | {len(cs)} | {dpt:.1f} | {np.mean([c["turns"] for c in cs]):.1f} | {np.mean([c["hp_lost"] for c in cs]):.1f} |')
            print()


if __name__ == '__main__':
    main()
