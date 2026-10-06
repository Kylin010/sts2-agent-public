"""事件怎么选。

1. 涅奥：按玩家数据里的胜率选（data/neow_scores.json）。
2. 个别事件有专门的规则（HANDLERS）。
3. 其他事件：按社区数据里「选这个选项的人最终胜率」打分（data/event_stats.json，tools/event_stats.py 生成；
   样本少的向 30% 收缩）。胜率混着牌组强弱的影响，只当基础分；没有数据的选项按文字粗略打分。
4. 两道保险：会把血掉到安全线以下的选项不选；同一个事件反复选了很多次就离开（防止「湿滑的桥」那种一直选到死）。
"""
import json, os
from params import P
from policy.knowledge import NEOW_SCORES

# 后台引擎里会崩的选项（10/3 事件体检，B-010）：选项任务在调用界面单例（音效 / 震屏 / 肖像 / 战斗画面）时抛空引用，
# 后面的步骤走不完。补丁 13 起引擎会直接结束事件（以前会回传旧选项、能再选一次白拿），但效果不完整：
# 茂密植被「休息」只回血不打仗（占便宜）、融合者 / 丛林迷宫结伴 / 拳击抢夺 / 审判接受 / 水晶球什么都没发生（吃亏）。有别的选项就不选。
BROKEN_OPTIONS = {
    'DENSE_VEGETATION.pages.INITIAL.options.REST', 'AMALGAMATOR.pages.INITIAL.options.COMBINE_STRIKES',
    'AMALGAMATOR.pages.INITIAL.options.COMBINE_DEFENDS', 'JUNGLE_MAZE_ADVENTURE.pages.INITIAL.options.JOIN_FORCES',
    'PUNCH_OFF.pages.INITIAL.options.NAB', 'TRIAL.pages.INITIAL.options.ACCEPT',
    'CRYSTAL_SPHERE.pages.INITIAL.options.UNCOVER_FUTURE', 'CRYSTAL_SPHERE.pages.INITIAL.options.PAYMENT_PLAN'}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    STATS = json.load(open(f'{HERE}/data/event_stats.json'))
except Exception:
    STATS = {}
OPT = {k: v for ev in STATS.values() for k, v in ev['options'].items()}

BAD_WORDS = ('curse', 'Curse', 'wound', 'Wound', 'Lose', 'lose', 'Max HP', 'damage')
GOOD_WORDS = ('Obtain', 'Gain', 'Upgrade', 'Remove', 'remove', 'relic', 'Relic', 'Heal', 'gold', 'Gold')
BAD_CARDS = ('Strike', 'Defend', 'Wound', 'Dazed', 'Burn', 'Slimed', 'Doubt', 'Regret', 'Injury', 'Decay', 'Shame', 'Writhe',
             'Normality', 'Pain', 'Clumsy', 'Poor Sleep', 'Guilty', 'Folly', 'Greed', 'Debt', 'Bad Luck', "Ascender's Bane")


def opt_key(o):
    """选项的身份（给学习层当特征）：text_key 去掉前缀，同一个事件的同一个选项在不同种子里一样"""
    k = str(o.get('text_key') or o.get('title') or o.get('index')).split('.')
    return f"{k[0]}.{k[-1]}" if len(k) > 1 else k[0]               # 事件名.选项名，如 SPIRALING_WHIRLPOOL.OBSERVE


def choose_neow(st, mem=None):
    from policy import learn
    opts = [(o['index'], NEOW_SCORES.get(str(o.get('text_key', '')).split('.')[-1], {}).get('score', 0.2),
             learn.feats('neow', opt_key(o), st)) for o in st.get('options') or [] if not o.get('is_locked')]
    return learn.pick('neow', opts, st, mem) if opts else 0


def hp_cost(o):
    """选项要扣多少血（读 vars 里 HpLoss / Damage 这类数字）"""
    tot = 0
    for k, v in (o.get('vars') or {}).items():
        kl = k.lower()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and ('hploss' in kl or kl in ('hpcost', 'selfdamage') or kl.endswith('damage')):
            tot = max(tot, v)
    return tot


def gold_cost(o):
    """选项要花多少金币（vars 里 ...Cost / Gold 这类数字）"""
    tot = 0
    for k, v in (o.get('vars') or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k.lower().endswith('cost') and 'hp' not in k.lower():
            tot = max(tot, v)
    return tot


def stat_score(o):
    s = OPT.get(str(o.get('text_key', '')))
    if not s: return None
    k = P['event_prior_n']
    return (s['win'] * s['n'] + P['event_prior_win'] * k) / (s['n'] + k)


def text_score(o, hpf):
    txt = f"{o.get('title', '')} {o.get('description', '')}"
    s = sum(1 for w in GOOD_WORDS if w in txt) - sum(1.5 if hpf < 0.6 else 0.7 for w in BAD_WORDS if w in txt)
    if any(w in txt for w in ('Leave', 'Proceed', 'Continue', 'Skip')): s = -0.5
    return P['event_prior_win'] + 0.03 * s


def slippery_bridge(st, opts, hp, mx):
    """湿滑的桥：「挺过去」删掉显示的那张牌；「抓紧」掉血（一次比一次多）换一张。显示的是废牌就直接挺过去"""
    over = next((o for o in opts if 'OVERCOME' in str(o.get('text_key'))), None)
    hold = next((o for o in opts if 'HOLD_ON' in str(o.get('text_key'))), None)
    if not over or not hold: return None
    card = str((over.get('vars') or {}).get('RandomCard', ''))
    if any(b.lower() == card.lower() for b in BAD_CARDS): return over['index']
    if hp - hp_cost(hold) > max(P['event_safe_hp_frac'] * mx, P['event_safe_hp']) and hp_cost(hold) <= 12: return hold['index']
    return over['index']


HANDLERS = {'Slippery Bridge': slippery_bridge}


def trap_rules(opts, hpf):
    """事件陷阱的硬规则（研究 14 号，都是源码核实过的，不靠统计）。返回选项下标；不适用返回 None"""
    key = lambda o: str(o.get('text_key') or '')
    by = lambda word: next((o['index'] for o in opts if word in key(o)), None)
    keys = ' '.join(key(o) for o in opts)
    if 'CRYSTAL_SPHERE.' in keys and P.get('crystal_always_plan', True):
        # 水晶球（research/水晶球事件.md 第 4 节）：遗物 4×4 至少要 4 次大占卜，「揭幕未来」只有 3 次、付 51~99 金，数学上拿不到遗物；
        # 「分期付款」6 次 + 1 张债务，新点法遗物 98%。学习层权重是事件坏掉那段时间学的（第三幕会选揭幕）→ 硬规则永远选分期
        i = by('PAYMENT_PLAN')
        if i is not None: return i
    if 'TRIAL.' in keys:
        # 审判：第一页「拒绝」后第二页的「坚持到底」= 放弃本局；三种案件都是判「无罪」更好
        for w in ('INNOCENT', '.ACCEPT'):
            i = by(w)
            if i is not None: return i
        safe = [o['index'] for o in opts if 'DOUBLE_DOWN' not in key(o) and 'REJECT' not in key(o)]
        return safe[0] if safe else None
    if 'TABLET_OF_TRUTH.' in keys:
        # 真理石板：越贪越差，第 5 次解读把最大生命扣到 1 → 最多解读 1 次；血低于一半直接砸碎回 20 血
        if by('GIVE_UP') is not None: return by('GIVE_UP')
        if hpf < 0.5 and by('SMASH') is not None: return by('SMASH')
        return by('DECIPHER_1')
    if 'THE_LANTERN_KEY.pages.INITIAL' in keys:
        # 灯火钥匙：留下钥匙 = 打神秘骑士（108 血，开场 +6 力量 +6 覆甲，撞击 23、连枷 16×2）。研究 14 号：血 ≥60% 才留，否则交还拿 100 金
        # （10/3：前 30 个种子里 3 个死在它手里，进场血 43 / 13 / 42）
        want = 'KEEP_THE_KEY' if hpf >= P.get('lantern_fight_hp', 0.6) else 'RETURN_THE_KEY'
        i = by(want)
        if i is not None: return i
    if 'WELCOME_TO_WONGOS.' in keys:
        # 旺购百货：「离开」会随机降级一张已升级的牌；默认 100 金的打折货物
        for w in ('BARGAIN_BIN', 'FEATURED_ITEM', 'MYSTERY_BOX'):
            i = by(w)
            if i is not None: return i
    return None


_AWR = {}
UPGRADE_RELICS = {'SAND_CASTLE': 1.0, 'YUMMY_COOKIE': 0.7, 'PAELS_TOOTH': 0.4}   # 拾起就升级 6 / 4 张；佩尔之牙是慢慢返还升级过的牌
# 10/3 假设实验：第二幕 Boss 撑过率 原样 48% → +3 升级 63%、+5 遗物 65%、+产能牌 43%


def choose_ancient(st, opts):
    """古神选遗物（10/3）：按社区数据「选了这件遗物之后的胜率」（data/ancient_wr.json，样本少向平均收缩）挑最高的。
    第二幕开头我们最常选佩尔之牙（人类只 11% 选、选了胜率 33%），人类多选烘焙手套（62%、50%）、佩尔之血（59%、44%）。
    选项认不出遗物（不是古神）返回 None"""
    if not P.get('ancient_wr_on', False): return None
    if not _AWR:
        import json, os
        try: _AWR.update(json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ancient_wr.json'))))
        except Exception: return None
    act = str((st.get('context') or {}).get('act', 1)); tab = _AWR.get(act) or {}
    from policy import kb
    sc = []
    for o in opts:
        rid = str(o.get('text_key', '')).split('.')[-1]
        if rid not in tab: rid = str(kb.id_by_name('relics', o.get('title')) or '').replace('RELIC.', '')
        if rid in tab: sc.append((tab[rid]['score'] + P.get('ancient_upgrade_bonus', 0.0) * UPGRADE_RELICS.get(rid, 0), o['index']))
    if len(sc) < 2 or len(sc) < len(opts) - 1: return None
    return max(sc)[1]


def choose(st, mem):
    if st.get('event_name') == 'Neow':
        a = choose_ancient(st, [o for o in st.get('options') or [] if not o.get('is_locked')])
        return a if a is not None else choose_neow(st, mem)
    pl = st.get('player') or {}; hp, mx = pl.get('hp', 1), max(pl.get('max_hp', 1), 1); hpf = hp / mx
    opts = [o for o in st.get('options') or [] if not o.get('is_locked')]
    if not opts: return 0
    gold = pl.get('gold', 0)
    opts = [o for o in opts if gold_cost(o) <= gold] or opts           # 钱不够的选项选了也没反应
    # Enable only with the compatible SDK; default stays False during WIP coverage.
    # 10/4：补丁 19（B-012）修好了 8 个里的 7 个，只剩审判「接受」——打开 event_ui_fixed 后黑名单只留它
    # 10/4：p19 远端水晶球两个选项都报 MissingMethodException（Vector2I.One）——部署时漏同步 Godot 替身库 GodotSharp.dll；p19b 补上后两个选项都能走完，黑名单只留审判「接受」
    broken = {'TRIAL.pages.INITIAL.options.ACCEPT'} if P.get('event_ui_fixed', False) else BROKEN_OPTIONS
    if True:
        ok = [o for o in opts if o.get('text_key') not in broken]
        if not ok:
            # The ordinary event UI has no general escape button. Let the caller
            # report a technical failure when this engine supports no offered choice.
            mem['event_unsupported_broken'] = mem.get('event_unsupported_broken', 0) + 1
            return None
        opts = ok
    name = st.get('event_name') or ''
    cnt = mem.setdefault('event_count', {}); key = f"{name}@{(st.get('context') or {}).get('floor')}"
    cnt[key] = cnt.get(key, 0) + 1
    if cnt[key] > P['event_max_repeats']:                    # 同一个事件选了太多次：先找离开的选项，再轮流换着选
        leave = [o for o in opts if any(w in str(o.get('title', '')) for w in ('Leave', 'Proceed', 'Continue', 'Stop', 'Overcome'))]
        if leave: return leave[0]['index']
        if cnt[key] > P['event_max_repeats'] + 6: return None          # 无法继续：技术故障，不强制离开房间
        safe_opts = [o for o in opts if not hp_cost(o)] or opts
        return safe_opts[cnt[key] % len(safe_opts)]['index']
    from policy import offclass                      # 色彩哲学家：按研究文档选颜色（docs/色彩哲学家.md）
    t = offclass.choose_color(st, opts)
    if t is not None: return t
    t = choose_ancient(st, opts)                      # 其他古神（佩尔、欧洛巴斯……）选遗物
    if t is not None: return t
    t = trap_rules(opts, hpf)
    if t is not None: return t
    if P.get('punchoff_nab', False):
        # 拳击比赛是事件时别打。打的话两台拳击构装体（各约 55 血、1 层人工制品，快拳带脆弱、重拳 16），人类打的平均掉 28 血；
        # 「顺走」= 一张受伤诅咒换一个随机遗物，不打仗
        nab = next((o for o in opts if o.get('text_key') == 'PUNCH_OFF.pages.INITIAL.options.NAB'), None)
        take = next((o for o in opts if o.get('text_key') == 'PUNCH_OFF.pages.INITIAL.options.I_CAN_TAKE_THEM'), None)
        if nab and take and P.get('punchoff_fight_when_strong', True):
            # 打赢给 1 遗物 + 1 药 + 91~98 金币 + 战斗奖励、不吃诅咒（PunchOff.cs）；
            # 状态一般就顺走（受伤诅咒换 1 遗物）。「极好」= 打精英准备度、血量、遗物数都过高线
            from policy import deckeval
            pl = st.get('player') or {}
            hpf = (pl.get('hp') or 0) / max(pl.get('max_hp') or 1, 1)
            if (deckeval.elite_ready(st) >= P.get('punchoff_fight_ready', 0.9) and hpf >= P.get('punchoff_fight_hp', 0.85)
                    and len(pl.get('relics') or []) >= P.get('punchoff_fight_relics', 4)):
                return take['index']
        if nab: return nab['index']
    h = HANDLERS.get(name)
    if h:
        r = h(st, opts, hp, mx)
        if r is not None: return r
    safe = max(P['event_safe_hp_frac'] * mx, P['event_safe_hp'])
    from policy import learn
    cand = []
    for o in opts:
        s = stat_score(o)
        if s is None: s = text_score(o, hpf)
        c = hp_cost(o)
        if c and hp - c < safe: s -= 1                         # 掉完血低于安全线：基本不选
        elif c: s -= P['event_hp_cost_weight'] * c / mx
        cand.append((o['index'], s, learn.feats('event', opt_key(o), st)))
    bi = learn.pick('event', cand, st, mem)
    mem['event_text'] = next((f"{o.get('title', '')} {o.get('description', '')}" for o in opts if o['index'] == bi), '')
    return bi
