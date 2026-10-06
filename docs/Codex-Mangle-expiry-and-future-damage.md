# 未来伤害预估没有返还 Mangle 的临时减力量

结论：源码规定 Mangle 在敌人的本回合结束后返还力量，但 `foresight.future` 将当前负力量继续用于之后所有预测回合。默认关闭开关 `foresight_public_mangle_expiry` 在计算下一个敌方回合之前加回可见的 MANGLE_POWER 层数。无需读取隐藏阶段、真实RNG或未来牌序；未知/异常层数返回None。

## 源码与正常实局证据

`TemporaryStrengthPower.cs:134` 应用力量变化，`:147` 在拥有者一侧回合结束返还；`ManglePower.cs:9` 的 IsPositive=false。`foresight.py:future` 原先只使用当前Strength及当前招的固定加力量效果，没有临时力量到期处理。未来预估会进入规划器 foresight、mentalmodel 和战斗价值特征，影响后续掉血预估。

主线开发60局的历史记录 `it-iter-pub-dev-1005-0034.jsonl`，种子 CJ2AJ95KRVKS：

| 已完成回合与trace索引 | 当前公开状态 | 旧预测下一击 | 到期修正 | 历史下一回合实际显示 |
|---|---|---:|---:|---:|
| R6，357 | 知识恶魔拍击11，力量−7，Mangle10 | 洪流6 | 洪流36 | 36 |
| R10，373 | 知识恶魔拍击14，力量−4，Mangle10 | 洪流15 | 洪流45 | 45 |

两条当前招只从当前HUD、力量、段数识别。下一条历史记录仅用于核对预测，**不会进入函数输入或当前决策**。原始记录的SHA和准确索引在 `reviews/mangle-strength-expiry/completed-actual-witnesses.json`。

另有12项纯机制检查通过，包含返还后的多段伤害、永久力量保留、缺字段拒绝、原观察不变、禁启动原生/子进程、默认关闭保持原结果。复现：`python3 reviews/mangle-strength-expiry/test_expiry.py`。未启动新游戏或进行训练。

## 可测改动

候选只打开 `foresight_public_mangle_expiry`。这是已打出Mangle后的未来规则修正，与 `codex/mangle-visible-defense` 的当前来伤评分修正相互独立；先分别测，再测组合。默认False不改变原预测或主线策略。只处理Mangle，不凭猜测推广到其他临时力量、永久减力量或不同来源的增益。

主线新100/dev60同种子整局配对，重点统计第二幕Boss、下一攻击预估误差和实际掉血；整体第二幕推进与进入第二幕后通过率分别报告，完整通关必须实际双Boss。没有承诺提升百分点。

## 尚未修的模型问题

- `tools/replay_situations.py:82` 的 fut_of只传敌人的Strength，丢掉ManglePower。开本修正后，现有人类训练FUT特征仍带旧误差；需Claude/value重提取公开事件历史里的临时力量层数，再重新训练验证，不能只改运行时就声称完成了训练数据修正。
- `foresight._resolve_first` 仍平均知识恶魔的条件分支，没有用已完成诅咒选择历史判定三次诅咒是否完成。当前补丁不解决这个另题。
- CV特征没有沙坑期限、瓦解伤害层数、Sloth剩余出牌数和朝向。源码机制强制死亡不能仅用平均来伤替代。当前进攻倍率 phase_alpha来自人类花在攻击类型卡上的能量比例；Mangle等防御用途攻击牌说明这个比例不是纯粹的攻守效用，不能当源码定理。
