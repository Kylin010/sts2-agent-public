# B012：补丁18b后的事件增量（7/8，WIP）

事件callback会因后台缺少音效、震屏、肖像和水晶球界面而中断。这个增量只替换纯表现调用、等待原生任务并提供公开水晶球点击；仍保留事件自身的奖励、选牌、强制战斗和随机过程，真实失败锁存为技术错误。

`patches/codex-event-ui-and-task-inputs-diff-since-18.patch` 基于 master `d16158e` 的实际修订18b（37fc79f，额外回合等待），三个文件独立应用后逐字匹配候选。SDK中的整个DoEndTurn、DoBuyRelic、SyncCardRemovalUsed、AfterRestOption和E02 GetSelectedCards逐字保留；不会还原18b额外回合修正。SDK包含B018普通章节构造和可选12双Boss。旧16后文件与历史证据保留，选择适合部署基线的一份增量，不能重复叠两份。

本分支包含从master移植的B012 Python接线与历史7/8说明；B019已经在master。`event_ui_fixed`仍默认False，只有匹配修复SDK的工程验证显式开启。Trial.Accept尚未获得正常实局覆盖，不能标B012全部修完。新18后增量是WIP交付，部署和合并由Claude决定。

## 已执行的验证

实际18b+B012+B020地图+B022可见血量+B023拳击隐藏Gold组成的新SDK首次编译0错误、9个继承警告。12任务/选牌、4同步context、8表现/公开grid、51地图、26可见HP、16事件变量的117项纯检查全部通过，没有加载游戏程序集。B023检查只认证PUNCH_OFF.Gold，不把其余变量自动认证为可见。

两个新增正常前缀面板共46次，全为正常64/80开局、一次Start、当前UI、No-SL，不使用原生存读档/set/强制进房/真实未来RNG。社区未来路径或结果只用于选工程样本，不作为actor输入。SDK、有限HP策略、helper和参数均冻结；所有native search/simeval/follow/learn关闭。transport只保留当前文本模板引用的事件变量，last_state仅保留公开态，actor只获得get_map门面，33项纯transport/UI/遭遇参数检查通过。这个保守过滤会舍弃只有hover显示的变量，不是所有SDK输入的全面认证。

- Trial14：8个已知社区接受种子+两个已知原生A3种子各3种公开路线，14全记录，正常死亡14、技术0、Trial暴露0。2止第一幕、6止第二幕、6进第三幕。QA7问号图臂过首A3 Aeonglass，随后死第二TestSubject；完整胜利0，不能推出策略收益。
- Trial32：另32个社区种子，正常死亡30、技术2、Trial暴露0；22止第一幕（含2技术）、10止第二幕。技术2是在巨人显示∞时明确停止：固定SDK给hp/max_hp null与alive=True，没有把隐藏数字送进actor，也没有把null当死。这个有限HP工程策略尚无经核对的∞阶段planner，两项保留原分母、不自动补局。

跨版本正常事件覆盖仍为7/8：Dense.Rest、Jungle.Join、Crystal.Future、Nab、PaymentPlan、CombineStrikes、CombineDefends已记录；Trial.Accept缺真实Accept→Guilty/Innocent页→callback→地图的完整证据。全部46次是有偏工程覆盖，不是s120、独立胜率或100连胜。

## 可选种子catalog的叠加顺序

原B013 catalog增量的文字context引用旧SettleEventTask，和B012会冲突。可先应用B012，再用`patches/codex-native-seed-catalog-after-event.patch`：它只把同一GenerateSeeds方法插在StartRun前，并加原dispatcher。实际clean18b和完整事件/地图/HP/变量SDK均apply通过；GenerateSeeds body SHA为49457af87504bae2c44b59505d83d01560f0f856f62d7d6da919544aec432bff，与原交付完全相同。新组合编译0错误/9警告、12原catalog纯断言通过；新增真实种子请求和Start均0。不要与旧catalog增量重复应用。B013 Python调度模块仍在单独codex/native-seed-pool分支。

## 本机证据

- `collaboration/reviews/headless-event-after18-v1/preparation-v3.json`、`preserved-methods-v1.json`：实际18b源码、独立apply、方法保留及原分支SHA。
- 同目录的build-v2.log和六组纯检查日志；catalog-order-source-v3.json、build-catalog-order-v3.log、catalog-order-pure-v3.log。
- `collaboration/reviews/headless-trial-normal-v2/normal-audit-v2.json`与v3同名文件：46全分母、raw gzip轨迹及源冻结。
- v2的QA7-public-route-three-arms-v1.json：同SDK/策略、单一已知种子的三个公开路线；首Boss进84HP、第二Boss进12HP提示双Boss补给预算不足，不能靠一个种子把问号权重推广。

准备断言失败和catalog文字hunk生成失败均是0-game预检，原报告保留后纠正；没有覆盖旧SDK、旧故障分母或历史证据。尚未部署Claude目录、远端或合并master。
