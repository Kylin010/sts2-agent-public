#!/bin/bash
# 第二、三幕遭遇实验室，依次跑
cd /opt/slay-the-spire-2/agent
python3 -u lab.py --act 2 --k 24 --tag lab-a2 > lab/run-a2.log 2>&1
python3 -u lab.py --act 3 --k 24 --tag lab-a3 > lab/run-a3.log 2>&1
