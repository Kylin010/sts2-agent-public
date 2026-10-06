#!/bin/bash
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_collect_turns.s[h]" > /dev/null || [ ! -f data/relic_model_v4.json ]; do sleep 20; done
python3 dist.py 400 --god 999 --tag g999-v12-pm4 --set pick_model_file=data/pick_model_v4.json --set relic_model_file=data/relic_model_v4.json > lab/ab-v12-pm4.log 2>&1
