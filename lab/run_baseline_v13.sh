#!/bin/bash
# 修好选牌竞态后的新基线：战斗基准、999 血整局、80 血整局
cd /opt/slay-the-spire-2/agent
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag v13-bench > lab/v13-bench.log 2>&1
python3 curriculum.py --start 999 --once --tag v13 > lab/v13-999.log 2>&1
python3 curriculum.py --start 80 --once --tag v13 > lab/v13-80.log 2>&1
