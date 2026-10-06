"""篝火 / 宝箱体检（10/3，claude-value，B-010 同类的非战斗流程审计）：
篝火：引擎 DoChooseOption 在后台线程跑 RestSiteSynchronizer.ChooseLocalOption，推进约 1 秒后 task.Wait(2000)；非锻造选项做完强制回地图，
锻造要先选牌——选完后会不会又回到篝火选项、让同一个篝火再做一件事（原版一个篝火只能做一件事，帐篷等遗物除外）。
宝箱：领完遗物能不能再领。每个种子从头进房间，血量 40/80。

用法：python3 tools/rest_audit.py <sts2-cli 目录（已编译）> [种子数，默认 8]
"""
import json, subprocess, sys, threading, time
CLI = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 8
DLL = f'{CLI}/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll'
p = subprocess.Popen(['/opt/dotnet9/dotnet', DLL], cwd=CLI, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
err = []
threading.Thread(target=lambda: [err.append(l.rstrip()) for l in p.stderr], daemon=True).start()


def send(c):
    p.stdin.write(json.dumps(c) + '\n'); p.stdin.flush()
    while True:
        l = p.stdout.readline()
        if not l: raise RuntimeError('引擎退出')
        l = l.strip()
        if l.startswith('{'):
            try: return json.loads(l)
            except Exception: pass


while True:
    l = p.stdout.readline().strip()
    if l.startswith('{') and '"ready"' in l: break


def act(a, **k): return send({'cmd': 'action', 'action': a, **({'args': k} if k else {})})
def pl(st): return st.get('player') or {}
def opts(st): return [(o.get('index'), o.get('option_id') or o.get('title'), o.get('is_enabled', True)) for o in st.get('options') or []]
def upgraded(st): return sum(1 for c in pl(st).get('deck') or [] if c.get('upgraded'))


RELIC_SETS = [[], ['GIRYA'], ['SHOVEL'], ['PEACE_PIPE'], ['MINIATURE_TENT']]
res = []
k = 0
for relics in RELIC_SETS:
    for s in range(N):
        k += 1
        send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'REST{k:04d}'})
        send({'cmd': 'set_player', 'hp': 40, 'max_hp': 80, **({'relics': ['BURNING_BLOOD'] + relics} if relics else {})})
        st0 = send({'cmd': 'enter_room', 'type': 'rest'})
        o0 = opts(st0)
        if st0.get('decision') != 'rest_site' or not o0:
            res.append({'relics': relics, 'note': f"进不去：{st0.get('decision')} {str(st0.get('message'))[:80]}"}); break
        for idx, oid, en in o0:
            if not en: continue
            # 每个选项从头进一个新篝火
            k += 1
            send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'REST{k:04d}'})
            send({'cmd': 'set_player', 'hp': 40, 'max_hp': 80, **({'relics': ['BURNING_BLOOD'] + relics} if relics else {})})
            st = send({'cmd': 'enter_room', 'type': 'rest'})
            hp0, up0, mx0 = pl(st).get('hp'), upgraded(st), pl(st).get('max_hp')
            e0 = len(err); path = []
            st = act('choose_option', option_index=idx)
            for _ in range(5):
                d = st.get('decision'); path.append(d)
                if d == 'card_select': st = act('select_cards', indices='0')
                elif d == 'card_reward': st = act('skip_card_reward')
                else: break
            time.sleep(0.2)
            r = {'relics': relics, 'option': oid, 'path': path, 'after': st.get('decision'), 'hp': [hp0, pl(st).get('hp')],
                 'max_hp': [mx0, pl(st).get('max_hp')], 'upgraded': [up0, upgraded(st)],
                 'fault': next((x[:200] for x in err[e0:] if 'Exception' in x or 'faulted' in x), None)}
            if st.get('decision') == 'rest_site':           # 做完一件事又回到篝火：再选一次别的
                again = [o for o in opts(st) if o[2]]
                r['again_options'] = [o[1] for o in again]
                if again:
                    hp1, up1 = pl(st).get('hp'), upgraded(st)
                    st2 = act('choose_option', option_index=again[0][0])
                    for _ in range(3):
                        if st2.get('decision') == 'card_select': st2 = act('select_cards', indices='0')
                        else: break
                    r['second'] = {'option': again[0][1], 'hp': [hp1, pl(st2).get('hp')], 'upgraded': [up1, upgraded(st2)], 'after': st2.get('decision')}
            flag = r.get('second') or r['fault'] or r['after'] not in ('map_select', 'rest_site')
            if flag: print(relics, oid, r['path'], '→', r['after'], '第二次：', r.get('second'), (r['fault'] or '')[:100], flush=True)
            res.append(r)
        break                                               # 每组遗物一个种子就够列出选项；上面每个选项各开新局
# 宝箱
for s in range(N):
    k += 1
    send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'CHEST{k:04d}'})
    st = send({'cmd': 'enter_room', 'type': 'treasure'})
    r0 = len(pl(st).get('relics') or []); path = [st.get('decision')]
    for _ in range(6):
        d = st.get('decision')
        if d in ('treasure', 'chest'): st = act('open_chest')
        elif d in ('card_reward',): st = act('skip_card_reward')
        elif d in ('relic_select', 'relic_reward', 'reward'): st = act('take_relic', relic_index=0) if 'relics' in st else act('proceed')
        else: break
        path.append(st.get('decision') or st.get('type'))
    r1 = len(pl(st).get('relics') or [])
    st2 = act('open_chest'); r2 = len(pl(st2).get('relics') or [])
    res.append({'chest': k, 'path': path, 'relics': [r0, r1, r2], 'second_open': st2.get('type') != 'error'})
    if r2 > r1: print('宝箱可重复领', k, path, [r0, r1, r2], flush=True)
send({'cmd': 'quit'})
rest = [r for r in res if 'option' in r]
print(f'篝火选项测了 {len(rest)} 个（{sorted({r["option"] for r in rest})}）；做完又回到篝火 {sum(1 for r in rest if r["after"] == "rest_site")}，'
      f'同一篝火第二件事成功 {sum(1 for r in rest if r.get("second") and (r["second"]["hp"][1] != r["second"]["hp"][0] or r["second"]["upgraded"][1] != r["second"]["upgraded"][0]))}；'
      f'引擎异常 {sum(1 for r in rest if r["fault"])}')
ch = [r for r in res if 'chest' in r]
print(f'宝箱 {len(ch)} 个：开完遗物数 {[r["relics"] for r in ch][:4]}…；第二次开箱多拿 {sum(1 for r in ch if r["relics"][2] > r["relics"][1])}')
for r in rest: print('  ', r['relics'], r['option'], r['path'], '→', r['after'], '血', r['hp'], '上限', r['max_hp'], '升级', r['upgraded'], r.get('again_options', ''))
