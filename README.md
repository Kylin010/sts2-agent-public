An automated agent for Slay the Spire 2 (Ironclad) — a turn planner plus public-information search that only uses what a human player can see.

# sts2-agent：杀戮尖塔 2 铁甲战士自动打牌程序

自动打《杀戮尖塔 2》的程序，角色是铁甲战士，主要在进阶 10 上开发。战斗里，**规划器**每回合列出所有付得起的出牌组合，按伤害、格挡、击杀、掉血打分；**公开信息推演**在另开的引擎里只按看得见的局面摆出战斗、用独立的随机种子往后试打。选牌、路线、商店、篝火、事件、药水各有一个决策模块，部分决策用从社区对局训练的小模型打分。

## 只用玩家看得见的信息

- 决策只用玩家在界面上能看到的东西：手牌、能量、敌人的血量和意图、抽牌堆 / 弃牌堆里有哪些牌（不看顺序）、地图、商店货架等。
- 不读档重来，不读游戏真实的未来随机数，也不读隐藏的抽牌顺序。
- 怪物的固定出招循环可以按游戏机制推算；随机分支只按公开的概率算。

## 需要准备

1. **自己购买的《杀戮尖塔 2》**（Steam，开发时用的是 v0.111.0 测试版）。本仓库不包含任何游戏文件。
2. **[sts2-cli](https://github.com/wuhao21/sts2-cli)**：在后台运行真游戏引擎的命令行工具。按它的 README 用自己的游戏文件搭好，需要 .NET 9 SDK。
3. **给 sts2-cli 打上本仓库的补丁**：补丁基于上游提交 `084d1aa`（v0.111.0），按顺序打 10–19 号：

   ```bash
   cd sts2-cli
   git checkout 084d1aa3d8e118ca7ce8d8774ad16d6be9c92367
   for n in 10 11 12 13 14 15 16 17 18 19; do git apply /path/to/sts2-agent/patches/$n-*.patch; done
   # 然后按 sts2-cli 的说明重新构建，得到 src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll
   ```

   01–09 号是早期的单项补丁，已经合在 10 号里；`codex-*` 开头的是实验性补丁，不用打。
4. **Python 3.10 以上和 numpy。**
5. **生成知识库**：`kb/` 里有几份文件带游戏文本，不随仓库分发，要用自己的游戏数据生成。两个脚本开头写的是开发机上的绝对路径，先改成自己的：
   - `kb/cards.json`、`kb/relics.json`、`kb/potions.json`：运行 `python3 build_knowledge.py`。输入是 [spire-codex](https://github.com/ptrlrd/spire-codex) 格式的游戏数据（`data-beta/v0.111.0/{eng,zhs}/*.json`），可以用 spire-codex 的工具从自己的游戏文件解出来；路径在脚本的 `SRC`。
   - `kb/monsters.json`、`kb/encounters_src.json`：先用 ILSpy 之类的工具把自己游戏目录里的 `sts2.dll` 按命名空间反编译到一个目录（脚本默认 `decompiled/v0.111.0/`），再运行 `python3 tools/extract_monsters.py`；脚本开头的 `ROOT`（反编译目录、sts2-cli 的本地化目录）和 `KB`（本仓库的 `kb/`）要改成自己的路径。

## 打一局

```bash
export STS2_CLI_DIR=/path/to/sts2-cli   # 打过补丁的 sts2-cli
export DOTNET=/path/to/dotnet            # .NET 9 的 dotnet 可执行文件

python3 run.py 1 --verbose               # 打一局，逐步打印每个决定
python3 run.py 40 --tag v1               # 打 40 局（种子来自 data/dev_seeds.txt），结果写到 results/v1.jsonl
python3 run.py 100 --stop-act 1          # 只打第一幕
python3 run.py 0 --bench                 # 战斗基准：用社区玩家当时的牌组 / 遗物 / 血量打同一场战斗
python3 run.py 40 --set alpha_max=1.2    # 临时改参数（所有参数在 params.json）
```

多台机器一起跑：把 `machines.example.json` 复制成 `machines.local.json`，填上自己的机器（这个文件已在 `.gitignore` 里），然后用 `python3 dist.py`，参数和 `run.py` 一样。

## 目录

| 位置 | 内容 |
|---|---|
| `run.py`、`sim.py` | 批量对局入口；和 sts2-cli 引擎通信 |
| `policy/` | 各类决策：战斗规划（`combat.py`）、推演（`search.py`）、选牌、路线、商店、篝火、事件、药水 |
| `params.json`、`params.py` | 所有可调参数 |
| `data/` | 汇总统计和训练好的模型权重（来源见 `THIRD_PARTY_NOTICES.md`） |
| `kb/` | 手写的机制规则、联动表、遭遇参数；带游戏文本的部分要自己生成（见上文） |
| `tools/`、`build_*.py` | 训练、统计、诊断脚本 |
| `patches/` | 对 sts2-cli 的补丁 |
| `docs/`、`reviews/` | 研究笔记和代码审查记录 |
| `tests/` | 测试 |
| `lab/`、`seedlab/` | 实验配置和固定种子集 |

## 数据来源和许可

- 本仓库的代码：MIT，见 `LICENSE`。
- `patches/` 修改的是 sts2-cli（MIT，作者 Hao Wu）。
- `data/` 里的统计和模型权重，大部分来自 [spire-codex](https://spire-codex.com) 公开的社区对局和录像（PolyForm Noncommercial 1.0.0），**只能用于非商业用途**；其余来自本程序自己的模拟对局。仓库里没有原始对局、录像或玩家身份信息。每个文件的来源见 `THIRD_PARTY_NOTICES.md`。
- 《杀戮尖塔 2》及其名称、文本、美术的版权归 Mega Crit 所有。这是非官方的爱好者项目，与 Mega Crit 无关。
