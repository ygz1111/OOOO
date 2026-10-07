#!/usr/bin/env bash
set -e
cd /home/wy/ai-projects/smart-grid
D=/mnt/c/MMXX/smart-grid
# figures + index
cp figures/thesis/*.png "$D/figures/thesis/"
cp figures/thesis/FIGURES_INDEX.md "$D/figures/thesis/"
# runs artifacts (final tf_v2) + logs
mkdir -p "$D/runs/tf_v2" "$D/runs/logs" "$D/models"
cp runs/tf_v2/metrics.json runs/tf_v2/calibration.json runs/tf_v2/train_log.csv "$D/runs/tf_v2/"
cp runs/logs/stage1_v2.log runs/logs/train_tf_v2.log "$D/runs/logs/"
cp models/tf_v2_best.weights.h5 "$D/models/"
echo PNGs: $(ls figures/thesis/*.png | wc -l) wsl / $(ls "$D/figures/thesis/"*.png | wc -l) win
