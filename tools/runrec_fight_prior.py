"""整局记录（ironclad-a10-all.jsonl.gz，每层掉血、没有逐回合）能做到什么程度（分析脚本，不写文件）：
每场战斗进场时的局面（遭遇、幕、层、血、上限、牌组张数 / 升级数 / 每回合伤害估计）→ 这场掉多少血（死了 +30）。
在人类检验对局（和价值网络同一批检验种子）上，和逐回合模型在第 1 回合结束时的估计比。
先跑 tools/replay_situations.py 和 tools/train_combat_value_human.py。用法：python3 tools/runrec_fight_prior.py（约 2 分钟）"""
import gzip, json, random, re, sys, collections
import numpy as np
import os
HV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HV)
from policy.combatvalue import deck_dpt, features, unblocked_now
SRC = '/opt/slay-the-spire-2/sources/community-runs'

# ---- 检验种子（和 train_combat_value_human.py 一样的划分）
recs = [json.loads(l) for l in open(f'{HV}/results/human-turns.jsonl')]
runs = sorted({r['replay'] for r in recs}); order = runs[:]; random.Random(4).shuffle(order)
test_runs = set(order[:len(order) // 5])
seed_of = {r['replay']: r['seed'] for r in recs}
test_seeds = {seed_of[r] for r in test_runs}; all_replay_seeds = set(seed_of.values())
print(f'检验对局 {len(test_runs)}，种子 {len(test_seeds)}')

START = ['STRIKE_IRONCLAD'] * 5 + ['DEFEND_IRONCLAD'] * 4 + ['BASH', 'ASCENDERS_BANE']
cid = lambda c: str(c.get('id') if isinstance(c, dict) else c).replace('CARD.', '')
rows = []; stats = collections.Counter(); builds = collections.Counter()
for l in gzip.open(f'{SRC}/ironclad-a10-all.jsonl.gz', 'rt'):
    r = json.loads(l)
    stats['runs'] += 1; builds[r.get('build_id')] += 1
    if r.get('game_mode') != 'standard' or r.get('modifiers'): continue
    if r.get('build_id') not in ('v0.111.0', 'v0.107.1'): continue
    if len(r.get('players') or []) != 1: continue
    stats['runs_used'] += 1
    deck = [[c, 0] for c in START]; hp = mx = 80; floor = 0
    killed = str(r.get('killed_by_encounter') or '').replace('ENCOUNTER.', '')
    seed = r.get('seed'); split = 'test' if seed in test_seeds else ('replay' if seed in all_replay_seeds else 'train')
    acts = r.get('map_point_history') or []
    for ai, act in enumerate(acts):
        for pi, mp in enumerate(act):
            floor += 1
            ps = (mp.get('player_stats') or [{}])[0]
            encs = [rm.get('model_id', '').replace('ENCOUNTER.', '') for rm in mp.get('rooms') or [] if str(rm.get('model_id', '')).startswith('ENCOUNTER.')]
            last = ai == len(acts) - 1 and pi == len(act) - 1
            if encs and mp.get('map_point_type') in ('monster', 'elite', 'boss'):
                enc = encs[0]; died = bool(last and not r.get('win') and killed == enc and not r.get('was_abandoned'))
                dl = [{'id': d[0], 'upgraded': bool(d[1])} for d in deck]
                rows.append({'enc': enc, 'act': ai + 1, 'floor': floor, 'hp': hp, 'max_hp': mx, 'deck': len(deck), 'ups': sum(1 for d in deck if d[1]),
                             'dpt': deck_dpt(dl), 'dmg': ps.get('damage_taken') or 0, 'died': died, 'split': split, 'seed': seed, 'turns': (mp.get('rooms') or [{}])[0].get('turns_taken')})
            # 这一格之后的牌组 / 血量
            for c in ps.get('cards_gained') or []: deck.append([cid(c), 1 if (isinstance(c, dict) and c.get('current_upgrade_level')) else 0])
            for c in ps.get('cards_removed') or []:
                k = next((i for i, d in enumerate(deck) if d[0] == cid(c)), None)
                if k is not None: deck.pop(k)
            for t in ps.get('cards_transformed') or []:
                k = next((i for i, d in enumerate(deck) if d[0] == cid(t.get('original_card') or {})), None)
                if k is not None: deck.pop(k)
                deck.append([cid(t.get('final_card') or {}), 0])
            for c in ps.get('upgraded_cards') or []:
                k = next((i for i, d in enumerate(deck) if d[0] == cid(c) and not d[1]), None)
                if k is not None: deck[k][1] = 1
            if ps.get('current_hp') is not None: hp = ps['current_hp']
            if ps.get('max_hp') is not None: mx = ps['max_hp']
print(stats, builds.most_common(8))
print(f"战斗 {len(rows)}：训练 {sum(r['split'] == 'train' for r in rows)}、检验种子 {sum(r['split'] == 'test' for r in rows)}、其他回放种子 {sum(r['split'] == 'replay' for r in rows)}；"
      f"死亡 {sum(r['died'] for r in rows)}")
by_act = collections.Counter(r['act'] for r in rows); print('按幕', dict(by_act))
encs = sorted({r['enc'] for r in rows}); ei = {e: i for i, e in enumerate(encs)}


def feat(r):
    v = np.zeros(len(encs) + 12, np.float32)
    if r['enc'] in ei: v[ei[r['enc']]] = 1
    b = len(encs)
    v[b:b + 12] = [1, r['hp'] / 80, r['hp'] / max(r['max_hp'], 1), r['max_hp'] / 80, r['deck'] / 30, r['ups'] / 10, r['dpt'] / 30, r['floor'] / 50,
                   r['act'] == 1, r['act'] == 2, r['act'] == 3, min(r['hp'], 30) / 30]
    return v


tr = [r for r in rows if r['split'] == 'train']; te = [r for r in rows if r['split'] == 'test']
X = np.array([feat(r) for r in tr]); Y = np.array([min(r['dmg'], r['hp']) + 30 * r['died'] for r in tr], np.float32)
w = np.linalg.lstsq(X.T @ X + 1.0 * np.eye(X.shape[1]), X.T @ Y, rcond=None)[0]
# 小网络（一层 ReLU，MSE）
rs = np.random.RandomState(0); mu = X.mean(0); sd = X.std(0); sd[sd < 1e-6] = 1; Xs = (X - mu) / sd; sc = Y.std()
H = 32; W1 = rs.randn(H, X.shape[1]) * np.sqrt(2 / X.shape[1]); b1 = np.zeros(H); W2 = rs.randn(H) * 0.1; b2 = Y.mean() / sc
P = [W1, b1, W2, np.array(b2)]; M_ = [np.zeros_like(p) for p in P]; V_ = [np.zeros_like(p) for p in P]; st = 0
for ep in range(6):
    idx = rs.permutation(len(Xs))
    for b in range(0, len(idx), 512):
        bi = idx[b:b + 512]; x = Xs[bi]; y = Y[bi] / sc
        z = x @ P[0].T + P[1]; h = np.maximum(z, 0); p = h @ P[2] + P[3]
        g = np.clip(p - y, -1, 1) / len(bi); gh = np.outer(g, P[2]) * (z > 0)
        G = [gh.T @ x + 1e-3 * P[0], gh.sum(0), h.T @ g + 1e-3 * P[2], np.array(g.sum())]; st += 1
        for i in range(4):
            M_[i] = 0.9 * M_[i] + 0.1 * G[i]; V_[i] = 0.999 * V_[i] + 0.001 * G[i] ** 2
            P[i] -= 3e-3 * (M_[i] / (1 - 0.9 ** st)) / (np.sqrt(V_[i] / (1 - 0.999 ** st)) + 1e-8)
nn = lambda Z: np.maximum((np.maximum(((Z - mu) / sd) @ P[0].T + P[1], 0) @ P[2] + P[3]) * sc, 0)
Xt = np.array([feat(r) for r in te]); Yt = np.array([min(r['dmg'], r['hp']) + 30 * r['died'] for r in te], np.float32)
rmse = lambda p, y: float(np.sqrt(np.mean((p - y) ** 2)))
print(f'\n整局记录 → 这场战斗总掉血（检验种子的 {len(te)} 场战斗）：只猜平均 {rmse(np.full(len(Yt), Y.mean()), Yt):.2f}  线性 {rmse(np.maximum(Xt @ w, 0), Yt):.2f}  小网络 {rmse(nn(Xt), Yt):.2f}')

# ---- 同一批战斗：逐回合人类模型在第 1 回合结束时的估计（unb + predict），目标 = 那一刻之后掉的血 + 死亡 30
from policy import combatvalue as CV
import params
params.P['cv_file'] = 'combat_value_human.json'
CV.M = None
fight_pred = {(r['seed'], r['floor']): (nn(feat(r)[None])[0], r) for r in te}
a = []; b = []; c = []; y = []
for rc in recs:
    if rc['replay'] not in test_runs or not rc['turns']: continue
    t0 = rc['turns'][0]
    if t0['s']['round'] != 1: continue
    key = (rc['seed'], rc['floor'])
    if key not in fight_pred: continue
    s = t0['s']; yy = t0['future'] + 30 * t0['died']
    a.append(CV.unblocked_now(s) + CV.predict(s)); b.append(fight_pred[key][0]); y.append(yy)
    c.append((fight_pred[key][1]['dmg'], rc['hp0'] - rc['end_hp']))
a, b, y = map(np.array, (a, b, y))
print(f'对上的检验战斗 {len(y)} 场（第 1 回合结束的局面）：逐回合人类模型 RMSE {rmse(a, y):.2f}（相关 {np.corrcoef(a, y)[0, 1]:.3f}）；'
      f'整局记录战斗级模型 {rmse(b, y):.2f}（相关 {np.corrcoef(b, y)[0, 1]:.3f}）；两者平均 {rmse((a + b) / 2, y):.2f}')
cc = np.array(c); print(f'整局记录的 damage_taken 和回放还原的这场掉血一致（±1）：{np.mean(np.abs(cc[:, 0] - cc[:, 1]) <= 1):.1%}')
# 每个遭遇的样本量：回放 vs 整局记录
rep_n = collections.Counter(r['enc'] for r in recs); run_n = collections.Counter(r['enc'] for r in rows)
print('遭遇样本量（回放场次 / 整局记录场次）：', ', '.join(f'{e} {rep_n[e]}/{run_n[e]}' for e, _ in sorted(rep_n.items(), key=lambda x: x[1])[:8]))
