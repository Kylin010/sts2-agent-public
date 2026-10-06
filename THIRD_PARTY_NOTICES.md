# Third-Party Notices

本仓库自己的代码按 MIT 许可发布（见 `LICENSE`）。下面列的是用到或派生自第三方的部分，它们各自的许可不变。

## 1. sts2-cli（MIT）

- 项目：<https://github.com/wuhao21/sts2-cli>，作者 Hao Wu
- 用途：`sim.py` 通过 sts2-cli 在后台运行游戏引擎；`patches/` 里的补丁是对 sts2-cli 源码（`src/Sts2Headless/`、`src/GodotStubs/`）的修改，基于上游提交 `084d1aa3d8e118ca7ce8d8774ad16d6be9c92367`。
- 许可全文：

```
MIT License

Copyright (c) 2025 Hao Wu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. Spire Codex（PolyForm Noncommercial 1.0.0）

- 项目：<https://github.com/ptrlrd/spire-codex>，网站 <https://spire-codex.com>
- Required Notice: Copyright © 2025-present Peter Lord and Spire Codex contributors.
- 许可：PolyForm Noncommercial License 1.0.0，<https://polyformproject.org/licenses/noncommercial/1.0.0>
- 用到的数据：
  - spire-codex 的游戏数据（卡牌 / 遗物 / 药水 / 遭遇的 id、名字、数值），由 `build_knowledge.py`、`build_baselines.py` 等脚本读取。带游戏文本的生成结果（`kb/cards.json` 等）不随本仓库分发。
  - spire-codex 公开的社区对局导出和对局录像（玩家通过它的模组 / 网站上传）。本仓库**不包含**任何原始对局或录像，只包含由它们算出的汇总统计、单场战斗基准和训练好的模型权重（见下表）。
- **这些由 spire-codex 数据派生的统计和模型权重只能用于非商业用途。**

## 3. 数据文件和模型权重的来源

「社区对局」= spire-codex 公开导出的《杀戮尖塔 2》对局记录（铁甲战士、进阶 10，主要是 v0.111.0）；「社区录像」= spire-codex 模组记录的逐事件对局录像。「自己的模拟」= 本程序用 sts2-cli 自己打出来的对局，不含第三方数据。

| 文件 | 内容 | 训练 / 统计数据 | 生成脚本 |
|---|---|---|---|
| `data/pick_model*.json` | 选牌模型 | 社区对局里的选牌决定 | `tools/train_pick_model.py` |
| `data/relic_model*.json` | 遗物估值模型 | 社区对局里的商店买 / 不买 | `tools/train_relic_model.py` |
| `data/value_model.json` | 胜率预测（因子分解机） | 社区对局（v0.111.0） | `tools/train_value_model.py` |
| `data/run_value*.json` | 整局价值网络 | 社区对局（全版本） | `tools/train_run_value.py` |
| `data/combat_value_human*.json` | 战斗局面估值 | 社区录像还原的逐回合局面 | `tools/replay_situations.py`、`tools/train_combat_value_human.py` |
| `data/imitation*.json` | 出牌模仿层 | 社区录像 | `tools/train_imitation.py` |
| `data/phase_profiles.json`、`data/phase_alpha.json` | 精英 / Boss 分阶段打法 | 社区录像 | `tools/phase_profiles.py`、`tools/phase_alpha.py` |
| `data/card_scores.json`、`neow_scores.json`、`event_stats.json`、`ancient_wr.json`、`relic_stats.json`、`rest_stats.json`、`upgrade_stats.json`、`human_play_rates.json`、`baselines.json` | 汇总统计 | 社区对局 / 社区录像 | `build_*.py`、`tools/*_stats.py` |
| `data/bench*.json`（`bench_a2ours.json`、`bench_a2whatif.json` 除外） | 单场战斗基准（牌组、遗物、血量、人类掉血，不含玩家身份） | 社区对局 / 社区录像 | `build_bench.py`、`tools/replay_turns.py` |
| `data/bench_a2ours.json`、`data/bench_a2whatif.json` | 单场战斗案例 | 自己的模拟（牌组）+ 社区对局（遗物出现频率） | `tools/make_a2_cases.py`、`tools/a2_whatif.py` |
| `data/combat_value.json` | 战斗局面估值 | 自己的模拟 | `tools/train_combat_value.py` |
| `data/cvnet.npz` | 战斗价值网络 | 自己的模拟（推演记录） | `tools/nn_combat_train.py` |
| `data/nn_v2.npz` | 神经网络出牌策略 | 自己的模拟（推演记录） | `tools/nn_dataset.py`、`tools/nn_train.py` |
| `data/learned_prefs.json` | 强化学习偏好权重 | 自己的模拟 | `tools/train_rl.py` |
| `data/engine_card_dicts.json` | 卡牌牌面（含英文描述） | 从 sts2-cli 引擎里读到的牌面 | 手工采集，无脚本 |

## 4. 游戏本体

《杀戮尖塔 2》（Slay the Spire 2）及其名称、卡牌 / 遗物 / 怪物的名字和文本、美术、代码的版权归 Mega Crit 所有。本项目是非官方的爱好者项目，与 Mega Crit 无关。本仓库不包含游戏文件和反编译代码；带游戏文本的知识库（`kb/cards.json` 等）需要用自己的游戏数据生成。仓库里出现的游戏内名称和 id 只用于标识；`data/engine_card_dicts.json` 里有从引擎读到的英文牌面描述、`kb/names_en.json` 是英文名到 id 的对照，只给研究工具用。
