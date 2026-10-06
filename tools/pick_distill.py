"""选牌蒸馏训练（10/4）：老师 = 选牌实打（结果里的 simeval_log），学生 = policy/pickdistill.py 的线性函数。
目标：同一次选牌里，各选项「实打分 / simeval_pick_scale」相对本次平均值的差（老师觉得哪张比别的好多少）。
方法：特征也按本次选牌去平均，岭回归（numpy）。留 20% 的选牌决定做验证：看「模型分 + 学到的修正」挑中的选项和老师一致的比例。
用法：python3 tools/pick_distill.py results/teach-pick-1.jsonl [更多文件...] [--lam 3] [--out data/pick_distill.json]
"""
import json, os, random, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from params import P
from policy import pickdistill as PD

args = [a for a in sys.argv[1:] if not a.startswith('--')]
lam = float(sys.argv[sys.argv.index('--lam') + 1]) if '--lam' in sys.argv else 3.0
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'data/pick_distill.json'
files = [a for a in args if a.endswith('.jsonl')]

decs = []
for f in files:
    for l in open(f):
        r = json.loads(l)
        for d in r.get('simeval_log') or []:
            if 'deck' not in d or len(d.get('opts') or []) < 2: continue
            decs.append(d)
print(f'选牌决定 {len(decs)} 次')
random.Random(1).shuffle(decs)
cut = int(len(decs) * 0.8)
scale = P['simeval_pick_scale']


def rows(ds):
    X, y, groups = [], [], []
    for gi, d in enumerate(ds):
        sim = np.array(d['sim'], float) / scale
        fs = [PD.features(o, d['deck'], d.get('act') or 1, d.get('boss'), d.get('act_name')) for o in d['opts']]
        X.append(fs); y.append(sim - sim.mean()); groups.append(d)
    return X, y, groups


Xtr, ytr, _ = rows(decs[:cut]); Xva, yva, gva = rows(decs[cut:])
vocab = {}
for fs in Xtr:
    for f in fs:
        for k in f: vocab.setdefault(k, len(vocab))
print(f'特征 {len(vocab)} 个')


def mat(X):
    blocks = []
    for fs in X:
        M = np.zeros((len(fs), len(vocab)))
        for i, f in enumerate(fs):
            for k, v in f.items():
                j = vocab.get(k)
                if j is not None: M[i, j] = v
        blocks.append(M - M.mean(0, keepdims=True))      # 同一次选牌内去平均：只学相对好坏
    return blocks


Btr = mat(Xtr); A = np.vstack(Btr); b = np.concatenate(ytr)
w = np.linalg.solve(A.T @ A + lam * np.eye(len(vocab)), A.T @ b)
pred_tr = A @ w
print(f'训练集 R² {1 - ((b - pred_tr) ** 2).sum() / (b ** 2).sum():.3f}')
Bva = mat(Xva)
agree_prior = agree_new = agree_corr = 0; ss_res = ss_tot = 0.0
pw = P['simeval_prior_w']
for M, yv, d in zip(Bva, yva, gva):
    p = M @ w; prior = np.array(d['prior'], float)
    teacher = np.argmax(yv + pw * prior)                    # 老师最终挑的（实打 + 模型分 × prior_w，忽略其他小加分）
    agree_prior += np.argmax(prior) == teacher
    agree_new += np.argmax(prior + p) == teacher           # 学生：模型分 + 学到的修正（权重 1，相当于 pick_distill_w=1、模型分不缩）
    agree_corr += np.argmax(pw * prior + p) == teacher
    ss_res += ((yv - p) ** 2).sum(); ss_tot += (yv ** 2).sum()
n = len(Bva)
print(f'验证 {n} 次：只用模型分和老师一致 {agree_prior / n:.1%}；模型分 + 修正 {agree_new / n:.1%}；模型分×{pw} + 修正 {agree_corr / n:.1%}；修正分 R² {1 - ss_res / ss_tot:.3f}')
inv = {j: k for k, j in vocab.items()}
json.dump({'w': {inv[j]: round(float(x), 5) for j, x in enumerate(w) if abs(x) > 1e-5}, 'lam': lam, 'n_dec': len(decs), 'files': files},
          open(f'{HERE}/{out}', 'w'), ensure_ascii=False)
top = sorted(((float(x), inv[j]) for j, x in enumerate(w)), reverse=True)
print('最看好的特征', [(k, round(v, 2)) for v, k in top[:12]])
print('最不看好的特征', [(k, round(v, 2)) for v, k in top[-12:]])
print('已写', out)
