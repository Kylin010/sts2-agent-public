#!/bin/bash
# 第二轮战斗局面采集（带「预判未来伤害」特征）
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_cv_bench.s[h]" > /dev/null || pgrep -f "run_levels.s[h]" > /dev/null; do sleep 20; done
for B in bench.json bench_normals.json; do
  STS2_LOG_TURNS=1 STS2_BENCH=$B python3 dist.py 0 --bench --reps 6 --tag turns2-$B > lab/turns2-$B.log 2>&1
done
STS2_LOG_TURNS=1 python3 dist.py 400 --tag turns2-run80 > lab/turns2-run80.log 2>&1
