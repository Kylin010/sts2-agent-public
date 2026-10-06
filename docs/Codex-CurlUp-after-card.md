# 蜷身格挡应在卡牌结算后获得；全格挡仍可触发

结论：当前Foe.hit在第一段掉血后立刻加蜷身盾，挡掉同张多段牌的其余段；全格挡时又完全不触发。源码CurlUpPower先记录攻击卡，AfterCardPlayed才加盾并移除。默认关 `combat_curl_after_card` 修正这两点，沿用当前Foe的一组hit对应一张卡牌的范围，未测胜率。

## 完整触发链

CurlUpPower.AfterDamageReceived要求本目标、IsPoweredAttack、cardSource非空，**没有UnblockedDamage>0条件**。CreatureCmd.Damage的第一遍结果循环对WasFullyBlocked使用continue，但后面第二遍results循环仍在存活目标调用Hook.AfterDamageReceived（:416），因此全格挡不会阻断CurlUp。

我此前交接写“全挡住不调用AfterDamageReceived”只读到了前一段循环，是错误判断；这里明确更正，原交接作为失败/阴性证据保留，不继续执行它。SourceCurl确实标记同一张卡，AfterCardPlayed才GainBlock，随后移除能力；死亡目标GainBlock不生效。

## 已完成公开回放与纯例子

扫描1050个历史回放，在v0.111.0/单人A10铁甲样本找到：痛击hit dmg0/blocked9，随后施加易伤，再block18。原始文件SHA、事件序号和头部在reviews/curl-up-after-card/completed-curl-witnesses.json。不是自己新正常对局、不是No-SL认证，也不是候选提升胜率。

纯公开例子：虱子母体90HP、蜷身18，双击7×2。旧HP损失7/剩盾11；正确HP损失14/卡末盾18。初始20盾，两段7全部挡住：正确剩原盾6+蜷身18=24。若目标12HP，应被双击斩杀且不给盾，旧估计误判仍活着。

13项纯检查覆盖完整多段、全部/部分格挡、死亡、后续卡不重复触发、复制/peek、默认关闭、普通目标不变和combat.evaluate斩杀；37旧回归通过。无引擎启动、无模型拟合、无远端任务。

## 边界

候选只针对当前预测的正per-hit卡攻击及正段数。预览0可能来自原始0伤害或伤害修正至0，CreatureCmd.Damage原始amount0有早返回，与修正后0不同；当前输入/方法没有编码这一区别，保持旧估计，不把它称已确定或已完整实现。随机目标、自动重放、同卡多个独立命令与其他监听继续需要核对。

与Skittish不同：胆小AfterAttack检查本目标第一条结果是否掉血；蜷身AfterCardPlayed不要求第一条掉血，且完全格挡仍能触发。不要把两个条件合并成“任何反应盾都在第一段掉血后触发”。当前胆小和蜷身两个分支都改enemy_powers.hit，主线合入需同时保留两个开关的独立行为。

## 主线评测

基于最新master414d7f2，默认False，只开combat_curl_after_card用新100/dev60配对，记录虱子母体/蜷身敌人的多段候选、斩杀、全格挡触发及完整hp_metrics。第一幕/第二幕推进及实际双Boss通关分别报告，胜率提升需真实结果，不承诺百分点。

复现：python3 reviews/curl-up-after-card/test_curl.py；python3 tests/test_codex_ports.py。
