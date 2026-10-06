# 族母：用可见睡眠层数区分准备回合与提前唤醒

结论：旧 foresight 对 SLEEP_BRANCH 平均分配「继续睡」与「斩击」，即使玩家能看到睡眠3/2/1层。CV候选又复用根局面的同一个fut，使不打穿格挡与提前叫醒的未来成本相同。默认关闭的 `foresight_public_matriarch_sleep` 将这两点改为源码固定时序，接入 foresight、CV候选和 mentalmodel；未证明提高胜率。

## 确认的时序

- AsleepPower.cs:21：只有 result.UnblockedDamage != 0 才移除Plating、眩晕并指定SLASH_MOVE、移除Asleep。全格挡不叫醒。
- AsleepPower.cs:46 / CombatManager.cs:1691、1699：敌方回合末才扣一层。
- CombatManager.cs:688、743 / Creature.cs:547：下一玩家回合开始才RollMove，因此新的可见层数决定睡眠分支。
- LagavulinMatriarch.cs:160：自然醒后斩击→开膛→斩击二→汲取→斩击；汲取敌方+2力量、我方-2力量/-2敏捷，:234。
- Creature.StunInternal:525：指定后续招不同于一般眩晕默认回到上次招。Whistle.cs:33确实调用一般眩晕，故本次**不根据通用Stun图标认定是Asleep唤醒**。最初纯模型把两者等同，经全项目Stun调用检查已收窄；旧纯日志保留为开发阶段证据。

只列源码A10基础来伤、当前力量0，未加我方易伤等修正，从「当前显示敌方回合之后」起：

| 当前可见睡眠 | 未造成HP伤害 | 候选造成正HP伤害、目标仍活着 |
|---|---|---|
| 3 | 0、0、21、20、14、0 | 21、20、14、0、23、24 |
| 2 | 0、21、20、14、0、23 | 同上 |
| 1 | 21、20、14、0、23、24 | 同上 |

提前叫醒不增加免费回合：本回合敌人从Sleep变Stun，本来就不会攻击；损失的是剩余Sleep回合。最后一层时叫醒与自然醒的未来攻击节奏相同。它依然可能因大爆发/斩杀/强能力先铺完而值得早醒，所以不新增一律禁攻击规则。

## 小函数与评分

`policy/public_matriarch.future_moves(enemy, turns, projected_hp_damage=0)` 只读敌人名、可见Sleep意图、ASLEEP_POWER的整数1~3层及当前候选的HP伤害。重复/矛盾/缺失层数或通用Stun返回None，绝不读原生move_id、下一招、RNG或round私有计数。

`foresight.future` 用这一序列替代平均条件分支，沿用原来的力量成长计算。`combat._score` 对每个CV候选按预计HP伤害更新fut；mentalmodel同样为每个叫醒候选重算schedule，候选间互不改变观察或根schedule。睡眠3时，三个后续回合平均来伤由旧13.458改为未叫醒7、叫醒18.333（基础/当前Strength0）。只影响上述状态；参数默认False。

## 回放与好坏样本

扫描1050个回放，按v0.111.0/单人标准A10铁甲、未弃局、无记录resume/attempt>0/reloads筛选，并要求战斗结束或同场终局死亡：31场族母，整局赢家14、整局输家17，其中族母当场死亡7。整局输家不等于这场Boss失败。

保存自然三次Sleep→Slash，以及Sleep/Sleep/Stun→Slash的源码时序见证，种子PGHBNZEGGCUN、WQH77HEWKEQF；原压缩文件SHA与过滤后的公开事件在 `reviews/matriarch-public-sleep/completed-sleep-witnesses.json`。仅2/31场含本次匹配的显式intent时间；其余None是缺观测，**不能从稀疏move序列做提前唤醒胜率比较**。

最初错误筛选attempt_id=1，得到22场非严格子集；保留 `initial-attempt1-excluded.json`、初版history-audit.log，不用于赢家/输家结论。最终脚本用全文件resume/attempt/reloads排除，另外14场截断或非死亡退出单列。这是历史研究证据，不是自己新的正常No-SL资格或改动收益。

主线旧fresh100中14次族母遭遇、11存活；dev60中10次、9存活（到第二幕/完整胜利来判断Boss存活）。这是影响面，不能承诺改变多少局。统计与源SHA在mainline-encounter-counts.json；最初不存在encounter字段的0结果已明确不采用。

## 验证与剩余限制

17项纯检查通过：3/2/1层、HP正伤/全格挡、力量循环、根CV、候选CV 7→18.333→7无泄漏、mental schedule对齐、输入不变、私有字段无影响、缺失/矛盾回退、Stun歧义回退与默认关旧值。37项旧回归通过，禁止Popen引擎启动。源码SHA及行号另存source-pins.json。

没有实现Plating未来盾的完整生命周期、我方汲取后输出/格挡衰减、药水或额外无源卡伤害的叫醒分配、独立普通Stun的已完成历史推导，也没有重提取/拟合人类CV。旧CV的fut分布与新规则不同，主线应先单开本flag做同种子整局检验；价值网络训练由原owner处理。当前未来伤害沿用KB A10基础攻击与Strength，不能称包含所有易伤/虚弱/遗物修正的精确实际HP损失。

基于master414d7f2交付，建议新100/dev60配对：记录睡眠层数、候选HP伤害、叫醒时机、战损hp_metrics、A1/A2与真正完整通关；失败结果照留。自己的新原生游戏、远端、拟合均0。

复现：`python3 reviews/matriarch-public-sleep/test_sleep.py`；`python3 tests/test_codex_ports.py`。
