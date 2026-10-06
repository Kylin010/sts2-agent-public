# 未完成事件必须按玩家界面操作

主线 `40e0c81` 在所有事件选项被黑名单排除时，让 `events.choose` 返回 None；`policy.decide` 把 None 转成 `leave_room`。旧的重复事件保护也有同一路径。SDK 的 DoLeaveRoom 会直接进入 MapRoom，从而离开尚未完成的强制事件。

原生 NEventRoom 只有在 EventModel.IsFinished 后才生成 Proceed 按钮；当前选项里没有 Leave 时，普通玩家不能直接离开。“没有获得奖励”也不足以证明等价：跳过事件还可能避免必选代价。不能用这种绕行减少技术故障，再将结果称为正常玩家胜率。

修复将没有支持选项的未完成事件作为 SimError 技术故障退出。重复事件里如果确实有公开 Leave，则一直用该选项的 index 正常选择；没有公开离开选项且无法推进时才技术退出。黑名单仍是尚未修复的引擎路径记录，不凭空加入玩家动作，不重试已经中断的局。

使用来自新普通开局完整面板的真实当前 Crystal Sphere、Endless Conveyor、Punch Off 界面做纯回归：原版在未完成水晶球返回 leave_room；候选停止并记录技术错误，保留真实 Leave 的正常选法，晚期重复也不丢掉真实 Leave，无离开选项的停滞事件显式失败。四项检查通过，拒绝任何原生IO的替身验证，没有启动或重放游戏。

这是操作边界修复，不能当策略提高。B012 的真实事件修复与正常覆盖继续单独推进；本分支不部署引擎、不操作 g10。证据 `/opt/slay-the-spire-2/codex-agent/collaboration/reviews/event-choice-boundary-v1/`，原生依据 `/opt/slay-the-spire-2/decompiled/v0.111.0/MegaCrit.Sts2.Core.Nodes.Rooms/NEventRoom.cs`。
