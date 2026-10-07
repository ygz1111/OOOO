#!/usr/bin/env bash
PY=/home/wy/ai-projects/tensorflow-env/bin/python
SP=/home/wy/ai-projects/tensorflow-env/lib/python3.10/site-packages

echo '=== sweep dlopen over candidate libs ==='
$PY - <<EOF
import ctypes, glob, os
cands = {
  "libcuda(wsllib)": "/usr/lib/wsl/lib/libcuda.so.1",
}
for sub in ["cudnn", "cublas", "cufft", "curand", "cusolver", "cusparse", "nccl", "cuda_nvrtc", "nvjitlink", "cuda_runtime"]:
    hits = sorted(glob.glob(f"{os.environ['SP']}/nvidia/{sub}/lib/*.so*"))
    # pick the versioned real file like libX.so.9 / libX.so.12
    real = [h for h in hits if ".so." in h and not h.endswith(".so")]
    if real: cands[sub] = real[0]
    elif hits: cands[sub] = hits[0]
for name, p in cands.items():
    try:
        ctypes.CDLL(p)
        print(f"OK   {name}: {p}")
    except OSError as e:
        print(f"FAIL {name}: {p}  -> {e}")
EOF

echo
echo '=== try TF with full LD_LIBRARY_PATH ==='
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:$SP/nvidia/cudnn/lib:$SP/nvidia/cublas/lib:$SP/nvidia/cufft/lib:$SP/nvidia/curand/lib:$SP/nvidia/cusolver/lib:$SP/nvidia/cusparse/lib:$SP/nvidia/nccl/lib:$SP/nvidia/cuda_nvrtc/lib:$SP/nvidia/nvjitlink/lib:$SP/nvidia/cuda_runtime/lib"
export TF_CPP_MIN_LOG_LEVEL=0
$PY - <<'EOF' 2>&1 | grep -vE 'port.cc|oneDNN|InitializeLog' | head -20
import tensorflow as tf
print("devices:", tf.config.list_physical_devices())
EOF
