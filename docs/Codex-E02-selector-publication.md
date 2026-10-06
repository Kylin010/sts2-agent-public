# E02：选牌完成后返回已被清空的共享 promise

补丁 `patches/codex-selector-publication-diff-since-15.patch` 是独立小补丁，基于 master 3720076 的 SDK 补丁15。无需事件表现补丁，不改变牌组、HP、RNG或选择规则。完整事件候选已经包含此修复，两份补丁不要重复应用。

`GetSelectedCards` 将 `_pendingTcs` 发布给请求线程，输出日志后再读取 `_pendingTcs.Task`。如果玩家在发布后立即回应，`ResolvePending` 会先清空该字段，因此原方法返回时空引用。修复保留本次 promise 的局部引用，返回局部 Task；volatile 发布与单次字段读取也保证 HasPending 不读取两个不同的共享引用。

纯 C# 复现实际提取安装 SDK 的 selector 类：在发布日志时同步回应，旧版确定性 NullReferenceException，补丁版得到已完成的原 Task，且没有遗留旧提示。这里的日志回调模拟线程调度点，没有加载 sts2.dll 或运行游戏。

```bash
python3 tests/check_event_task_fence.py /path/to/sdk --selector-only
```

本机证据在 `/opt/slay-the-spire-2/codex-agent/collaboration/reviews/headless-event-cosmetics-v1/`：`pure-selector-latest15-before-v1.log`（原版失败）、`pure-selector-latest15-after-v1.log`（通过）、`selector-minfix-text-check/`（15后应用并逐字节核对）。这项检查不是正常胜率或发生频率测量。
