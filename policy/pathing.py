"""路线：把这一幕剩下的地图当成一张图，用动态规划找总分最高的路线，走它的下一步。"""
from params import P
from policy import deckeval


def choose(sim_map, st):
    pl = st.get('player') or {}; hpf = pl.get('hp', 1) / max(pl.get('max_hp', 1), 1); gold = pl.get('gold', 0)
    nodes = {(n['col'], n['row']): n for row in sim_map.get('rows') or [] for n in row}
    row0 = min((c['row'] for c in st.get('choices') or []), default=0)
    ready = deckeval.elite_ready(st)          # 0 = 别打精英，1 = 放心打（牌组强度 × 血量）
    stone = any(str(r.get('id')) == 'SWORD_OF_STONE' for r in pl.get('relics') or [])   # 石之剑：打满 5 个精英变玉之剑
    def w(n):
        t = n.get('type'); r = n['row']
        if t == 'Elite':
            if r - row0 <= 2 and hpf < P['elite_hp_mid']: return -10      # 血不到一半，接下来两层的精英不能碰
            return P['elite_weight_hi'] * ready - P['elite_unready_penalty'] * (1 - ready) + (P['sword_of_stone_elite_bonus'] * ready if stone else 0)
        if t == 'RestSite': return P['rest_weight_low_hp'] if hpf < 0.6 else P['rest_weight']
        if t == 'Shop': return P['shop_weight_rich'] if gold >= P['shop_gold_rich'] else 0.3
        if t == 'Treasure': return P['treasure_weight']
        if t == 'Unknown': return P['unknown_weight']
        if t == 'Monster': return P['monster_weight_early'] if r < 8 else P['monster_weight_late']
        return 0.5
    memo = {}
    def best(k, elites):
        if (k, elites) in memo: return memo[(k, elites)]
        n = nodes.get(k)
        if n is None: return 0
        e2 = elites + (n.get('type') == 'Elite')
        v = w(n) - (2.5 if n.get('type') == 'Elite' and e2 > P['max_elites_per_act'] else 0)
        v += max((best((c['col'], c['row']), e2) for c in n.get('children') or []), default=0)
        memo[(k, elites)] = v
        return v
    return max(st.get('choices') or [], key=lambda c: best((c['col'], c['row']), 0))
