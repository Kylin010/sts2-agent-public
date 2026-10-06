#!/bin/bash
# 战斗估值模型的基准测试：权重 0 / 0.5 / 1（精英 + Boss 基准，每案例 2 个种子）
cd /opt/slay-the-spire-2/agent
for W in 0 0.5 1.0; do
  STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag cv$W-bench --set cv_weight=$W > lab/cv$W-bench.log 2>&1
done
