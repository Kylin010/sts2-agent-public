"""整局价值网络（tools/train_run_value.py 用社区整局记录训练）：看得见的家底 → 这一局最后通关的概率。


训练数据：社区铁甲 A10 整局记录（全版本约 5.3 万局可用，v0.111 检验），每一层「进入这一层之前」的家底
（第几幕、本幕打完几层、血 / 上限、金币、牌组含升级、遗物、药水、第一幕章节）+ 这局最后有没有通关。

模型（data/run_value.json）：逻辑回归，特征见 features()：数值（血量比例 / 绝对值 / × 进度、上限、金币、药水数、牌组大小、升级数）
  + 牌组汇总（类型、标签张数、有没有 / 有没有两张、平均伤害 / 格挡 / 费用）+ 每张牌张数（含 × 第几幕）+ 升级张数 + 遗物（含 × 幕）
  + 药水 id + 第一幕章节 + 版本（运行时固定 v0.111）。训练脚本也能训宽+深（一层隐藏层），比线性好不到 0.001 就不用。
  另带「下一个点」修正头（next_head）：Q(家底, 下一个点类型) = 家底 logit + 类型 × 血量 / 低血 / 家底强弱 / 进度 / 金币 / 药水。
  data/run_value_style.json 是去混杂版：训练时多给「打法历史」（普通 / 精英战掉血、选牌跳过率、篝火升级率、删牌数、已打精英数）当水平代理，
  运行时这些统一填人群平均 → 血量、牌组大小等的权重里少掉「高手才这样」的部分。用 --set run_value_file=data/run_value_style.json 切换做 A/B。
推理纯 Python（不依赖 numpy），一次 win_prob 约 1~3 毫秒。

用法：
  from policy import runvalue
  p = runvalue.win_prob(st)                                  # st = 引擎局面（st['player']、st['context']）；context.floor = 本幕第几层
  runvalue.delta_card(st, 'CARD.DEMON_FORM')                 # 拿这张牌 − 不拿（通关概率差，0.01 = 1 个百分点）
  runvalue.card_choice_values(st, [('CARD.UPPERCUT', False), ...])   # 战后选牌：每个选项（含 SKIP）拿了之后的通关概率
  runvalue.delta_relic(st, 'VAJRA')；delta_remove(st, 'CARD.STRIKE_IRONCLAD')；delta_upgrade(st, 'CARD.BASH')；delta_potion / delta_gold / delta_hp
  runvalue.rest_values(st, next_types=['boss'])             # 篝火：{'HEAL': 概率, 'SMITH': (概率, 升哪张), 'pick': ...}
  runvalue.route_values(st, ['monster', 'elite', 'rest_site']) # 路线：下一步走哪种点的通关概率（试验性，见下）
注意：
  - 这是「社区玩家（人类）接着打」的通关概率，绝对值比我们的程序高；做决定只看同一局面下选项之间的差。
  - 混杂：高手的习惯（常拿 / 常跳的牌、血量高）也会被学成「赢的原因」，接进决策时当一个信号，用实打 A/B 验证。
  - 篝火：不给 next_types 时低血回血被低估（人类低血几乎都回血，数据里「低血不回血」的后果看不到）；第一 / 二幕中等血量又偏爱回血。
  - 路线：next_head 的类型差带人类选路的选择偏差（强的时候才进精英），低血进精英也显示为正——别直接拿来选路，
    选路更稳的做法是「战斗模型估的掉血 / 奖励 → 打完后的家底 → prob_of」。
  - 只在同一种遗物来源之间比（先古之民三选一、Boss 遗物三选一、商店）；第一幕局面里加第二幕才有的遗物，差值没有意义。
"""
import json, math, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = f'{HERE}/data/run_value.json'
OVERRIDE = None                      # 训练 / 检验脚本直接指定模型文件时用（优先于参数）
_M = None
_KB = None

TAGS = ['damage', 'power', 'draw', 'block', 'energy', 'vuln', 'aoe', 'strength', 'self_damage', 'multi_hit', 'exhaust_fuel',
        'block_payoff', 'strike_arch', 'exhaust_payoff', 'exhaust_engine', 'scaling', 'weak']
TYPES = ['Attack', 'Skill', 'Power', 'Curse', 'Status']
NEXT_TYPES = ['monster', 'elite', 'rest_site', 'shop', 'unknown', 'treasure', 'boss', 'ancient']    # 地图点类型（社区记录的 map_point_type）
_NEXT_ALIAS = {'monster': 'monster', 'elite': 'elite', 'restsite': 'rest_site', 'rest_site': 'rest_site', 'rest': 'rest_site', 'shop': 'shop',
               'merchant': 'shop', 'unknown': 'unknown', 'event': 'unknown', 'treasure': 'treasure', 'chest': 'treasure', 'boss': 'boss', 'ancient': 'ancient'}
CHAPTER_NAMES = {'OVERGROWTH': 'OVERGROWTH', 'UNDERDOCKS': 'UNDERDOCKS', '密林': 'OVERGROWTH', '暗港': 'UNDERDOCKS',
                 'ACT.OVERGROWTH': 'OVERGROWTH', 'ACT.UNDERDOCKS': 'UNDERDOCKS'}


def _norm(x, pre):
    return str(x or '').replace(pre, '').rstrip('+').strip()


def kb_cards():
    """卡牌知识库 → {id: (类型, 标签, 伤害×段数, 格挡, 抽牌, 能量, 费用)}"""
    global _KB
    if _KB is None:
        _KB = {}
        try:
            for k, v in json.load(open(f'{HERE}/kb/cards.json')).items():
                _KB[k] = (v.get('type'), tuple(v.get('tags') or ()), (v.get('damage') or 0) * max(v.get('hits') or 1, 1),
                          v.get('block') or 0, v.get('draw') or 0, v.get('energy') or 0, v.get('cost') if isinstance(v.get('cost'), int) else 1)
        except Exception:
            pass
    return _KB


def build_group(b):
    """版本号 → 版本组（全版本 + 版本特征的模型用）"""
    b = str(b or '')
    for g in ('v0.111', 'v0.110', 'v0.109', 'v0.108', 'v0.107', 'v0.106', 'v0.105', 'v0.104', 'v0.103'):
        if b.startswith(g): return g
    return 'old'


def features(s, opt):
    """家底 → {特征名: 值}。s = {act, done, hp, max_hp, gold, deck [(id, 升级?)], relics [id], potions [id], chapter, build,
    （训练时另有 hist 打法历史、elites / elites_act 已打精英数）}
    opt = 模型训练时的特征开关（存在模型文件里，训练和运行用同一份）"""
    kb = kb_cards()
    act = min(max(int(s.get('act') or 1), 1), 3); A = f'|A{act}'
    done = max(int(s.get('done') or 0), 0); prog = min(done, 18) / 17.0
    mhp = max(float(s.get('max_hp') or 80), 1.0); hp = min(max(float(s.get('hp') or 0), 0.0), mhp)
    if mhp > 150: hp, mhp = hp / mhp * 80.0, 80.0          # 练习模式（999 血）按比例折回正常范围
    frac = hp / mhp; gold = min(max(float(s.get('gold') or 0), 0.0), 900.0)
    f = {}

    def add(k, v):
        if v: f[k] = f.get(k, 0.0) + v

    add('act' + str(act), 1.0); add('prog' + A, prog); add('prog2' + A, prog * prog)
    add('frac', frac); add('frac' + A, frac); add('frac*prog' + A, frac * prog)
    add('hp', hp / 80.0); add('hp' + A, hp / 80.0); add('hp*prog' + A, hp / 80.0 * prog)
    add('mhp', (mhp - 80.0) / 20.0); add('mhp' + A, (mhp - 80.0) / 20.0)
    add('lo30', 1.0 if frac < 0.3 else 0.0); add('lo50', 1.0 if frac < 0.5 else 0.0)
    add('gold', gold / 300.0); add('gold' + A, gold / 300.0)
    pots = [_norm(p, 'POTION.') for p in s.get('potions') or [] if p]
    add('pots', len(pots) / 3.0); add('pots' + A, len(pots) / 3.0)
    ch = CHAPTER_NAMES.get(str(s.get('chapter') or '').upper()) or CHAPTER_NAMES.get(str(s.get('chapter') or ''))
    if ch == 'UNDERDOCKS' and act == 1: add('docks|A1', 1.0); add('docks*prog|A1', prog)     # 第一幕章节只在第一幕用（运行时第二幕起拿不到）
    if opt.get('style'):
        # 水平 / 风格代理（到目前为止的打法历史）。训练时用真实历史，把「高手的习惯」从牌组 / 遗物的权重里剥出去；
        # 运行时没有历史 → 填人群平均（模型文件里的 style_ref，按幕和层），所以给出的是「普通社区玩家接着打」的通关概率
        h = s.get('hist')
        if h is None:
            ref = (opt.get('style_ref') or {})
            for k, v in (ref.get(f'{act}|{min(done, 18)}') or ref.get(f'{act}|0') or {}).items(): add(k, v)
        else:
            dm = h['dmg_m'] / (h['n_m'] + 3) / 10.0; sk = (h['n_skip'] - 0.23 * h['n_rw']) / (h['n_rw'] + 3.0)
            add('sk:dmg', dm); add('sk:dmg' + A, dm); add('sk:dmg_e', h['dmg_e'] / (h['n_e'] + 2) / 10.0)
            add('sk:turns', h['turns_m'] / (h['n_m'] + 3)); add('sk:skip', sk); add('sk:skip' + A, sk)
            add('sk:smith', (h['n_smith'] - 0.65 * h['n_rest']) / (h['n_rest'] + 2.0)); add('sk:rm', h['n_rm'] / 3.0)
            add('sk:el', (s.get('elites') or 0) / 5.0); add('sk:el_act' + A, (s.get('elites_act') or 0) / 3.0)
    if opt.get('version'):
        add('v:' + build_group(s.get('build') or 'v0.111.0'), 1.0); add('v:' + build_group(s.get('build') or 'v0.111.0') + A, 1.0)

    # ---- 牌组 ----
    cnt = {}; upc = {}; size = 0; nup = 0
    for c, up in s.get('deck') or []:
        c = _norm(c, 'CARD.'); cnt[c] = cnt.get(c, 0) + 1; size += 1
        if up: upc[c] = upc.get(c, 0) + 1; nup += 1
    tg = {}; ty = {}; dmg = blk = drw = en = cost = 0.0; n_play = 0
    for c, n in cnt.items():
        k = kb.get(c)
        if not k: continue
        t, tags, d, b, dr, e, co = k
        ty[t] = ty.get(t, 0) + n
        for x in tags: tg[x] = tg.get(x, 0) + n
        if t in ('Attack', 'Skill', 'Power'):
            dmg += d * n; blk += b * n; drw += dr * n; en += e * n; cost += max(co, 0) * n; n_play += n
    add('size', size / 30.0); add('size' + A, size / 30.0); add('size2', (size / 30.0) ** 2)
    add('nup', nup / 10.0); add('nup' + A, nup / 10.0); add('upfrac', nup / max(size, 1))
    for t in TYPES:
        if ty.get(t): add('ty:' + t, ty[t] / 10.0); add('ty1:' + t, 1.0)
    for t in TAGS:
        n = tg.get(t, 0)
        if n:
            add('t:' + t, n / 5.0); add('t:' + t + A, n / 5.0); add('t1:' + t, 1.0); add('t2:' + t, 1.0 if n >= 2 else 0.0)
            add('t/' + t, n / max(size, 1))
    if n_play:
        add('avg_dmg', dmg / n_play / 10.0); add('avg_blk', blk / n_play / 10.0); add('avg_cost', cost / n_play)
        add('sum_draw', drw / 10.0); add('sum_en', en / 5.0)
    for c, n in cnt.items():
        v = min(n, 8) / 2.0
        add('c:' + c, v)
        if opt.get('card_act'): add('c:' + c + A, v)
        if n >= 2: add('c2:' + c, 1.0)
    for c, n in upc.items():
        add('u:' + c, min(n, 8) / 2.0)

    # ---- 遗物 / 药水 ----
    rel = [_norm(r, 'RELIC.') for r in s.get('relics') or [] if r]
    add('nrel', len(rel) / 10.0)
    for r in rel:
        add('r:' + r, 1.0)
        if opt.get('relic_act'): add('r:' + r + A, 1.0)
    for p in pots: add('p:' + p, 1.0)
    return f


def _load():
    global _M, PATH
    want = OVERRIDE
    if want is None:
        try:                                                # 模型文件可以用 --set run_value_file=data/run_value_style.json 换（A/B 测试用）
            from params import P
            want = os.path.join(HERE, P.get('run_value_file', 'data/run_value.json'))
        except Exception:
            want = PATH
    if want != PATH: PATH, _M = want, None
    if _M is None and os.path.exists(PATH):
        d = json.load(open(PATH))
        idx = {k: i for i, k in enumerate(d['vocab'])}
        opt = dict(d.get('opt') or {}); opt['style_ref'] = d.get('style_ref') or {}
        nh = d.get('next_head') or {}
        _M = {'idx': idx, 'w': d['w'], 'b': d['b'], 'W1': d.get('W1'), 'b1': d.get('b1'), 'w2': d.get('w2'),
              'opt': opt, 'meta': d.get('meta') or {}, 'nh': dict(zip(nh.get('names') or [], nh.get('w') or []))}
    return _M


def available():
    return _load() is not None


def logit(s):
    m = _load(); z = m['b']; W1 = m['W1']
    h = list(m['b1']) if W1 else None
    for k, x in features(s, m['opt']).items():
        i = m['idx'].get(k)
        if i is None: continue
        z += m['w'][i] * x
        if W1:
            row = W1[i]
            for j in range(len(h)): h[j] += row[j] * x
    if W1:
        z += sum(v * hj for v, hj in zip(m['w2'], h) if hj > 0)
    return z


def prob_of(s):
    z = max(-30.0, min(30.0, logit(s)))
    return 1.0 / (1.0 + math.exp(-z))


# ---------------- 下一个点：Q(家底, 下一个点的类型) ----------------
def next_type(t):
    t = str(t or '').lower().replace('roomtype.', '').replace(' ', '')
    return _NEXT_ALIAS.get(t)


def next_feats(s, z, T):
    """「下一个点是 T」的修正项特征（线性，加在价值网络的 logit z 上）：血量 / 低血 / 牌组强度（z 本身）/ 进度 / 金币 / 药水 × 点的类型"""
    act = min(max(int(s.get('act') or 1), 1), 3); prog = min(max(int(s.get('done') or 0), 0), 18) / 17.0
    mhp = max(float(s.get('max_hp') or 80), 1.0); hp = min(max(float(s.get('hp') or 0), 0.0), mhp)
    if mhp > 150: hp, mhp = hp / mhp * 80.0, 80.0
    frac = hp / mhp; gold = min(max(float(s.get('gold') or 0), 0.0), 900.0) / 300.0
    pots = len([p for p in s.get('potions') or [] if p]) / 3.0
    return {T: 1.0, f'{T}|A{act}': 1.0, f'{T}*z': z, f'{T}*z|A{act}': z, f'{T}*frac': frac, f'{T}*frac|A{act}': frac, f'{T}*hp': hp / 80.0,
            f'{T}*lo30': 1.0 if frac < 0.3 else 0.0, f'{T}*lo50': 1.0 if frac < 0.5 else 0.0, f'{T}*prog': prog,
            f'{T}*gold': gold, f'{T}*pots': pots, f'{T}*frac*prog': frac * prog}


def q_of(s, T):
    """家底 s、下一个点类型 T → 通关概率（社区玩家走进 T 之前的口径）。T 认不出来就退回 prob_of"""
    m = _load(); T = next_type(T); z = logit(s)
    if T is None or not m['nh']: return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
    z2 = z + sum(m['nh'].get(k, 0.0) * v for k, v in next_feats(s, z, T).items())
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z2))))


def best_next(s, next_types):
    """下一步能去的几种点里最好的那个 → (概率, 类型)；next_types 为空就用 prob_of"""
    ts = [t for t in (next_types or []) if next_type(t)]
    if not ts: return prob_of(s), None
    return max((q_of(s, t), next_type(t)) for t in ts)


def route_values(st, next_types):
    """路线：下一步走哪种点 → {类型: 通关概率}（同一家底，只看点的类型；具体战斗掉血请用战斗模型另算）"""
    s = state_of(st); return {next_type(t): q_of(s, t) for t in next_types if next_type(t)}


# ---------------- 引擎局面 → 家底 ----------------
def state_of(st):
    """引擎局面 → 家底。st['context']['floor'] 是本幕第几层（先古之民 = 1）；在这一层做完决定后的家底 = 本幕已打完 floor 层。
    打法历史（水平代理）不从程序里取，统一用人群平均（见 features 里的 style）。"""
    if isinstance(st, dict) and 'deck' in st and 'player' not in st: return st          # 已经是家底
    pl = st.get('player') or {}; ctx = st.get('context') or {}
    deck = []
    for c in pl.get('deck') or []:
        cid = str(c.get('id') or '')
        deck.append((_norm(cid, 'CARD.'), bool(c.get('upgraded')) or cid.endswith('+') or (c.get('upgrade_level') or 0) > 0))
    act = int(ctx.get('act') or 1)
    return {'act': act, 'done': int(ctx.get('floor') or 0), 'hp': pl.get('hp', 0), 'max_hp': pl.get('max_hp', 80),
            'gold': pl.get('gold', 0), 'deck': deck, 'relics': [_norm(r.get('id'), 'RELIC.') for r in pl.get('relics') or [] if r],
            'potions': [_norm(p.get('id'), 'POTION.') for p in pl.get('potions') or [] if p and p.get('id')],
            'chapter': ctx.get('act_name') if act == 1 else None, 'build': 'v0.111.0'}


def win_prob(st):
    """这局最后通关的概率（社区玩家接着打的口径）"""
    return prob_of(state_of(st))


# ---------------- 边际价值：同一局面下「做 / 不做」的通关概率差 ----------------
def with_card(s, card_id, upgraded=False):
    return dict(s, deck=list(s['deck']) + [(_norm(card_id, 'CARD.'), bool(upgraded))])


def without_card(s, card_id, upgraded=None):
    d = list(s['deck']); c = _norm(card_id, 'CARD.')
    order = [False, True] if upgraded is None else [bool(upgraded), not upgraded]     # 删牌默认删没升级的那张
    for want in order:
        for i, (x, up) in enumerate(d):
            if x == c and up == want: d.pop(i); return dict(s, deck=d)
    return dict(s, deck=d)


def upgraded(s, card_id):
    d = list(s['deck']); c = _norm(card_id, 'CARD.')
    for i, (x, up) in enumerate(d):
        if x == c and not up: d[i] = (x, True); break
    return dict(s, deck=d)


def with_relic(s, relic_id):
    return dict(s, relics=list(s['relics']) + [_norm(relic_id, 'RELIC.')])


def with_potion(s, potion_id):
    return dict(s, potions=list(s.get('potions') or []) + [_norm(potion_id, 'POTION.')])


def healed(s, amount):
    return dict(s, hp=min(float(s['max_hp']), float(s['hp']) + amount))


def delta_card(st, card_id, upgraded_=False):
    s = state_of(st); return prob_of(with_card(s, card_id, upgraded_)) - prob_of(s)


def delta_remove(st, card_id):
    s = state_of(st); return prob_of(without_card(s, card_id)) - prob_of(s)


def delta_upgrade(st, card_id):
    s = state_of(st); return prob_of(upgraded(s, card_id)) - prob_of(s)


def delta_relic(st, relic_id):
    s = state_of(st); return prob_of(with_relic(s, relic_id)) - prob_of(s)


def delta_potion(st, potion_id):
    s = state_of(st); return prob_of(with_potion(s, potion_id)) - prob_of(s)


def delta_gold(st, amount):
    s = state_of(st); return prob_of(dict(s, gold=max(0, s['gold'] + amount))) - prob_of(s)


def delta_hp(st, amount):
    s = state_of(st); return prob_of(dict(s, hp=max(1, min(s['max_hp'], s['hp'] + amount)))) - prob_of(s)


def best_upgrade(st):
    """升级哪张牌通关概率涨得最多 → (概率差, 牌 id)；没有能升的返回 (None, None)"""
    s = state_of(st); p0 = prob_of(s); best = (None, None)
    for c in sorted({x for x, up in s['deck'] if not up}):
        if c in ('ASCENDERS_BANE',) or (kb_cards().get(c) or ('',))[0] in ('Curse', 'Status'): continue
        d = prob_of(upgraded(s, c)) - p0
        if best[0] is None or d > best[0]: best = (d, c)
    return best


def best_remove(st):
    s = state_of(st); p0 = prob_of(s); best = (None, None)
    for c in sorted({x for x, _ in s['deck']}):
        d = prob_of(without_card(s, c)) - p0
        if best[0] is None or d > best[0]: best = (d, c)
    return best


def rest_values(st, heal_frac=0.30, next_types=None):
    """篝火：回血（30% 上限，有皇家枕头 +15）vs 升级最好的那张。
    next_types = 篝火之后能去的点的类型（程序看得到地图，比如 ['boss'] 或 ['monster', 'elite']）：给了就按「之后走最好的那个点」比，
    低血时在 Boss / 战斗前回血的价值才算得出来；不给就只用家底（低血时会低估回血，见模型说明）。
    → {'now': 现在, 'HEAL': 回血后, 'SMITH': (升级后, 牌 id), 'pick': 'HEAL' / 'SMITH'}"""
    s = state_of(st)
    amt = heal_frac * float(s['max_hp']) + (15 if 'REGAL_PILLOW' in s['relics'] else 0)
    heal = best_next(healed(s, amt), next_types)[0]
    best = (None, None)
    for c in sorted({x for x, up in s['deck'] if not up}):
        if c in ('ASCENDERS_BANE',) or (kb_cards().get(c) or ('',))[0] in ('Curse', 'Status'): continue
        v = best_next(upgraded(s, c), next_types)[0]
        if best[0] is None or v > best[0]: best = (v, c)
    return {'now': best_next(s, next_types)[0], 'HEAL': heal, 'SMITH': best,
            'pick': 'SMITH' if best[0] is not None and best[0] > heal else 'HEAL'}


def card_choice_values(st, offered, skip=True):
    """战后选牌：[(牌 id, 升级?)] → {牌 id 或 'SKIP': 拿了之后的通关概率}"""
    s = state_of(st); out = {'SKIP': prob_of(s)} if skip else {}
    for o in offered:
        cid, up = (o if isinstance(o, (tuple, list)) else (o, False))
        out[_norm(cid, 'CARD.') + ('+' if up else '')] = prob_of(with_card(s, cid, up))
    return out
