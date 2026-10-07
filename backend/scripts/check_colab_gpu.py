"""检查 Google Colab 中的 TensorFlow GPU 环境。"""

import tensorflow as tf


print(f"TensorFlow Version: {tf.__version__}")
gpus = tf.config.list_physical_devices("GPU")
print(f"TensorFlow GPU Available: {bool(gpus)}")
for index, gpu in enumerate(gpus):
    print(f"TensorFlow GPU Device {index}: {gpu.name}")
