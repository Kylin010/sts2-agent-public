# 幽灵园丁的胆小格挡被错误插入同次多段攻击中间

结论：Skittish在整个AttackCommand结束后获得格挡，当前Foe.hit却在第一段掉血之后立刻加7盾，挡住同次攻击剩余段。默认关闭候选 `combat_skittish_after_attack` 将该盾延后，严格按源码检查本目标的**第一条**DamageResult；第一条全挡住、之后才掉血时不触发。这个修复会改变多段牌的伤害与斩杀候选，尚未测胜率。

## 源码和已完成回放

`SkittishPower.cs:56` AfterAttack、`:60` FirstOrDefault本目标的第一条结果、`:61` UnblockedDamage!=0、`:66` GainBlock。`AttackCommand.cs:669` 每段记录结果，`:672` 循环完成后才调用AfterAttack；`CreatureCmd.cs:674` 对死亡目标不给格挡。

已源码核对当前HITS表的10张多段牌，以及旋风斩、恶魔之火、扯碎、拆解：使用一个AttackCommand.WithHitCount，因此一次Foe.hit对应整组攻击。随机目标分配和重放次数仍沿用原模型，不把本补丁宣称为它们已精确。

回放修正字段后找到3个已完成双击实例：8HP伤害→8HP伤害→7格挡，以及两例5→5→7。对应原始文件SHA、事件序号、头部版本和完整事件片段在reviews/skittish-after-attack/completed-card-witnesses.json。第一次扫描将block的src错当dst，零结果保留在initial-witness-wrong-block-field.json，不用错误零结果作为缺少实局的依据。这是人类历史机制顺序核验，不是自己的新游戏或候选收益。

## 评分例子

目标30HP、0盾、胆小7，7×2双击：旧模型HP损失7、剩盾0；正确模型HP损失14、攻击结束后盾7。若目标12HP，正确模型会判斩杀，死亡不给盾；旧模型把第二段挡掉，误判还剩5HP。若初始盾7，第一段全挡住、第二段掉血7：源码FirstOrDefault检查第一条，实际不加新盾，不能改成“任何一段掉血就触发”。

13项纯检查覆盖两个条件分支、死亡、后续攻击不可重复触发、复制/peek不污染原输入、普通敌人和默认关闭一致、combat.evaluate的双击斩杀。37项现有回归过。Popen禁用，0新原生/远端/拟合。

## 仍存在的范围限制

同一候选组合中Foe会保留胆小是否触发，但每次新规划仍从能力徽章初始化；如果本回合早先真实动作已经触发过，新的初始估计可能再次加盾。当前CLI不公开这个私有bool，**不能读取HasGainedBlockThisTurn去补齐**；后续需要已完成公开动作/盾变化历史推导，缺证据时保留未知。当前补丁只修组内时序，没有声称解决所有跨实际动作记忆。

蜷身CurlUp另有AfterCardPlayed钩子，当前代码也按第一段加盾，应单独研究；不要混淆它和胆小的第一结果条件。非攻击伤害/随机目标/自动重放、死亡与其他监听造成的变化并未被本修复重新结算。

幽灵园丁主线复盘47场旧dmg均值26.8、人类赢家15.7/输家22.8见主线好坏表；旧dmg漏致死终态，不能直接把这三个数字当同口径净HP损耗或候选改善。请用新hp_metrics补完整终态，再做同种子新100/dev60配对，记录多段牌候选覆盖、真实斩杀与掉血，A1/A2及实际双Boss通关单列。

基于master7b5a3ea，候选只开combat_skittish_after_attack；默认False、不改引擎、不读真实未来。报告预期影响第一幕幽灵园丁与同能力敌人，提升多少需主线实测，不承诺百分点。

复现：`python3 reviews/skittish-after-attack/test_skittish.py`；`python3 tests/test_codex_ports.py`。
