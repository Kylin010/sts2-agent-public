#!/bin/bash
# 输出核心研究：按顺序（单进程）跑全部分析，结果存到 out/。机器忙时全部跑完约 20 分钟。
# 用法：bash run_all.sh   （第一次会解析社区对局并缓存到 $CORE_CACHE，默认放 /tmp）
cd "$(dirname "$0")"
export CORE_CACHE=${CORE_CACHE:-/tmp/sts2-core-runs.pkl}
mkdir -p out
for s in core_discover.py "core_discover.py c1" core_effects.py core_timing.py core_extra.py core_phase.py core_complete.py our_decks.py gap_decomp.py replay_damage.py replay_cores.py; do
  name=$(echo "$s" | sed 's/\.py//; s/ /-/g')
  echo "== $s"
  nice -n 10 python3 $s > "out/$name.txt" 2>&1 || echo "失败：$s"
done
