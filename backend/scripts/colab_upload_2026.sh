#!/bin/bash
# 上传 2026 数据集（13 块 + scaler）
source /home/ygz/colab-cli/.venv/bin/activate
cd /home/ygz/colab-cli

echo "STEP scaler"
for try in 1 2 3; do
  out=$(colab upload -s cd656e /mnt/d/GitHub/OOOOOO/processed/tf_step5_scalers_2026.pkl /content/tf_backend/processed/tf_step5_scalers_2026.pkl 2>&1 | tail -1)
  if echo "$out" | grep -q "Uploaded"; then echo "OK scaler"; break; else echo "RETRY scaler ${try}"; sleep 3; fi
done

echo "STEP chunks"
for p in /home/ygz/split26/p26_*; do
  n=$(basename "$p")
  ok=0
  for try in 1 2 3 4 5; do
    out=$(colab upload -s cd656e "$p" "/content/tf_backend/processed/tf_step6_2026.pkl.${n}" 2>&1 | tail -1)
    if echo "$out" | grep -q "Uploaded"; then
      echo "OK ${n}"
      ok=1
      break
    else
      echo "RETRY ${n} try${try}"
      sleep 3
    fi
  done
  if [ "$ok" -eq 0 ]; then echo "FAIL ${n}"; fi
done
echo ALL_DONE
