# 商店遗物购买回执与真实任务故障

购买遗物的原生逻辑完成后，普通货位会将 `MerchantRelicEntry.Model` 清空。旧 SDK 随后用 `entry.Model.GetType()` 写日志，导致已经扣款、获得遗物的购买返回空引用错误。快递员补货及会员卡折扣还会改变该货位和价格，不能用购买后的货位字段作为原购买回执。这是既有 C16 根因的 SDK 修复；策略侧 `skip_select` 恢复没有修复该日志错误。

另外，旧 SDK 在后台购买任务已经完成时跳过 `Wait`，没有检查其真实异常或布尔结果；遇到选牌则丢弃局部任务，选完后的真实失败也无法结算。此次保留任务到原生购买完全结束，持续推进 SDK 同步队列，只在真实选牌/选包时返回对应界面。异常、拒绝和超时均返回并锁存 `MERCHANT_FAULT`；Python 收到该前缀立即作为技术故障退出，不重试购买或离开半完成的商店。

原生扣款、获得遗物、补货、购买钩子和随机数均调用原来的 `OnTryPurchaseWrapper`。回执只缓存购买前可见的名称和标价。等待购买输入时阻止无关动作启动第二次购买或提前离店。

## 应用

分支 `codex/merchant-relic-logging`，基于 master `1f6e0f15963b2402ef69498b47028245704a6809`。

- `patches/codex-merchant-relic-receipt-diff-since-15.patch`：主线补丁15之后的增量，可用于含或不含补丁12的链。
- `patches/codex-merchant-relic-receipt-diff-since-B012.patch`：B012候选 SDKv3（`codex/headless-event-cosmetics` / `cfa49a5`）之后的等价增量。

二者二选一；不要重复应用。补丁编号由 Claude 整合时分配，不修改正在跑 g10 的引擎。分支还包含 `sim.py` 对 `MERCHANT_FAULT` 的退出处理及纯回归脚本。

## 验证与限制

安装源码的9项纯C#回归通过：清空货位、快递员补货、会员卡回执价格、真实任务失败、真实选牌并恢复、原生拒绝、选牌后失败及锁存、超时、同步队列异常。测试不加载游戏程序集。三项 Python 驱动回归通过。B012候选及主线15独立编译均通过；两增量逐字节应用检查通过，15无12链也通过。

原完整24局中5个商店故障种子，已正常从头复测至购买结束：5/5完成、技术故障0。五个种子的购买前动作与全部公开状态均与原轨迹完全一致；实际扣款157/197/189/203/157，分别获得光滑石、药水腰带、金刚杵、会员卡、灯笼，并下架原货位。全部正常64/80开局、每进程一次Start、当前UI/No-SL审计通过，策略/SDK/辅助文件冻结。

这五个测试是工程前缀，完整胜利数0。原完整24的5个技术故障仍保留原分母。快递员、复杂购买选牌和真实故障只完成了纯替身检查，不能称所有商店遗物已认证。B012仍是3/8正常事件选项覆盖的WIP。

使用原24已知合法种子的完整兼容面板已全部闭合：24个正常原生死亡、检测到的技术故障0，过第一幕6/24、过第二幕1/24、完整胜利0。19个原本无故障的完整局动作和公开状态全部逐字一致；原5故障局直到原购买前缀也全部一致，随后继续正常游戏。8次实际遗物购买全部按标价扣款、获得1件遗物并下架，没有实际购买选牌暴露。公开字段审计24/24正常开局、0私有字段、0雾下奖励泄漏，策略/SDK/辅助文件与原证据哈希均未改变。新到第三幕的1局仅走至第3层普通战，没有双Boss或其奖励暴露。

该面板不属于fresh、s120策略改善或独立连胜：原5局因技术错误中断，修复后的幕通过比例不能当策略增益。B012正常事件覆盖仍3/8；完整局零技术仅限定本批，并非所有遗物、药水、事件均已认证。

## 证据

完整证据目录：`/opt/slay-the-spire-2/codex-agent/collaboration/reviews/merchant-relic-logging-v1/`。

- `patch-chain-v3.json`、`pure-after-v3.log`、`pure-peer15-v3.log`、`python-fault-contract-v2.log`、`peer15-integration-build-v3.log`。
- `prefix-plan-v1.json`、`prefix-summary-v1.json`、`prefix-traces-v1/`；原证据在 B012 的 `full-normal-summary-v1.json` 和 `full-normal-traces-v1/`。
- `full-normal-plan-v1.json`、`full-normal-summary-v1.json`、`full-normal-public-and-event-audit-v1.json`、`full-normal-merchant-and-paired-audit-v1.json`，及24条完整原始轨迹。
- `preflight-failures-v1.json` 保存原测试与准备失败；`setup.json` 仅代表早期回执候选，最终补丁与状态以 v3 清单为准。
- 原生依据：`/opt/slay-the-spire-2/decompiled/v0.111.0/MegaCrit.Sts2.Core.Entities.Merchant/MerchantRelicEntry.cs` 与 `MerchantEntry.cs`。
