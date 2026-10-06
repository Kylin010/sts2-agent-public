"""从人类回放还原 Boss / 精英的进场配置，做成「同一副牌」的战斗基准（10/3 claude-value）。
data/bench.json 的人类配置只有掉血和输赢，没有逐回合记录；这里的每个案例都带 replay 文件名，
程序打完可以和人类在同一副牌上逐回合对照（打谁、挡多少、朝向、用药）。

还原：牌组按卡牌 id 记账（同名牌可以互换，升级哪一张都一样）：开局牌组 + 获得 − 删除 ± 变化，只算战斗外的升级；
奖励里本来就是升级版的牌，升级事件在拿牌之前，先记下、拿牌时补上；有整副牌快照（v5 回放的 deck 事件）就以快照为准。
遗物 = 开局遗物 + relic − relic_lost；药水按 potion_got / used / dropped 记账；读档重打回到进场时的药水和血量。
血量和上限优先用整局记录（ironclad-a10*.jsonl.gz 里同一种子、Boss 前一层的 current_hp / max_hp）。
附魔给不了（set_player 不支持），只记数；带模组内容（游戏里没有的卡牌 / 遗物类）的局整局去掉。
只取 v0.111.0、单人、标准模式、A10、无修改器的回放，每场取第一次打（attempt 0）。

用法：python3 tools/replay_cases.py KAISER_CRAB_BOSS data/bench_crab_replay.json
      STS2_BENCH=bench_crab_replay.json python3 run.py 0 --bench --only KAISER_CRAB_BOSS --reps 2 --set search_on=true
"""
import collections, glob, gzip, json, os, re, sys
SRC = '/opt/slay-the-spire-2/sources/community-runs'
DEC = '/opt/slay-the-spire-2/decompiled/v0.111.0'
ENC, OUT = sys.argv[1], sys.argv[2]


def _ids(folder):
    up = lambda s: re.sub(r'(?<!^)(?=[A-Z])', '_', s).upper()
    return {up(f[:-3]) for f in os.listdir(f'{DEC}/{folder}') if f.endswith('.cs')}


CARDS, RELICS = _ids('MegaCrit.Sts2.Core.Models.Cards'), _ids('MegaCrit.Sts2.Core.Models.Relics')


def take(deck, cid, up=None):
    """从牌组里拿掉一张 id 为 cid 的牌（up 指定时优先拿对应升级状态的）；拿不到返回 None"""
    cands = [i for i, d in enumerate(deck) if d[0] == cid]
    if up is not None: cands = [i for i in cands if bool(deck[i][1]) == bool(up)] or cands
    return deck.pop(cands[0]) if cands else None


def from_replay(path):
    relics = []; pots = []; hp = None; deck = []; snap = {}; got = None; enchants = 0; miss = 0; in_combat = False; pend = collections.Counter(); hdr = None
    for line in gzip.open(path, 'rt'):
        try: x = json.loads(line)
        except Exception: continue
        t = x.get('t')
        if t == 'header':
            hdr = x
            if not (x.get('build_id') == 'v0.111.0' and x.get('player_count') == 1 and x.get('game_mode') == 'standard'
                    and x.get('ascension') == 10 and not x.get('modifiers')): return None
            relics = list(x.get('starting_relics') or []); deck = [[d['id'], d.get('up', 0)] for d in x.get('starting_deck') or []]
        elif t == 'relic': relics.append(x['id'])
        elif t == 'relic_lost' and x.get('id') in relics: relics.remove(x['id'])
        elif t == 'potion_got': pots.append(x['id'])
        elif t in ('potion_used', 'potion_dropped') and x.get('id') in pots: pots.remove(x['id'])
        elif t == 'hp' and 'hp' in x and not x.get('dst'): hp = x['hp']
        elif t == 'deck': deck = [[d['id'], d.get('up', 0)] for d in x['cards']]; miss = 0
        elif t == 'acquire' and not in_combat: deck.append([x['id'], x.get('up', 0) + pend.pop(x.get('c'), 0)])
        elif t == 'remove' and not in_combat: miss += take(deck, x.get('id')) is None
        elif t == 'transform' and not in_combat:
            miss += take(deck, x.get('from_id')) is None; deck.append([x.get('to_id'), x.get('to_up', 0)])
        elif t == 'upgrade' and not in_combat:
            d = take(deck, x.get('id'), up=0)
            if d is not None: deck.append([d[0], d[1] + 1])
            elif x.get('c') is not None: pend[x['c']] += 1        # 奖励里本来就是升级版：升级事件在拿牌之前
            else: miss += 1
        elif t == 'enchant' and x.get('pile') == 'deck': enchants += 1
        elif t == 'combat_end':
            in_combat = False
            if got is not None:
                got.update(human_dmg=x.get('hp_lost_total'), human_survived=x.get('result') == 'victory')
                return got
        if t == 'combat_start':
            in_combat = True
            if x.get('encounter') != ENC: continue
            base = (x.get('combat_id') or '').split('#')[0]
            if base in snap: pots, hp = list(snap[base][0]), snap[base][1]      # 读档重打：回到进场时
            else: snap[base] = (list(pots), hp)
            if x.get('attempt_id'): continue
            got = {'deck': [d[0] + ('+' if d[1] else '') for d in deck], 'relics': list(relics), 'potions': list(pots), 'hp': hp,
                   'act': x.get('act'), 'seed': hdr.get('seed'), 'replay': os.path.basename(path), 'enchanted': enchants, 'miss': miss}
    return None


cases = [c for c in (from_replay(f) for f in sorted(glob.glob(f'{SRC}/replays/ironclad-a10/*.ndjson.gz'))) if c]
seeds = {c['seed'] for c in cases}; stats = {}
for name in ('ironclad-a10-v0.111.0.jsonl.gz', 'ironclad-a10-all.jsonl.gz'):
    for l in gzip.open(f'{SRC}/{name}', 'rt'):
        if not any(s in l for s in seeds - set(stats)): continue
        r = json.loads(l)
        if r.get('seed') not in seeds or r['seed'] in stats: continue
        for act in r['map_point_history']:
            prev = None
            for mp in act:
                if any(ENC in (rm.get('model_id') or '') for rm in mp.get('rooms') or []):
                    ps = (prev or mp)['player_stats'][0]; stats[r['seed']] = (ps.get('max_hp'), ps.get('current_hp'))
                prev = mp
    if not seeds - set(stats): break
out = []; dropped = collections.Counter()
for c in cases:
    mx, h = stats.get(c['seed'], (None, None))
    hp = h if h is not None else c['hp']
    if hp is None: dropped['血量未知'] += 1; continue
    if c['miss']: dropped['牌组记账对不上'] += 1; continue
    if any(d.rstrip('+') not in CARDS for d in c['deck']) or any(r not in RELICS for r in c['relics']): dropped['模组内容'] += 1; continue
    room = 'boss' if ENC.endswith('_BOSS') else 'elite' if ENC.endswith('_ELITE') else 'monster'
    out.append({'encounter': ENC, 'act': c['act'], 'room': room, 'deck': c['deck'], 'relics': c['relics'], 'potions': c['potions'],
                'hp': min(hp, mx) if mx else hp, 'max_hp': mx or max(hp, 80), 'human_dmg': c['human_dmg'], 'human_survived': c['human_survived'],
                'human_won_run': None, 'replay': c['replay'], 'enchanted': c['enchanted'], 'max_hp_known': bool(mx)})
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(f'{ENC}：{len(out)} 个案例（去掉 {dict(dropped)}）；上限来自整局记录 {sum(o["max_hp_known"] for o in out)}；'
      f'有附魔 {sum(1 for o in out if o["enchanted"])}；人类撑过 {sum(o["human_survived"] for o in out)}，平均掉血 {sum(o["human_dmg"] or 0 for o in out) / max(len(out), 1):.1f}')
