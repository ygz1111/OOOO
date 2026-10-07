"""T4-only formal training entry. Run only after official sample approval."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import tensorflow as tf


def main() -> None:
    devices = tf.config.list_physical_devices("GPU")
    names = [tf.config.experimental.get_device_details(device).get("device_name", "") for device in devices]
    if not tf.test.is_built_with_cuda() or not any("T4" in name for name in names):
        raise RuntimeError(f"Formal Colab entry requires the requested NVIDIA T4 runtime; detected {names}")
    print(json.dumps({"tensorflow": tf.__version__, "gpu_devices": names, "role": "formal training after approved samples"}))
    subprocess.run([sys.executable, str(Path(__file__).with_name("train.py")), *sys.argv[1:]], check=True)


if __name__ == "__main__":
    main()
