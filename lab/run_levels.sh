#!/bin/bash
cd /opt/slay-the-spire-2/agent
while pgrep -f "run_v4_ab.s[h]" > /dev/null || pgrep -f "run_collect_turns.s[h]" > /dev/null; do sleep 20; done
python3 curriculum.py --start 500 --once --tag lvl-v12 > lab/lvl500.log 2>&1
python3 curriculum.py --start 80 --once --tag lvl-v12 > lab/lvl80.log 2>&1
