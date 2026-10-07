"""Run the uploaded TensorFlow PV training script inside Colab."""

import os
import runpy


os.environ["PV_SEED"] = "42"
runpy.run_path("/content/smart-grid/scripts/train_pv.py", run_name="__main__")
