#!/bin/bash
set -e
export http_proxy=http://172.24.64.1:7897
export https_proxy=http://172.24.64.1:7897
source /home/ygz/colab-cli/.venv/bin/activate
cd /home/ygz/colab-cli

echo "=========================================="
echo "1. 创建 Colab 目录"
echo "=========================================="
printf 'import os\nos.makedirs("/content/tf_backend/models/tensorflow_load", exist_ok=True)\nos.makedirs("/content/tf_backend/processed", exist_ok=True)\nos.makedirs("/content/tf_backend/models/tensorflow_load/artifacts/tf_orig", exist_ok=True)\nprint("Directories created successfully")\n' > /tmp/mkdirs.py
colab exec -s cd656e -f /tmp/mkdirs.py

echo "=========================================="
echo "2. 上传代码与 Scaler"
echo "=========================================="
for f in tf_layers tf_four_models tf_train_four_models; do
  for try in 1 2 3; do
    echo "上传 ${f}.py (尝试 $try)..."
    out=$(colab upload -s cd656e "/mnt/d/GitHub/OOOOOO/backend/models/tensorflow_load/${f}.py" "/content/tf_backend/models/tensorflow_load/${f}.py" 2>&1)
    if echo "$out" | grep -q "Uploaded"; then
      echo "✅ OK ${f}.py"
      break
    else
      echo "⚠️ RETRY ${f} (out: $out)"
      sleep 2
    fi
  done
done

for try in 1 2 3; do
  echo "上传 step5_scalers.pkl (尝试 $try)..."
  out=$(colab upload -s cd656e "/mnt/d/GitHub/OOOOOO/processed/step5_scalers.pkl" "/content/tf_backend/processed/step5_scalers.pkl" 2>&1)
  if echo "$out" | grep -q "Uploaded"; then
    echo "✅ OK step5_scalers.pkl"
    break
  else
    echo "⚠️ RETRY scalers (out: $out)"
    sleep 2
  fi
done

echo "=========================================="
echo "3. 上传 10 个数据分块"
echo "=========================================="
for p in /home/ygz/split_pkl/part_*; do
  n=$(basename "$p")
  ok=0
  for try in 1 2 3 4 5; do
    echo "上传 $n (尝试 $try)..."
    out=$(colab upload -s cd656e "$p" "/content/tf_backend/processed/step6_sequences.pkl.${n}" 2>&1)
    if echo "$out" | grep -q "Uploaded"; then
      echo "✅ OK ${n}"
      ok=1
      break
    else
      echo "⚠️ RETRY ${n} (out: $out)"
      sleep 3
    fi
  done
  if [ "$ok" -eq 0 ]; then
    echo "❌ FAIL ${n}"
    exit 1
  fi
done

echo "=========================================="
echo "4. 远端合并分块并校验大小"
echo "=========================================="
cat << 'EOF' > /tmp/merge_remote.py
import os
import glob

parts = sorted(glob.glob("/content/tf_backend/processed/step6_sequences.pkl.part_*"))
out_file = "/content/tf_backend/processed/step6_sequences.pkl"
print(f"找到 {len(parts)} 个分块，开始合并...")

with open(out_file, "wb") as f_out:
    for p in parts:
        with open(p, "rb") as f_in:
            f_out.write(f_in.read())

merged_size = os.path.getsize(out_file)
expected_size = 655232144
print(f"合并完成: 大小 = {merged_size:,} 字节 (期望 = {expected_size:,})")
assert merged_size == expected_size, f"大小不匹配: {merged_size} != {expected_size}"
print("✅ 远端 step6_sequences.pkl 校验通过！")
EOF

colab exec -s cd656e -f /tmp/merge_remote.py

echo "=========================================="
echo "🎉 全部上传与合并校验完成！"
echo "=========================================="
