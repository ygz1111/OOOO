# -*- coding: utf-8 -*-
"""评估指标口径测试：反归一化真实单位 + 统一掩码 MAPE。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compute_metrics(y_true_mw, y_pred_mw):
    """与 scripts/recompute_final_metrics.py 完全一致的统一指标口径"""
    y_true = np.asarray(y_true_mw).flatten()
    y_pred = np.asarray(y_pred_mw).flatten()
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mask = np.abs(y_true) > 1.0
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100) if np.any(mask) else float("nan")
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
    return {"mae": mae, "rmse": rmse, "mape": mape, "r2": r2}


class TestUnifiedMetrics:
    def test_perfect_prediction(self):
        y_true = np.array([10000.0, 12000.0, 15000.0, 18000.0])
        m = _compute_metrics(y_true, y_true)
        assert m["mae"] == 0.0
        assert m["rmse"] == 0.0
        assert m["mape"] == 0.0
        assert m["r2"] == 1.0

    def test_known_error(self):
        """10% 偏差（1000/10000）→ MAPE 应恰为 10%，而非归一化空间的虚高值"""
        y_true = np.array([10000.0, 10000.0, 10000.0, 10000.0])
        y_pred = y_true + 1000.0
        m = _compute_metrics(y_true, y_pred)
        assert abs(m["mape"] - 10.0) < 1e-6

    def test_mape_mask_ignores_tiny_values(self):
        """|y_true|<=1 的值被掩码排除，不会造成分母趋零的虚高"""
        y_true = np.array([0.5, 0.5, 10000.0])
        y_pred = np.array([50.0, 50.0, 11000.0])
        m = _compute_metrics(y_true, y_pred)
        # 若不过滤小值，MAPE 会被 0.5 的小分母拉到天文数字
        assert m["mape"] < 20.0

    def test_r2_range(self):
        rng = np.random.RandomState(42)
        y_true = 12000 + 2000 * np.sin(np.arange(100))
        y_pred = y_true + rng.normal(0, 500, 100)
        m = _compute_metrics(y_true, y_pred)
        assert 0.0 < m["r2"] < 1.0
