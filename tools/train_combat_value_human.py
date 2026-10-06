"""用人类对局训练战斗局面估值模型（policy/combatvalue.py 直接读，params.json 里 cv_file 切换）。


数据：tools/replay_situations.py 从社区回放还原的回合结束局面（results/human-turns.jsonl）。
特征、目标、网络和 tools/train_combat_value.py 完全一样：
  特征 = policy.combatvalue.features；目标 = 这次敌方回合之后到战斗结束还掉的血（future − 这次敌方回合的漏伤）+ 死了 30；
  一层 ReLU 隐藏层，numpy 手写 Adam + Huber 损失。
和旧脚本的区别：
  - 按对局（回放文件）划分训练 / 检验（8:2，固定种子）；训练局里再留 1/8 做验证集挑轮数——检验集只用来报成绩，不参与挑选
  - 对照：只猜平均、线性回归（岭）、现有 data/combat_value.json（我们自己的对局训练的）
  - 另外拿我们自己的对局（results/turns*-*.jsonl）检验：按旧脚本同样的随机种子复现它的检验场次，两个模型在同一批场次上比
读档 / 重开（存档退出或重开整场战斗）：--subset 选训练用哪些战斗——
  all（打完的每一遍都用）/ norestart（去掉重来过的战斗）/ clean（只用整局一次都没重来过的对局）。
  检验成绩同时报「全部检验对局」和「其中一次都没重来过的对局」（后者最接近不读档的真实结果）。
默认：4 个隐藏层 16 的网络（L2 0.01）取平均——在验证集上挑的（隐藏层 16/32/64 × L2 1e-4/1e-3/1e-2 × Huber/MSE，再加更强 L2 和集成）。
用法：python3 tools/train_combat_value_human.py [--subset all] [--hidden 16] [--ensemble 4] [--l2 0.01] [--out combat_value_human.json]
      [--ours '/opt/slay-the-spire-2/agent/results/turns*-*.jsonl']
"""
import argparse, collections, glob, json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from policy.combatvalue import features, unblocked_now

ap = argparse.ArgumentParser()
ap.add_argument('--data', default=f'{HERE}/results/human-turns.jsonl')
ap.add_argument('--ours', default='/opt/slay-the-spire-2/agent/results/turns*-*.jsonl', help='我们自己的对局（检验通用性）')
ap.add_argument('--old', default=f'{HERE}/data/combat_value.json', help='现有模型（对照）')
ap.add_argument('--subset', default='all', choices=['all', 'norestart', 'clean'])
ap.add_argument('--hidden', type=int, default=16); ap.add_argument('--epochs', type=int, default=80)
ap.add_argument('--lr', type=float, default=3e-3); ap.add_argument('--l2', type=float, default=1e-2); ap.add_argument('--death', type=float, default=30)
ap.add_argument('--seed', type=int, default=4); ap.add_argument('--out', default='combat_value_human.json')
ap.add_argument('--ensemble', type=int, default=4, help='训练几个不同随机种子的网络取平均（合并成一个隐藏层更宽的网络，格式不变）')
ap.add_argument('--loss', default='huber', choices=['huber', 'mse'], help='huber = 旧脚本的做法（误差超过 1 个标准差梯度封顶）；mse 估的是期望')
ap.add_argument('--no-write', action='store_true')
ap.add_argument('--train-frac', type=float, default=1.0, help='只用这么多比例的训练对局（学习曲线：判断数据量够不够）')
ap.add_argument('--drop', default='ehp,ehp_all', help='模型里不用的特征（逗号分隔）。默认去掉不封顶的敌人血量：瀑布巨兽无限血阶段运行时是 999999999，'
                '人类数据里没有这么大的数，ReLU 外推会算出几百万；敌人血量的信息由封顶的 turns_left / inc_x_turns / fut_x_turns 带')
a = ap.parse_args()
random.seed(a.seed); np.random.seed(a.seed)


def target(t, death):
    unb = min(unblocked_now(t['s']), t['s']['hp'])               # 这次敌方回合的漏伤由规划器精确算，模型只学之后的部分
    return max(0, t['future'] - unb) + (death if t['died'] else 0)


# ---------------------------------------------------------------- 人类数据
recs = [json.loads(l) for l in open(a.data)]
runs = sorted({r['replay'] for r in recs})
rng = random.Random(a.seed); order = runs[:]; rng.shuffle(order)
n_te = len(order) // 5; test_runs = set(order[:n_te]); rest = order[n_te:]
val_runs = set(rest[:len(rest) // 8]); train_runs = rest[len(rest) // 8:]
train_runs = set(train_runs[:max(1, int(len(train_runs) * a.train_frac))])
rows = []                                    # (特征, 目标, 对局, 战斗编号, 整局没重来过, 这场重来过, 幕)
for ci, r in enumerate(recs):
    for t in r['turns']:
        rows.append((features(t['s']), target(t, a.death), r['replay'], ci, r['file_restart_frac'] == 0, r['restarted'], t['s']['act']))
print(f'人类局面 {len(rows)} 个，{len(recs)} 场战斗，{len(runs)} 局；对局划分：训练 {len(train_runs)} / 验证 {len(val_runs)} / 检验 {len(test_runs)}')

DROP = {k for k in a.drop.split(',') if k}
names = sorted({k for f, *_ in rows for k in f} - DROP)
idx = {k: i for i, k in enumerate(names)}


def matrix(fs, names_idx):
    X = np.zeros((len(fs), len(names_idx)), np.float32)
    for n, f in enumerate(fs):
        for k, v in f.items():
            j = names_idx.get(k)
            if j is not None: X[n, j] = v
    return X


X = matrix([r[0] for r in rows], idx); Y = np.array([r[1] for r in rows], np.float32)
RUN = np.array([r[2] for r in rows]); CLEAN = np.array([r[4] for r in rows]); RESTARTED = np.array([r[5] for r in rows]); ACT = np.array([r[6] for r in rows])
te = np.isin(RUN, list(test_runs)); va = np.isin(RUN, list(val_runs)); tr = np.isin(RUN, list(train_runs))
if a.subset == 'norestart': tr &= ~RESTARTED; va &= ~RESTARTED
elif a.subset == 'clean': tr &= CLEAN; va &= CLEAN
te_clean = te & CLEAN
print(f'训练子集 {a.subset}：训练 {tr.sum()} / 验证 {va.sum()} / 检验 {te.sum()}（其中整局没重来过的对局 {te_clean.sum()}）；'
      f'目标均值 {Y[tr].mean():.1f}，标准差 {Y[tr].std():.1f}')

rmse = lambda p, y: float(np.sqrt(np.mean((p - y) ** 2)))
mae = lambda p, y: float(np.mean(np.abs(p - y)))


def report(name, pred, mask_sets, y=Y):
    parts = []
    for label, m in mask_sets:
        p, yy = pred[m], y[m]
        r = float(np.corrcoef(p, yy)[0, 1]) if p.std() > 1e-9 else 0.0
        parts.append(f'{label} RMSE {rmse(p, yy):5.2f} MAE {mae(p, yy):5.2f} 偏差 {float((p - yy).mean()):+5.2f} 相关 {r:.3f}')
    print(f'  {name:<22}' + '｜'.join(parts))
    return {label: {'rmse': rmse(pred[m], y[m]), 'mae': mae(pred[m], y[m]), 'bias': float((pred[m] - y[m]).mean()),
                    'r': float(np.corrcoef(pred[m], y[m])[0, 1]) if pred[m].std() > 1e-9 else 0.0, 'n': int(m.sum())} for label, m in mask_sets}


# ---------------------------------------------------------------- 模型：一层 ReLU（和 train_combat_value.py 一样）
def fit_mlp(X, Y, tr, va, hidden, epochs, lr, l2, seed, loss='huber'):
    rs = np.random.RandomState(seed)
    mu = X[tr].mean(0); sd = X[tr].std(0); sd[sd < 1e-6] = 1.0
    Xs = (X - mu) / sd
    scale = float(np.std(Y[tr]) or 1); F = X.shape[1]
    W1 = rs.randn(hidden, F) * np.sqrt(2 / F); b1 = np.zeros(hidden); W2 = rs.randn(hidden) * 0.1; b2 = np.array(Y[tr].mean() / scale)
    params = [W1, b1, W2, b2]; mom = [np.zeros_like(p) for p in params]; vel = [np.zeros_like(p) for p in params]; step = 0
    Yt = Y / scale; best = (9e9, None, -1); idx_tr = np.where(tr)[0]
    pred = lambda W1, b1, W2, b2, Z: np.maximum((np.maximum(Z @ W1.T + b1, 0) @ W2 + b2) * scale, 0)
    for ep in range(epochs):
        rs.shuffle(idx_tr)
        for b in range(0, len(idx_tr), 256):
            bi = idx_tr[b:b + 256]; x = Xs[bi]; y = Yt[bi]
            z = x @ W1.T + b1; h = np.maximum(z, 0); p = h @ W2 + b2
            g = (np.clip(p - y, -1.0, 1.0) if loss == 'huber' else (p - y)) / len(bi)
            gW2 = h.T @ g + l2 * W2; gb2 = g.sum(); gh = np.outer(g, W2) * (z > 0)
            gW1 = gh.T @ x + l2 * W1; gb1 = gh.sum(0); step += 1
            for i, (pp, gg) in enumerate(zip(params, [gW1, gb1, gW2, gb2])):
                mom[i] = 0.9 * mom[i] + 0.1 * gg; vel[i] = 0.999 * vel[i] + 0.001 * gg * gg
                pp -= lr * (mom[i] / (1 - 0.9 ** step)) / (np.sqrt(vel[i] / (1 - 0.999 ** step)) + 1e-8)
        e = rmse(pred(W1, b1, W2, b2, Xs[va]), Y[va])
        if e < best[0]: best = (e, [p.copy() for p in params], ep + 1)
    e, (W1, b1, W2, b2), ep = best
    return {'mu': mu, 'sd': sd, 'W1': W1, 'b1': b1, 'W2': W2, 'b2': float(b2), 'scale': scale, 'val_rmse': e, 'epoch': ep}


def mlp_predict(m, X):
    Z = (X - m['mu']) / m['sd']
    return np.maximum((np.maximum(Z @ m['W1'].T + m['b1'], 0) @ m['W2'] + m['b2']) * m['scale'], 0)


def json_model_predict(M, fs):
    """按 policy/combatvalue.predict 的算法用 numpy 算（模型里没有的特征忽略；主怪全死 = 0）"""
    Xm = matrix(fs, M['idx'])
    mu = np.array(M.get('mu') or [0.0] * len(M['features'])); sd = np.array(M.get('sd') or [1.0] * len(M['features']))
    Z = (Xm - mu) / sd
    y = np.maximum(np.maximum(Z @ np.array(M['W1']).T + np.array(M['b1']), 0) @ np.array(M['W2']) + M['b2'], 0) * M['scale']
    won = np.array([f.get('won', 0) for f in fs]) > 0
    return np.where(won, 0.0, y)


def fit_linear(X, Y, tr):
    Xa = np.hstack([X, np.ones((len(X), 1), np.float32)])
    w = np.linalg.lstsq(Xa[tr].T @ Xa[tr] + 1.0 * np.eye(Xa.shape[1]), Xa[tr].T @ Y[tr], rcond=None)[0]
    return lambda Z: np.maximum(np.hstack([Z, np.ones((len(Z), 1), np.float32)]) @ w, 0)


# ---------------------------------------------------------------- 训练 + 人类检验集
print(f'\n训练（隐藏层 {a.hidden}，最多 {a.epochs} 轮，按验证集挑轮数）……', flush=True)
members = [fit_mlp(X, Y, tr, va, a.hidden, a.epochs, a.lr, a.l2, a.seed + k, a.loss) for k in range(a.ensemble)]
for k, m in enumerate(members): print(f'  网络 {k + 1}：验证集最好第 {m["epoch"]} 轮 RMSE {m["val_rmse"]:.2f}')
# 几个网络取平均 = 一个隐藏层拼起来、输出权重除以个数的网络（标准化和 scale 相同），policy/combatvalue.py 照常读
mlp = {'mu': members[0]['mu'], 'sd': members[0]['sd'], 'W1': np.vstack([m['W1'] for m in members]), 'b1': np.concatenate([m['b1'] for m in members]),
       'W2': np.concatenate([m['W2'] for m in members]) / len(members), 'b2': float(np.mean([m['b2'] for m in members])), 'scale': members[0]['scale'],
       'epoch': [m['epoch'] for m in members]}
mlp['val_rmse'] = rmse(mlp_predict(mlp, X[va]), Y[va])
print(f'合起来（隐藏层 {mlp["W1"].shape[0]}）：验证集 RMSE {mlp["val_rmse"]:.2f}')
lin = fit_linear(X, Y, tr)
OLD = json.load(open(a.old)) if os.path.exists(a.old) else None
masks = [('全部检验对局', te), ('没重来过的对局', te_clean)]
print('\n人类检验集（按对局划分，模型没见过这些对局）：')
res = {'human_test': {}}
res['human_test']['mean'] = report('只猜平均', np.full(len(Y), Y[tr].mean(), np.float32), masks)
res['human_test']['linear'] = report('线性回归', lin(X), masks)
if OLD:
    fs_all = [r[0] for r in rows]
    res['human_test']['old_ours'] = report('现有模型(自己对局)', json_model_predict(OLD, fs_all), masks)
res['human_test']['human_mlp'] = report('人类模型(新)', mlp_predict(mlp, X), masks)
print('  按幕（人类模型 / 现有模型，全部检验对局）：')
for act in (1, 2, 3):
    m = te & (ACT == act)
    if not m.any(): continue
    p1 = mlp_predict(mlp, X[m]); line = f'    第 {act} 幕 {m.sum()} 个：人类模型 RMSE {rmse(p1, Y[m]):.2f}'
    if OLD: line += f'，现有模型 {rmse(json_model_predict(OLD, [rows[i][0] for i in np.where(m)[0]]), Y[m]):.2f}'
    print(line + f'，只猜平均 {rmse(np.full(m.sum(), Y[tr].mean()), Y[m]):.2f}')

# ---------------------------------------------------------------- 灵敏度：规划器比较的是同一回合不同打法的结束局面，模型对这些差别的反应方向要对
import copy
def sens(pred_fn):
    out = {}
    tests = [('主怪有效血 −10', lambda s: [e.update(ehp=max(1, e['ehp'] - 10)) for e in s['enemies'] if not e['minion']][:1], -1),
             ('敌人全挂易伤', lambda s: [e.update(vuln=1) for e in s['enemies']], -1),
             ('敌人全挂虚弱', lambda s: [e.update(weak=1) for e in s['enemies']], -1),
             ('我方力量 +2', lambda s: s.update(str=s['str'] + 2), -1),
             ('我方血量 −10', lambda s: s.update(hp=max(1, s['hp'] - 10)), +1)]
    sample = [t['s'] for ci in sorted({r[3] for r in rows if r[2] in test_runs}) for t in recs[ci]['turns']][:3000]
    p0 = pred_fn([features(s) for s in sample])
    for name, fn, sign in tests:
        mod = []
        for s in sample:
            s2 = copy.deepcopy(s); fn(s2); mod.append(features(s2))
        d = pred_fn(mod) - p0
        out[name] = (float(d.mean()), float(np.mean(np.sign(d) == sign)), float(np.mean(np.abs(d) < 1e-6)))
    return out
print('\n灵敏度（人类检验集 3000 个局面，改一个地方看预测变化；方向对 = 掉血预测往该去的方向变）：')
print('  ' + ' ' * 22 + ''.join(f'{n:<16}' for n in ('主怪有效血−10', '敌人易伤', '敌人虚弱', '我方力量+2', '我方血量−10')))
sens_fns = [('线性回归', lambda fs: lin(matrix(fs, idx))), ('人类模型(新)', lambda fs: mlp_predict(mlp, matrix(fs, idx)))]
if OLD: sens_fns.insert(0, ('现有模型(自己对局)', lambda fs: json_model_predict(OLD, fs)))
res['sensitivity'] = {}
for name, fn in sens_fns:
    r_ = sens(fn); res['sensitivity'][name] = r_
    print(f'  {name:<22}' + ''.join(f'{v[0]:+5.2f} 对{v[1]:4.0%}     ' for v in r_.values()))

# ---------------------------------------------------------------- 我们自己的对局：复现旧脚本的检验场次
ours = []; fight = 0
files = sorted(glob.glob(a.ours))
for fn in files:
    for line in open(fn):
        r = json.loads(line)
        for g in [r.get('turns') or []] + [c.get('turns') or [] for c in r.get('combats') or []]:
            if not g: continue
            for t in g: ours.append((features(t['s']), target(t, a.death), fight))
            fight += 1
if ours:
    G = np.array([o[2] for o in ours]); Yo = np.array([o[1] for o in ours], np.float32)
    rs_old = np.random.RandomState(4); fights = np.unique(G); rs_old.shuffle(fights)      # 和 train_combat_value.py 一样：np.random.seed(4) 后第一次 shuffle
    old_test = np.isin(G, fights[:len(fights) // 5])
    fo = [o[0] for o in ours]
    Xo = matrix(fo, idx)
    print(f'\n我们自己的对局：{len(ours)} 个局面，{fight} 场战斗（{len(files)} 个文件）；旧模型训练时留出的检验场次 {old_test.sum()} 个局面'
          f'（目标均值 {Yo.mean():.1f}，人类 {Y.mean():.1f}——我们掉血多得多、死得多）')
    mo = [('旧模型的检验场次', old_test), ('全部', np.ones(len(Yo), bool))]
    res['ours'] = {}
    res['ours']['mean_human'] = report('只猜平均(人类均值)', np.full(len(Yo), Y[tr].mean(), np.float32), mo, Yo)
    if OLD: res['ours']['old_ours'] = report('现有模型(自己对局)', json_model_predict(OLD, fo), mo, Yo)
    res['ours']['linear_human'] = report('线性回归(人类)', lin(Xo), mo, Yo)
    res['ours']['human_mlp'] = report('人类模型(新)', mlp_predict(mlp, Xo), mo, Yo)
    # 只看排序：同一场战斗里局面之间谁更危险（规划器比较的是候选局面的相对好坏）
    def within_fight_concord(p, y, g, mask):
        ok = tot = 0
        by = collections.defaultdict(list)
        for i in np.where(mask)[0]: by[g[i]].append(i)
        for ids in by.values():
            for x_ in range(len(ids)):
                for z_ in range(x_ + 1, len(ids)):
                    i, j = ids[x_], ids[z_]
                    if abs(y[i] - y[j]) < 3: continue
                    tot += 1; ok += (p[i] - p[j]) * (y[i] - y[j]) > 0
        return ok / max(tot, 1), tot
    print('  同一场战斗里两个局面谁之后掉血更多（差 ≥3），模型排对的比例（旧模型的检验场次）：')
    for name, p in ([('现有模型(自己对局)', json_model_predict(OLD, fo))] if OLD else []) + [('人类模型(新)', mlp_predict(mlp, Xo)), ('线性回归(人类)', lin(Xo))]:
        c, n = within_fight_concord(p, Yo, G, old_test)
        print(f'    {name:<20}{c:.1%}（{n} 对）'); res['ours'].setdefault('concord', {})[name] = c
    Gh = np.array([r[3] for r in rows])
    print('  同样的排序指标，人类检验集：')
    for name, p in ([('现有模型(自己对局)', json_model_predict(OLD, [r[0] for r in rows]))] if OLD else []) + [('人类模型(新)', mlp_predict(mlp, X)), ('线性回归(人类)', lin(X))]:
        c, n = within_fight_concord(p, Y, Gh, te)
        print(f'    {name:<20}{c:.1%}（{n} 对）'); res['human_test'].setdefault('concord', {})[name] = c

if not a.no_write:
    out = {'features': names, 'idx': idx, 'mu': mlp['mu'].tolist(), 'sd': mlp['sd'].tolist(), 'W1': mlp['W1'].tolist(), 'b1': mlp['b1'].tolist(),
           'W2': mlp['W2'].tolist(), 'b2': mlp['b2'], 'scale': mlp['scale'],
           'meta': {'source': 'human replays (tools/replay_situations.py)', 'rows': int(len(rows)), 'train_rows': int(tr.sum()), 'runs': len(runs),
                    'subset': a.subset, 'dropped': sorted(DROP), 'death': a.death, 'hidden': int(mlp['W1'].shape[0]), 'ensemble': a.ensemble, 'l2': a.l2, 'loss': a.loss, 'epoch': mlp['epoch'], 'val_rmse': mlp['val_rmse'],
                    'test_rmse': res['human_test']['human_mlp']['全部检验对局']['rmse'], 'eval': res}}
    json.dump(out, open(f'{HERE}/data/{a.out}', 'w'))
    print(f'\n写入 data/{a.out}')
