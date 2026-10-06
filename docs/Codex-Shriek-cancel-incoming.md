# 骇鳗跨尖叫阈值后，评分仍按未被取消的攻击扣血

结论：现有combat._score只给跨线眩晕奖励，没有删除被取消的当前来伤；玩家会因旧攻击被判死亡。默认关闭 `combat_public_shriek_stun`，用可见Shriek.amount及预计实际HP损失确认眩晕，将该目标当前来伤归零，并同步到候选CV输入。没有读私有招式阶段或真实未来。

## 源码与实际已完成动作

ShriekPower.AfterDamageReceived条件为目标是拥有者、UnblockedDamage>0、当前HP<=Amount；调用CreatureCmd.Stun接TerrorState，再移除Shriek。它不要求“最大HP的一半”，也不是必须之前HP高于阈值。TerrorEel.cs的A10阈值75；TerrorState随后给99易伤，故本次眩晕不等于整场安全。

主线新100/dev60历史中，当前HP>75、攻击后仍活着且HP<=75的36个连续公开帧，全部显示来伤从正值变0。例TW01NSMQNY8J/step146：87→69，24→0；XWQUYJQAL784/step79：77→69，24→0。原始SHA和36段前后公开观察在reviews/shriek-cancel-incoming/completed-threshold-witnesses.json。后帧只核验机制，不进入前帧决策。这是36动作，不是36新增游戏或候选胜利。

## 评分错误与改动

公开例子：玩家10HP、0盾，骇鳗76HP、尖叫75、本回合攻击24；打一张6伤打击后敌人70HP，源规则立即眩晕。旧unblocked=24且left<0，导致死亡罚分；新unblocked=0，当前生命风险计算正确。原先的阈值奖励和两回合内收尾偏好继续存在，本补丁未重新调权重。

候选专用set保存预计眩晕的索引，每次_score新建，不写入共享ctx。CV的候选enemies.intent同时设0，避免规则层已取消攻击而神经网络仍预测吃24。没有真正伤害、不跨线、无徽章、未知阈值及已经死亡的目标不会新增眩晕。

13纯检查覆盖精确阈值、已在阈值下的后续正伤害、可见阈值与maxHP/2不同、缺数据、无伤害、不跨线、死亡、低血当前来伤/CV同步、候选隔离和输入不变；37现有回归通过。原ResourceWarning保留，无原生游戏或模型训练。

## 范围与主线测试

使用现有Foe预计HP损失；若实际被特殊机制减伤或复活改变HP，仍需公开模拟器核验，不能把这个函数当完整伤害引擎。狱火/药水等非攻击造成阈值眩晕的额外伤害分配不在本补丁内。后续“恐吓→易伤后的攻击”的FUT尚未重建；本修复只确保被取消的**当前**攻击不再产生死亡惩罚，不宣称整场风险已精确。

基于master7b5a3ea，默认False。主线新100/dev60同种子单开本flag，记录跨线候选/实际选择、眩晕回合多余格挡、当前掉血、两回合收尾、A1/A2和双Boss完整胜利。使用完整hp_metrics与人类DamageTaken合理对齐，不用旧漏终态dmg冒充净损耗或增胜。尚无可承诺的提升百分点。

运行：python3 reviews/shriek-cancel-incoming/test_shriek.py；python3 tests/test_codex_ports.py。
