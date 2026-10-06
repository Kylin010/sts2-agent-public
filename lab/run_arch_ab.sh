#!/bin/bash
cd /opt/slay-the-spire-2/agent
python3 dist.py 400 --god 999 --tag g999-v11-base > lab/ab-v11-base.log 2>&1
python3 dist.py 400 --god 999 --tag g999-v11-arch --set arch_weight=0.6 > lab/ab-v11-arch.log 2>&1
