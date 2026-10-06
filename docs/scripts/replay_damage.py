"""输出核心研究 · 录像伤害归属：赢家第二、三幕的伤害到底是哪些牌打出来的。

数据：sources/community-runs/replays/ironclad-a10/*.ndjson.gz（SpireCodex 模组逐事件录像，铁甲 A10）。
默认只用 v0.111.0 的录像（加参数 all 用全部版本）；装了影响玩法的模组或开了控制台的整局排除。读档重打过的战斗只取最后保留的那一次。

伤害口径：每个 player → 敌人的 hit 事件，dmg + blocked（打在敌人格挡上的也算输出），不含溢出伤害。
归属：
- 有 card 字段 → 那张牌（自动打出、重放都算在牌上）。
- 没有 card 字段的「无加成伤害」（能力、遗物、药水打出的）→ 按紧挨着的上一个事件推断：
  上一个是 block（我获得格挡）→ 势不可当；exhaust → 消耗触发（卡戎之灰等）；
  我掉血（hp 下降 / 自伤 hit）→ 狱火；potion_used → 药水；敌人回合 → 反伤（火焰屏障等）；其他 → 其他无来源。
  推断出来的条目用「〔…〕」标出。

输出：按幕 × 房间类型 × 胜负，各来源的伤害占比；每场战斗伤害第一的牌（「主力」）分布；每张牌出场时平均占这场伤害的比例。
用法：python3 replay_damage.py [all]
"""
import json, gzip, glob, sys, collections
sys.path.insert(0, __import__('os').path.dirname(__file__))
from core_data import ROOT, name

DIR = f'{ROOT}/sources/community-runs/replays/ironclad-a10'
ALL = len(sys.argv) > 1 and sys.argv[1] == 'all'
idx = {}
for l in open(f'{DIR}/index.jsonl'):
    r = json.loads(l); idx[r['run_hash']] = r


def room_of(enc):
    enc = str(enc or '')
    return 'boss' if enc.endswith('_BOSS') else 'elite' if enc.endswith('_ELITE') else 'monster'


def parse(path):
    combats = []; cur = None; prev = None; eturn = False; powers = set()
    for line in gzip.open(path, 'rt'):
        e = json.loads(line); t = e.get('t')
        if t == 'header' and ([m for m in e.get('mods') or [] if m.get('affects_gameplay')] or e.get('full_console')):
            return None                                   # 装了影响玩法的模组 / 开了控制台：整局不用
        if t == 'combat_start':
            if cur is not None: combats.append(cur)
            cur = {'id': e.get('combat_id'), 'enc': e.get('encounter'), 'act': e.get('act'), 'src': collections.Counter(), 'total': 0,
                   'room': room_of(e.get('encounter')), 'turns': 0}
            eturn = False; powers = set(); prev = None
            continue
        if cur is None: continue
        if t == 'turn':
            eturn = e.get('side') == 'enemy'
            if not eturn: cur['turns'] += 1
        elif t == 'power' and e.get('tgt') in ('IRONCLAD', 'player'):
            powers.add(e.get('id'))
        elif t == 'hit' and e.get('src') == 'player' and e.get('dst') not in ('player', None):
            amt = (e.get('dmg') or 0) + (e.get('blocked') or 0)
            if amt <= 0: prev = e; continue
            c = e.get('card')
            if not c:
                pt = (prev or {}).get('t')
                if eturn: c = '〔反伤：火焰屏障等〕'
                elif pt == 'block': c = '〔势不可当〕' if 'JUGGERNAUT_POWER' in powers else '〔格挡触发：其他〕'
                elif pt == 'exhaust': c = '〔消耗触发：卡戎之灰等〕'
                elif pt == 'potion_used': c = '〔药水〕'
                elif pt in ('hp', 'hp_loss') or (pt == 'hit' and (prev or {}).get('dst') == 'player'):
                    c = '〔狱火〕' if 'INFERNO_POWER' in powers else '〔掉血触发：其他〕'
                elif pt == 'hit' and not (prev or {}).get('card'):
                    c = cur.get('_last_unp', '〔其他无来源〕')
                else: c = '〔其他无来源〕'
                cur['_last_unp'] = c
            cur['src'][c] += amt; cur['total'] += amt
        elif t == 'combat_end':
            cur['result'] = e.get('result'); combats.append(cur); cur = None
            continue
        if t not in ('draw',): prev = e
    if cur is not None: combats.append(cur)
    # 读档重打：同一个 combat_id 只留最后一次
    last = {}
    for i, c in enumerate(combats): last[c['id']] = i
    return [c for i, c in enumerate(combats) if last[c['id']] == i and c['total'] > 0]


def main():
    agg = collections.defaultdict(collections.Counter)      # (act, room, win) → 来源 → 伤害
    tot = collections.Counter()
    top = collections.defaultdict(collections.Counter)      # (act>=2, room, win) → 主力牌
    share = collections.defaultdict(list)                   # (act>=2, win, 来源) → 出场时占这场伤害比例
    ncomb = collections.Counter(); nrun = collections.Counter()
    for path in sorted(glob.glob(f'{DIR}/*.ndjson.gz')):
        h = path.split('/')[-1].split('.')[0]
        r = idx.get(h)
        if r is None: continue
        if not ALL and r.get('build_id') != 'v0.111.0': continue
        w = bool(r.get('win'))
        cs = parse(path)
        if cs is None: continue
        nrun[w] += 1
        for c in cs:
            a = c['act'] or 0; room = c['room']
            key = (a, room, w)
            agg[key].update(c['src']); tot[key] += c['total']; ncomb[key] += 1
            hi = 'a2+' if a >= 2 else 'a1'
            if c['src']:
                best = c['src'].most_common(1)[0][0]
                top[(hi, room, w)][best] += 1
            for s, v in c['src'].items():
                share[(hi, w, s)].append(v / c['total'])
    print(f'录像：赢 {nrun[True]} 局，输 {nrun[False]} 局（{"全部版本" if ALL else "v0.111.0"}）\n')
    for act_sel, lab in ((lambda a: a >= 2, '第二、三幕'), (lambda a: a == 1, '第一幕')):
        for room in ('monster', 'elite', 'boss'):
            for w in (True, False):
                src = collections.Counter(); T = 0; n = 0
                for (a, rm, ww), v in agg.items():
                    if act_sel(a) and rm == room and ww == w: src.update(v); T += tot[(a, rm, ww)]; n += ncomb[(a, rm, ww)]
                if not T: continue
                rows = '，'.join(f'{name(s)} {v / T:.1%}' for s, v in src.most_common(18))
                print(f'## {lab} {room} {"赢家" if w else "输家"}：{n} 场，每场平均输出 {T / n:.0f}\n{rows}\n')
    print('\n## 每场伤害第一的来源（「主力」）\n')
    for hi in ('a2+', 'a1'):
        for room in ('monster', 'elite', 'boss'):
            for w in (True, False):
                c = top[(hi, room, w)]; n = sum(c.values())
                if not n: continue
                print(f'{hi} {room} {"赢" if w else "输"}（{n} 场）：' + '，'.join(f'{name(s)} {v / n:.0%}' for s, v in c.most_common(15)))
    print('\n## 第二、三幕：某张牌出场（打出过伤害）时，平均占这场伤害的比例（≥15 场）\n')
    for w in (True, False):
        rows = [(s, sum(v) / len(v), len(v)) for (hi, ww, s), v in share.items() if hi == 'a2+' and ww == w and len(v) >= 15]
        rows.sort(key=lambda x: -x[1])
        print(('赢家' if w else '输家') + '：' + '，'.join(f'{name(s)} {m:.0%}（{n}）' for s, m, n in rows[:40]) + '\n')


if __name__ == '__main__':
    main()
