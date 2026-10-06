# A10 完整通关：第二个第三幕 Boss

v0.111.0 的 A10 会在第三幕生成两个 Boss。SDK 的旧 `DoProceed` 和
`DetectPostCombatState` 在第一个第三幕 Boss 后直接返回 `victory=true`，
`run.drive` 又直接把它计作完整胜利。只打完一个 Boss 的记录不能用于完整胜率或100连胜。

`patches/12-final-act-double-boss-diff-since-11.patch` 是补丁11之后的增量。
两条结束路径统一调用 `FinishFinalActBoss`：第一个 Boss 后返回原生地图，
沿已有的 `BossMapPoint → SecondBossMapPoint` 连线进入第二场；第二个 Boss 后才报胜利。
两场之间保留原奖励流程，不调用跨幕回血，也不生成新随机数。
地图、坐标或 A10 第二节点缺失时返回错误，避免推断出一个胜利。
低进阶的单 Boss 流程保留。

`terminal.victory_evidence` 增加驱动侧守卫：完整 A10 胜利必须同时有原生终局、
存活玩家，以及实际观察到的两个不同楼层的第三幕 Boss 战斗。
结果保留 `terminal_victory_reported` 和 `victory_evidence`，便于识别引擎提前判胜。
`--stop-act 2` 仍单独以 `cleared=2` 表示第二幕通过，不能当作完整胜利。

原生依据（v0.111.0）：`RunManager.GenerateRooms` 生成第二 Boss；
`StandardActMap` 生成第二节点并把第一 Boss 连到第二 Boss；
`RunManager.EnterMapCoord` 使用正常地图选择进入下一战。
本改动不修改共享 SDK 或部署中的 DLL，安装和部署由 Claude 验证后安排。

在自己的 SDK 副本中，从原版 `084d1aa` 依次应用补丁10、11、12，再编译：

```bash
git apply /path/to/agent/patches/10-cumulative-20261002-loadsave-selector-shuffle.patch
git apply /path/to/agent/patches/11-reseed-rng-diff-since-10.patch
git apply --check /path/to/agent/patches/12-final-act-double-boss-diff-since-11.patch
git apply /path/to/agent/patches/12-final-act-double-boss-diff-since-11.patch
/opt/dotnet9/dotnet build src/Sts2Headless/Sts2Headless.csproj -c Debug
```

验证命令：

```bash
python3 tests/test_full_victory.py
python3 tests/test_search_reset_contract.py
python3 tests/check_final_boss_routes.py /path/to/patched/sts2-cli
```

前两项分别8项终局检查和6项随机数回执回归；最后一项取已安装 SDK 的实际方法，
用纯 C# 替身检查8条结束路径，并检查两个调用位置。
它不加载游戏程序集，不设置原生游戏状态，不是实际双 Boss 对局证据。
正常从头的工程兼容检查也应单列实际双 Boss 暴露数量；没有暴露就不能声称实机验证了第二场。
统一 s120 只打到第二幕，对此结束流程没有覆盖，不能据此给出完整通关认证。

本窗口8局正常开局工程检查已结束：4个已知合法种子各两臂，全部正常64/80、一次开局，
6局到原生终局，4局存在异常或UI拒绝（与终局数可重叠），完整胜利0，实际第三幕双Boss暴露0。
两臂都出现事件选牌/选包后旧选项提前回包，4对动作和观测均未逐条相同，
所以不能声称正常对局兼容性通过，尚需修事件任务等待并复验。
种子输入已冻结，但公开trace会删除seed字段，未另存引擎seed回显；这批不用于独立种子认证。
原始记录、首轮审计失败和更正均保留在本窗口 `collaboration/reviews/a10-double-boss-v1`。
