"""引擎体检：把每一种遭遇都实际打一遍（999 血、一副中等强度的牌组），抓 sts2-cli 日志里的
MissingMethodException / TypeLoadException / 「卡死、强制 game_over」之类的引擎问题。
起因：10/2 发现实验体复活时调用 Godot 替身库里没有的 SetSelfModulate，敌方回合卡死，被判负（第三幕约两成的「死亡」是假的）。
用法：python3 tools/engine_scan.py [--workers 4] [--only 遭遇,遭遇]   结果写 lab/engine_scan.md
"""
import argparse, json, os, queue, re, subprocess, sys, threading
from multiprocessing import Pool

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
DECK = ['STRIKE_IRONCLAD'] * 3 + ['DEFEND_IRONCLAD'] * 3 + ['BASH', 'INFLAME', 'UPPERCUT', 'HEADBUTT', 'BLUDGEON', 'FEED', 'DEMON_FORM',
        'HEMOKINESIS', 'CARNAGE', 'POMMEL_STRIKE', 'SHRUG_IT_OFF', 'TWIN_STRIKE', 'THUNDERCLAP', 'FEEL_NO_PAIN', 'BURNING_PACT']
BAD = re.compile(r'MissingMethod|MissingField|TypeLoad|NotImplemented|NullReference|nuclear fallback|forcing game_over|turn loop died', re.I)


def scan(enc):
    import sim as S, run
    log = f'/tmp/engine_scan_{os.getpid()}.log'

    class Sim2(S.Sim):
        def __init__(self, timeout=30):
            env = dict(os.environ, DOTNET_ROOT=os.path.dirname(S.DOTNET), DOTNET_CLI_TELEMETRY_OPTOUT='1')
            self.timeout = timeout; self.err = open(log, 'w')
            self.p = subprocess.Popen([S.DOTNET, S.DLL], cwd=S.CLI_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err,
                                      text=True, bufsize=1, env=env)
            self.q = queue.Queue(); threading.Thread(target=self._pump, daemon=True).start(); self._read()
    out = {'enc': enc}
    try:
        s = Sim2(); s.start('SCAN' + enc[:8])
        s.send({'cmd': 'set_player', 'hp': 999, 'max_hp': 999, 'deck': DECK})
        st = s.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': enc})
        if st.get('decision') not in ('combat_play', 'card_select', 'card_reward'):
            out['error'] = f"进不去：{st.get('message') or st.get('decision')}"
        else:
            r = run.drive(s, st, {}, verbose=False, combat_only=True, max_steps=2500)
            c = (r.get('combats') or [{}])[0]
            out.update(win=r.get('win'), rounds=c.get('rounds'), dmg=c.get('dmg'))
        s.close()
    except Exception as e:
        out['error'] = str(e)[:150]
    try:
        lines = [l.strip() for l in open(log) if BAD.search(l)]
        out['problems'] = sorted(set(l[:160] for l in lines))[:5]
        os.remove(log)
    except Exception:
        pass
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=4); ap.add_argument('--only', default=None)
    a = ap.parse_args()
    E = json.load(open(f'{HERE}/kb/encounters_src.json'))
    encs = sorted(k for k, v in E.items() if not k.startswith('_') and isinstance(v, dict) and v.get('in_act_pool'))
    if a.only: encs = a.only.split(',')
    with Pool(a.workers) as p:
        rs = p.map(scan, encs, chunksize=1)
    bad = [r for r in rs if r.get('problems') or r.get('error') or not r.get('win')]
    lines = ['# 引擎体检（tools/engine_scan.py）\n', f'{len(rs)} 种遭遇，有问题的 {len(bad)} 种\n', '| 遭遇 | 结果 | 回合 | 问题 |', '|---|---|---|---|']
    for r in bad:
        lines.append(f"| {r['enc']} | {'赢' if r.get('win') else '输/中断'} | {r.get('rounds')} | {r.get('error', '')} {'；'.join(r.get('problems') or [])} |")
    open(f'{HERE}/lab/engine_scan.md', 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
