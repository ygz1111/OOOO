#!/usr/bin/env bash
cd /home/wy/ai-projects/smart-grid || exit 1
rm -rf runs/baselines /mnt/c/MMXX/smart-grid/runs/baselines 2>/dev/null
echo '--- final runs (WSL) ---'
ls -1 runs/
echo '--- final tensorboard ---'
ls -1 runs/tensorboard/ 2>/dev/null
