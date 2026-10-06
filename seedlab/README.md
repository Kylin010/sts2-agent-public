# 种子研究（seedlab）

用来研究「难打的种子」：脚本输掉的种子自动收集到 `hard_seeds.jsonl`，再用不同流派分别去打，看哪种能赢。
结论写进 `NOTES.md`，能推广的规则再改进主策略（`policy/`、`kb/`）。

| 文件 | 内容 |
|---|---|
| `hard_seeds.jsonl` | 输掉的种子：哪个版本、死在第几幕第几层、死在谁手里、最终牌组（`run.py` 跑完整对局时自动追加） |
| `archetypes.json` | 流派定义：选牌时给哪些标签的牌加分，用来「强制」某种流派 |
| `try_seed.py` | 对一个或几个种子，每种流派各打一局：`python3 seedlab/try_seed.py 种子1 种子2` |
| `results.jsonl` | `try_seed.py` 的结果 |
| `NOTES.md` | 观察记录：这个种子难在哪、哪种流派能过 |

种子都是游戏自己生成的（12 位，字符集不含 O 和 I），不是自己编的。
