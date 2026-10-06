# 独立模型：真实显示停用不等于原生熔化标记

确认缺口：p27cv SetCombat:801只用反射复制Status。Player.MeltRelicInternal:521同时设置IsMelted=true；CombatState.IterateHookListeners:435过滤IsMelted而不是Status。因此仅恢复Disabled的影子遗物，仍可能接收攻击/格挡/回合事件，错误继续触发钢笔尖、双截棍等。这个问题是模型物理不一致，不能用表面Status相同证明根还原成功。

默认生效的协议修正：接收当前UI可见的is_wax/is_melted，独立模型set_combat另传relic_lifecycle，恢复后逐件核对。缺少公开字段、模型忽略字段、重复遗物实例不明或类型不合法时，不启动/不接受这次模拟，回到实际动作规划器。**必须先接SDK补丁再接Python；旧p27没有字段会明显增加回退，不能单独合Python当提胜策略。**

`patches/codex-public-model-relic-lifecycle.patch`按本地p27cv源码生成，增加UI输出及模型设置两种bool。属性IsWax/IsMelted由蜡制名称前缀、暗红图标可辨，公开性证据与正常窗口12报告一致；不读或复制真实CombatsSeen、内部IsUsed等变量。源与模型原生数据始终分开，没有修改实际游戏。

复杂寿命尚未闭合：ToyBox当前计数是CombatsSeen%3，下一件由当前蜡制顺序选择，累计15次后停止。当前UI计数本身不等于完整寿命；所有ToyBox模型根暂不接受，等待完整公开获得/移除/战斗历史推导。另扫描10种覆写IsUsedUp的遗物：Disabled且未熔化时不能只设Status伪造已用尽，亦回退。BoneTea用CombatsLeft而非Status控制下回合初始费用效果，不能被错误“熔化”来压掉钩子。

这与纸蛙/纸鹤的直接GetRelic路径不同；后者熔化仍可能保留倍率，不能全局删除Disabled遗物。相关源码结论已交第14支。

12新纯协议检查+37移植检查通过/Popen阻断，覆盖明确熔化、非熔化用尽、未知标记、模型忽略字段拒绝、无模型命令回退和输入不变。独立拷贝SDK编译最终0错误/2旧警告；初版JsonValueKind未全限定及随后替换过宽的编译失败日志均保留，修复后重建。没有运行该DLL或原生对局，没有启动模型服务/远端/拟合。

复制SDK仅留本地研究，不入Git；原p27cv源SHA与未修改证明、拷贝源/二进制SHA和编译日志在reviews/public-model-relic-lifecycle。尚无原生根恢复资格、正常整局配对或胜率提高证据。无需新实验开关容许模型错误，主线Claude核补丁链后联合接入并测试。
