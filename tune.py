"""自动调参：坐标下降。每次只改一个参数，用分布式跑一批对局评估，变好就留下。

用法（在 agent/ 目录）：python3 tune.py [每次评估的局数，默认 300] [--stop-act 1] [--rounds 2]
目标分 = 平均走到第几层（全局）+ 打完目标幕的局 × 20 + 剩余血量比例 × 5（只打第一幕时）
每次评估写进 tune_log.jsonl；当前最好的参数写进 params_best.json（不会自动覆盖 params.json，要人看过再合并）。
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
STOP = sys.argv[sys.argv.index('--stop-act') + 1] if '--stop-act' in sys.argv else '1'
ROUNDS = int(sys.argv[sys.argv.index('--rounds') + 1]) if '--rounds' in sys.argv else 2

SPACE = {   # 参数 → 候选值
    'elite_weight_hi': [-2, 0, 1.0, 2.2],
    'elite_dpt_act1': [18, 24, 32],
    'alpha_base': [0.1, 0.25, 0.4],
    'alpha_scaling_enemy': [0, 0.15, 0.3],
    'alpha_in_mode': ['ema', 'max'],
    'alpha_max': [1.0, 1.5, 2.0],
    'risk_hp': [20, 30, 45],
    'kill_bonus': [3, 6, 10],
    'power_weight': [0.3, 0.6, 1.0],
    'draw_value': [0.5, 1.5, 2.5],
    'heal_below': [0.45, 0.55, 0.7],
    'reward_skip_below': [0.2, 0.28, 0.36],
    'need_damage': [0.05, 0.12, 0.25],
    'need_block': [0.0, 0.08, 0.16],
    'rest_weight_low_hp': [1.6, 3.0],
    'unknown_weight': [0.4, 0.8, 1.2],
    'monster_weight_early': [0.3, 0.7, 1.0],
}


def evaluate(params, tag):
    sets = [x for k, v in params.items() for x in ('--set', f'{k}={json.dumps(v)}')]
    subprocess.run([sys.executable, f'{HERE}/dist.py', str(N), '--stop-act', STOP, '--tag', tag, *sets],
                   cwd=HERE, capture_output=True, text=True, timeout=3600)
    rs = [json.loads(l) for l in open(f'{HERE}/results/{tag}.jsonl')]
    n = max(len(rs), 1)
    floors = sum(((r.get('act') or 1) - 1) * 17 + (r.get('floor') or 0) for r in rs) / n
    cleared = sum(bool(r.get('win')) for r in rs) / n
    hp = sum(r['hp'] / r['max_hp'] for r in rs if r.get('cleared') and r.get('max_hp')) / n
    return floors + 20 * cleared + 5 * hp, {'floors': round(floors, 2), 'cleared': round(cleared, 3), 'hp': round(hp, 3), 'n': len(rs)}


if __name__ == '__main__':
    base = {k: v for k, v in json.load(open(f'{HERE}/params.json')).items() if k in SPACE}
    best_path = f'{HERE}/params_best.json'
    if os.path.exists(best_path): base.update(json.load(open(best_path)))
    best, info = evaluate(base, 'tune-base')
    log = open(f'{HERE}/tune_log.jsonl', 'a')
    log.write(json.dumps({'t': time.strftime('%m-%d %H:%M'), 'params': base, 'score': best, **info}, ensure_ascii=False) + '\n'); log.flush()
    print(f'起点：{best:.2f} {info}', flush=True)
    for rd in range(ROUNDS):
        for k, vals in SPACE.items():
            for v in vals:
                if v == base.get(k): continue
                trial = dict(base, **{k: v})
                sc, inf = evaluate(trial, 'tune-trial')
                log.write(json.dumps({'t': time.strftime('%m-%d %H:%M'), 'changed': {k: v}, 'score': sc, **inf}, ensure_ascii=False) + '\n'); log.flush()
                mark = ''
                if sc > best + 0.3:          # 留一点余量，避免把随机波动当成进步
                    best, base, mark = sc, trial, '  ← 采用'
                    json.dump(base, open(best_path, 'w'), ensure_ascii=False, indent=2)
                print(f'[第{rd + 1}轮] {k}={v}: {sc:.2f} {inf}{mark}', flush=True)
    print(f'结束：最好 {best:.2f}，参数写在 params_best.json', flush=True)
