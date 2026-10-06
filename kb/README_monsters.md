# 怪物 / 遭遇知识库（monsters.json、encounters_src.json）

从《杀戮尖塔2》**v0.111.0** 反编译源码自动提取，给自动打牌程序查「怪有多少血、下一招打多少、会不会塞状态牌、什么时候变身」。

| 文件 | 作用 |
|---|---|
| `kb/monsters.json` | 全部 120 个怪物（键 = 怪物 id），外加 `_meta` |
| `kb/encounters_src.json` | 全部 90 个遭遇（键 = 遭遇 id），外加 `_meta` |
| `kb/overrides/monsters_manual.json` | 手工补丁：所有怪的中文 notes / tags，以及自动解析不准的少数招式 |
| `tools/extract_monsters.py` | 生成脚本（只用 Python 标准库） |

## 怎么重新生成

```bash
cd /opt/slay-the-spire-2/agent
python3 tools/extract_monsters.py            # 读源码 + 合并手工补丁，写 kb/monsters.json 和 kb/encounters_src.json
python3 tools/extract_monsters.py --check    # 只解析、打印数量，不写文件
python3 tools/extract_monsters.py --out DIR  # 写到别的目录（改脚本时先输出到临时目录对比）
```

原理：脚本用正则找出每个怪物类的属性（`XxxDamage => AscensionHelper.GetValueIfAscension(...)`）、
`GenerateMoveStateMachine()` 里的状态机（`MoveState` / `RandomBranchState` / `ConditionalBranchState`
和 `FollowUpState`、`AddBranch`、`AddState`），再逐句扫描每个招式方法体里的 `DamageCmd.Attack`、
`PowerCmd.Apply<X>`、`CardPileCmd.AddToCombatAndPreview<X>`、`CreatureCmd.Add<X>` 等命令。
数值表达式交给一个很小的求值器：进阶判断 `HasAscension(level)` 就是「当前进阶 ≥ 该等级号」，
所以分别按进阶 0 和进阶 10 各算一遍，得到 `a0` / `a10`。最后把 `overrides/monsters_manual.json` 深度合并进去
（字典逐层合并、列表整体替换，手工值优先）。

源码换版本时：改脚本顶部的 `SRC` / `GAME_VERSION`，重跑，看打印的 `parse_errors` 和下面「检查」一节。

## 进阶等级

`AscensionLevel` 枚举（`_meta.ascension.levels`）：SwarmingElites=1 … ToughEnemies=**8**、DeadlyEnemies=**9**、DoubleBoss=10。
怪物文件里只用到两个：

- **ToughEnemies（8）**：主要是血量，少数怪的格挡/覆甲/开局能力（如墨影幻灵的滑溜 8→9）。
- **DeadlyEnemies（9）**：主要是伤害，少数怪的力量成长/仪式/状态牌数量。

进阶 10 包含 1~10 全部，所以 `a10` = 两个都生效；`a0` = 都不生效。

## 数值格式

所有数值统一写成：

```json
{"a0": 8, "a10": 9}                         // 普通 / 进阶10
{"a0": 3, "a10": 4, "dynamic": true, "formula": "..."}  // 会随战斗变化：a0/a10 是初始值，formula 说明怎么变
"13 + base.Creature.GetPowerAmount<...>()"  // 极少数完全算不出来的写成字符串公式
```

`hp` 是 `{"a0": [最小, 最大], "a10": [最小, 最大]}`（开局在区间里随机）。
**伤害都是基础值**，不含力量、虚弱、易伤、活力等加成（sts2-cli 输出的 intent 伤害是加成后的）。

## monsters.json 每个怪的字段

| 字段 | 含义 |
|---|---|
| `id` | 游戏内 `Id.Entry`（类名转大写下划线，如 `KinPriest` → `KIN_PRIEST`） |
| `class` / `file` | 源码类名 / 文件 |
| `name` / `name_zh` | 英文名 / 中文名（来自 sts2-cli 的 localization）。**sts2-cli 输出敌人时只给名字不给 id**，用名字对回来 |
| `inherits` | 继承的父类怪（神秘骑士 ← 连枷骑士，千足虫三节 ← 抽象基类） |
| `category` | `enemy`（会作为遭遇开局成员出现）/ `summon`（只会被召唤出来）/ `event`（只在事件战斗里）/ `test` / `pet` / `unused` |
| `tags` | 手工标签，见下表 |
| `hp` | 见上 |
| `hp_phases` | 多条命的怪每条命的血量（实验体） |
| `start_powers` | 开局（`AfterAddedToRoom`）挂在自己身上的能力：`power`（类名）、`amount`、可选 `power_target`（能力挂在怪身上但作用于玩家，如凋萎存在、偷窃、沙坑）、`when`（条件） |
| `start_effects` | 开局的其他效果（给玩家挂「遭到包围」、开局格挡等） |
| `moves` | 招式表，键 = 招式 id（就是 `MoveState` 的 id，与游戏日志里 `performing move XXX` 一致） |
| `branches` | 分支状态（不是招式，只决定下一招） |
| `initial` | 第一回合所处的状态 id（可能是分支 id，要再按分支解一层） |
| `initial_options` | 起手招取决于配置/站位时的全部可能 `[{state, when:[条件]}]`；具体某个遭遇里的起手招已经算好写在 `encounters_src.json` 的 `initial_move` |
| `forced_moves` | 被代码强制插入的招式（眩晕、复活、死亡、将爆…）：`id`、`intents`、`trigger`（触发条件）、`then`（之后去哪）。手工整理 |
| `hooks` | 源码里覆写的钩子名（给人看，说明这个怪有额外机制，机制本身写在 notes） |
| `notes` | 中文机制说明（手写，打法要点都在这） |
| `encounters` / `acts` | 出现在哪些遭遇 / 哪几幕（1=密林或暗港，2=蜂巢，3=荣耀） |
| `spawns` / `spawned_by` | 召唤关系（包括死亡时召唤，如地精佣兵、异蛙寄生虫、巨斧机器人） |
| `manual` | 这个怪有哪些字段来自手工补丁 |

### moves.<招式 id>

```json
"ORB_OF_FRAILTY_MOVE": {
  "name": "Orb of Frailty", "name_zh": "脆弱法球",
  "intents": [{"type": "attack", "cli_type": "Attack", "damage": {"a0":8,"a10":9}, "hits": 1},
              {"type": "debuff", "cli_type": "Debuff"}],
  "effects": [{"kind": "attack", "damage": {"a0":8,"a10":9}, "hits": 1, "target": "player"},
              {"kind": "apply_power", "power": "FrailPower", "target": "player", "amount": {"a0":1,"a10":1}}],
  "perform": "OrbOfFrailtyMove",
  "next": "ORB_OF_WEAKNESS_MOVE"
}
```

- `intents`：玩家能看到的意图。`type` ∈ attack / death_blow / buff / debuff / debuff_strong / defend / escape / heal / hidden / summon / sleep / stun / status / card_debuff / unknown；
  `cli_type` 是 sts2-cli 输出里 `intents[].type` 的原样字符串（Attack、StatusCard、DebuffStrong…）。攻击类带 `damage`、`hits`；status 带 `count`（塞几张牌）。
- `effects`：招式实际做的事（按源码执行顺序）。`kind`：
  - `attack`：`damage`、`hits`、`target`
  - `apply_power`：`power`（能力类名，含 `Power` 后缀）、`target`、`amount`（负数 = 减益，如 -2 力量）、可选 `power_target`
  - `remove_power`：`power`、`target`
  - `block`：`target`、`amount`
  - `add_card`：`card`（卡牌类名）、`pile`（discard / draw / hand）、`count`、可选 `position: random`、`to`
  - `summon`：`monster` 或 `one_of`、`count`
  - `heal` / `set_hp` / `set_max_hp`：`target`、`amount`
  - `escape`（逃跑）、`suicide`（自毁）、`stun_self`、`steal_card`（偷牌）、`steal_gold`（偷金币）、`player_choose_card`、`reattach`（千足虫接回）、`upgrade_cards`、`force_move`
  - 通用可选字段：`when`（条件，原样 C# 表达式或中文）、`times` / `per`（循环）
- `target` 取值：`player`、`self`、`allies_incl_self`（含自己的所有敌人）、`allies_excl_self`、`ally:<怪物id>`、`summoned`（刚召唤出来的那只）。
- `next`：这招之后进入的状态 id（招式或分支）；`null` 表示没有后续（如气态炸弹自爆后就死了）。
- `must_perform_once`：这招一定会执行一次才能切走（眩晕、复活类）。
- `special_entry: true`：正常循环走不到，只会被代码强制切进来（眩晕、死亡、复活、千足虫的死亡/接回、瀑布巨兽的爆炸）。

### branches.<分支 id>

```json
"RAND": {"kind": "random", "options": [
  {"move": "SKITTER_MOVE", "weight": 1, "repeat": "CannotRepeat", "cannot_repeat": true, "max_consecutive": 1, "cooldown": 0}, ...]}
"INIT_MOVE": {"kind": "conditional", "conditions": [{"move": "SKITTER_MOVE", "when": "base.Creature.SlotName == \"first\""}, ...]}
```

随机分支的规则（`RandomBranchState.GetStateWeight`，判断依据是这只怪自己的出招记录）：

- `CanRepeatForever`：随便重复。
- `CannotRepeat`（`cannot_repeat: true`）：上一招是它就不能选。
- `CanRepeatXTimes`（`max_times` = `max_consecutive` = N）：最近 N 招都是它就不能选。
- `UseOnlyOnce`（`use_only_once: true`）：整场用过就不能再选。
- `cooldown` = N：最近 N 招里出现过就不能选。
- 剩下的按 `weight` 加权随机；`weight` 是字符串时是依赖战况的公式（如双尾鼠的呼叫支援）。

条件分支按顺序取第一个成立的 `when`。`unused: true` 的分支在源码里定义了但走不到。

## encounters_src.json 每个遭遇的字段

| 字段 | 含义 |
|---|---|
| `id` | 游戏内遭遇 id（如 `THE_KIN_BOSS`、`FABRICATOR_NORMAL`，sts2-cli 的 `context.encounter` / `enter_room` 用的就是它） |
| `name` / `name_zh` | 遭遇名 |
| `room_type` | `Monster` / `Elite` / `Boss` |
| `is_weak` | 是否「弱遭遇」（每幕开头几场从弱遭遇池里出） |
| `act` / `act_names` | 第几幕；`Overgrowth`(密林) 和 `Underdocks`(暗港) 都是第 1 幕的两种版本，`Hive`=2，`Glory`=3 |
| `in_act_pool` | 是否在某一幕的遭遇池里（`false` = 事件战斗或当前版本不会遇到） |
| `event` / `event_shared` | 事件战斗对应的事件类；`event_shared` = 共享事件（任意幕） |
| `slots` | 站位名列表（召唤会填空位） |
| `tags` | 源码里的 `EncounterTag`（同一 tag 的遭遇不会连着出） |
| `possible_monsters` | 这场战斗里可能出现的全部怪（含召唤物） |
| `random_composition` | 开局成员 / 起手招是否随机 |
| `monsters` | 开局成员：`monster`（id）、`slot`、`config`（遭遇给这只怪设的参数，如 `StartsWithDance`）、`initial_move`（该站位/配置下第一回合的状态；`random` = 随机轮换）。随机挑选的成员写成 `one_of: [...]` 或 `one_of_groups: [[...], ...]` + `group_weights` |
| `notes` | 中文说明 |

## tags 词表（monsters.json）

| tag | 含义 |
|---|---|
| boss / elite / event / test / pet / unused | 身份 |
| minion | 爪牙：首领（最后一个非爪牙敌人）死了它就跟着死，打它不能结束战斗 |
| summoner / illusion | 会召唤 / 幻象（死后下回合满血复活，爪牙） |
| revives / multi_body / transforms | 会复活或多条命 / 多节身体要一起打死 / 会变形（卵孵化） |
| death_trigger / self_destruct | 死亡时触发效果 / 会自爆 |
| scaling / scaling_dot | 力量或伤害随回合增长 / 持续伤害越叠越高 |
| adds_status | 往你牌堆塞状态牌 |
| permanent_player_debuff / steals_stats / max_hp_loss | 给你整场负面 / 偷你力量敏捷 / 扣你最大生命 |
| card_restriction | 限制出牌（昏眩、魂缚、烟雾、缠结、虚无、降级…） |
| punishes_skills / punishes_powers / punishes_card_count / punishes_multi_hit | 打技能 / 能力 / 每多打一张牌 / 多段攻击会被惩罚 |
| rewards_card_count | 本回合打得越多它越疼（旧日雕像的缓慢） |
| damage_cap / damage_reduction | 单次/单回合伤害上限（难以杀灭、硬化外壳、滑溜、无实体）/ 减伤（翱翔、振翅） |
| hp_threshold | 跨血线触发（眩晕、清力量、大招） |
| sleeps | 开局睡觉 |
| escapes / steals_card / steals_gold / timer / doom_timer | 会逃跑 / 偷牌 / 偷钱 / 有回合时限 / 倒计时到就秒杀你（沙坑） |
| thorns / artifact / heals / protector / back_attack / enrage_on_ally_death | 反伤 / 人工制品 / 回血 / 给同伴格挡 / 背后攻击×1.5 / 同伴死后暴怒 |
| stun_if_fully_blocked / block_break_stun | 攻击被全挡就眩晕 / 格挡被打穿就眩晕 |
| glass_cannon / multi_hit / debuffer | 血少伤害高 / 多段攻击 / 主要给减益 |

## `_meta`

- `monsters.json._meta.powers`：所有出现过的能力的中英文名、描述（本地化原文，`{Amount}` 等占位符没替换）、Buff/Debuff、叠加方式。
- `monsters.json._meta.cards`：怪物塞给你的状态牌（费用、关键词、回合结束在手里的伤害）。
- `skipped_classes`：没输出的抽象类（`DecimillipedeSegment`、`BattlewornDummyEventEncounter`）。

## 哪些是手工补的

所有怪的 `notes` 和 `tags` 都是手写的（读源码 + 能力源码后总结）。下面这些怪的结构化字段也有手工覆盖（`manual` 字段里能看到）：

| 怪 | 手工覆盖了什么 | 原因 |
|---|---|---|
| FABRICATOR | 两个召唤招的 `effects`、`spawns` | 召唤目标是从静态集合里随机挑的，正则拿不到 |
| THE_INSATIABLE | 液化地面的 `effects` | 6 张狂乱逃离是 `for` 循环 + 三元表达式分配牌堆（3 张抽牌堆、3 张弃牌堆） |
| TOUGH_EGG | `start_powers`、`start_effects`、孵化的 `effects` | 孵化倒计时取决于产卵时机；孵化后血量是随机区间 |
| WATERFALL_GIANT | 压力枪、爆炸的 `intents`/`effects` | 伤害存在可变字段里（压力枪每次 +5；爆炸 = 被打死时的蒸汽层数） |
| TEST_SUBJECT | 复活的 `effects`、多重爪击段数、`hp_phases` | 复活血量通过带参数的 helper 传进去；爪击段数每次 +1 |
| AEONGLASS | 愈发强烈的 `effects` | 力量每次 +1、凋萎升级 |
| AXEBOT | 启动的 `effects` | 力量 = 3/4 × 已替换次数，原始那台为 0 |
| THE_FORGOTTEN | 恐惧的伤害 | = 13/15 + 自身当前敏捷 |
| KNOWLEDGE_DEMON | 知识诅咒的 `effects` | 三次二选一的具体选项 |
| MAGI_KNIGHT | 抑制的条件 | 只在玩家还没有抑制时施加 |
| LIVING_FOG | 膨胀的 `effects` | 召唤次数是可变字段（实际恒为 1） |

遭遇里 `BOWLBUGS_*`、`FLYCONID_NORMAL`、`RUBY_RAIDERS_NORMAL`、`SLIMES_*`、`SLITHERING_STRANGLER_NORMAL`、
`DENSE_VEGETATION_EVENT_ENCOUNTER` 的 `monsters` 是手写的（成员由 `base.Rng` 随机挑选或在 `foreach` 里生成），
其余遭遇的 `notes` 也是手写的。

## 已知不完美的地方

1. **伤害是基础值**：力量、虚弱、易伤、活力、缩小、背后攻击×1.5、污染等加成都不在里面，要自己按当前能力算（或直接用 sts2-cli 给的 intent 伤害）。
2. **可变状态只给初始值**：带 `dynamic: true` 的值会随战斗变化（如巨斧机器人库存、压力枪），看 `formula` 和 notes。
3. **条件写的是 C# 原文**：`when` / 分支 `conditions[].when` 是源码表达式（如 `HasBeetleCharged || base.Creature.CurrentHp >= base.Creature.MaxHp / 2`），需要人看或自己翻译；重要的条件在 notes 里有中文。
4. **眩晕不在状态机里**：被眩晕（打穿埋地、失衡、横冲直撞血线、尖叫血线、振翅、熟睡被吵醒、饥饿吃尸体）时，游戏临时插入一个 id 为 `STUNNED` 的招式（意图 Stun），执行完进入 `CreatureCmd.Stun(..., nextMoveId)` 指定的招式（没指定就重复眩晕前最后执行的那招）。
   这些情况手工整理在怪物的 `forced_moves` 字段：`[{id, intents, trigger, then}]`；幻象复活（`REVIVE_MOVE`）、千足虫死亡/接回、实验体复活、瀑布巨兽将爆、女王暴怒也在里面。
   注意仪式兽/骇鳗状态机里的 `STUN_MOVE`、地道虫的 `DIZZY_MOVE` 只是给图鉴用的，实战走的是 `STUNNED`。
5. **能力的具体结算**（滑溜减到 1、硬化外壳上限、沙坑倒计时等）只在 notes 和 `_meta.powers` 的描述里，没有做成结构化字段。
6. **多人缩放没管**：血量、部分能力层数在多人时会缩放，这里全部按单人。
7. `name_zh` 来自 sts2-cli 仓库里的本地化文件，实验体的名字带 `{Count}` 占位符（游戏里会显示编号）。
8. 源码里定义了但走不到的东西已标出：旧日雕像 `SLEEP_MOVE_2`、墨宝 `INIT_RAND`、异蛙寄生虫 `RAND`（`special_entry` / `unused`）；`TUNNELER_NORMAL` 遭遇和三个 `THE_ADVERSARY_MK_*` 怪不在任何一幕的池子里。

## 检查

改脚本或换版本后至少确认：

- 输出的 `parse_errors=[]`；
- 每个攻击意图都能在 `effects` 里找到同样伤害、同样段数的 `attack`（脚本作者用一段临时脚本对全部 120 个怪核对过，除手工写成中文公式的 2 处外全部一致）；
- 抽查：KIN_PRIEST、CEREMONIAL_BEAST、VANTOM、FABRICATOR、SLIMED_BERSERKER、BYGONE_EFFIGY、FUZZY_WURM_CRAWLER 已逐项对照源码确认（血量、各招伤害/段数、减益、力量、状态牌、循环顺序、起手招）。
