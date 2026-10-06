"""篝火：默认升级；血少（或下一个是 Boss 而血不够）才休息。
rest_mode = imitate（10/3）：按人类赢家在同样处境下的选择（tools/rest_stats.py → data/rest_stats.json）。"""
import json, os
from params import P
from policy import longterm, valuemodel
from policy.knowledge import best_upgrade, UPGRADE, cid, is_bad

_TABLE = []


def _rest_table():
    if not _TABLE:
        try: _TABLE.append(json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'rest_stats.json'))))
        except Exception: _TABLE.append({})
    return _TABLE[0]


def upgrade_score(card_id, act):
    """升级值多少：人类赢家手里有这张牌（没升级）时、篝火选它升级的比例（分幕）。神化 / 添柴 0.9，打击 0.003，中位 0.1"""
    u = UPGRADE.get(card_id)
    if not isinstance(u, dict) or u.get('n', 0) < 15: return 0.05
    return u.get('by_act', {}).get(str(act), u['rate'])


def imitate_choice(st, mem, opts):
    """查人类 A10 赢家在「同一幕、下一个是不是 Boss、
    同一血量档、牌组里最好的升级分数同一档」时选升级的比例（15206 个篝火决定），≥ rest_imitate_th 就升级。
    表上看：血量 ≥60% 几乎都升级；45~60% 有值得升的就升、饱和（最好的 <0.05）多半睡；30~45% 升级越值钱越会敲；<30% 基本睡"""
    if 'HEAL' not in opts or 'SMITH' not in opts: return None
    T = _rest_table()
    if not T.get('_hp_bins'): return None
    pl = st.get('player') or {}; act = min(max(int((st.get('context') or {}).get('act') or 1), 1), 3)
    hp0 = pl.get('hp', 0) / max(pl.get('max_hp', 1), 1)
    best = max((upgrade_score(cid(c), act) for c in pl.get('deck') or [] if not c.get('upgraded') and not is_bad(c)), default=0.0)
    band = lambda x, bins: next((i for i, b in enumerate(bins) if x < b), len(bins))
    h, u = band(hp0, T['_hp_bins']), band(best, T['_up_bins'])
    r = T.get(f"{act}|{int(bool(mem.get('next_is_boss')))}|{h}|{u}")
    if not r or r[1] < 5: r = T.get(f'{act}|0|{h}|{u}')         # Boss 前样本少：用同一格的非 Boss 前
    if not r or r[1] < 5: return None
    p = r[0] / r[1]
    mem['rest_imitate'] = (round(hp0, 2), round(best, 2), round(p, 2))
    return 'SMITH' if p >= P.get('rest_imitate_th', 0.5) else 'HEAL'


def value_choice(st, mem, opts):
    """胜率模型：比较「回 30% 血」和「升级最值得升的几张牌之一」之后的胜率"""
    pl = st.get('player') or {}; s0 = valuemodel.state_of(st)
    best, pick = -1.0, None
    if 'HEAL' in opts:
        heal = dict(s0, hp=min(s0['max_hp'], s0['hp'] + 0.3 * s0['max_hp']))
        best, pick = valuemodel.win_prob(heal) + P['rest_heal_bias'] / 100, 'HEAL'
    if 'SMITH' in opts:
        act = (st.get('context') or {}).get('act', 2)
        for c in best_upgrade(pl.get('deck') or [], act)[:5]:
            if c.get('upgraded'): continue
            v = valuemodel.win_prob(valuemodel.upgraded(s0, c.get('id')))
            if v > best: best, pick = v, 'SMITH'
    return pick


def choose(st, mem):
    index = _choose(st, mem)
    replacement = pumpkin_kindling_choice(st, mem, index)
    if replacement is not None:
        mem.pop('select_purpose', None)
        return replacement
    return index


def pumpkin_kindling_choice(st, mem, selected_index):
    """Optional replacement of an already chosen Smith, never a chosen Heal.

    Pumpkin Candle's counter is the displayed DisplayAmount (ShowCounter=True).
    No historical save, private KindleCount or future encounter is consulted.
    """
    if (not P.get('rest_pumpkin_rekindle', False)
            or (st.get('context') or {}).get('act', 1) not in P.get('rest_pumpkin_rekindle_acts', [2])
            or P.get('rest_mode', 'rule') != 'rule' or P.get('rest_boss_sim')):
        return None
    options = [o for o in st.get('options') or [] if o.get('is_enabled', True)]
    selected = next((o for o in options if o.get('index') == selected_index), {})
    kindle = next((o for o in options if o.get('option_id') == 'KINDLE'), None)
    if selected.get('option_id') != 'SMITH' or kindle is None:
        return None
    relic = next((r for r in (st.get('player') or {}).get('relics') or []
                  if str(r.get('id') or '').removeprefix('RELIC.') == 'PUMPKIN_CANDLE'), {})
    counter = relic.get('counter')
    if not isinstance(counter, int) or isinstance(counter, bool) or counter < 0:
        return None
    if counter > P.get('rest_pumpkin_rekindle_max', 1):
        return None
    if mem.get('next_is_boss') and counter >= 1:
        return None       # Already supplies the imminent Boss; keep the upgrade.
    mem['rest_pumpkin_rule'] = {'public_counter': counter, 'selected_before': 'SMITH',
                               'pick': 'KINDLE', 'next_is_boss': bool(mem.get('next_is_boss'))}
    return kindle['index']


def _choose(st, mem):
    """规则选出一个（底分 1，其余 0），再交给 learn.pick 加上学出来的偏好（按血量档）"""
    from policy import learn
    mem.pop('rest_potion_rule', None)
    i = _rule(st, mem)
    opts = [o for o in st.get('options') or [] if o.get('is_enabled', True)]
    if len(opts) < 2: return i
    if mem.pop('rest_rule_forced', False):
        mem['select_purpose'] = 'upgrade'; return i
    if P.get('rest_mode') == 'imitate' and mem.get('rest_imitate_used'):
        mem.pop('rest_imitate_used', None); return i    # 表本身就是高手的偏好，不再叠学到的偏好
    if (st.get('context') or {}).get('act', 1) not in P.get('rest_learn_acts', [1, 2, 3]):
        return i                                       # 这一幕篝火按规则（高手录像研究：第二幕 Boss 前人类升级 ~7 次、我们 5~6；学到的偏好偏回血）
    k = learn.pick('rest', [(o['index'], 1.0 if o['index'] == i else 0.0, learn.feats('rest', o.get('option_id'), st)) for o in opts], st, mem)
    o = next((x for x in opts if x['index'] == k), {})
    pl = st.get('player') or {}
    smith = next((x for x in opts if x.get('option_id') == 'SMITH'), None)
    if o.get('option_id') == 'HEAL' and smith and pl.get('hp', 0) >= P.get('rest_no_heal_above', 0.85) * max(pl.get('max_hp', 1), 1):
        k, o = smith['index'], smith                   # 10/3：学到的偏好在 80/80 满血时还选回血（白白少一次升级）；回血一半以上会浪费就改升级
    mem['select_purpose'] = 'upgrade' if o.get('option_id') == 'SMITH' else mem.get('select_purpose') if k == i else None
    return k


def _rule(st, mem):
    pl = st.get('player') or {}; hpf = pl.get('hp', 1) / max(pl.get('max_hp', 1), 1)
    opts = {o.get('option_id'): o for o in st.get('options') or [] if o.get('is_enabled', True)}
    if P.get('rest_mode') == 'imitate':
        k = imitate_choice(st, mem, opts)
        if k == 'HEAL':
            mem['rest_imitate_used'] = True; return opts['HEAL']['index']
        if k == 'SMITH':
            mem['rest_imitate_used'] = True
            lift = longterm.rest_choice(opts)             # 举重等长期收益的选项照原规则优先
            if lift is not None: return lift
            mem['select_purpose'] = 'upgrade'; return opts['SMITH']['index']
    if P.get('rest_mode') == 'value' and valuemodel.available() and ('HEAL' in opts or 'SMITH' in opts):
        lift = longterm.rest_choice(opts)
        if lift is not None: return lift
        k = value_choice(st, mem, opts)
        if k == 'SMITH': mem['select_purpose'] = 'upgrade'
        if k: return opts[k]['index']
    if P.get('rest_boss_sim') and 'HEAL' in opts and 'SMITH' in opts:
        k = boss_sim_choice(st, mem, opts)
        if k is not None:
            mem['rest_rule_forced'] = True             # Boss 账算出来的：学到的偏好别再改回去
            if k == 'SMITH': mem['select_purpose'] = 'upgrade'
            return opts[k]['index']
    hb, hbb = P['heal_below'], P['heal_below_before_boss']
    if P.get('heal_below_a23') is not None and (st.get('context') or {}).get('act', 1) >= 2:
        hb = P['heal_below_a23']                       # 10/4：第二幕 Boss 前我们比人类少升 3.5 张；第一幕不动（上次全局降回血线第一幕 70% → 52%）
    if P.get('rest_potion_smith', False) and 'HEAL' in opts and 'SMITH' in opts:
        # 带瓶中精灵：只在血极低时回血；每瓶好药 / 牌组够强：回血线往下挪
        from policy import potions as PO, deckeval
        ids = [PO.pid(p) for p in pl.get('potions') or [] if p and p.get('name')]
        good = sum(1 for i, p in zip(ids, [p for p in pl.get('potions') or [] if p and p.get('name')])
                   if i in PO.KEY_RANK or PO.kind(p) in ('heal', 'defense'))
        shift = min(P.get('rest_potion_shift_max', 0.15), P.get('rest_potion_shift', 0.05) * good)
        if deckeval.elite_ready(st) >= P.get('rest_strong_ready', 0.9): shift += P.get('rest_strong_shift', 0.1)
        hb, hbb = hb - shift, hbb - shift
        if 'FAIRY_IN_A_BOTTLE' in ids:
            hb = hbb = min(hb, P.get('rest_fairy_heal_below', 0.25))
        if shift or 'FAIRY_IN_A_BOTTLE' in ids:
            mem['rest_potion_rule'] = (round(hpf, 2), round(hb, 2), round(hbb, 2), good, 'FAIRY_IN_A_BOTTLE' in ids)
    if 'HEAL' in opts and (hpf < hb or (mem.get('next_is_boss') and hpf < hbb)):
        return opts['HEAL']['index']
    if mem.get('rest_potion_rule') and 'SMITH' in opts and hpf < max(P['heal_below'], P['heal_below_before_boss'] if mem.get('next_is_boss') else 0):
        mem['rest_rule_forced'] = True                 # 原规则会回血、因为身上的药 / 牌改成敲牌：别再让学到的偏好改回去
    lift = longterm.rest_choice(opts)
    if lift is not None: return lift
    if 'SMITH' in opts:
        mem['select_purpose'] = 'upgrade'; return opts['SMITH']['index']
    o = next(iter(opts.values()), None)
    return o['index'] if o else 0


BOSS_FLOOR = {1: 17, 2: 16, 3: 15}               # 各幕 Boss 所在层（整局记录里的楼层是按幕算的）


def boss_sim_choice(st, mem, opts):
    """篝火 Boss 账。
    根源：人类第一幕篝火 72% 选升级、进 Boss 时 50/81 血、牌组升级 3.5 张；我们升级只占约 3 成、牌组升级 1.2 张，
    进 Boss 血更多却打不过（亲自打失败对局：灵魂异鱼 / 族母那几副牌换谁打都不够）。
    做法：回血 → 当前牌组带「回血后的血 − 路上预计掉血」；升级 → 升级后的牌组带「当前血 − 路上预计掉血」，
    各拿去按真实血量模拟打本幕 Boss（地图上公开，新种子，只用看得见的信息），数打赢几次；
    升级的胜率不比回血低 rest_sim_tol 以上就选升级（升级以后几幕还有用，回血没有），一样时比剩血。"""
    from policy import simeval
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    hp, mx = pl.get('hp', 1), max(pl.get('max_hp', 1), 1)
    act = min(max(int(ctx.get('act') or 1), 1), 3); floor = int(ctx.get('floor') or 0)
    deck_cards = pl.get('deck') or []
    if not deck_cards or not (ctx.get('boss') or {}).get('id'): return None
    order = best_upgrade([c for c in deck_cards if not c.get('upgraded')], act)
    if not order: return 'HEAL'
    deck0 = simeval.deck_ids(st); top = cid(order[0]); deck_u = list(deck0)
    if top in deck_u: deck_u[deck_u.index(top)] = top + '+'
    rem = max(0, BOSS_FLOOR.get(act, 17) - floor - 1)
    path = rem * P.get('rest_sim_floor_loss', 4.0)
    heal = round(P.get('rest_heal_frac', 0.3) * mx)
    hp_h = min(mx, hp + heal) - path; hp_s = hp - path
    rh = simeval.boss_runs(st, deck0, hp_h, tag='rest-h'); rs = simeval.boss_runs(st, deck_u, hp_s, tag='rest-s')
    if len(rh) < 2 or len(rs) < 2: return None
    wh = sum(w for w, _ in rh) / len(rh); ws = sum(w for w, _ in rs) / len(rs)
    eh = sum(h for _, h in rh) / len(rh); es = sum(h for _, h in rs) / len(rs)
    if ws > wh - P.get('rest_sim_tol', 0.05) - 1e-9 and not (abs(ws - wh) < 1e-9 and eh > es + P.get('rest_sim_hp_margin', 15)):
        k = 'SMITH'
    else:
        k = 'HEAL'
    mem['rest_sim'] = dict(act=act, floor=floor, hp=hp, mx=mx, up=top, path=round(path, 1), hp_heal=round(hp_h), hp_smith=round(hp_s),
                           win_heal=round(wh, 2), win_smith=round(ws, 2), left_heal=round(eh), left_smith=round(es), pick=k)
    mem.setdefault('rest_sim_log', []).append(mem['rest_sim'])
    return k
