#!/bin/bash
# 用两轮全部数据重训估值模型，再测 0.3 / 0.5 / 0.7 三档权重（精英 + Boss 基准）
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_collect2.s[h]" > /dev/null; do sleep 20; done
python3 -u tools/train_combat_value.py --epochs 60 --lr 1e-3 > lab/train_cv4.log 2>&1
for W in 0 0.3 0.5 0.7; do
  STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag cv4-$W-bench --set cv_weight=$W > lab/cv4-$W-bench.log 2>&1
done
