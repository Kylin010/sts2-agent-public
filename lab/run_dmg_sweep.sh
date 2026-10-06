#!/bin/bash
# 伤害效率扫描：易伤持续价值、能力牌权重（只测第一幕三个 Boss，每案例 3 个种子）
cd /opt/slay-the-spire-2/agent
O="--only VANTOM_BOSS,CEREMONIAL_BEAST_BOSS,THE_KIN_BOSS --reps 3"
STS2_BENCH=bench.json python3 dist.py 0 --bench $O --tag dmg-base > lab/dmg-base.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench $O --tag dmg-vuln2 --set vuln_future=2.0 > lab/dmg-vuln2.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench $O --tag dmg-pw12 --set power_weight=1.2 > lab/dmg-pw12.log 2>&1
STS2_BENCH=bench.json python3 dist.py 0 --bench $O --tag dmg-both --set vuln_future=2.0 --set power_weight=1.2 > lab/dmg-both.log 2>&1
