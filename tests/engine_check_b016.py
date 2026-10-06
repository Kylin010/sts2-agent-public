"""B-016：带祈祷轮打赢普通战，数战后出现几组卡牌奖励（应为 2 组）"""
import json, subprocess, sys
CLI = sys.argv[1]
p = subprocess.Popen(['/opt/dotnet9/dotnet', f'{CLI}/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll'], cwd=CLI, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
def send(c):
    p.stdin.write(json.dumps(c) + '\n'); p.stdin.flush()
    while True:
        l = p.stdout.readline().strip()
        if l.startswith('{') and '"ready"' not in l: return json.loads(l)
for relics in (['BURNING_BLOOD'], ['BURNING_BLOOD', 'PRAYER_WHEEL']):
    send({'cmd': 'start_run', 'character': 'Ironclad', 'ascension': 10, 'seed': 'B016'})
    send({'cmd': 'set_player', 'hp': 80, 'max_hp': 80, 'relics': relics, 'deck': ['BLUDGEON+'] * 10})
    st = send({'cmd': 'enter_room', 'type': 'combat', 'encounter': 'SHRINKER_BEETLE_WEAK'})
    for _ in range(60):
        if st.get('decision') != 'combat_play': break
        hand = [c for c in st.get('hand') or [] if c.get('can_play')]
        if hand:
            st = send({'cmd': 'action', 'action': 'play_card', 'args': {'card_index': hand[0]['index'], 'target_index': (st.get('enemies') or [{}])[0].get('index', 0)}})
        else:
            st = send({'cmd': 'action', 'action': 'end_turn'})
    n = 0; deck0 = len((st.get('player') or {}).get('deck') or [])
    while st.get('decision') == 'card_reward' and n < 5:
        n += 1; st = send({'cmd': 'action', 'action': 'select_card_reward', 'args': {'card_index': 0}})
    print(relics, '战后卡牌奖励', n, '组；牌组', deck0, '→', len((st.get('player') or {}).get('deck') or []), '；之后', st.get('decision'))
send({'cmd': 'quit'})
