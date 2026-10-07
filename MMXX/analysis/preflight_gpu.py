# -*- coding: utf-8 -*-
"""
GPU preflight for Ubuntu/WSL2 TensorFlow environment.
Run:  source /home/wy/ai-projects/tensorflow-env/bin/activate
      python preflight_gpu.py
Checks: TF/CUDA/cuDNN versions, GPU visibility, real matmul speedup GPU vs CPU.
"""
import os
import sys
import time

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf

print("Python:", sys.version.split()[0])
print("TF version:", tf.__version__)
bi = tf.sysconfig.get_build_info()
print("Built with CUDA:", bi.get("cuda_version"), "| cuDNN:", bi.get("cudnn_version"))

gpus = tf.config.list_physical_devices("GPU")
print("GPU devices:", gpus)
if not gpus:
    raise SystemExit("GPU NOT available - fix Windows WSL driver / CUDA before training")

# optional memory growth (important on 4GB RTX 3050 Laptop)
for g in gpus:
    try:
        tf.config.experimental.set_memory_growth(g, True)
    except Exception as e:  # noqa
        print("memory_growth warn:", e)

a = tf.random.normal([2048, 2048])
b = tf.random.normal([2048, 2048])


def bench(dev):
    with tf.device(dev):
        tf.matmul(a, b)  # warmup
        t0 = time.perf_counter()
        for _ in range(10):
            tf.matmul(a, b)
        return (time.perf_counter() - t0) / 10


tg, tc = bench("/GPU:0"), bench("/CPU:0")
print(f"matmul 2048^2 x10 avg -> GPU: {tg*1e3:.1f} ms | CPU: {tc*1e3:.1f} ms | speedup {tc/tg:.1f}x")
print("is_gpu_available:", tf.test.is_gpu_available(cuda_only=True))
print("GPU OK" if tf.test.is_gpu_available(cuda_only=True) and tg < tc else "GPU WARN: check benchmark")
