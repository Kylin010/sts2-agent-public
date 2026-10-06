"""战斗模型：
按源码把一场 Boss 战抽象成「回合 → 敌人招式（源码出招循环）→ 我方分配能量（进攻 / 格挡）」的小模型，动态规划求最优。
我方每回合：进攻比例 a，伤害 a × D，格挡 (1 − a) × B；D / B 来自当前牌组（全力进攻 / 全力格挡每回合多少），抽牌运气按 0.7 / 1.0 / 1.3 三档。
目标：赢的概率最大（同胜率下剩血多更好）。输出：每个状态的最优进攻比例、状态价值（期望剩血，死 = −死亡罚分）。
第一个：知识恶魔（招式完全确定、纯伤害竞赛，A10 数值见 decompiled .../Monsters/KnowledgeDemon.cs）。
"""
import functools

ALLOC = (0.0, 0.25, 0.5, 0.75, 1.0)
LUCK = ((0.7, 0.25), (1.0, 0.5), (1.3, 0.25))
DEATH = 100.0


def kd_move(t, curses_before):
    """第 t 个敌方回合（1 起）出什么：诅咒没满 3 次时 诅咒 / 拍击 / 洪流 / 沉思 循环，满了以后 拍击 / 洪流 / 沉思"""
    if curses_before < 3:
        return ('CURSE', 'SLAP', 'KO', 'PONDER')[(t - 1) % 4]
    return ('SLAP', 'KO', 'PONDER')[(t - 1) % 3]


class KDModel:
    """知识恶魔：399 血；拍击 18、洪流 9×3、沉思 13 + 回 30 + 3 力；三次诅咒（瓦解 6/7/8 每回合末掉血可格挡；心智腐烂 少抽 1；懒惰 每回合最多 3 张；衰朽 能量 −1）"""
    HP = 399
    CURVE = 0.6

    def __init__(self, D, B, hp_max, curses=('MIND_ROT', 'SLOTH', 'DISINTEGRATION'), step=3):
        self.D, self.B, self.hpmax, self.curses, self.step = D, B, hp_max, curses, step

    def factors(self, n):
        """已经吃了前 n 个诅咒：输出倍数、每回合瓦解伤害"""
        f = 1.0; dis = 0
        for i, c in enumerate(self.curses[:n]):
            if c == 'MIND_ROT': f *= 0.82
            elif c == 'SLOTH': f *= 0.85
            elif c == 'WASTE_AWAY': f *= 0.72
            elif c == 'DISINTEGRATION': dis += (6, 7, 8)[i]
        return f, dis

    @functools.lru_cache(maxsize=None)
    def V(self, t, h, e, n, s):
        """第 t 回合开始（我方先手）；h 我血、e 敌血、n 已吃诅咒数、s 敌人力量。返回 (价值, 最优进攻比例)"""
        if e <= 0: return h, 1.0
        if h <= 0: return -DEATH * (0.5 + 0.5 * min(1.0, e / self.HP)), 0.0     # 输了：离打死越近越好
        if t > 30: return -DEATH * (0.5 + 0.5 * min(1.0, e / self.HP)), 0.0
        mv = kd_move(t, n)
        f, dis = self.factors(n)
        inc = {'CURSE': 0, 'SLAP': 18 + s, 'KO': 3 * (9 + s), 'PONDER': 13 + s}[mv]
        best = None
        for a in ALLOC:
            v = 0.0
            for luck, p in LUCK:
                dmg = (a ** self.CURVE) * self.D * f * luck; blk = ((1 - a) ** self.CURVE) * self.B * f * luck   # 凹的取舍：很多牌既有伤害又有格挡
                e2 = e - dmg
                if e2 <= 0: v += p * h; continue
                left_blk = max(0.0, blk - dis); h2 = h - min(dis, blk) * 0 - max(0, dis - blk)   # 瓦解先吃格挡
                h2 = h2 - max(0.0, inc - left_blk)
                n2, s2 = n, s
                if mv == 'CURSE': n2 = n + 1
                if mv == 'PONDER': e2 = min(self.HP, e2 + 30); s2 = s + 3
                q = self.step
                v += p * self.V(t + 1, int(round(h2 / q) * q), int(round(e2 / q) * q), n2, s2)[0]
            if best is None or v > best[0]: best = (v, a)
        return best


if __name__ == '__main__':
    for D, B in ((50, 30), (42, 26), (35, 22)):
        m = KDModel(D, B, 80)
        v, a = m.V(1, 70, 399, 0, 0)
        print(f'牌组 每回合全力进攻 {D}、全力格挡 {B}，70 血进场：期望价值 {v:.1f}')
        h, e, n, s = 70, 399, 0, 0
        for t in range(1, 13):
            mv = kd_move(t, n); val, a = m.V(t, h, e, n, s)
            f, dis = m.factors(n)
            inc = {'CURSE': 0, 'SLAP': 18 + s, 'KO': 3 * (9 + s), 'PONDER': 13 + s}[mv]
            print(f'   回合 {t:2} 敌人 {mv:7} 来伤 {inc:2}  → 进攻比例 {a:.2f}（我 {h} 血 / 敌 {e}）')
            dmg = a * D * f; blk = (1 - a) * B * f
            e = e - dmg; h = h - max(0, dis - blk) - max(0, inc - max(0, blk - dis))
            if mv == 'CURSE': n += 1
            if mv == 'PONDER': e = min(399, e + 30); s += 3
            h, e = int(round(h / 3) * 3), int(round(e / 3) * 3)
            if e <= 0 or h <= 0: print('   结束', '赢' if e <= 0 else '输', h, e); break
