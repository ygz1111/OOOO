#!/usr/bin/env bash
# GPU-enabled run wrapper for the tensorflow-env venv in WSL2.
# Fixes: TF 2.21 cannot auto-discover bundled nvidia-* pip libs in this venv.
SP=/home/wy/ai-projects/tensorflow-env/lib/python3.10/site-packages
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:$SP/nvidia/cudnn/lib:$SP/nvidia/cublas/lib:$SP/nvidia/cufft/lib:$SP/nvidia/curand/lib:$SP/nvidia/cusolver/lib:$SP/nvidia/cusparse/lib:$SP/nvidia/nccl/lib:$SP/nvidia/cuda_nvrtc/lib:$SP/nvidia/nvjitlink/lib:$SP/nvidia/cuda_runtime/lib"
exec "$@"
