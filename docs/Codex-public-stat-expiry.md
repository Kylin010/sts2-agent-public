# 临时属性到期：补齐敌方恢复与公开顺序结算

结论：当前future只在单独开关下恢复Mangle，仍把Dark Shackles、Shackling Potion等临时减力量延续到后续回合。默认关闭 `foresight_public_stat_expiry` 将已经显示的八类临时负力量恢复纳入预判；有正临时力量等无法用本次窄规则算准的情况明确回退。另提供17类临时力量/敏捷的可组合数值结算函数，供玩家回合末模型与价值网络使用，未宣称完整回合模拟或胜率提升。

## 规则和完整调用链

- TemporaryStrengthPower.AfterSideTurnEnd:147 / TemporaryDexterityPower:143：仅在Owner所在side结束时，Remove本能力，再按原Amount施加 -Sign×Amount 的Strength/Dexterity。
- PowerCmd.Remove:291 / PowerModel.RemoveInternal:575：移除能力不把Amount归零，因此随后仍使用原层数，不能按移除后0算。
- PowerModel.GetTypeForAmount:460：Counter+AllowNegative且offset负判Debuff，即使既有Strength是正、结算后仍为正，也会被Artifact拦截。
- ArtifactPower:17、38：负offset归零后消耗1层。正的恢复力量是Buff，不消耗Artifact。
- PowerCmd.Apply:124~160、ModifyAmount:231~253：数值修正、应用、AfterModifying逐次完成，下一项才消费新的Artifact层数。
- Creature.Powers:327、ApplyPowerInternal:606：保留插入顺序；CombatState.IterateHookListeners:411、Hook.AfterSideTurnEnd:1279按它枚举；HookPlayerChoiceContext:124等候无玩家选择的该次任务完成。
- NPowerContainer.Add/UpdatePositions/SetCreature按同一个顺序显示可见图标；自己的已存在SDK源码Where(IsVisible).Select(ExportVisiblePower).ToList保留顺序，未修改/部署SDK。若输入被排序或失去来源，不可声称顺序有公开依据。

扫描v0.111.0的所有直接TemporaryStrength/Dexterity子类，共17类，逐个完整源码已固定在subclasses-source.json：8类临时负Strength、5类正Strength、4类正Dexterity。正临时能力到期扣属性；负临时能力到期恢复属性。所有17项规则与源码列表一一检查。

## 接入战斗预判的函数

`negative_strength_return(powers)`返回已存在、可见、合法正整数计数的负临时力量恢复之和；有正临时力量则None，畸形/重复计数、无id的未知能力也None。完整公开输入是契约，不可把历史提取中丢掉的能力列表当作确认不存在。

`foresight.future`开新flag后将恢复量加回Strength，再沿原出招表继续算；同时开旧Mangle flag时，新分支优先，避免把Mangle加回两次。认不准时expected_incoming回原EMA、CV回当前意图；mentalmodel.schedule返回None，不能把未知未来当0伤害。默认关时保留旧行为。

例：知识恶魔显示Strength -7与枷锁7，当前拍击11。其后确定的KO/Ponder，旧预测6/6，新预测27/13（KO 9×3，Ponder13）。之后的诅咒分支仍沿用原不确定分支；有公开第三诅咒完成证明且开kd-loop时才走最终循环，随后Slap21。没有读取真实下一招/RNG。

这里依据**已经完成动作后显示的临时能力**，没有补齐“候选中尚未打出的卡/药水”的完整能力与伤害投影。future仍是KB基础伤害+Strength的估计，不是含全部易伤/虚弱/监听的精确实际HP损失。

## 公开玩家结算原语

`resolve_subphase(powers, order_is_public=False, helmet='absent')`按已认证的图标顺序结算已识别的临时属性指令，输出属性/Artifact变化、过期能力、每项变化及unhandled_power_ids。多个过期能力而顺序未认证则None。Unknown Helmet遇到正Strength恢复也None，不读UsedThisCombat。unused/used只能来自公开已完成历史的推导，不能照抄原生私有标志。

玩家当前Strength5/Dex5、Flex5/Speed5、Artifact1：Flex先到期则Strength5/Dex0；Speed先则Strength0/Dex5。Artifact2可把两次扣除都挡住并变0。这可以解释为什么不能静态按“有一层Artifact就保住族母扣力量”评分：玩家回合末可能已经把它花在临时属性消退上。

RuinedHelmet只倍增正Strength：原力量-7、负临时力量7，若Helmet确认尚未用，恢复offset14，最后力量7；已用则恢复7，最后0。临时增益本身若被Helmet加倍，也要以当前实际Strength和原临时能力计数为输入，不能假设两者幅度相同。UnsettlingLamp要求触发CardSource，临时消退cardSource=null，不倍增；SneckoSkull仅Poison。

本原语只覆盖数值子阶段。未知能力/遗物的监听、先前回合末伤害、临时属性之间其他触发、清除能力和后续技能尚需模型合成；unhandled列表不是“无关证明”。不会把它直接当整个回合清理或单凭它改CV的Str/Dex特征。现有value网络的Artifact1/2碰撞与汲取研究继续由原owner训练接口处理。

## 历史证据与影响面

1050回放按v0.111.0/单人标准A10铁甲、无记录restart/reloads/resume/attempt>0、未弃局筛选后，找到1个严格匹配：赢家YGXE1YZVYL6K，第48层Aeonglass，同一cid109的SHACKLING_POTION_POWER7，在敌方end_turn之后Strength +7恢复到0。原始压缩SHA/公开事件固定于completed-shackling-witnesses.json。是第三幕历史规则证据，不能当自己的第二幕实机资格或候选收益。

旧fresh100/dev60公开fpow的确切枚举.title键：64个临时负力量记录，其中Mangle46；旧修复之外18个（DarkShackles16、ShacklingPotion2）。fresh100的非Mangle部分有7个种子/13记录，第二幕3种子/6记录；dev60有3个种子/5记录，第二幕2种子/4记录。记录不是独立游戏，缺失别名不作不存在结论；mainline-exposures.json保存每个帧位置与源SHA。

## 验证、失败与主线评测

29新纯检查通过：17子类源码对应、正/负到期、Artifact、公开顺序、Helmet状态回退、计数/别名/未处理项/不变性、KD未来与CV输入、Mangle双flag不重复、公开最终诅咒组合及mental未知回退；121既有机制检查+37旧回归也通过，合计187项，Popen阻断，0原生/远端/fit。

首次新检查5项失败：测试错误地把第三个未来敌人回合视为0伤害，忽略Ponder后的知识诅咒分支未确定，实际旧混合7、新混合10.5；修正测试期望并加公开final证明组合检查，未为迎合测试修改分支机制。初版pure-checks.log保留；最终combined-pure-regression.log。上述混合只是原通用分支模型，不称准确的真实未来。

基于最新master6c27b15；该commit只记录CV v2与v1持平（fresh100更远13/更近14，p=.65，继续v1），不继承对方结果为本候选提升。建议主线单开foresight_public_stat_expiry，可保留原mangle-expiry但不能双算，记录临时badge/API完整性、恢复后攻击误差、A2与实际完整通关配对。与单独Inferno分支无冲突。尚未合并/部署或得到候选整局结果。

复现：`python3 reviews/public-stat-expiry/test_expiry.py`；已有合并机制和37回归见combined-pure-regression.log。
