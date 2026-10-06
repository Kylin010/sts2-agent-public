# 公开信息四项修复的隔离整合

> 一切以增加胜率为主！！不要想乱七八糟。
> 目标改为，争取更好的胜率 争取到第三幕 争取通关 才对。不是改乱七八糟。

本支把此前15/16/17/18公平边界同时保留，解决独立合入时可能覆盖 `build_public` 门禁或 actual observer 的冲突。**没有部署、原生对局、模型服务或胜率测量；不宣称提高胜率。** 项目规则禁止实际存读档和隐藏信息，这些边界无可关闭的作弊开关。

基线 master `013645ef36ce3a30a64a4f9740ea791c190a23cb`；先18 `9985498`，随后 cherry-pick 原15代码 `4bebd27`、16 `919d6a1`、17 `08b15a7`。隔离整合提交分别 `25e26b5` / `56366bb` / `55f5e28`，本支 `codex/public-information-boundaries` 是可直接审查的联合候选，不是另一条主线。Claude可合本支一次，无须重复合前四支；若已合部分，请审查净增量，不盲重复cherry-pick。此前各主题报告与失败证据完整保留。

冲突处理：

- `_vis` 保留18的公开意图（类型、显示伤害、段数），不恢复16的非Stun原生ID。
- `build_public` 同时保留16的Stun公开followup证明、18的非Stun唯一候选及17的遗物公开flag门禁/传参/回读；任何不足先返回None。递归force_fresh仍传actual公共历史。
- `run.drive` 真实transport成功返回后同时调用 move-belief 和 stun 两个observer，各用自己memory键；15禁actual checkpoint/SL/god仍保留。
- `.gitignore` 两个本地SDK拷贝目录取并集。没有拷贝别窗physics或修改源SDK。

验证重新在此联合代码执行（日志 `reviews/public-information-boundaries`）：20当前招式 + 15Stun + 12遗物 + 7普通动作边界 + 7独立PUB随机/恢复契约 + 37原ports + 5新交叉 = **103项PASS**。新交叉明确有存活敌人：公开Stun+熔化遗物同时传对，遗物缺flag不能被合法Stun证明绕过，冷Stun不能被合法遗物flag绕过，沙虫实际历史+熔化遗物同时恢复，以及真实drive两observer均在transport返回后收到同一before/after。Popen禁启动；py_compile/diff-check通过。

SDK的16→17→18单文件源patch链已在18独立拷贝apply核验，使用18patch的 `--unidiff-zero`，原源SHA未动。**联合SDK未编译/部署；17单独编译通过不能当联合运行资格。** 正式旧p27缺wax/melted字段会保守回退，Python与SDK需一起接，不能为了支持率跳过flag门禁。

后续仍需Claude在联合SDK实机核验公开root一致性、冷/完整历史支持率，然后重新冻结正常HP/NoSL同种子A2/A3/full评测。旧含真实ID输入的NN数据/模型需要value owner重编码复训；其他teacher数据/API未全审完，不声称整个游戏接口完整认证。更多一般怪物历史、随机/条件阶段的集合概率预测仍待研究；当前未知保留None，不填0。阴性0905结果仍保留，独立完整通关改善尚未证明。
