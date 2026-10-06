"""第二幕 Boss 研究 · 公共数据层：从人类录像里抽出帝皇蟹 / 知识恶魔的每一场 Boss 战（逐事件），附带进场状态。

数据：sources/community-runs/replays/ironclad-a10/*.ndjson.gz（SpireCodex 模组逐事件录像，铁甲 A10）。
只用第一行 header 的 build_id == v0.111.0 的录像；装了影响玩法的模组或开了控制台的整局排除（同 replay_damage.py）。

每场 Boss 战 = 同一个 combat_id（去掉 "#n" 重开后缀）的**最后一次尝试**：
    result      'win'（combat_end victory）/ 'loss'（combat_end loss，或这次尝试里血量归 0，或录像以 death 结束且停在这场）/
                'abandon'（录像在这场战斗中途结束、又不是死亡：退出没回来，不计入胜负）
    attempts    这场 Boss 打了几次（>1 = 用了「重开战斗」或读档重打）；prev = 之前没打完就重来的尝试（同样的字段）
    hp / maxhp  进场血量 / 最大血量（maxhp 取最近的 header.starting_max_hp 与 max_hp 事件）
    deck        进场牌组 tuple（升级过的 id 后加 '+'）；v5+ 录像用 deck 快照，否则从 starting_deck + acquire/remove/transform/upgrade/downgrade 正推
    relics      进场遗物列表；potions 进场药水列表
    ev          这次尝试里的事件（去掉 s/ms/floor/act）
用法：
    from boss_data import load_fights
    for f in load_fights(): ...
缓存：环境变量 BOSS_CACHE（默认 /tmp/sts2-boss-fights.pkl），录像目录更新或本文件改动后自动重建。
自检：python3 boss_data.py   （打印场数、胜负、牌组正推与 deck 快照 / final_deck 的一致率）
"""
import gzip, json, glob, os, re, collections, pickle

ROOT = '/opt/slay-the-spire-2'
DIR = f'{ROOT}/sources/community-runs/replays/ironclad-a10'
BOSSES = ('KAISER_CRAB_BOSS', 'KNOWLEDGE_DEMON_BOSS')
KEEP = {'turn', 'end_turn', 'play', 'hit', 'block', 'hp', 'hp_loss', 'power', 'power_lost', 'move', 'intent', 'potion_used',
        'potion_start', 'exhaust', 'death', 'combat_end', 'energy', 'draw', 'generate', 'discard', 'attack', 'max_hp', 'combat_start'}
CACHE = os.environ.get('BOSS_CACHE', '/tmp/sts2-boss-fights.pkl')


def base_id(cid):
    return re.sub(r'#\d+$', '', str(cid))


class Deck:
    """按 id 计数的牌组 + 每个 id 的升级张数（和 core_data 同口径）。另外记 c → (id, up) 方便删牌时知道删的是不是升级过的。"""

    def __init__(self, cards):
        self.n = collections.Counter(); self.up = collections.Counter(); self.c = {}
        for x in cards:
            self.add(x['id'], x.get('up', 0) or 0, x.get('c'))

    def add(self, i, up=0, c=None):
        self.n[i] += 1
        if up: self.up[i] += 1
        if c is not None: self.c[c] = [i, 1 if up else 0]

    def remove(self, i, c=None):
        if self.n[i] <= 0: return
        rec = self.c.pop(c, None) if c is not None else None
        self.n[i] -= 1
        if rec and rec[0] == i and rec[1] and self.up[i] > 0:
            self.up[i] -= 1
        self.up[i] = min(self.up[i], self.n[i])

    def upgrade(self, i, c=None):
        if self.up[i] < self.n[i]: self.up[i] += 1
        if c in self.c: self.c[c][1] = 1

    def downgrade(self, i, c=None):
        if self.up[i] > 0: self.up[i] -= 1
        if c in self.c: self.c[c][1] = 0

    def snap(self):
        out = []
        for i, k in self.n.items():
            u = min(self.up[i], k)
            out += [i + '+'] * u + [i] * (k - u)
        return tuple(sorted(out))

    def copy(self):
        d = Deck([]); d.n = self.n.copy(); d.up = self.up.copy(); d.c = {k: list(v) for k, v in self.c.items()}
        return d


def parse_file(path, stats=None):
    """返回这局录像里所有目标 Boss 战（每次尝试一条），以及整局的 meta。"""
    attempts = []
    st = {'deck': None, 'relics': [], 'potions': [], 'hp': None, 'maxhp': None}
    cur = None; meta = None; last_end = None; in_combat = False
    snaps = {}      # 楼层 → (房间 key, 进房间时的状态)：读档 / 重开会重放同一个房间，要退回进房间时的状态，否则买牌、拿牌会记两次

    def save():
        return (st['deck'].copy(), list(st['relics']), list(st['potions']), st['hp'], st['maxhp'])

    def restore(x):
        st['deck'] = x[0].copy(); st['relics'] = list(x[1]); st['potions'] = list(x[2]); st['hp'] = x[3]; st['maxhp'] = x[4]
    with gzip.open(path, 'rt') as fh:
        for line in fh:
            e = json.loads(line); t = e.get('t')
            if t == 'header':
                if meta is None:
                    if e.get('build_id') != 'v0.111.0': return None, None
                    if e.get('player_count', 1) != 1 or e.get('game_mode') != 'standard' or e.get('ascension') != 10: return None, None
                    if [m for m in e.get('mods') or [] if m.get('affects_gameplay')] or e.get('full_console'): return None, None
                    meta = {'seed': e.get('seed'), 'replay_version': e.get('replay_version'), 'reloads': 0}
                    st['deck'] = Deck(e.get('starting_deck') or [])
                    st['relics'] = list(e.get('starting_relics') or [])
                    st['maxhp'] = e.get('starting_max_hp'); st['hp'] = None
                else:
                    meta['reloads'] = max(meta['reloads'], e.get('reloads') or 0)
                    if e.get('starting_max_hp'): st['maxhp'] = e['starting_max_hp']
                    if e.get('relics'): st['relics'] = list(e['relics'])
                    if e.get('potions') is not None: st['potions'] = [p if isinstance(p, str) else p.get('id') for p in e['potions']]
                if cur is not None:                          # 战斗中途退出 → 这次尝试没有结果
                    attempts.append(cur); cur = None
                in_combat = False
                continue
            if meta is None: continue
            # —— 整局状态 ——
            if t == 'deck':
                st['deck'] = Deck(e.get('cards') or [])
                if stats is not None and '_chk' in st:
                    stats['snap_n'] += 1; stats['snap_ok'] += st.pop('_chk') == st['deck'].snap()
            elif t in ('acquire', 'remove', 'transform', 'upgrade', 'downgrade') and not in_combat:   # 战斗里的是临时变化（武装、原初之力等）
                d = st['deck']
                if t == 'acquire': d.add(e['id'], e.get('up', 0), e.get('c'))
                elif t == 'remove': d.remove(e['id'], e.get('c'))
                elif t == 'transform':
                    if e.get('from_id'): d.remove(e['from_id'], e.get('from_c'))
                    d.add(e['to_id'], 0, e.get('to_c'))
                elif t == 'upgrade': d.upgrade(e['id'], e.get('c'))
                elif t == 'downgrade': d.downgrade(e['id'], e.get('c'))
                if stats is not None and meta['replay_version'] >= 5: st['_chk'] = d.snap()
            elif t == 'relic': st['relics'].append(e['id'])
            elif t == 'relic_lost':
                if e['id'] in st['relics']: st['relics'].remove(e['id'])
            elif t == 'potion_got': st['potions'].append(e['id'])
            elif t in ('potion_used', 'potion_dropped'):
                if e['id'] in st['potions']: st['potions'].remove(e['id'])
            elif t == 'room':
                key = (e.get('kind'), e.get('id'), e.get('coord')); fl = e.get('floor')
                if fl in snaps and snaps[fl][0] == key:          # 同一个房间又进了一次 = 读档 / 重开
                    restore(snaps[fl][1])
                    for k in [k for k in snaps if k > fl]: del snaps[k]
                elif fl not in snaps:
                    snaps[fl] = (key, save())
            elif t == 'resume':
                if e.get('combat_id') and e.get('floor') in snaps: restore(snaps[e['floor']][1])
                if e.get('hp') is not None: st['hp'] = e['hp']
                if e.get('relics'): st['relics'] = list(e['relics'])
                if e.get('potions') is not None: st['potions'] = [p if isinstance(p, str) else p.get('id') for p in e['potions']]
            elif t == 'max_hp' and e.get('dst') in (None, 'player'):
                st['maxhp'] = e.get('max_hp', st['maxhp'])
            elif t == 'hp' and e.get('dst') in (None, 'player'):
                st['hp'] = e.get('hp', st['hp'])
            elif t == 'end':
                last_end = e; in_combat = False
                if cur is not None:
                    cur['end_reason'] = e.get('terminal_reason'); attempts.append(cur); cur = None
                continue
            # —— Boss 战 ——
            if t == 'combat_start': in_combat = True
            elif t == 'combat_end': in_combat = False
            if t == 'combat_start':
                if cur is not None: attempts.append(cur); cur = None
                if e.get('encounter') in BOSSES:
                    cur = {'boss': e['encounter'], 'cid': base_id(e.get('combat_id')), 'floor': e.get('floor'),
                           'hp': st['hp'], 'maxhp': st['maxhp'], 'deck': st['deck'].snap(), 'relics': list(st['relics']),
                           'potions': list(st['potions']), 'ev': [], 'result': None, 'end_reason': None}
            if cur is not None and t in KEEP:
                cur['ev'].append({k: v for k, v in e.items() if k not in ('s', 'ms', 'floor', 'act')})
                if t == 'combat_end':
                    cur['result'] = {'victory': 'win', 'loss': 'loss'}.get(e.get('result'), e.get('result'))
                    attempts.append(cur); cur = None
    if cur is not None: attempts.append(cur)
    if meta is None: return None, None
    meta['final_reason'] = (last_end or {}).get('terminal_reason')
    meta['final_deck'] = last_end.get('final_deck') if last_end else None
    meta['final_snap'] = st['deck'].snap() if st['deck'] else None
    # 同一个 combat_id 只留最后一次尝试
    by = collections.OrderedDict()
    for a in attempts:
        by.setdefault(a['cid'], []).append(a)
    fights = []
    for cid, lst in by.items():
        f = lst[-1]; f['attempts'] = len(lst)
        f['prev'] = lst[:-1]                         # 之前放弃重来的尝试（result 为 None 或 loss）
        hp0 = any(ev['t'] == 'hp' and ev.get('dst') in (None, 'player') and (ev.get('hp') or 0) <= 0 for ev in f['ev'])
        if f['result'] is None:
            if hp0 or (f is attempts[-1] and meta['final_reason'] == 'death'):
                f['result'] = 'loss'
            else:
                f['result'] = 'abandon'
        fights.append(f)
    return fights, meta


def _build(stats=None):
    out = []
    for p in sorted(glob.glob(f'{DIR}/*.ndjson.gz')):
        fights, meta = parse_file(p, stats)
        if meta is None: continue
        h = os.path.basename(p).split('.')[0]
        if stats is not None:
            stats['runs'] += 1
            fd = meta.get('final_deck')
            if fd:
                want = tuple(sorted(x['id'] + ('+' if x.get('up') else '') for x in fd))
                has_up = any('up' in x for x in fd)
                got = meta['final_snap'] if has_up else tuple(sorted(c.rstrip('+') for c in meta['final_snap']))
                if not has_up: want = tuple(sorted(c.rstrip('+') for c in want))
                stats['final_n'] += 1; stats['final_ok'] += got == want
        for f in fights:
            f['run'] = h; f['reloads_run'] = meta['reloads']
            out.append(f)
    return out


def load_fights(rebuild=False):
    src_m = max(os.path.getmtime(p) for p in glob.glob(f'{DIR}/*.ndjson.gz'))
    if not rebuild and os.path.exists(CACHE) and os.path.getmtime(CACHE) > max(src_m, os.path.getmtime(__file__)):
        with open(CACHE, 'rb') as f: return pickle.load(f)
    out = _build()
    with open(CACHE, 'wb') as f: pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    return out


if __name__ == '__main__':
    import time
    t = time.time(); stats = collections.Counter()
    fs = _build(stats)
    with open(CACHE, 'wb') as f: pickle.dump(fs, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f'录像（v0.111.0、无改玩法模组）{stats["runs"]} 局，用时 {time.time() - t:.0f}s')
    print(f'牌组正推 vs deck 快照：{stats["snap_ok"]}/{stats["snap_n"]} 一致；vs 最终牌组（只比 id）：{stats["final_ok"]}/{stats["final_n"]} 一致')
    c = collections.Counter((f['boss'], f['result']) for f in fs)
    for k in sorted(c): print(k, c[k])
    print('重开过的：', collections.Counter((f['boss'], f['result']) for f in fs if f['attempts'] > 1))
