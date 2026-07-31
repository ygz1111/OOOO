"""
模型推理服务单元测试

测试内容:
  1. 模型加载（4个.pth文件）
  2. 单次推理
  3. 批量推理
  4. 集成权重正确性
  5. 逆归一化
  6. 性能监控
  7. 错误处理
  8. 线程安全
  9. 数值异常处理

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_prediction_service.py -v
"""

import unittest
import os
import sys
import time
import threading
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.prediction_service import (
    ModelInferenceService,
    ModelInferenceError,
    ModelLoadError,
    InferenceResult,
    MODEL_CONFIGS,
)


# ============================================================================
# 工具函数
# ============================================================================

def make_mock_input(batch=1, seq_len=168, n_features=38):
    """生成模拟输入数据"""
    np.random.seed(42)
    return np.random.uniform(0, 1, size=(batch, seq_len, n_features)).astype(np.float32)


# ============================================================================
# 测试类
# ============================================================================

class TestModelLoading(unittest.TestCase):
    """测试模型加载"""

    @classmethod
    def setUpClass(cls):
        """所有测试共享一个服务实例"""
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_all_models_loaded(self):
        """测试所有4个模型都加载成功"""
        self.assertEqual(len(self.service.models), 4)

    def test_model_names(self):
        """测试模型名称正确"""
        expected_names = {"EnhancedLSTM", "BiGRU", "DeepTCN", "SpatialTransformer"}
        self.assertEqual(set(self.service.models.keys()), expected_names)

    def test_models_in_eval_mode(self):
        """测试模型处于eval模式"""
        for name, model in self.service.models.items():
            self.assertFalse(model.training, f"{name} 不在 eval 模式")

    def test_model_info_recorded(self):
        """测试模型信息被记录"""
        info = self.service.get_model_info()
        self.assertEqual(len(info), 4)
        for name, data in info.items():
            self.assertTrue(data['loaded'])
            self.assertGreater(data['num_params'], 0)

    def test_ensemble_weights_sum_to_one(self):
        """测试集成权重之和为1"""
        total = sum(self.service.ensemble_weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_correct_weights(self):
        """测试权重值正确"""
        self.assertAlmostEqual(self.service.ensemble_weights["EnhancedLSTM"], 0.35, places=2)
        self.assertAlmostEqual(self.service.ensemble_weights["BiGRU"], 0.30, places=2)
        self.assertAlmostEqual(self.service.ensemble_weights["DeepTCN"], 0.15, places=2)
        self.assertAlmostEqual(self.service.ensemble_weights["SpatialTransformer"], 0.20, places=2)

    def test_nonexistent_model_dir(self):
        """测试不存在的模型目录"""
        with self.assertRaises(ModelLoadError):
            service = ModelInferenceService(models_dir="/nonexistent/path")
            service.load_models()


class TestSingleInference(unittest.TestCase):
    """测试单次推理"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_predict_returns_result(self):
        """测试推理返回正确类型"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        self.assertIsInstance(result, InferenceResult)

    def test_output_shape(self):
        """测试输出形状正确"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        # 集成预测应为 (1, 24)
        self.assertEqual(result.ensemble_prediction.shape, (1, 24))

    def test_individual_predictions(self):
        """测试各模型单独预测"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        self.assertEqual(len(result.individual_predictions), 4)
        for name, pred in result.individual_predictions.items():
            self.assertEqual(pred.shape, (1, 24))

    def test_inference_time_under_1s(self):
        """测试推理时间<1秒"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        self.assertLess(result.inference_time_ms, 1000,
                        f"推理耗时 {result.inference_time_ms}ms 超过1000ms")

    def test_prediction_values_reasonable(self):
        """测试预测值在合理范围内（MW）"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X, inverse_transform=True)

        # 负荷应在 5000~30000 MW 范围内
        preds = result.ensemble_prediction[0]
        self.assertTrue(preds.min() >= 0, "存在负负荷值")
        self.assertTrue(preds.max() < 50000, "负荷值过大")

    def test_numpy_input(self):
        """测试 numpy 输入"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)
        self.assertEqual(result.ensemble_prediction.shape, (1, 24))

    def test_tensor_input(self):
        """测试 torch.Tensor 输入"""
        X = torch.from_numpy(make_mock_input(batch=1))
        result = self.service.predict(X)
        self.assertEqual(result.ensemble_prediction.shape, (1, 24))

    def test_2d_input_auto_reshape(self):
        """测试2D输入自动扩展为3D"""
        X = make_mock_input(batch=1).squeeze(0)  # (168, 38)
        result = self.service.predict(X)
        self.assertEqual(result.ensemble_prediction.shape, (1, 24))

    def test_predict_single(self):
        """测试 predict_single 便捷方法"""
        X = make_mock_input(batch=1)
        pred = self.service.predict_single(X)

        # 应返回 (24,) 形状
        self.assertEqual(pred.shape, (24,))

    def test_no_inverse_transform(self):
        """测试不逆归一化"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X, inverse_transform=False)

        # 归一化空间预测应在 [0, 1] 附近
        preds = result.ensemble_prediction[0]
        self.assertTrue(preds.min() >= -1)
        self.assertTrue(preds.max() <= 2)


class TestBatchInference(unittest.TestCase):
    """测试批量推理"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_batch_size_4(self):
        """测试批量大小4"""
        X = make_mock_input(batch=4)
        result = self.service.predict(X)

        self.assertEqual(result.ensemble_prediction.shape, (4, 24))

    def test_batch_size_8(self):
        """测试批量大小8"""
        X = make_mock_input(batch=8)
        result = self.service.predict(X)

        self.assertEqual(result.ensemble_prediction.shape, (8, 24))

    def test_batch_consistency(self):
        """测试批量预测一致性"""
        X = make_mock_input(batch=2)
        result1 = self.service.predict(X)
        result2 = self.service.predict(X)

        np.testing.assert_almost_equal(
            result1.ensemble_prediction,
            result2.ensemble_prediction,
            decimal=4
        )


class TestEnsembleWeights(unittest.TestCase):
    """测试集成权重"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_weighted_average_correctness(self):
        """测试加权平均计算正确"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X, inverse_transform=False)

        # 手动计算加权平均
        manual_ensemble = np.zeros_like(result.ensemble_prediction)
        for name, pred in result.normalized_individual.items():
            weight = self.service.ensemble_weights[name]
            manual_ensemble += weight * pred

        np.testing.assert_almost_equal(
            result.normalized_ensemble, manual_ensemble, decimal=5
        )

    def test_ensemble_better_than_worst_individual(self):
        """测试集成预测合理（值在个体预测范围内）"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X, inverse_transform=False)

        individual_min = min(
            p.min() for p in result.normalized_individual.values()
        )
        individual_max = max(
            p.max() for p in result.normalized_individual.values()
        )

        # 集成应在个体范围的合理范围
        ensemble_val = result.normalized_ensemble.mean()
        self.assertGreaterEqual(ensemble_val, individual_min - 0.1)
        self.assertLessEqual(ensemble_val, individual_max + 0.1)


class TestNumericalHandling(unittest.TestCase):
    """测试数值异常处理"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_nan_input_handled(self):
        """测试NaN输入处理"""
        X = make_mock_input(batch=1)
        X[0, 10, 5] = np.nan
        result = self.service.predict(X)

        self.assertFalse(np.isnan(result.ensemble_prediction).any())

    def test_inf_input_handled(self):
        """测试Inf输入处理"""
        X = make_mock_input(batch=1)
        X[0, 10, 5] = np.inf
        result = self.service.predict(X)

        self.assertFalse(np.isinf(result.ensemble_prediction).any())

    def test_zero_input(self):
        """测试全零输入"""
        X = np.zeros((1, 168, 38), dtype=np.float32)
        result = self.service.predict(X)

        self.assertEqual(result.ensemble_prediction.shape, (1, 24))

    def test_wrong_feature_count(self):
        """测试错误特征数"""
        X = np.random.uniform(0, 1, (1, 168, 20)).astype(np.float32)  # 20 != 38
        with self.assertRaises(ModelInferenceError):
            self.service.predict(X)


class TestPerformanceMonitoring(unittest.TestCase):
    """测试性能监控"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_inference_time_recorded(self):
        """测试推理时间被记录"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        self.assertGreater(result.inference_time_ms, 0)

    def test_model_times_recorded(self):
        """测试各模型时间被记录"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)

        self.assertEqual(len(result.model_times_ms), 4)
        for name, t in result.model_times_ms.items():
            self.assertGreaterEqual(t, 0)

    def test_performance_stats(self):
        """测试性能统计"""
        # 记录调用前的计数
        before_stats = self.service.get_performance_stats()
        before_count = before_stats['total_inferences']

        X = make_mock_input(batch=1)
        self.service.predict(X)
        self.service.predict(X)

        stats = self.service.get_performance_stats()
        self.assertEqual(stats['total_inferences'], before_count + 2)
        self.assertGreater(stats['average_time_ms'], 0)

    def test_result_to_dict(self):
        """测试结果转字典"""
        X = make_mock_input(batch=1)
        result = self.service.predict(X)
        d = result.to_dict()

        self.assertIn('ensemble_prediction', d)
        self.assertIn('individual_predictions', d)
        self.assertIn('inference_time_ms', d)


class TestErrorHandling(unittest.TestCase):
    """测试错误处理"""

    def test_predict_without_loading(self):
        """测试未加载模型就推理"""
        service = ModelInferenceService()
        # 不调用 load_models()
        X = make_mock_input(batch=1)
        with self.assertRaises(ModelInferenceError):
            service.predict(X)

    def test_wrong_input_dimension(self):
        """测试错误输入维度"""
        service = ModelInferenceService()
        service.load_models()

        X = np.random.uniform(0, 1, (168,))  # 1D
        with self.assertRaises(ModelInferenceError):
            service.predict(X)

        service.release()


class TestConcurrency(unittest.TestCase):
    """测试并发推理"""

    @classmethod
    def setUpClass(cls):
        cls.service = ModelInferenceService()
        cls.service.load_models()

    @classmethod
    def tearDownClass(cls):
        cls.service.release()

    def test_concurrent_predictions(self):
        """测试多线程并发推理"""
        results = []
        errors = []

        def run_prediction():
            try:
                X = make_mock_input(batch=1)
                result = self.service.predict(X)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(4):
            t = threading.Thread(target=run_prediction)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"并发推理出现错误: {errors}")
        self.assertEqual(len(results), 4)

        # 所有结果形状一致
        for r in results:
            self.assertEqual(r.ensemble_prediction.shape, (1, 24))


class TestServiceLifecycle(unittest.TestCase):
    """测试服务生命周期"""

    def test_is_ready_before_load(self):
        """测试加载前 not ready"""
        service = ModelInferenceService()
        self.assertFalse(service.is_ready())

    def test_is_ready_after_load(self):
        """测试加载后 ready"""
        service = ModelInferenceService()
        service.load_models()
        self.assertTrue(service.is_ready())

    def test_release(self):
        """测试资源释放"""
        service = ModelInferenceService()
        service.load_models()
        service.release()
        self.assertEqual(len(service.models), 0)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
