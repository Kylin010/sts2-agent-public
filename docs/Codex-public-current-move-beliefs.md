# 当前招式只由公开意图与实际历史判断

> 一切以增加胜率为主！！不要想乱七八糟。
> 目标改为，争取更好的胜率 争取到第三幕 争取通关 才对。不是改乱七八糟。

当前 p27cv 导出真实 `NextMove.StateId`；普通意图 UI 不展示这个内部名称。沙虫两次撕扯、Cubex 两次攻击加力量、Kin Priest 两种减益攻击的界面形状相同，但后续不同。复制真实 ID 会泄露玩家尚不能确定的阶段。这里移除这个决策信息源，并提供 `candidates / unique_move / observe_completed` 函数。**这是禁止作弊规则要求的必需修复，不提供关闭公平边界的开关。没有测出胜率提升，也没有部署主线。**

## 源码与复现

- `decompiled/v0.111.0/MegaCrit.Sts2.Core.MonsterMoves.Intents/AbstractIntent.cs:45,67–75`：悬浮说明使用通用 IntentPrefix 本地化键；没有 StateId。
- `.../MegaCrit.Sts2.Core.Nodes.Combat/NIntent.cs:258`：显示攻击伤害或状态牌标记；不显示内部招式名。
- `.../MegaCrit.Sts2.Core.MonsterMoves.Intents/AttackIntent.cs:86–90`：预览伤害包含能力修正，不能无条件用基础伤害反解阶段。
- 只读实际 p27cv 来源 `codex-agent/research/claude-value/sts2-cli-p27cv/src/Sts2Headless/RunSimulator.cs:2896` 导出原生 StateId。未检查远端部署字节，不以本地源代替远端认证。
- `.../Models.Monsters/TheInsatiable.cs:93–105`：两招9×2；Liquify→Thrash→Bite→Salivate→Thrash2→Thrash。
- `.../Models.Monsters/CubexConstruct.cs:113–132`：Charge→Repeater→Repeater2→Expel→Repeater；HP变化监听只改声音，不改状态机。
- `.../Models.Monsters/KinPriest.cs:106–124`：Frailty→Weakness→Beam→Ritual→Frailty；本函数历史限制单存活敌人，不从击杀随从前后的不完整历史推阶段。

静态 KB 盘点见 `reviews/public-intent-move-beliefs/signature-collisions.json`：27组类型/段数碰撞；12组连基础伤害也相同，对应12种怪物；TEST_SUBJECT是正式第三幕Boss实验体，并非测试怪。**这只是 KB 碰撞清单，不是全怪物源码完整性证明。** 不能称12种都无条件不可辨识：公开历史可以消除部分歧义，某些元数据状态正常路径不可达。

## 改动与信息边界

1. 当前候选集合只看公开意图类型和攻击段数，不读取真实 move_id/move_next，不把修正后伤害强行倒算成基础伤害。类型/段数唯一才能建模型；未知或歧义在发送任何模型命令前返回 None。
2. 历史只在已核的沙虫、Cubex、Kin Priest 固定循环使用。观察接口接在实际 `sim.act` 返回之后；只接连续一次 end_turn，或同回合未附魔/感染的限定普通牌。单存活、同 act/floor/encounter/name/index/maxHP；错误、缺口、未知动作、药水、额外回合或矛盾都丢掉历史。不会以“第一回合应该是某招”虚构缺失历史。
3. 推演 payload 使用公开证明的招；`_vis` 改为类型/可见伤害/段数，因此真实 ID 不再影响一致性校验或独立 PUB 随机种子。
4. `combat.plan` 的 phase_alpha 不再优先读取原生 ID；歧义不套某一招的倍率。`nnpolicy.encode_state` 保留字段形状，move token 仅来自冷公开唯一判断；歧义编码为空。
5. SDK 建议删除原生 move_id 导出；独立模型 `set_combat.move` 仍可接受由公开证明得到的值。补丁须用 `git apply --unidiff-zero`（无尾部上下文，兼容16已经删 move_next）；本地只读核验通过，自有单文件拷贝按16→17→18应用也通过。未编译/运行/部署 SDK；原 value 源未修改。

## 验证与负证

`python3 tests/test_public_move_beliefs.py`：20项 PASS，Popen 被禁止；覆盖相同意图歧义、伪造私有字段不变、公开回合历史消歧、历史缺口/错误/未知动作回退、模型 payload、阶段规划和NN编码不变。原 `tests/test_codex_ports.py` 37/37 PASS。`git diff --check` PASS。

初次阶段评分测试手牌为空，planner 返回 None，1项 fixture 错误；补上合法 Strike 后通过，失败日志保留。初普通 git apply 无尾部上下文被拒；明确 unidiff-zero 后和完整16→17→18 SDK源链通过，原失败记录保留。没有新游戏、模型服务、拟合、远端任务或胜率批量。

## 合入顺序与剩余工作

本支独立基于 master 013645ef；前15（禁实际checkpoint）、16（Stun公开历史）、17（熔化生命周期）尚未合 master。Claude 合并时要**保留全部边界**：先15/16/17，再18，并解决 `build_public` 与 `run.drive` 冲突。Stun沿16：可见Stun图标→STUNNED，followup必须由16已完成公开动作证明；非Stun沿18：unique_move。同时保留两个 actual observer，17 relic_lifecycle 的门禁/传参/回读，不可用18的独立旧基线代码覆盖它们。本支单独面对Stun保守回退；本报告没有宣称这四支Python整合已验证。

NN输入语义已改变，旧模型用真实招式token训练的离线成绩不可直接继承；value owner 应用同编码重建数据并重新冻结评测。旧数据解析/训练其它路径未逐项审完，不声称数据全面公平。`foresight.identify`、mentalmodel、rerank仍有“最像一招”的公开近似，未偷读ID但不能当唯一证明；这里没有把它们全换成统一集合概率模型。泛化当前招式识别仍依赖KB完整性，动态段数/特殊意图/响应式相位需继续源码核验。

公平修复后 Claude 应重新冻结完整同种子对照，并分别记录非Stun歧义回退率、历史消歧率、BOSS/精英支持率、A1/A2/A3与最终完整胜利。不能为保持旧数字重新打开真实ID。此前0905 Boss组 A1 73→71、A2 29→27、完整0→0的阴性证据仍有效，不能把这次纯检查当成救回了这些局。

后续联合资格更新：本支已隔离整合15/16/17/18，103纯检查通过，见 `docs/Codex-public-information-boundaries-integration.md`。此前“Python组合尚待核”由该限定纯检查结果更新；SDK联合运行和胜率仍未核验。

2026-10-05源码复核更正：此前按英文名称误将TEST_SUBJECT称为测试怪，现已核 `Models.Encounters/TestSubjectBoss.cs:20,24` 及KB acts=[3]/category=enemy；原碰撞JSON本来包含它，数据未删，文本改为12种。此前共享回执的“含1测试怪”撤回。
