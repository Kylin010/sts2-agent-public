#!/bin/bash
cd /opt/slay-the-spire-2/agent
for W in 0.5 1.0; do
  STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag cv3-$W-bench --set cv_weight=$W > lab/cv3-$W-bench.log 2>&1
done
