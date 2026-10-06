# 02 路线的Boss前篝火预测与实际规则不一致

**发现：路线在所有篝火只使用55%回血线，实际规则在Boss前使用75%。在第二幕55%～75%区间，现有fresh100/dev60共有25次“下一场记录战斗是Boss”的篝火动作，全部实际选择回血。路线却把该区间预测成升级，漏算Boss前回血，可能高估绕开篝火的路线。**

这是预测模型的一致性问题，不是“玩家应该更多升级/回血”的因果证明。`agent/docs/胜率记录.md:54`中的全局降回血线/模仿升级率已经失败，不重复该实验。

源码（固定基线master c0e6d01）：`policy/route.py:147`仅按`route_rest_below`选择heal/upgrade；`policy/rest.py:108`与125使用`heal_below=0.55`及`heal_below_before_boss=0.75`。新100/dev60配置中两个值确为55%/75%，`route_rest_below=0.55`。

数据：fresh100第二幕16次、dev60第二幕9次；第一幕该区间分别26/21次，其中46/47实际回血。第三幕为11次，10次回血。不是所有此类火堆都在公开地图上直接连Boss：统计只证明“之后没有其他记录战斗”，可能仍有非战斗节点。**补丁只处理公开children直接指向Boss的火堆**，不把这83个动作都声称会被修改。

例子（已发生动作）：

| 记录/seed | A2火堆 | HP | 实际选择 | 后续Boss |
|---|---:|---:|---|---|
| fresh/MZW48PKH7KHV | 15 | 61/101 | Heal | Crusher + Rocket，死亡 |
| fresh/RRFXZSSZ95WV | 15 | 49/87 | Heal | Knowledge Demon，过幕 |
| fresh/KYMR50UHZVZZ | 15 | 44/80 | Heal | Knowledge Demon，死亡 |

这些例子不能证明若改变路线就能赢；当前trace缺少整张当时地图，无法逐局离线重算所有路径。详细字段及全部动作在`rest-decisions.csv`，两源SHA在`mainline-analysis-v1.json`。

## 可直接测的改动

分支`codex/route-rest-consistency`在最新master基线上加入：

```json
{"route_rest_boss_heal_below": 0.75, "route_rest_boss_heal_acts": [2]}
```

默认`route_rest_boss_heal_below=null`，行为保持原版。启用后只在第二幕、公开路径直接连Boss、普通rule火堆策略时，把路线预测回血线从0.55抬到0.75，按原路线近似增加30% maxHP，避免给原本实际要回血的火堆发升级收益。实际`rest.choose`、学习权重及出牌都不改。

`rest_mode=value/imitate`、`rest_boss_sim`、`rest_potion_smith`自定义规则一律保留原近似，非法/NaN参数回退。学习偏好、禁止回血的遗物、特殊篝火选项和沿途牌组变化仍不是完整模型；启用前主线应针对这些病例检查，不将本改动叫作实际火堆动作的完整预测器。`learn_on`可能改变实际动作，数据上此HP区间主要仍服从base heal规则。

4项纯测试通过：默认/其他幕/非Boss保持；HP边界与实际base rest._rule一致；自定义策略与非法参数回退；可见的“宝箱/火堆→Boss”两路径夹具在50/80HP时启用才改变路线。未启动游戏或模型，不报告胜率提升。

**预期主要影响第二幕进入Boss前的路线选择**。先由Claude在开发60同种子完整对照中只启此参数；若有效，再在新100验证。主指标看A2幸存率、A2Boss入场HP、路线实际改变局数及完整通关，A1应保持；不要求火堆升级比例向人类72%靠拢。可能触发的局数待主线带完整地图记录核验，25只是观察范围，不能当预测受影响25局。
