#!/bin/bash
# 采集战斗局面（训练战斗估值模型）：两个基准各 6 个种子
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_arch_ab.s[h]" > /dev/null; do sleep 20; done
for B in bench.json bench_normals.json; do
  STS2_LOG_TURNS=1 STS2_BENCH=$B python3 dist.py 0 --bench --reps 6 --tag turns-$B > lab/turns-$B.log 2>&1
done
