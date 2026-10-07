#!/bin/bash
# 续传：从 part_ac 开始上传剩余分块 + 合并校验
set -e
export http_proxy=http://172.24.64.1:7897
export https_proxy=http://172.24.64.1:7897
source /home/ygz/colab-cli/.venv/bin/activate

echo "=========================================="
echo "续传剩余数据分块 (part_ac ~ part_aj)"
echo "=========================================="
for p in /home/ygz/split_pkl/part_a{c,d,e,f,g,h,i,j}; do
  n=$(basename "$p")
  ok=0
  for try in 1 2 3 4 5; do
    echo "上传 $n (尝试 $try)..."
    out=$(colab upload -s cd656e "$p" "/content/tf_backend/processed/step6_sequences.pkl.${n}" 2>&1)
    if echo "$out" | grep -q "Uploaded"; then
      echo "OK ${n}"
      ok=1
      break
    else
      echo "RETRY ${n} (try ${try})"
      sleep 5
    fi
  done
  if [ "$ok" -eq 0 ]; then
    echo "FAIL ${n}"
    exit 1
  fi
done

echo "=========================================="
echo "远端合并分块并校验"
echo "=========================================="
cat << 'PYEOF' > /tmp/merge_remote.py
import os, glob
parts = sorted(glob.glob("/content/tf_backend/processed/step6_sequences.pkl.part_*"))
out_file = "/content/tf_backend/processed/step6_sequences.pkl"
print(f"Found {len(parts)} chunks, merging...")
with open(out_file, "wb") as f_out:
    for p in parts:
        with open(p, "rb") as f_in:
            f_out.write(f_in.read())
merged_size = os.path.getsize(out_file)
expected = 655232144
print(f"Merged size: {merged_size:,} bytes (expected: {expected:,})")
assert merged_size == expected, f"SIZE MISMATCH: {merged_size} != {expected}"
print("Merge verified OK!")
PYEOF

colab exec -s cd656e -f /tmp/merge_remote.py

echo "=========================================="
echo "ALL DONE - Upload + Merge complete"
echo "=========================================="
