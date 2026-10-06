#!/bin/bash
cd /opt/slay-the-spire-2/agent
STS2_BENCH=bench.json python3 dist.py 0 --bench --reps 2 --tag pot-bench > lab/pot-bench.log 2>&1
