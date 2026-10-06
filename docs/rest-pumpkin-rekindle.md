# 南瓜蜡烛添火：第二幕篝火候选

当前篝火规则没有南瓜蜡烛的专门处理。蜡烛可见计数耗尽后，添火使计数增加5；计数为正的战斗每回合最大能量增加1，每场战斗结束扣1。补能量能影响后续多场战斗，而升级通常只改变一张牌。本候选让主线单独测这一取舍，不预先声称添火一定更好。

基于 master `414d7f283778362ed3d97804478ac75304977dbc`。默认 `rest_pumpkin_rekindle=false`；建议只打开此项，同种子完整对照，以过第二幕为主指标，另报第三幕与通关。

启用时仅作用于第二幕、规则模式、未启用 `rest_boss_sim` 的篝火。先执行原有规则和学习偏好，只有最终选中可用的 `SMITH` 才考虑替换：当前拥有南瓜蜡烛、公开 `counter` 为0或1、且有可用 `KINDLE`。即将打已知 Boss 且计数为1时保留升级；计数已为0才补火。原本选中的回血、举重和其他选项一律保留。未知计数保持原选择，绝不读取私有 `KindleCount` 或猜测真实未来路线。

参数：`rest_pumpkin_rekindle_acts=[2]`，`rest_pumpkin_rekindle_max=1`。替换时清掉 `select_purpose`，避免把添火后的界面误当作升级选牌。计数来自游戏已显示的遗物计数；历史紧凑 trace 缺失该计数，无法据其推算本候选准确会改多少次选择。

源码依据：v0.111.0 `PumpkinCandle.cs` 的 `ShowCounter`、`DisplayAmount`、`ModifyMaxEnergy`、`AfterCombatEnd` 与 `Rekindle`；`KindleRestSiteOption.OnSelect`。SDK `RunSimulator.cs` 的 relic `counter` 导出按 `ShowCounter` 取 `DisplayAmount`，不要求私有字段扩展。

纯检查：新增6项，原路线/休息一致性4项，共10项通过；测试中阻断原生进程启动。正常实局、独立模型、远端任务均未启动；未验证胜率收益。风险是本来该升级关键牌却改为添火、或后续战斗过少浪费计数；默认关闭并保留回血，交主线测试。

配套分析和输局案例：`/opt/slay-the-spire-2/codex-agent/research/normal-strategy-20261005/08-篝火配对退步与南瓜蜡烛添火.md`，可复核脚本 `analyze_rest_paired.py`。近期开发60局的45%休息线与停用第二三幕学习偏好一起测试，过第二幕16→14，不能把这两项的作用分开归因，也不能当本候选已被测试。
