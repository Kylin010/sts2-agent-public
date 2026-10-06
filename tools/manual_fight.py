"""亲自打一场。
后台进程拿着引擎，按案例（牌组 / 遗物 / 药水 / 血量 / 遭遇）摆出这场战斗；我每次发一条命令，返回玩家看得见的局面：
手牌（费用、伤害 / 格挡）、抽牌堆 / 弃牌堆 / 消耗牌堆的内容（抽牌堆只给内容、不给顺序）、敌人血量 / 格挡 / 意图 / 能力、自己的能力、药水、遗物计数。
不读档、不重来：一场一次机会。

用法：
  python3 tools/manual_fight.py serve 案例.json 序号 [种子]     # 后台起服务（socket 在 /tmp/manual_fight.sock）
  python3 tools/manual_fight.py show
  python3 tools/manual_fight.py play 手牌序号 [敌人序号]
  python3 tools/manual_fight.py potion 药水序号 [敌人序号]
  python3 tools/manual_fight.py end
  python3 tools/manual_fight.py select 序号,序号      # 战斗中的选牌
  python3 tools/manual_fight.py raw '{"action": ..., "args": {...}}'
"""
import json, os, socket, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
SOCK = os.environ.get('MANUAL_SOCK', '/tmp/manual_fight.sock')


def fmt(st):
    if not isinstance(st, dict): return str(st)
    if st.get('type') == 'error': return '错误：' + str(st.get('message'))[:300]
    d = st.get('decision'); out = [f'== 决定：{d}  第 {st.get("round")} 回合']
    if d == 'game_over': return out[0] + ('  胜利' if st.get('victory') else '  失败')
    pl = st.get('player') or {}
    out.append(f'我：血 {pl.get("hp")}/{pl.get("max_hp")}  格挡 {pl.get("block")}  能量 {st.get("energy")}  '
               f'能力 {[(p.get("name"), p.get("amount")) for p in st.get("player_powers") or []]}')
    out.append('药水：' + str([(i, p.get('name')) for i, p in enumerate(pl.get('potions') or []) if p]))
    rel = [(r.get('id'), r.get('counter')) for r in pl.get('relics') or [] if r.get('counter') is not None]
    if rel: out.append('遗物计数：' + str(rel))
    for e in st.get('enemies') or []:
        if (e.get('hp') or 0) <= 0: continue
        it = [(i.get('type'), i.get('damage'), i.get('hits')) for i in e.get('intents') or []]
        out.append(f'敌[{e.get("index")}] {e.get("name")}  血 {e.get("hp")}/{e.get("max_hp")}  格挡 {e.get("block")}  意图 {it}  '
                   f'能力 {[(p.get("name"), p.get("amount")) for p in e.get("powers") or []]}')
    out.append('手牌：')
    for c in st.get('hand') or []:
        s = c.get('stats') or {}
        kv = ' '.join(f'{k}={v}' for k, v in s.items() if v not in (None, 0))
        out.append(f'  [{c.get("index")}] {c.get("name")}{"+" if c.get("upgraded") else ""}  费 {c.get("cost")}  {c.get("type")}  {kv}'
                   f'{"" if c.get("can_play") else "  (不能打)"}  | {str(c.get("description") or "")[:90]}')
    from collections import Counter
    for k, nm in (('draw_pile', '抽牌堆（只看内容）'), ('discard_pile', '弃牌堆'), ('exhaust_pile', '消耗堆')):
        v = st.get(k)
        if v is not None: out.append(f'{nm} {len(v)} 张：' + ', '.join(f'{c}×{n}' if n > 1 else c for c, n in sorted(Counter(v).items())))
    if d in ('card_select', 'combat_select', 'card_reward'):
        out.append('选项：' + str([(i, c.get('name')) for i, c in enumerate(st.get('cards') or st.get('options') or [])]))
        out.append('原始：' + json.dumps({k: st[k] for k in st if k not in ('hand', 'enemies', 'player', 'draw_pile', 'discard_pile', 'exhaust_pile', 'player_powers')}, ensure_ascii=False)[:600])
    return '\n'.join(out)


def serve(path, idx, seed):
    from sim import Sim
    case = json.load(open(path))[idx]
    sim = Sim()
    sim.start(seed, ascension=10) if hasattr(sim, 'start') else sim.send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': seed})
    sp = {'cmd': 'set_player', 'hp': case['hp'], 'max_hp': case['max_hp'], 'deck': case['deck'], 'relics': case['relics']}
    if case.get('potions'): sp['potions'] = case['potions']
    sim.send(sp)
    st = sim.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': case['encounter']})
    log = open(f'/tmp/manual_fight_{idx}.log', 'a')
    log.write(json.dumps({'case': idx, 'seed': seed, 'start': fmt(st)}, ensure_ascii=False) + '\n'); log.flush()
    if os.path.exists(SOCK): os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(SOCK); srv.listen(1)
    while True:
        conn, _ = srv.accept()
        req = json.loads(conn.recv(65536).decode())
        if req.get('cmd') == 'quit': conn.sendall(b'bye'); conn.close(); break
        if req.get('cmd') != 'show':
            r = sim.act(req['action'], **req.get('args', {}))
            log.write(json.dumps({'req': req, 'after': fmt(r)}, ensure_ascii=False) + '\n'); log.flush()
            if r.get('type') == 'error':                      # 出错不改当前局面
                conn.sendall((fmt(r) + '\n' + fmt(st)).encode()); conn.close(); continue
            st = r
        conn.sendall(fmt(st).encode()); conn.close()


def client(req):
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.connect(SOCK)
    c.sendall(json.dumps(req).encode()); data = b''
    while True:
        b = c.recv(65536)
        if not b: break
        data += b
    print(data.decode())


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'serve': serve(a[1], int(a[2]), a[3] if len(a) > 3 else f'MANUAL{a[2]}')
    elif a[0] == 'show': client({'cmd': 'show'})
    elif a[0] == 'play':
        args = {'card_index': int(a[1])}
        if len(a) > 2: args['target_index'] = int(a[2])
        client({'cmd': 'act', 'action': 'play_card', 'args': args})
    elif a[0] == 'potion':
        args = {'potion_index': int(a[1])}
        if len(a) > 2: args['target_index'] = int(a[2])
        client({'cmd': 'act', 'action': 'use_potion', 'args': args})
    elif a[0] == 'end': client({'cmd': 'act', 'action': 'end_turn', 'args': {}})
    elif a[0] == 'select': client({'cmd': 'act', 'action': 'select_cards', 'args': {'indices': a[1]}})   # 引擎要逗号分隔的字符串
    elif a[0] == 'raw': client(json.loads(a[1]) | {'cmd': 'act'})
    elif a[0] == 'quit': client({'cmd': 'quit'})
