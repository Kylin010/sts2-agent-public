"""整局决策的强化学习层。

原有的打分（路线期望值、选牌模型、篝火规则）当作底分，上面加一层学出来的偏好分：
    总分 = 底分 / 尺度 + Σ 偏好权重[特征]
  - 探索（P['learn_explore']=true，训练时）：按 softmax(总分 / 温度) 随机选——分高的常选，分低的偶尔也试，打出各种不同的局
  - 正式打（探索关）：选总分最高的
特征按「选项类型 + 第几幕 + 当时血量档」记，不按种子记——学到的是「第一幕血多时走精英」这类习惯，换了种子也能用。
每个决定记进 mem['decisions']；一局结束后 tools/train_rl.py 按这局的奖励（打到第几层、过了几幕、赢没赢）
用 REINFORCE 更新权重：比同种子平均好的局里做过的选择加分，差的扣分。权重存在 data/learned_prefs.json。
"""
import json, math, os, random
from params import P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.environ.get('STS2_PREFS', f'{HERE}/data/learned_prefs.json')
_W = {'w': None}
SCALE = {'route': 100.0, 'pick': 1.0, 'rest': 1.0, 'event': 0.05, 'neow': 0.05, 'upg': 1.0}       # 各模块底分的单位不同，先换算到「差 1 分 ≈ 明显不同」


def weights():
    if _W['w'] is None:
        _W['w'] = json.load(open(PATH)).get('w', {}) if os.path.exists(PATH) else {}
    return _W['w']


def hp_bucket(st):
    pl = st.get('player') or {}
    f = pl.get('hp', 1) / max(pl.get('max_hp', 1), 1)
    return 'h0' if f < 0.3 else 'h1' if f < 0.5 else 'h2' if f < 0.7 else 'h3'


def feats(kind, name, st):
    """一个选项的特征：类型、类型 × 幕、类型 × 幕 × 血量档"""
    act = f"a{min(max(int((st.get('context') or {}).get('act') or 1), 1), 3)}"
    b = f'{kind}:{name}'
    return [b, f'{b}:{act}', f'{b}:{act}:{hp_bucket(st)}']


def pick(kind, options, st, mem):
    """options: [(选项, 底分, 特征列表)]；返回选中的选项"""
    if not options: return None
    if len(options) == 1: return options[0][0]
    if not P.get('learn_on') and not P.get('learn_explore'):          # learn_on=false 时和加这一层之前完全一样（对照实验用）
        return max(options, key=lambda o: o[1])[0]
    w = {} if kind in (P.get('learn_skip_kinds') or []) else weights(); sc = SCALE.get(kind, 1.0)   # 这类决定不用学到的偏好（对照 / 发现学偏了时用）
    tot = [o[1] / sc + sum(w.get(f, 0.0) for f in o[2]) for o in options]
    if P.get('learn_explore'):
        tau = P.get(f'learn_tau_{kind}', P.get('learn_tau', 1.0))
        m = max(tot); ex = [math.exp((t - m) / tau) for t in tot]; z = sum(ex); pr = [e / z for e in ex]
        r = random.random(); acc = 0.0; k = len(pr) - 1
        for i, p in enumerate(pr):
            acc += p
            if r <= acc: k = i; break
        if mem is not None and 'decisions' in mem:
            mem['decisions'].append({'k': kind, 'f': [o[2] for o in options], 'p': [round(p, 4) for p in pr], 'c': k, 'tau': tau})
        return options[k][0]
    k = max(range(len(tot)), key=lambda i: tot[i])
    return options[k][0]


def update(runs, lr, baseline):
    """REINFORCE：runs = [(奖励, 决定列表, 种子)]；baseline(种子) = 这个种子的平均奖励。返回改动最大的几个特征"""
    w = weights(); g = {}
    for R, decs, seed in runs:
        A = R - baseline(seed)
        for d in decs:
            c = d['c']; tau = d.get('tau', 1.0)
            exp_f = {}
            for p, fs in zip(d['p'], d['f']):
                for f in fs: exp_f[f] = exp_f.get(f, 0.0) + p
            for f in d['f'][c]: g[f] = g.get(f, 0.0) + A / tau
            for f, v in exp_f.items(): g[f] = g.get(f, 0.0) - A * v / tau
    n = max(1, len(runs))
    cap = P.get('learn_w_cap', 3.0)
    dk = P.get('learn_decay', 0.0)            # 10/2：每轮把所有权重往 0 拉一点，过时的偏好（战斗变强前学的「别打精英」「别升级」）会慢慢淡掉
    if dk:
        for f in list(w): w[f] *= (1 - dk)
    for f, v in g.items():
        w[f] = max(-cap, min(cap, w.get(f, 0.0) + lr * v / n))
    return sorted(g.items(), key=lambda t: -abs(t[1]))[:12]


def save(extra=None):
    json.dump({'_说明': '整局决策的学习偏好（policy/learn.py，tools/train_rl.py 训练）', **(extra or {}), 'w': weights()},
              open(PATH, 'w'), ensure_ascii=False, indent=0)
