"""事件体检（B-010，10/3）：每个事件 × 每个初始选项，进事件选一次，看事件任务有没有崩（引擎日志 faulted）、回传的是不是旧选项。
用法：python3 tools/event_audit.py <sts2-cli 目录（已编译）> [输出 json]
10/3 结果：旧引擎（补丁 11）144 个选项里 46 个回传旧选项；补丁 13 后只剩 7 个（锁住的选项、湿滑桥、巨花再深入，都是正常的），8 个会崩的选项直接结束事件"""
import json, os, re, subprocess, sys, threading, time, glob
CLI = sys.argv[1]; OUT = sys.argv[2] if len(sys.argv) > 2 else None
DLL = f'{CLI}/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll'
EV = '/opt/slay-the-spire-2/decompiled/v0.111.0/MegaCrit.Sts2.Core.Models.Events'
ids = []
for f in sorted(glob.glob(f'{EV}/*.cs')):
    s = open(f).read()
    if re.search(r'class \w+ : (EventModel|AncientEventModel)\b', s):
        n = os.path.basename(f)[:-3]; ids.append(re.sub(r'(?<!^)(?=[A-Z])', '_', n).upper())
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
while True:                                     # 引擎启动先发一行 {"type":"ready"}
    l = p.stdout.readline().strip()
    if l.startswith('{') and '"ready"' in l: break
def act(a, **k): return send({'cmd': 'action', 'action': a, **({'args': k} if k else {})})
names = lambda st: [o.get('title') or o.get('option_id') for o in st.get('options') or []]
res = []; k = 0
for eid in ids:
    for i in range(4):
        k += 1; send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': f'EVA{k}'})
        send({'cmd': 'set_player', 'hp': 60, 'max_hp': 80, 'gold': 300})
        st = send({'cmd': 'enter_room', 'type': 'event', 'event': eid})
        if st.get('decision') != 'event_choice':
            res.append({'event': eid, 'opt': i, 'note': f"进不去：{st.get('decision')} {str(st.get('message'))[:60]}"}); break
        o0 = names(st)
        if i >= len(o0): break
        e0 = len(err); hp0 = (st.get('player') or {}).get('hp'); g0 = (st.get('player') or {}).get('gold')
        st = act('choose_option', option_index=i); path = []
        for _ in range(8):
            d = st.get('decision'); path.append(d)
            if d == 'card_select': st = act('select_cards', indices='0')
            elif d == 'bundle_select': st = act('select_bundle', bundle_index=0)
            elif d == 'card_reward': st = act('skip_card_reward')
            else: break
            if st.get('type') == 'error': path.append('error:' + str(st.get('message'))[:50]); break
        time.sleep(0.3)
        faults = [x for x in err[e0:] if 'faulted' in x or 'Exception' in x]
        r = {'event': eid, 'opt': i, 'label': o0[i], 'path': path, 'end': st.get('decision'),
             'stale': st.get('decision') == 'event_choice' and names(st) == o0, 'fault': faults[0][:160] if faults else None,
             'hp': [hp0, (st.get('player') or {}).get('hp')], 'gold': [g0, (st.get('player') or {}).get('gold')]}
        res.append(r)
        if r['fault'] or r['stale']: print(eid, i, o0[i], '| 崩溃' if r['fault'] else '', '| 回传旧选项' if r['stale'] else '', r['end'], flush=True)
send({'cmd': 'quit'})
bad = [r for r in res if r.get('fault') or r.get('stale')]
print(f'事件 {len(ids)} 个，测了 {sum(1 for r in res if "label" in r)} 个选项；崩溃 {sum(1 for r in res if r.get("fault"))}，回传旧选项 {sum(1 for r in res if r.get("stale"))}；进不去 {sum(1 for r in res if "note" in r)}')
if OUT: json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=0)
