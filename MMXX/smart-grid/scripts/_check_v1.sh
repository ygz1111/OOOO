#!/usr/bin/env bash
cd /home/wy/ai-projects/smart-grid || exit 1
echo '--- WSL runs/tf_v1 ---'
ls -la runs/tf_v1/ 2>&1 | head -12
echo '--- WSL runs/tf_v2 ---'
ls runs/tf_v2/ 2>&1 | head -6
echo '--- WSL runs/pv_v1 ---'
ls runs/pv_v1/ 2>&1 | head -6
echo '--- WSL models ---'
ls -la models/ 2>&1
echo '--- WSL runs/logs (v1/v2/pv/baselines) ---'
ls -la runs/logs/ | grep -aE 'train_tf|stage|baselines|pv' | head -20
echo '--- Windows mirror runs & models ---'
ls -la /mnt/c/MMXX/smart-grid/runs/ 2>&1 | head
ls /mnt/c/MMXX/smart-grid/runs/tf_v1/ 2>&1 | head -6
ls /mnt/c/MMXX/smart-grid/models/ 2>&1
