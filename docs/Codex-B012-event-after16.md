# 事件兼容：补丁16后的独立增量（WIP）

B012源于后台缺少音效、震屏、肖像和水晶球界面；原生callback在中途失败，不能按普通玩家完成事件。候选只替换对应纯表现调用并实现公开水晶球点击，保留原生卡牌、金钱、奖励、战斗、随机过程。真实异常/超时仍锁存技术错误；禁止强制结束或离开未完成事件。

`patches/codex-event-ui-and-task-inputs-diff-since-16.patch` 是实际16后增量。16的商店等待/回执、E02 GetSelectedCards源码保持逐字一致；事件/选项名称诊断保留。无需重用15后旧B012、E02或B017增量。普通开局B018是独立补丁，本增量有无B018均可应用；有无可选12均可应用，不能据此宣布双Boss奖励已认证。数字编号交Claude分配，未部署他的任务。

本分支基于master12416d1，包含B019未完成事件的policy边界修复作为依赖（原交付b0ba68b、这里cherry-pick为7c34ea9）。Claude已合B019时可只cherry-pick本主题的新提交。`event_ui_fixed`默认False；只在候选SDK工程验证时显式True。尚未完成全部正常覆盖，不默认解除黑名单，也不引用旧跳事件成绩。

## 新实际正常前缀

8次正常从头工程前缀已全部闭合：三个已知合法native种子×控制/候选，加候选两次明确重复。控制为16+B018，候选为16+B012+B018；正常64/80、一次Start、当前UI、No-SL，禁止原生存读档/set/进房或未来RNG。其余策略、GameDLL及helper冻结，目标只有公开选项出现且可用才按当前index选择，不重放历史动作。

- 控制3/3在真实目标产生EVENT_FAULT：两个PunchOff.Nab为空引用，CrystalSphere.PaymentPlan缺Vector2I.One。原技术分母保留。
- 候选5/5目标流程完成、技术0。三个Nab（一个明确重复）各加1张Injury、获1遗物并正常回map；两个PaymentPlan（一个明确重复）各加1张Debt、完成6次公开点击，真实card_reward选BattleTrance并加入牌组后回map。
- 三组控制/候选直到目标选择的整条公开states/commands完全一致；两候选重复全轨迹一致。8次正常/public/seed echo/UI审计与源文件冻结通过，0雾下Item导出。没有完整胜利，不是共同s120、fresh策略增益或独立连胜。

12纯事件/selector、4纯context、8纯表现/公开grid检查及候选编译通过；这些检查不加载游戏程序集、不提供额外真实奖励样本。patch链实际apply与source一致已核。初次预检whole-selector equality断言过宽（B012合法扩展其他selector方法），0-game失败保留，改核E02实际GetSelectedCards逐字一致。奖励审计v1覆盖了整条前缀，v2限定目标事件；原native轨迹未变。

Python移植首次预检错用supported变量名（当前主线为ok），中止在events修改之前；后面的纯检查只验证了当时部分移植，不作为最终集成通过证据。0native，记录保留；最终集成检查另存v2。

跨版本正常选项覆盖由3/8增至7/8：Dense.Rest、Jungle.Join、Crystal.Future为之前SDK记录，实际16后验证Nab、PaymentPlan、Amalg.CombineStrikes及CombineDefends。Trial.Accept仍未从正常开局走到并完成；不能标B012全修完。本次只有PaymentPlan暴露了真实奖励选牌，其余奖励机制/分支不能据纯fixture推定全部正确。

证据：`/opt/slay-the-spire-2/codex-agent/collaboration/reviews/headless-event-after16-v1/`中的normal-plan-v1.json、normal-summary-v1.json、normal-audit-v2.json、原始8条gzip轨迹、构建/24纯检查日志和patch-chain-v1.json。原v1/v2/v3与完整24故障分母继续保留。


## 后续正常覆盖（7/8，仍WIP）

社区原生种子工程16次已全部闭合：两种子×Strikes/Defends共4次真实融合者callback完成，实际card_select要求选2张、移除2张对应基础牌并加入Ultimate1张，然后正常回map；另外12次普通死亡未到目标，技术0，全部原分母及trace保留。社区已知事件/胜局用于选择工程样本，没有把历史未来路线或奖励传给agent，不能作为随机独立胜率。候选SDK不变，d42585d的159个策略文件冻结，所有native模拟/学习关闭。

Trial4另从正常开局运行，两已知原生seed各default与仅第三幕提高公开问号价值；全部死第一A3 Aeonglass、技术0、Trial暴露0。default两个全部公开states/commands匹配原Std24，问号臂也没有增加事件曝光。此面板已闭合，不重复重派；未覆盖的Trial.Accept继续WIP。

新增证据：`/opt/slay-the-spire-2/codex-agent/collaboration/reviews/headless-event-normal-coverage-v2/normal-audit-v2.json`（16次实际轨迹与四个融合者选择/牌组变化）、`/opt/slay-the-spire-2/codex-agent/collaboration/reviews/headless-trial-normal-v1/normal-audit-v2.json`（4次实际、helper冻结复核）。完整胜利0，不是共享s120/100第一幕策略提升或正式100连胜。


实际最新18b后增量与新增46次正常目标覆盖见[18b说明](Codex-B012-event-after18.md)。Trial.Accept仍未实局暴露，跨版本覆盖仍7/8；请按当前部署基线选择16后或18后增量，不重复叠加。
