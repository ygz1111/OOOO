#!/usr/bin/env bash
set -e
cd /home/wy/ai-projects/smart-grid || exit 1

echo '--- removing tf_v1 artifacts (WSL) ---'
rm -rf runs/tf_v1 runs/tensorboard/tf_v1 models/tf_v1_best.weights.h5
rm -f runs/logs/train_tf.log runs/logs/stage3_baselines.log

echo '--- removing tf_v1 artifacts (Windows mirror) ---'
rm -rf /mnt/c/MMXX/smart-grid/runs/tf_v1
rm -f /mnt/c/MMXX/smart-grid/runs/logs/train_tf.log /mnt/c/MMXX/smart-grid/runs/logs/stage3_baselines.log

echo '--- surviving runs (WSL) ---'
ls -1 runs/
echo '--- surviving models (WSL) ---'
ls -1 models/
echo '--- surviving logs (WSL) ---'
ls -1 runs/logs/ | grep -av '^total'
echo '--- surviving runs (Windows mirror) ---'
ls -1 /mnt/c/MMXX/smart-grid/runs/ 2>/dev/null
echo '--- surviving models (Windows mirror) ---'
ls -1 /mnt/c/MMXX/smart-grid/models/ 2>/dev/null
echo '--- figures ---'
echo thesis: $(ls figures/thesis/*.png | wc -l) pv: $(ls figures/pv/*.png | wc -l)
echo any tf_v1 leftovers:
find . /mnt/c/MMXX/smart-grid -maxdepth 3 -iname '*tf_v1*' 2>/dev/null | head
