"""Read-only TensorFlow/device probe; never starts training or edits models."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def main() -> None:
    report = {
        "purpose": "hardware_probe_only_not_training",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timestamp_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    import tensorflow as tf

    devices = tf.config.list_physical_devices("GPU")
    report.update(tensorflow=tf.__version__, cuda_build=tf.test.is_built_with_cuda())
    report["gpus"] = [device.name for device in devices]
    for device in devices:
        tf.config.experimental.set_memory_growth(device, True)
    device_name = "/GPU:0" if devices else "/CPU:0"
    with tf.device(device_name):
        x = tf.ones((256, 256), dtype=tf.float32)
        started = time.perf_counter()
        result = tf.matmul(x, x)
        finite = bool(tf.reduce_all(tf.math.is_finite(result)).numpy())
    report["matmul_smoke"] = {
        "finite": finite,
        "device": result.device,
        "seconds": round(time.perf_counter() - started, 6),
    }
    try:
        process = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        report["nvidia_smi"] = {
            "returncode": process.returncode,
            "devices": process.stdout.strip(),
            "error": process.stderr.strip() if process.returncode else None,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        report["nvidia_smi"] = {"error": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
