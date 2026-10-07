#!/usr/bin/env bash
cd /home/wy/ai-projects/smart-grid || exit 1
echo '--- runs/tf_v1 ---'
ls -la runs/tf_v1/
echo '--- models ---'
ls -la models/
echo '--- logs ---'
ls -la runs/logs/ | head -20
echo '--- tensorboard files ---'
find runs/tensorboard -type f | head -10
echo '--- figures count (wsl) ---'
ls figures/thesis/*.png | wc -l
echo '--- figures count (win mirror) ---'
ls /mnt/c/MMXX/smart-grid/figures/thesis/*.png | wc -l
echo '--- index exists both sides? ---'
ls -la figures/thesis/FIGURES_INDEX.md /mnt/c/MMXX/smart-grid/figures/thesis/FIGURES_INDEX.md
