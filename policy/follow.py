"""照着人类赢家的整局决定打。

社区对局（sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz）每局都带种子和逐层记录：走了什么类型的点、
选卡奖励里拿了哪张、篝火休息还是升级（升了哪张）、事件选了哪个选项、商店买了 / 删了什么、开局古神选了哪个遗物。
引擎能开任意种子，所以可以在同一个种子上：整局决定全部照人类的来，只有战斗是我们自己打。
  - 用途 1（诊断）：照着赢家的决定还输 → 瓶颈在战斗；能赢 → 瓶颈在整局决定
  - 用途 2（训练）：同一个局面「人类拿了什么」可以在引擎里精确还原，作为模仿学习 / 强化学习的起点
sts2-cli 第一幕永远是密林，所以只用第一幕是密林的赢局（v0.111.0 有 1017 局）。
对不上的时候（我们战斗打得不同 → 掉的血、药水不同；随机数分叉 → 奖励不同）就退回我们自己的决定，并记一笔「分叉」。
"""
import gzip, json, os
from policy import kb

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = f'{HERE}/lab/human/winners.jsonl.gz'      # 从社区数据里只抽出种子和逐层记录（远端机器也有；不进 git 仓库）
if not os.path.exists(SRC): SRC = '/opt/slay-the-spire-2/sources/community-runs/ironclad-a10-v0.111.0.jsonl.gz'
TYPE = {'ancient': 'Ancient', 'monster': 'Monster', 'unknown': 'Unknown', 'elite': 'Elite', 'rest_site': 'RestSite',
        'shop': 'Shop', 'treasure': 'Treasure', 'boss': 'Boss'}


def winners(overgrowth_only=True):
    out = []
    with gzip.open(SRC, 'rt') as f:
        for l in f:
            r = json.loads(l)
            if r.get('win') and r.get('seed') and (not overgrowth_only or r['acts'][0] == 'ACT.OVERGROWTH') and not r.get('modifiers'):
                out.append(r)
    return out


def _strip(x):
    return str(x or '').split('.', 1)[-1] if str(x or '').startswith(('CARD.', 'RELIC.', 'POTION.', 'ENCOUNTER.', 'EVENT.')) else str(x or '')


class Script:
    def __init__(self, run):
        self.seed = run['seed']
        self.acts = run['map_point_history']
        self.div = []                                   # 分叉记录：(幕, 层, 决定, 说明)
        self.used = {}                                  # 每层已经照做到第几个（事件多页、商店多次购买）

    def entry(self, act, floor):
        """我们的 (幕, 层) 对应人类记录里的哪一项：层从 1 开始（第 1 层是古神），所以下标 = 层 - 1"""
        a = self.acts[act - 1] if 0 < act <= len(self.acts) else []
        i = (floor or 0) - 1
        return a[i]['player_stats'][0] if 0 <= i < len(a) else None, (a[i] if 0 <= i < len(a) else None)

    def types(self, act):
        return [TYPE.get(p['map_point_type'], p['map_point_type']) for p in self.acts[act - 1]] if 0 < act <= len(self.acts) else []

    def note(self, act, floor, what, info=''):
        self.div.append((act, floor, what, str(info)[:120]))

    # ---- 各种决定：返回动作；照不了就返回 None（由调用方退回自己的决定）----
    def route(self, sim_map, st):
        ctx = st.get('context') or {}; act = ctx.get('act') or 1; floor = ctx.get('floor') or 0
        seq = self.types(act)[floor:]                   # 从下一层开始人类走的点类型
        nodes = {(n['col'], n['row']): n for row in sim_map.get('rows') or [] for n in row}

        def ok(k, i):
            n = nodes.get(k) or {'type': 'Boss'}
            if i >= len(seq): return True
            t = n.get('type') or 'Boss'
            if t != seq[i]: return False
            kids = n.get('children') or []
            return not kids or i + 1 >= len(seq) or any(ok((c['col'], c['row']), i + 1) for c in kids)
        for c in st.get('choices') or []:
            if ok((c['col'], c['row']), 0): return c
        self.note(act, floor, 'route', f'想走 {seq[:3]}，可选 {[(c.get("type")) for c in st.get("choices") or []]}')
        return None

    def card_reward(self, st):
        ctx = st.get('context') or {}; act, floor = ctx.get('act') or 1, ctx.get('floor') or 0
        ps, _ = self.entry(act, floor)
        if not ps or not ps.get('card_choices'): self.note(act, floor, 'pick', '没有记录'); return None
        k = (act, floor, 'pick'); n = self.used.get(k, 0); self.used[k] = n + 1
        offered = {str(c.get('id', '')).replace('CARD.', ''): c['index'] for c in st.get('cards') or []}
        hc = ps['card_choices']; hset = {_strip(c['card']['id']) for c in hc}
        if set(offered) != hset: self.note(act, floor, 'pick', f'奖励不同：人类 {sorted(hset)} 我们 {sorted(offered)}')
        picked = [_strip(c['card']['id']) for c in hc if c.get('was_picked')]
        for p in picked:
            if p in offered: return ('select_card_reward', {'card_index': offered[p]})
        if not picked: return ('skip_card_reward', {})
        return None

    def rest(self, st):
        ctx = st.get('context') or {}; act, floor = ctx.get('act') or 1, ctx.get('floor') or 0
        ps, _ = self.entry(act, floor)
        ch = (ps or {}).get('rest_site_choices') or []
        opts = {o.get('option_id'): o for o in st.get('options') or [] if o.get('is_enabled', True)}
        for c in ch:
            if c in opts: return opts[c]['index'], c
        self.note(act, floor, 'rest', f'人类 {ch} 可选 {list(opts)}')
        return None

    def select(self, st, purpose):
        """篝火升级 / 商店删牌选哪张"""
        ctx = st.get('context') or {}; act, floor = ctx.get('act') or 1, ctx.get('floor') or 0
        ps, _ = self.entry(act, floor)
        want = [_strip(x) for x in (ps or {}).get('upgraded_cards') or []] if purpose == 'upgrade' else \
               [_strip(x.get('id')) for x in (ps or {}).get('cards_removed') or []] if purpose == 'remove' else []
        for w in want:
            for c in st.get('cards') or []:
                if str(c.get('id', '')).replace('CARD.', '') == w and (purpose != 'upgrade' or not c.get('upgraded')):
                    return str(c['index'])
        if want: self.note(act, floor, 'select', f'{purpose} 想要 {want}')
        return None

    def event(self, st):
        ctx = st.get('context') or {}; act, floor = ctx.get('act') or 1, ctx.get('floor') or 0
        ps, _ = self.entry(act, floor)
        if not ps: return None
        opts = [o for o in st.get('options') or [] if not o.get('is_locked')]
        if st.get('event_name') == 'Neow' or ps.get('ancient_choice'):
            want = [c['TextKey'] for c in ps.get('ancient_choice') or [] if c.get('was_chosen')]
            for o in opts:
                if str(o.get('text_key', '')).split('.')[-1] in want or any(w in str(o.get('text_key', '')) for w in want): return o['index']
            self.note(act, floor, 'ancient', f'想要 {want}'); return None
        k = (act, floor, 'event'); n = self.used.get(k, 0)
        keys = [str((c.get('title') or {}).get('key', '')).replace('.title', '') for c in ps.get('event_choices') or []]
        if n < len(keys):
            for o in opts:
                if str(o.get('text_key', '')).replace('.title', '') == keys[n]:
                    self.used[k] = n + 1; return o['index']
        self.note(act, floor, 'event', f'想要 {keys[n:n + 1]} 可选 {[o.get("text_key") for o in opts]}')
        return None

    def shop(self, st, mem):
        ctx = st.get('context') or {}; act, floor = ctx.get('act') or 1, ctx.get('floor') or 0
        ps, _ = self.entry(act, floor)
        if not ps: return ('leave_room', {})
        done = mem.setdefault('follow_shop', set())
        if ps.get('cards_removed') and 'remove' not in done:
            done.add('remove'); mem['select_purpose'] = 'remove'; return ('remove_card', {})
        want_r = [_strip(x) for x in ps.get('bought_relics') or []]
        for r in st.get('relics') or []:
            i = str(r.get('id') or kb.id_by_name('relics', r.get('name')) or '').replace('RELIC.', '')
            if i in want_r and ('r', i) not in done: done.add(('r', i)); return ('buy_relic', {'relic_index': r['index']})
        gained = [_strip(c.get('id')) for c in ps.get('cards_gained') or []]
        for c in st.get('cards') or []:
            i = str(c.get('id') or kb.id_by_name('cards', c.get('name')) or '').replace('CARD.', '')
            if i in gained and ('c', c['index']) not in done: done.add(('c', c['index'])); return ('buy_card', {'card_index': c['index']})
        want_p = [_strip(x) for x in ps.get('bought_potions') or []]
        for p in st.get('potions') or []:
            i = str(p.get('id') or kb.id_by_name('potions', p.get('name')) or '').replace('POTION.', '')
            if i in want_p and ('p', p['index']) not in done: done.add(('p', p['index'])); return ('buy_potion', {'potion_index': p['index']})
        mem.pop('follow_shop', None)
        return ('leave_room', {})


_BY = {}


def by_seed(seed):
    if not _BY:
        for r in winners(): _BY.setdefault(r['seed'], r)
    return _BY.get(seed)
