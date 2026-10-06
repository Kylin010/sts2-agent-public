"""敌人身上的能力 → 战斗规划要用的修正（通用：哪个怪带了这个能力都按同样的规则算，不用逐个遭遇写）。

能力名用引擎给的英文标题（小写匹配）。说明来自游戏本地化文本（v0.111.0）：
  Slippery 滑溜 N      接下来 N 次掉血，每次只掉 1
  Artifact 人工制品 N  抵消 N 次减益（易伤 / 虚弱白给）
  Hardened Shell 坚硬外壳 N  每回合最多掉 N 血
  Hard to Kill 难以杀死 N    每次伤害最多 N
  Curl Up 蜷缩 N       第一次受伤后得 N 格挡（每场一次）
  Skittish 胆怯 N      每回合第一次被打得 N 格挡
  Illusion / Adaptable / Reattach   死了会复活：打死它不太值
  Slow 迟缓            这回合每出一张牌，它受到的攻击伤害 +10%
  Enrage 激怒 N        每打出一张技能牌，它 +N 力量
  Personal Hive 私人蜂巢   每被攻击一次，往抽牌堆塞一张晕眩
  Imbalanced 失衡      攻击被完全挡住就晕一回合
  Suck 吸取 / Paper Cuts 纸割   打穿格挡时它加力量 / 我掉最大生命：格挡更重要
  Crab Rage 螃蟹之怒   队友死了它 +5 力量、+99 格挡
  Shriek 尖啸          第一次降到半血以下时晕一回合
  Sandpit 沙坑（挂在无厌沙虫身上）  敌方回合开始 -1，归零玩家直接死；每打一张狂乱逃离 +1（那张牌之后 +1 费）
  Reattach 重组（千足虫）  一节死了、别的节还活着，就两回合后带 25 血接回来：先把几节一起压低，能两回合内收完再打死
  Burrowed 钻地        格挡不会在它回合开始时消失；格挡被全部打掉就眩晕（地道虫）
"""
from params import P
from policy.knowledge import is_attack_intent


def amt(e, word):
    for p in e.get('powers') or []:
        if word in str(p.get('name', '')).lower(): return p.get('amount') or 1
    return 0


class Foe:
    """规划一组牌时，单个敌人的「剩余状态」：格挡、滑溜层数、蜷缩是否已触发、本回合已掉血（坚硬外壳）"""
    __slots__ = ('e', 'blk', 'slip', 'curl', 'skit', 'shell', 'lost', 'cap', 'stripped')

    def __init__(self, e):
        self.e = e
        self.blk = e.get('block') or 0
        self.slip = amt(e, 'slippery')
        self.curl = amt(e, 'curl up')
        self.skit = amt(e, 'skittish')
        self.shell = amt(e, 'hardened shell') or None
        self.cap = amt(e, 'hard to kill') or None
        self.lost = 0
        self.stripped = 0

    def copy(self):
        f = Foe.__new__(Foe)
        for k in Foe.__slots__: setattr(f, k, getattr(self, k))
        return f

    def hit(self, per_hit, hits):
        """打 hits 段、每段 per_hit 伤害，返回「敌人有效生命（血 + 格挡）减少了多少」，并更新状态"""
        total = 0
        delayed_skit = P.get('combat_skittish_after_attack', False)
        first_unblocked = False
        delayed_curl = P.get('combat_curl_after_card', False)
        curl_card_hit = delayed_curl and self.curl and per_hit > 0 and int(hits) > 0
        for hit_index in range(int(hits)):
            x = per_hit
            if self.cap: x = min(x, self.cap)
            if self.blk >= x:
                self.blk -= x; total += x; continue
            total += self.blk; x -= self.blk; self.blk = 0
            if x <= 0: continue
            if self.slip > 0:
                x = 1; self.slip -= 1; self.stripped += 1
            if self.shell is not None:
                x = max(0, min(x, self.shell - self.lost))
            if hit_index == 0 and x > 0: first_unblocked = True
            self.lost += x; total += x
            if self.curl and x > 0 and not delayed_curl:
                self.blk += self.curl; self.curl = 0
            if self.skit and x > 0 and not delayed_skit:
                self.blk += self.skit; self.skit = 0
        if delayed_skit and self.skit and first_unblocked:
            # Skittish.AfterAttack examines the first result for this enemy,
            # then gains block after the entire attack command resolves.
            # GainBlock ignores dead creatures. Missing HP retains old scope.
            ehp = self.e.get('hp')
            if ehp is None or self.lost < ehp: self.blk += self.skit
            self.skit = 0
        if curl_card_hit:
            # CreatureCmd still emits AfterDamageReceived for fully blocked
            # powered card hits. CurlUp waits for AfterCardPlayed to grant block.
            hp = self.e.get('hp')
            if hp is None or self.lost < hp: self.blk += self.curl
            self.curl = 0
        return total

    def peek(self, per_hit, hits):
        return self.copy().hit(per_hit, hits)


def revives(e):
    return any(amt(e, w) for w in ('illusion', 'adaptable', 'reattach'))


def debuff_blocked(e):
    return amt(e, 'artifact') > 0


def slow_mult(e, n_before):
    return 1 + 0.1 * n_before if amt(e, 'slow') else 1


def block_priority(enemies):
    return P['suck_block_priority'] if any(amt(e, 'suck') or amt(e, 'paper cuts') for e in enemies) else 1


def skill_strength(enemies):
    """激怒：每张技能让它加多少力量（× 它这回合的攻击段数，近似成多挨的伤害）"""
    tot = 0
    for e in enemies:
        n = amt(e, 'enrage')
        if n:
            hits = sum(max(it.get('hits') or 1, 1) for it in e.get('intents') or [] if is_attack_intent(it))
            tot += n * max(hits, 1)
    return tot


def shriek_stuns_after_damage(e, predicted_hp_loss):
    """Source Shriek: positive HP damage, surviving target at/below visible amount.

    Never use max-HP/2 or a hidden phase/count to replace the public threshold.
    """
    threshold = next((power.get('amount') for power in e.get('powers') or []
                      if str(power.get('id', '')).split('.')[-1] == 'SHRIEK_POWER'
                      or 'shriek' in str(power.get('name', '')).lower()), None)
    hp = e.get('hp')
    if (type(threshold) is not int or threshold <= 0
            or type(hp) not in (int, float) or type(predicted_hp_loss) not in (int, float)):
        return False
    return predicted_hp_loss > 0 and 0 < hp - predicted_hp_loss <= threshold
