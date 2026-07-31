"""
净负荷计算模块单元测试

测试内容:
  1. 基础净负荷计算
  2. 峰谷识别
  3. 储能调度（削峰填谷）
  4. 弃光处理
  5. 电网容量约束
  6. 爬坡约束
  7. 经济调度成本
  8. 调度建议
  9. 分钟级分辨率
  10. 边界情况

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_net_load_calculator.py -v
"""

import unittest
import os
import sys
import math
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.net_load_calculator import (
    NetLoadCalculator,
    NetLoadResult,
    HourlyResult,
    GridConstraints,
    StorageParams,
    GenerationMix,
    NetLoadError,
)


# ============================================================================
# 辅助函数
# ============================================================================

def make_mock_load_pv(n=24, pv_peak=400, load_base=12000, load_peak=3000):
    """生成模拟负荷和光伏数据"""
    np.random.seed(42)
    hours = np.arange(n)
    load = load_base + load_peak * np.sin((hours - 14) * np.pi / 12) + np.random.normal(0, 200, n)
    pv = np.array([
        max(0, pv_peak * np.sin((h - 6) * np.pi / 12)) if 6 <= h <= 18 else 0
        for h in hours
    ])
    return load, pv


# ============================================================================
# 基础计算测试
# ============================================================================

class TestBasicCalculation(unittest.TestCase):
    """测试基础净负荷计算"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_result_type(self):
        """测试返回类型正确"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertIsInstance(result, NetLoadResult)

    def test_hourly_count(self):
        """测试24小时结果"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertEqual(len(result.hourly), 24)

    def test_net_load_formula(self):
        """测试净负荷 = 负荷 - 光伏"""
        result = self.calc.calculate(self.load, self.pv)
        for i, h in enumerate(result.hourly):
            expected_net = self.load[i] - self.pv[i]
            self.assertAlmostEqual(h.net_load_mw, expected_net, places=1)

    def test_total_load_mwh(self):
        """测试总负荷"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertAlmostEqual(result.total_load_mwh, self.load.sum(), places=0)

    def test_total_pv_mwh(self):
        """测试总光伏"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertAlmostEqual(result.total_pv_mwh, self.pv.sum(), places=0)

    def test_negative_load_handled(self):
        """测试负负荷被裁剪为0"""
        load = np.array([-100, 5000, 10000])
        pv = np.array([0, 0, 0])
        result = self.calc.calculate(load, pv)
        self.assertGreaterEqual(result.hourly[0].load_forecast_mw, 0)

    def test_length_mismatch_raises(self):
        """测试长度不匹配抛出异常"""
        with self.assertRaises(NetLoadError):
            self.calc.calculate(np.array([1, 2, 3]), np.array([1, 2]))


# ============================================================================
# 峰谷识别测试
# ============================================================================

class TestPeakValleyIdentification(unittest.TestCase):
    """测试峰谷时段识别"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_peak_hours_exist(self):
        """测试峰值时段被识别"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreater(len(result.peak_hours), 0)

    def test_valley_hours_exist(self):
        """测试谷值时段被识别"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreater(len(result.valley_hours), 0)

    def test_peak_valley_no_overlap(self):
        """测试峰谷不重叠"""
        result = self.calc.calculate(self.load, self.pv)
        overlap = set(result.peak_hours) & set(result.valley_hours)
        self.assertEqual(len(overlap), 0)

    def test_peak_hours_marked(self):
        """测试峰值时段标记"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.peak_hours:
            self.assertTrue(result.hourly[h].is_peak)

    def test_valley_hours_marked(self):
        """测试谷值时段标记"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.valley_hours:
            self.assertTrue(result.hourly[h].is_valley)

    def test_peak_load_higher_than_valley(self):
        """测试峰值负荷高于谷值"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreater(result.peak_load_mw, result.valley_load_mw)


# ============================================================================
# 储能调度测试
# ============================================================================

class TestStorageDispatch(unittest.TestCase):
    """测试储能充放电调度"""

    def setUp(self):
        self.storage = StorageParams(
            capacity_mwh=400, power_charge_mw=200,
            power_discharge_mw=200, soc_initial=0.5
        )
        self.calc = NetLoadCalculator(storage=self.storage)
        self.load, self.pv = make_mock_load_pv()

    def test_soc_in_range(self):
        """测试SOC在约束范围内"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.hourly:
            self.assertGreaterEqual(h.soc_percent, self.storage.soc_min * 100 - 1)
            self.assertLessEqual(h.soc_percent, self.storage.soc_max * 100 + 1)

    def test_charge_during_valley(self):
        """测试谷值时段充电"""
        result = self.calc.calculate(self.load, self.pv)
        valley_charges = [h.storage_charge_mw for h in result.hourly if h.is_valley]
        if valley_charges:
            self.assertGreater(max(valley_charges), 0)

    def test_discharge_during_peak(self):
        """测试峰值时段放电"""
        result = self.calc.calculate(self.load, self.pv)
        peak_discharges = [h.storage_discharge_mw for h in result.hourly if h.is_peak]
        if peak_discharges:
            self.assertGreater(max(peak_discharges), 0)

    def test_charge_power_limit(self):
        """测试充电功率不超限"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.hourly:
            self.assertLessEqual(h.storage_charge_mw, self.storage.power_charge_mw + 0.1)

    def test_discharge_power_limit(self):
        """测试放电功率不超限"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.hourly:
            self.assertLessEqual(h.storage_discharge_mw, self.storage.power_discharge_mw + 0.1)

    def test_storage_totals_recorded(self):
        """测试储能总量被记录"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreaterEqual(result.total_storage_charged_mwh, 0)
        self.assertGreaterEqual(result.total_storage_discharged_mwh, 0)


# ============================================================================
# 弃光处理测试
# ============================================================================

class TestCurtailment(unittest.TestCase):
    """测试光伏弃光处理"""

    def test_no_curtailment_normal(self):
        """测试正常情况无弃光"""
        calc = NetLoadCalculator()
        load = np.full(24, 15000.0)
        pv = np.full(24, 500.0)
        result = calc.calculate(load, pv)
        self.assertEqual(result.total_curtailed_mwh, 0.0)

    def test_curtailment_high_pv(self):
        """测试高光伏时有弃光"""
        grid = GridConstraints(reverse_flow_limit_mw=1000.0)
        calc = NetLoadCalculator(grid=grid)
        # 光伏远超负荷
        load = np.array([5000] * 24, dtype=float)
        pv = np.array([8000] * 24, dtype=float)
        result = calc.calculate(load, pv)
        self.assertGreater(result.total_curtailed_mwh, 0)

    def test_curtailment_nonnegative(self):
        """测试弃光量非负"""
        calc = NetLoadCalculator()
        load, pv = make_mock_load_pv(pv_peak=5000)
        result = calc.calculate(load, pv)
        for h in result.hourly:
            self.assertGreaterEqual(h.curtailed_pv_mw, 0)


# ============================================================================
# 电网约束测试
# ============================================================================

class TestGridConstraints(unittest.TestCase):
    """测试电网容量约束"""

    def test_max_generation_constraint(self):
        """测试最大出力约束"""
        grid = GridConstraints(max_generation_mw=20000.0)
        calc = NetLoadCalculator(grid=grid)
        load = np.full(24, 30000.0)  # 超过最大出力
        pv = np.zeros(24)
        result = calc.calculate(load, pv)
        for h in result.hourly:
            self.assertLessEqual(h.adjusted_net_load_mw, 20000.0 + 1)

    def test_ramp_constraint_applied(self):
        """测试爬坡约束"""
        grid = GridConstraints(ramp_rate_mw_per_min=10.0)  # 600 MW/hour
        calc = NetLoadCalculator(grid=grid)
        # 负荷突变
        load = np.array([10000, 10000, 10000, 25000, 10000, 10000], dtype=float)
        pv = np.zeros(6)
        result = calc.calculate(load, pv)
        # 时段3的变化不应超过 10*60=600
        delta = result.hourly[3].adjusted_net_load_mw - result.hourly[2].adjusted_net_load_mw
        self.assertLessEqual(abs(delta), 600 + 1)

    def test_reverse_flow_limit(self):
        """测试反向潮流限制"""
        grid = GridConstraints(reverse_flow_limit_mw=500.0)
        calc = NetLoadCalculator(grid=grid)
        load = np.array([3000] * 24, dtype=float)
        pv = np.array([5000] * 24, dtype=float)
        result = calc.calculate(load, pv)
        # 应有弃光
        self.assertGreater(result.total_curtailed_mwh, 0)


# ============================================================================
# 经济调度测试
# ============================================================================

class TestEconomicDispatch(unittest.TestCase):
    """测试经济调度成本"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_cost_positive(self):
        """测试发电成本为正"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreater(result.total_generation_cost_usd, 0)

    def test_higher_load_higher_cost(self):
        """测试负荷越高成本越高"""
        load_low, pv = make_mock_load_pv(load_base=8000, load_peak=2000)
        load_high, _ = make_mock_load_pv(load_base=15000, load_peak=4000)
        result_low = self.calc.calculate(load_low, pv)
        result_high = self.calc.calculate(load_high, pv)
        self.assertGreater(result_high.total_generation_cost_usd, result_low.total_generation_cost_usd)

    def test_pv_reduces_cost(self):
        """测试光伏降低成本"""
        pv_zero = np.zeros(24)
        pv_high, _ = make_mock_load_pv(pv_peak=800)
        result_no_pv = self.calc.calculate(self.load, pv_zero)
        result_with_pv = self.calc.calculate(self.load, pv_high)
        self.assertLess(result_with_pv.total_generation_cost_usd, result_no_pv.total_generation_cost_usd)

    def test_hourly_cost_positive(self):
        """测试每小时成本非负"""
        result = self.calc.calculate(self.load, self.pv)
        for h in result.hourly:
            self.assertGreaterEqual(h.generation_cost_usd, 0)


# ============================================================================
# 调度建议测试
# ============================================================================

class TestDispatchActions(unittest.TestCase):
    """测试调度建议"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_actions_generated(self):
        """测试调度建议被生成"""
        result = self.calc.calculate(self.load, self.pv)
        self.assertGreater(len(result.dispatch_actions), 0)

    def test_peak_shaving_action(self):
        """测试削峰建议"""
        result = self.calc.calculate(self.load, self.pv)
        peak_actions = [a for a in result.dispatch_actions if a['type'] == 'peak_shaving']
        if result.peak_hours:
            self.assertGreater(len(peak_actions), 0)

    def test_action_has_recommendation(self):
        """测试建议包含推荐"""
        result = self.calc.calculate(self.load, self.pv)
        for a in result.dispatch_actions:
            if a['type'] in ('peak_shaving', 'valley_filling', 'curtailment'):
                self.assertIn('recommendation', a)

    def test_curtailment_action_when_high_pv(self):
        """测试高光伏时生成弃光建议"""
        load = np.array([5000] * 24, dtype=float)
        pv = np.array([8000] * 24, dtype=float)
        result = self.calc.calculate(load, pv)
        curtail_actions = [a for a in result.dispatch_actions if a['type'] == 'curtailment']
        self.assertGreater(len(curtail_actions), 0)


# ============================================================================
# 结果格式测试
# ============================================================================

class TestResultFormat(unittest.TestCase):
    """测试结果格式"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_to_dict(self):
        """测试结果转字典"""
        result = self.calc.calculate(self.load, self.pv)
        d = result.to_dict()

        self.assertIn('hourly', d)
        self.assertIn('summary', d)
        self.assertEqual(len(d['hourly']), 24)

    def test_hourly_fields(self):
        """测试每小时结果字段完整"""
        result = self.calc.calculate(self.load, self.pv)
        h = result.hourly[0]
        self.assertIn('hour', dir(h))
        self.assertIn('timestamp', dir(h))
        self.assertIn('load_forecast_mw', dir(h))
        self.assertIn('pv_generation_mw', dir(h))
        self.assertIn('net_load_mw', dir(h))
        self.assertIn('curtailed_pv_mw', dir(h))
        self.assertIn('storage_charge_mw', dir(h))
        self.assertIn('storage_discharge_mw', dir(h))
        self.assertIn('adjusted_net_load_mw', dir(h))
        self.assertIn('soc_percent', dir(h))
        self.assertIn('generation_cost_usd', dir(h))


# ============================================================================
# 分钟级分辨率测试
# ============================================================================

class TestMinuteResolution(unittest.TestCase):
    """测试分钟级分辨率"""

    def setUp(self):
        self.calc = NetLoadCalculator()
        self.load, self.pv = make_mock_load_pv()

    def test_15min_resolution(self):
        """测试15分钟分辨率"""
        result = self.calc.calculate_minute_resolution(self.load, self.pv, minutes_per_step=15)
        self.assertEqual(len(result.hourly), 24 * 4)  # 96步

    def test_5min_resolution(self):
        """测试5分钟分辨率"""
        result = self.calc.calculate_minute_resolution(self.load, self.pv, minutes_per_step=5)
        self.assertEqual(len(result.hourly), 24 * 12)  # 288步

    def test_fine_resolution_consistent(self):
        """测试分钟级与小时级负荷量级一致"""
        result_hourly = self.calc.calculate(self.load, self.pv)
        result_15min = self.calc.calculate_minute_resolution(self.load, self.pv, minutes_per_step=15)

        # 小时级 total = sum(24值)，分钟级 total = sum(96值) ≈ 4x
        # 比较 MWh/步 的平均值应该接近
        avg_hourly = result_hourly.total_load_mwh / 24
        avg_15min = result_15min.total_load_mwh / 96
        self.assertAlmostEqual(avg_hourly, avg_15min, delta=avg_hourly * 0.15)


# ============================================================================
# 边界情况测试
# ============================================================================

class TestEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.calc = NetLoadCalculator()

    def test_zero_pv(self):
        """测试零光伏"""
        load = np.full(24, 15000.0)
        pv = np.zeros(24)
        result = self.calc.calculate(load, pv)
        self.assertEqual(result.total_pv_mwh, 0)
        self.assertEqual(result.total_curtailed_mwh, 0)

    def test_zero_load(self):
        """测试零负荷"""
        load = np.zeros(24)
        pv = np.full(24, 500.0)
        result = self.calc.calculate(load, pv)
        # 所有光伏应被弃光或储能
        self.assertGreaterEqual(result.total_curtailed_mwh, 0)

    def test_all_negative_net_load(self):
        """测试全负净负荷"""
        load = np.full(24, 3000.0)
        pv = np.full(24, 10000.0)
        result = self.calc.calculate(load, pv)
        # 应有大量弃光
        self.assertGreater(result.total_curtailed_mwh, 0)

    def test_single_hour(self):
        """测试单小时输入"""
        load = np.array([15000.0])
        pv = np.array([500.0])
        result = self.calc.calculate(load, pv)
        self.assertEqual(len(result.hourly), 1)

    def test_very_high_load(self):
        """测试极高负荷"""
        load = np.full(24, 50000.0)
        pv = np.zeros(24)
        result = self.calc.calculate(load, pv)
        # 应被约束到最大出力
        for h in result.hourly:
            self.assertLessEqual(h.adjusted_net_load_mw, self.calc.grid.max_generation_mw + 1)

    def test_storage_revenue(self):
        """测试储能收益计算"""
        load, pv = make_mock_load_pv()
        result = self.calc.calculate(load, pv)
        # 储能收益可能为正（套利）或负（成本大于收益）
        self.assertIsInstance(result.storage_revenue_usd, float)


# ============================================================================
# 自定义参数测试
# ============================================================================

class TestCustomParameters(unittest.TestCase):
    """测试自定义参数"""

    def test_custom_grid(self):
        """测试自定义电网参数"""
        grid = GridConstraints(
            min_generation_mw=5000,
            max_generation_mw=20000,
            ramp_rate_mw_per_min=30,
        )
        calc = NetLoadCalculator(grid=grid)
        self.assertEqual(calc.grid.max_generation_mw, 20000)

    def test_custom_storage(self):
        """测试自定义储能参数"""
        storage = StorageParams(
            capacity_mwh=1000,
            power_charge_mw=500,
            power_discharge_mw=500,
        )
        calc = NetLoadCalculator(storage=storage)
        self.assertEqual(calc.storage.capacity_mwh, 1000)

    def test_custom_gen_mix(self):
        """测试自定义发电组合"""
        gen = GenerationMix(nuclear_mw=5000, gas_mw=8000)
        calc = NetLoadCalculator(gen_mix=gen)
        self.assertEqual(calc.gen_mix.nuclear_mw, 5000)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
