#!/usr/bin/env bash
cd /home/wy/ai-projects/smart-grid || exit 1
D=/mnt/c/MMXX/smart-grid/runs
mkdir -p "$D/tf_v1" "$D/logs"
cp runs/tf_v1/metrics.json runs/tf_v1/train_log.csv "$D/tf_v1/"
cp runs/logs/train_tf.log "$D/logs/"
ls -la "$D/tf_v1/"
