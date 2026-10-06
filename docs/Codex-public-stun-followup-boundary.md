# 公开模型的眩晕后续：禁止复制原生保存字段

已确认本机p27cv源码泄漏路径：RunSimulator.cs:2897把 `NextMove.FollowUpStateId` 导出为move_next，search.build_public原先直接传给set_combat；p27cv:791再用它设置影子怪物眩晕后动作。STUN.description只有眩晕提示，不能从当前图标判断这是吹哨、尖啸还是熟睡叫醒。Creature.StunInternal:525会保存被取消动作或调用方指定动作；**它不是总能从当前UI确定的公开后续**。本地p27cv与正式p27的对应由主线胜率文档声明；未读远端实际随机数或跑远端验证其字节一致性。

修改默认生效的公开模型边界：不读取或复制move_next。没有公开证明时，任何眩晕模型构建在发送命令前返回None，使用现有实际动作规划器；不假装知道保存动作。STUNNED当前标记只由可见Stun意图得到，不能由原生ID覆盖。

`public_stun_history.observe_completed`仅在run.drive的实际动作返回之后调用。当前先覆盖单个怪、同幕/层/遭遇/回合和同可见目标、源码核对的5种普通攻击及Whistle：

- 未眩晕骇鳗可见Shriek阈值，经成功攻击掉HP到阈值以下且存活、Shriek消失并出现Stun，才证明后续TERROR_MOVE。
- 未眩晕族母233最大HP，可见Asleep，经成功攻击掉HP、Asleep消失并出现Stun，才证明后续SLASH_MOVE。
- 不靠战后字段、候选伤害或私有phase创建证明；缺徽章、未知卡/附魔、失败、回合/楼层缺口、目标不符都不推断。

再次眩晕边界：Creature.StunInternal创建MustPerformOnceBeforeTransitioning的MoveState，MonsterModel.SetMoveImmediate不强制时不能覆盖尚未执行的眩晕。已有吹哨眩晕时再跨尖啸，即使Shriek消失，也不能提升为Terror。原Eel候选/observer已另补此处2测试（见codex/terror-eel-public-future最新提交），原始机制推断的不足保留，不声称首次就已完备。

抽牌堆检查为**阴性**：p27cv:2931在导出前OrderBy，接收者得到组成而非真实顺序；本题不指控该字段泄漏未来抽牌。非眩晕move_id是否在UI中可唯一识别仍待更广泛接口研究，不能由本补丁认证所有私有字段都已取消。

附带只读接口补丁 `patches/codex-stun-followup-visible-powers.patch`：删除原生move_next导出，并按IsVisible过滤双方能力（p27cv此前导出全部，AmbergrisPower隐藏能力也会进入）。对本地p27cv源apply-check通过，但未写入、编译或部署他人SDK。需要Claude核其当前补丁链后应用。

15新纯检查+37移植检查通过/Popen禁止创建进程：更改隐藏后续不改变构建结果；无证明不发送任何模型命令；证明来自实际完成行动；覆盖Eel/Matriarch、连续Stun、不能覆盖旧Stun及冷启动/缺口回退。源SHA和初/终日志在reviews/public-model-no-hidden-followup。新增原生/模型常驻/批量/fit/远端全部0；没有胜率收益或完整资格声明。
