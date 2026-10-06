#!/bin/bash
# 格挡偏好扫描（脚本挡掉来伤的比例 52~58%，人类 65~70%）
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_baseline_v13.s[h]" > /dev/null; do sleep 20; done
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag blk-bm15 --set block_mult=1.5 > lab/blk-bm15.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag blk-bm20 --set block_mult=2.0 > lab/blk-bm20.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag blk-amax10 --set alpha_max=1.0 > lab/blk-amax10.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag blk-abase --set alpha_base=0.1 --set alpha_min=0.15 > lab/blk-abase.log 2>&1
