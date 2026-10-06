#!/bin/bash
# 全局默认值调整的战斗基准对比（三幕实验室数据里一致的方向）
cd /opt/slay-the-spire-2/agent
while [ ! -f results/g999-v10-pm3.jsonl ]; do sleep 20; done
NEW="--set power_weight=1.0 --set alpha_base=0.15 --set block_mult=1.2 --set draw_value=2.0 --set long_max=2.0"
for B in bench.json bench_normals.json; do
  STS2_BENCH=$B python3 dist.py 0 --bench --reps 2 --tag def-old-$B > lab/def-old-$B.log 2>&1
  STS2_BENCH=$B python3 dist.py 0 --bench --reps 2 --tag def-new-$B $NEW > lab/def-new-$B.log 2>&1
done
