#!/usr/bin/env bash
set -e
cd /home/wy/ai-projects/smart-grid
D=/mnt/c/MMXX/smart-grid
mkdir -p "$D/figures/pv" "$D/runs/pv_v1" "$D/models"
cp figures/pv/*.png figures/pv/FIGURES_INDEX.md "$D/figures/pv/"
cp runs/pv_v1/metrics.json runs/pv_v1/train_log.csv "$D/runs/pv_v1/"
cp models/pv_v1_best.weights.h5 "$D/models/"
echo "pv figures: $(ls figures/pv/*.png | wc -l) wsl / $(ls "$D/figures/pv/"*.png | wc -l) win"
