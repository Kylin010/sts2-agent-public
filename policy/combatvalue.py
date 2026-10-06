"""战斗局面估值：回合结束时的局面 → 「这次敌方回合之后，到战斗结束还要掉多少血」（死了 +惩罚）。
v2：这次敌方回合要吃的伤害（意图 − 格挡）由规划器精确算，模型只预测之后的部分——v1 让模型连这一下一起猜，
结果它对格挡几乎不敏感（格挡 5 → 15 预测不变），接进规划器后存活率从 57% 掉到 26%。

用法分两步：
1. 采集：环境变量 STS2_LOG_TURNS=1 时，run.drive 在每次结束回合前用 situation_from_state 记下局面，
   战斗结束后补上结果（之后掉的血、死没死），写进结果文件（tools/train_combat_value.py 训练）。
2. 规划：combat.py 对每个候选出牌组合，用 situation_after 推算「打完这组牌、结束回合时」的局面，交给模型估值。

局面（situation）只用打完牌就能确定的信息：我的血 / 格挡 / 力量 / 减益，每个敌人剩多少有效血、这回合意图伤害、力量、
是否随从，遭遇 id、第几回合、牌组大小、抽牌堆 / 弃牌堆张数、我每回合大概能打多少伤害。
"""
import json, math, os
from policy.knowledge import is_attack_intent

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/combat_value.json'
M = None


def _amt(powers, word, exact=False):
    for p in powers or []:
        n = str(p.get('name', '')).lower()
        if (n == word) if exact else (word in n): return p.get('amount') or 1
    return 0


def _intent(e):
    tot = 0
    for it in e.get('intents') or []:
        if is_attack_intent(it):
            d = it.get('damage') or 0
            tot += d * (it.get('hits') or 1) if it.get('hits') else d
    return tot


_DPT = {}


def deck_dpt(deck):
    """整副牌组每回合大概能打多少（policy/deckeval 的估计，按牌组缓存）"""
    key = tuple(sorted(f"{c.get('id')}{'+' if c.get('upgraded') else ''}" for c in deck or []))
    if key not in _DPT:
        from policy import deckeval
        _DPT[key] = deckeval.evaluate(deck or [])['dmg_per_turn']
    return _DPT[key]


def situation_from_state(st, my_dpt=None):
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    my_dpt = deck_dpt(pl.get('deck'))
    pw = st.get('player_powers') or []
    ens = []
    for e in st.get('enemies') or []:
        if (e.get('hp') or 0) <= 0: continue
        ep = e.get('powers') or []
        try:                                               # 出招表推算的接下来 3 回合平均伤害（认不出招就用这回合意图）
            from policy import foresight
            mv = foresight.identify(e); f3 = foresight.future(e, mv, 3, public_player_powers=pw) if mv else None
            fut = sum(f3) / len(f3) if f3 else _intent(e)
        except Exception:
            fut = _intent(e)
        ens.append({'index': e.get('index'), 'fut': fut,
                    'ehp': (e.get('hp') or 0) + (e.get('block') or 0), 'intent': _intent(e), 'str': _amt(ep, 'strength', True),
                    'minion': 1 if _amt(ep, 'minion') else 0, 'vuln': 1 if _amt(ep, 'vulner') else 0, 'weak': 1 if _amt(ep, 'weak') else 0})
    return {'enc': ctx.get('encounter') or '', 'act': ctx.get('act') or 1, 'round': st.get('round') or 1,
            'hp': pl.get('hp', 1), 'max_hp': pl.get('max_hp', 80), 'block': pl.get('block', 0),
            'str': _amt(pw, 'strength', True), 'dex': _amt(pw, 'dexterity', True), 'n_pw': len(pw),
            'p_weak': 1 if _amt(pw, 'weak') else 0, 'p_vuln': 1 if _amt(pw, 'vulner') else 0, 'p_frail': 1 if _amt(pw, 'frail') else 0,
            'deck': pl.get('deck_size') or len(pl.get('deck') or []), 'draw': st.get('draw_pile_count') or 0,
            'discard': st.get('discard_pile_count') or 0, 'my_dpt': my_dpt or 0, 'enemies': ens}


def features(s):
    """局面 → 数值特征（字典），模型按名字取权重。遭遇 id 做成独热"""
    ens = s['enemies']; mains = [e for e in ens if not e['minion']] or ens
    inc = sum(e['intent'] for e in ens)                 # 引擎给的意图伤害已经算了虚弱 / 易伤
    unb = max(0, inc - s['block'])
    ehp = sum(e['ehp'] for e in mains); ehp_all = sum(e['ehp'] for e in ens)
    dpt = max(s['my_dpt'], 5)
    hp = max(s['hp'] - unb, 1)                         # v2：以「这次敌方回合挨打之后」的血量为起点（这一下由规划器精确算）
    f = {'bias': 1.0, 'hp': hp / 80, 'hp_frac': hp / max(s['max_hp'], 1), 'inc': inc / 30, 'ehp': ehp / 200, 'ehp_all': ehp_all / 200, 'turns_left': min(ehp / dpt, 20) / 5,
         'inc_x_turns': min(inc * ehp / dpt, 2000) / 300, 'n_en': len(ens) / 3, 'max_int': max([e['intent'] for e in ens] or [0]) / 30,
         'e_str': sum(e['str'] for e in ens) / 10, 'e_vuln': sum(e['vuln'] for e in ens) / 3, 'e_weak': sum(e['weak'] for e in ens) / 3,
         'fut': sum(e.get('fut', e['intent']) for e in ens) / 30, 'fut_x_turns': min(sum(e.get('fut', e['intent']) for e in ens) * ehp / dpt, 2000) / 300,
         'str': s['str'] / 10, 'dex': s['dex'] / 10, 'n_pw': s['n_pw'] / 5, 'p_weak': s['p_weak'], 'p_vuln': s['p_vuln'],
         'p_frail': s['p_frail'], 'deck': s['deck'] / 30, 'draw': s['draw'] / 20, 'round': min(s['round'], 20) / 10, 'dpt': dpt / 30,
         f"act{min(max(int(s['act']), 1), 3)}": 1.0, 'won': 1.0 if not mains else 0.0}
    if s['enc']: f['enc:' + s['enc']] = 1.0
    return f


def _load():
    global M
    from params import P
    path = f"{HERE}/data/{P.get('cv_file') or 'combat_value.json'}"   # cv_file 选模型（combat_value_teacher.json = 推演老师蒸馏的）
    if M is not None and M.get('_path') != path: M = None
    if M is None and os.path.exists(path):
        M = json.load(open(path)); M['_path'] = path
        # 把输入标准化折进第一层权重：只有非零特征需要算（特征大多是 0，遭遇独热 90 多个里只有 1 个），快 3~4 倍
        mu = M.get('mu') or [0.0] * len(M['features']); sd = M.get('sd') or [1.0] * len(M['features'])
        M['_cols'] = {k: [row[i] / sd[i] for row in M['W1']] for k, i in M['idx'].items()}
        M['_b1'] = [b - sum(row[i] * mu[i] / sd[i] for i in range(len(mu))) for row, b in zip(M['W1'], M['b1'])]
    return M


def available():
    return _load() is not None


def unblocked_now(s):
    """这次敌方回合要吃的伤害（意图 − 格挡）"""
    return max(0, sum(e['intent'] for e in s['enemies']) - s['block'])


def predict(s):
    """预计这次敌方回合之后、到战斗结束还要掉多少血（死了 + 惩罚）；这次敌方回合本身的伤害不含在内"""
    if not [e for e in s['enemies'] if not e['minion']]:
        return 0.0                                      # 主怪全死 = 赢了。训练数据里没有这种局面，不能交给模型外推
    m = _load(); f = features(s)
    h = list(m['_b1']); cols = m['_cols']
    for k, v in f.items():
        if v and k in cols:
            h = [a + v * c for a, c in zip(h, cols[k])]
    y = sum(w * hi for w, hi in zip(m['W2'], h) if hi > 0) + m['b2']        # 一层 ReLU
    return max(0.0, y * m['scale'])
