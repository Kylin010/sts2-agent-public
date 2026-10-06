"""用真引擎核对几条移植（docs/Codex发现梳理.md 表一）。只做机制核对，不计任何胜率。

  A（C02）正常开局（不改任何状态），第一场战斗里手里有痛击时：规划器预计痛击打多少 vs 实际掉多少血
  B（C01 / C11）测试局：牌组只有燃烧+ / 恶魔形态 / 打击，带一瓶甲虫汁，进多个敌人的精英战：
      手牌预览里燃烧+ / 恶魔形态的 strengthpower；整回合要打出牌，不能一开局就不带目标喝甲虫汁

运行：cd <仓库根目录> && python3 tests/engine_check_codex_ports.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from params import P  # noqa: E402
import policy  # noqa: E402
from policy import combat  # noqa: E402
from policy.knowledge import cid  # noqa: E402
from sim import Sim  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P['simeval_pick'] = False


def check_bash(sim, seed):
    st = sim.start(seed, ascension=10)
    mem = {}
    for _ in range(400):
        d = st.get('decision')
        if st.get('type') == 'error' or d == 'game_over': return None
        if d == 'combat_play':
            bash = next((c for c in st.get('hand') or [] if cid(c) == 'BASH' and c.get('can_play')), None)
            enemies = [e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]
            if bash and (st.get('energy') or 0) >= 2 and enemies:
                e = max(enemies, key=lambda x: x.get('hp') or 0)
                if not any('vulner' in str(p.get('name', '')).lower() for p in e.get('powers') or []):
                    ctx = combat.plan(st, mem, set(), topk=-1)['ctx']
                    ctx = dict(ctx, primaries=[e])
                    det = {}
                    combat.evaluate((bash,), ctx, detail=det)
                    pred = det['lost'][e['index']]
                    args = {'card_index': bash['index']}
                    if len(enemies) > 1: args['target_index'] = e['index']
                    hp0 = e['hp']
                    st2 = sim.act('play_card', **args)
                    e2 = next((x for x in st2.get('enemies') or [] if x.get('index') == e['index']), None)
                    actual = hp0 - (e2['hp'] if e2 else 0)
                    return {'seed': seed, 'enemy': e.get('name'), 'preview': (bash.get('damage_by_target') or [{}])[0].get('damage'),
                            'predicted_hp_loss': pred, 'actual_hp_loss': actual, 'enemy_block_before': e.get('block') or 0}
        a, args = policy.decide(st, mem, sim)
        st = sim.act(a, **args)
    return None


def check_test_room(sim):
    sim.start('PORTCHECK1', ascension=10)
    sim.send({'cmd': 'set_player', 'hp': 80, 'max_hp': 80,
              'deck': ['INFLAME+', 'INFLAME+', 'INFLAME+', 'DEMON_FORM', 'DEMON_FORM', 'DEMON_FORM',
                       'STRIKE_IRONCLAD', 'STRIKE_IRONCLAD', 'STRIKE_IRONCLAD', 'STRIKE_IRONCLAD'],
              'potions': ['BEETLE_JUICE']})
    st = sim.send({'cmd': 'enter_room', 'type': 'combat', 'encounter': 'PHANTASMAL_GARDENERS_ELITE'})
    out = {'decision': st.get('decision'), 'enemies': len([e for e in st.get('enemies') or [] if (e.get('hp') or 0) > 0]),
           'potions': [p.get('name') for p in (st.get('player') or {}).get('potions') or [] if p],
           'stats': {f"{cid(c)}": (c.get('stats') or {}).get('strengthpower') for c in st.get('hand') or []}}
    mem = {}; acts = []
    for _ in range(12):
        if st.get('decision') != 'combat_play': break
        a, args = policy.decide(st, mem, sim)
        acts.append((a, dict(args)))
        st = sim.act(a, **args)
        if st.get('type') == 'error': acts.append(('ERROR', st.get('message'))); break
        if a == 'end_turn': break
    out['turn1_actions'] = acts
    return out


if __name__ == '__main__':
    sim = Sim(timeout=180)
    try:
        seeds = open(f'{HERE}/data/dev_seeds.txt').read().split()[2:8]
        res = []
        for s in seeds:
            r = check_bash(sim, s)
            if r: res.append(r); print('A', r)
            if len(res) >= 3: break
        ok_a = bool(res) and all(abs(r['predicted_hp_loss'] - r['actual_hp_loss']) < 1e-6 for r in res)
        b = check_test_room(sim); print('B', b)
        ok_b = (b['enemies'] >= 2 and any(a == 'play_card' for a, _ in b['turn1_actions'])
                and not any(a == 'use_potion' and 'target_index' not in args for a, args in b['turn1_actions'] if isinstance(args, dict))
                and all(v in (None, 3) for v in b['stats'].values()))
        print('A 痛击预计 = 实际：', ok_a, '｜B 多敌人带甲虫汁照常出牌、力量读牌面：', ok_b)
        sys.exit(0 if ok_a and ok_b else 1)
    finally:
        sim.close()
