#!/usr/bin/env bash
export TF_CPP_MIN_LOG_LEVEL=0
PY=/home/wy/ai-projects/tensorflow-env/bin/python
$PY - <<'EOF' > /tmp/tf_full.log 2>&1
import tensorflow as tf
print("visible:", tf.config.list_physical_devices())
EOF
echo "=== relevant error lines ==="
grep -iE 'dlopen|could not|cannot|not found|error|failed|no such file|undefined symbol' /tmp/tf_full.log | head -40
echo
echo "=== first 60 lines of log ==="
head -60 /tmp/tf_full.log
