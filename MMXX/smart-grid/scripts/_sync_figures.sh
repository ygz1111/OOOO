#!/usr/bin/env bash
set -e
cd /home/wy/ai-projects/smart-grid
mkdir -p /mnt/c/MMXX/smart-grid/figures/thesis
cp figures/thesis/*.png /mnt/c/MMXX/smart-grid/figures/thesis/
cp /mnt/c/MMXX/smart-grid/figures/thesis/FIGURES_INDEX.md figures/thesis/
echo "--- WSL figures/thesis ---"
ls -1 figures/thesis/ | grep -c '\.png$'
echo "--- Windows mirror figures/thesis ---"
ls -1 /mnt/c/MMXX/smart-grid/figures/thesis/ | grep -c '\.png$'
echo "--- metrics.json ---"
cat runs/tf_v1/metrics.json
