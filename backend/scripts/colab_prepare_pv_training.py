"""Prepare the directory layout for TensorFlow PV training on Colab."""

from pathlib import Path

import tensorflow as tf


for path in (
    "/content/smart-grid/scripts",
    "/content/smart-grid/data/processed",
    "/content/smart-grid/models",
    "/content/smart-grid/runs/pv_v1",
    "/content/smart-grid/runs/tensorboard/pv_v1",
):
    Path(path).mkdir(parents=True, exist_ok=True)

gpus = tf.config.list_physical_devices("GPU")
if not gpus:
    raise RuntimeError("TensorFlow cannot see a Colab GPU")

print("PV training workspace ready")
print("TensorFlow:", tf.__version__)
print("GPU:", gpus[0].name)
