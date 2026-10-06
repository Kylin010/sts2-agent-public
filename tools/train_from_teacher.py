"""推演当老师 → 蒸馏进规划器。
数据：search_teach_log 记下的真实局面（引擎状态，不是回放近似）+ 推演选中的出法。
每个局面：规划器列出全部组合（combat.plan topk=-1），老师那组在其中才算一条样本；特征 = 出牌模仿的特征（policy/imitation.feats）
+ 按遭遇复制一份（「遭遇|特征」，每个精英 / Boss 一套专属权重）+ 按遭遇 × 敌人招式再复制一份（阶段函数）。
softmax 似然让老师那组排第一（tools/train_imitation.fit），按「哪场战斗」分训练 / 检验。输出 data/imitation_teacher.json（imit_file 用它，下场 search_on=false）。
用法：python3 tools/train_from_teacher.py 记录1.jsonl 记录2.jsonl ...
"""
import collections, copy, json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import params
params.P['imit_w'] = 0.0
from policy import combat, imitation, foresight
from policy.knowledge import cid
import importlib.util
_spec = importlib.util.spec_from_file_location('ti', f'{HERE}/tools/train_imitation.py'); sys.argv = sys.argv[:1] + [a for a in sys.argv[1:]]
BASE = ('unb', 'unb_hp', 'over', 'blk_atk', 'blk_noatk', 'dmg', 'n', 'en_left', 'pow', 'status')


def phase(st):
    for e in st.get('enemies') or []:
        if (e.get('hp') or 0) > 0:
            mv = foresight.identify(e)
            if mv: return mv
    return None


def samples(paths):
    out = []
    for p in paths:
        fight = None; prev_round = None
        for n, line in enumerate(open(p)):
            r = json.loads(line); st = dict(r['state']); st['decision'] = 'combat_play'
            if prev_round is None or (r.get('round') or 0) < prev_round: fight = f'{p}#{n}'
            prev_round = r.get('round') or 0
            try:
                res = combat.plan(copy.deepcopy(st), {}, set(), topk=-1)
            except Exception:
                continue
            if not res or not isinstance(res, dict) or len(res['pool']) < 2: continue
            ctx, pool = res['ctx'], res['pool']
            want = collections.Counter(x.replace('CARD.', '') for x in r['chosen'])
            k = next((j for j, (_, cb) in enumerate(pool) if collections.Counter(str(c.get('id') or c.get('name')).replace('CARD.', '') for c in cb) == want), None)
            if k is None: continue
            enc = r.get('enc') or ''; mv = phase(st)
            fs = []
            for _, cb in pool:
                f = imitation.feats(cb, ctx)
                for b in BASE:
                    v = f.get(b, 0.0)
                    f[f'{enc}|{b}'] = v
                    if mv: f[f'{enc}|{mv}|{b}'] = v
                fs.append(f)
            out.append((fs, [ev / 10 for ev, _ in pool], k, enc, fight))
    return out


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('ti', f'{HERE}/tools/train_imitation.py')
    paths = sys.argv[1:]; sys.argv = sys.argv[:1]
    ti = importlib.util.module_from_spec(spec); spec.loader.exec_module(ti)
    S = samples(paths)
    fights = sorted({s[4] for s in S}); random.Random(11).shuffle(fights); va_f = set(fights[:len(fights) // 5])
    tr = [s[:4] for s in S if s[4] not in va_f]; va = [s[:4] for s in S if s[4] in va_f]
    cnt = collections.Counter(k for fs, _, _, _ in tr for f in fs for k in f)
    keys = [k for k, c in cnt.items() if not k.startswith('c:') or c >= 20]
    print(f'样本：训练 {len(tr)}，检验 {len(va)}（战斗 {len(fights)}）；特征 {len(keys)}')
    print(f'只用规划器：检验和老师一致 {ti.agree(va, {}, 1.0):.1%}')
    theta, a = ti.fit(tr, keys, 0.01, 400, fix_a=True)
    print(f'加老师权重：检验和老师一致 {ti.agree(va, theta, a):.1%}')
    json.dump({'_说明': '推演老师蒸馏的出牌权重（tools/train_from_teacher.py），全局 + 遭遇 + 遭遇×招式', 'a': a, 'scale': 10.0 / max(a, 1e-3),
               'theta': {k: round(v, 5) for k, v in theta.items()}, 'n_train': len(tr), 'n_val': len(va)},
              open(f'{HERE}/data/imitation_teacher.json', 'w'), ensure_ascii=False, indent=1)
    print('已存 data/imitation_teacher.json')
