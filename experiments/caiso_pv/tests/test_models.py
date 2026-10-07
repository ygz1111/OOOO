"""TensorFlow model interface checks on random mathematical tensors only."""
import sys
import unittest
from pathlib import Path

import numpy as np
import tensorflow as tf

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from models import MODEL_NAMES, ModelConfig, build_model  # noqa: E402


class ModelTests(unittest.TestCase):
    def test_three_bounded_models_have_required_shapes_and_finite_gradients(self):
        rng = np.random.default_rng(42)
        past = rng.normal(size=(2, 96, 36)).astype(np.float32)
        future = rng.normal(size=(2, 24, 35)).astype(np.float32)
        for name in MODEL_NAMES:
            with self.subTest(name=name):
                tf.keras.backend.clear_session()
                model = build_model(name, 36, 35)
                self.assertGreaterEqual(model.count_params(), 100000)
                self.assertLessEqual(model.count_params(), 2000000)
                with tf.GradientTape() as tape:
                    output = model({"past": past, "future": future}, training=True)
                    loss = tf.reduce_mean(tf.square(output))
                gradients = tape.gradient(loss, model.trainable_variables)
                self.assertEqual(tuple(output.shape), (2, 24, 1))
                self.assertTrue(all(value is not None and np.isfinite(value.numpy()).all() for value in gradients))

    def test_final_linear_layer_can_preserve_signed_solar_outputs(self):
        model = build_model("gru", 2, 2)
        output_layer = model.get_layer("solar_standardized")
        kernel, bias = output_layer.get_weights()
        output_layer.set_weights([np.zeros_like(kernel), np.full_like(bias, -2)])
        output = model({"past": np.zeros((1, 96, 2), np.float32),
                        "future": np.zeros((1, 24, 2), np.float32)}, training=False).numpy()
        np.testing.assert_array_equal(output, np.full((1, 24, 1), -2))

    def test_wrong_task_or_window_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            build_model("unknown", 20, 18)
        with self.assertRaises(ValueError):
            build_model("gru", 20, 18, ModelConfig(past_hours=48))


if __name__ == "__main__":
    unittest.main()
