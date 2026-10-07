#!/usr/bin/env bash
export TF_CPP_MIN_LOG_LEVEL=0
PY=/home/wy/ai-projects/tensorflow-env/bin/python
echo '=== nvidia pip pkgs in venv ==='
$PY -m pip list 2>/dev/null | grep -iE 'nvidia|cudnn|cublas|cuda' || echo '(none)'
echo
echo '=== site-packages nvidia dirs ==='
ls /home/wy/ai-projects/tensorflow-env/lib/python3.10/site-packages/ 2>/dev/null | grep -iE 'nvidia|cudnn|cublas' || echo '(none)'
echo
echo '=== /usr/lib/wsl/lib ==='
ls -la /usr/lib/wsl/lib/ 2>&1 | head -30
echo
echo '=== ldconfig matches ==='
ldconfig -p 2>/dev/null | grep -iE 'libcuda|libcudnn|cublas|cufft|curand|libnvrtc' | head -20 || echo '(no matches)'
echo
echo '=== nvcc ==='
which nvcc 2>/dev/null || echo '(nvcc not found)'
echo
echo '=== LD_LIBRARY_PATH ==='
echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-<unset>}"
echo
echo '=== TF verbose device probe ==='
$PY - <<'EOF' 2>&1 | head -60
import tensorflow as tf
try:
    print("visible devices:", tf.config.list_physical_devices())
except Exception as e:
    print("probe exception:", e)
print("BUILD:", tf.sysconfig.get_build_info().get("cuda_version"),
      tf.sysconfig.get_build_info().get("cudnn_version"))
EOF
