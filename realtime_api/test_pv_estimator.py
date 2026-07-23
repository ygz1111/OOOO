"""
光伏发电估算模块单元测试

测试内容:
  1. 太阳位置计算（赤纬、时角、高度角、方位角）
  2. 入射角计算
  3. 温度损失修正
  4. 云量遮挡损失
  5. 大气透射率
  6. 晴空辐照度
  7. 24小时预测
  8. 效率曲线
  9. 多组件类型对比
  10. 不确定性估计
  11. 夜间/边界情况
  12. 兼容旧接口

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_pv_estimator.py -v
"""

import unittest
import os
import sys
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.pv_estimator import (
    PVGenerationEstimator,
    PVForecastResult,
    PanelType,
    PANEL_TYPES,
)


# ============================================================================
# 辅助函数
# ============================================================================

def make_mock_weather(n=24, start_hour=0):
    """生成24小时模拟气象数据"""
    now = datetime(2025, 7, 23, start_hour)
    timestamps = [now + timedelta(hours=i) for i in range(n)]
    hours = [ts.hour for ts in timestamps]

    # 模拟日内辐射 (6:00-18:00 为白天)
    radiation = [
        max(0, 800 * math.sin((h - 6) * math.pi / 12)) if 6 <= h <= 18 else 0
        for h in hours
    ]
    cloud = [20 + 10 * math.sin(i * 0.5) for i in range(n)]
    temp = [15 + 10 * math.sin((h - 6) * math.pi / 12) if 6 <= h <= 18 else 15 for h in hours]

    return pd.DataFrame({
        "timestamp": timestamps,
        "shortwave_radiation": radiation,
        "cloud_cover": cloud,
        "temperature_2m": temp,
    })


# ============================================================================
# 太阳位置计算测试
# ============================================================================

class TestSolarPosition(unittest.TestCase):
    """测试太阳位置计算"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_solar_declination_range(self):
        """测试赤纬角范围 [-23.45°, 23.45°]"""
        for day in [1, 80, 172, 266, 355]:
            decl = math.degrees(self.est.solar_declination(day))
            self.assertGreaterEqual(decl, -23.5, f"day {day}: decl={decl}")
            self.assertLessEqual(decl, 23.5, f"day {day}: decl={decl}")

    def test_declination_summer_solstice(self):
        """测试夏至日(6/21, day=172)赤纬接近+23.45°"""
        decl = math.degrees(self.est.solar_declination(172))
        self.assertAlmostEqual(decl, 23.45, delta=1.0)

    def test_declination_winter_solstice(self):
        """测试冬至日(12/21, day=355)赤纬接近-23.45°"""
        decl = math.degrees(self.est.solar_declination(355))
        self.assertAlmostEqual(decl, -23.45, delta=1.0)

    def test_hour_angle_at_noon(self):
        """测试正午时角接近0"""
        ha = math.degrees(self.est.hour_angle(12))
        self.assertAlmostEqual(abs(ha), 0, delta=5)

    def test_hour_angle_morning_negative(self):
        """测试上午时角为负"""
        ha = math.degrees(self.est.hour_angle(8))
        self.assertLess(ha, 0, f"上午时角应为负: {ha}")

    def test_hour_angle_afternoon_positive(self):
        """测试下午时角为正"""
        ha = math.degrees(self.est.hour_angle(16))
        self.assertGreater(ha, 0, f"下午时角应为正: {ha}")

    def test_solar_elevation_nonnegative(self):
        """测试高度角非负"""
        decl = self.est.solar_declination(172)
        for hour in range(6, 19):
            ha = self.est.hour_angle(hour)
            elev = self.est.solar_elevation(decl, ha)
            self.assertGreater(elev, 0, f"hour {hour}: elev should be > 0")

    def test_solar_elevation_midnight_zero(self):
        """测试午夜高度角为0"""
        decl = self.est.solar_declination(172)
        ha = self.est.hour_angle(0)  # 午夜
        elev = self.est.solar_elevation(decl, ha)
        self.assertEqual(elev, 0.0)

    def test_solar_elevation_noon_max(self):
        """测试正午高度角最大"""
        decl = self.est.solar_declination(172)
        noon_elev = self.est.solar_elevation(decl, self.est.hour_angle(12))
        morning_elev = self.est.solar_elevation(decl, self.est.hour_angle(8))
        self.assertGreater(noon_elev, morning_elev, "正午高度角应大于早晨")


# ============================================================================
# 入射角测试
# ============================================================================

class TestIncidenceAngle(unittest.TestCase):
    """测试入射角计算"""

    def setUp(self):
        self.est = PVGenerationEstimator(tilt_angle=42, azimuth_angle=180)

    def test_noon_incidence_max(self):
        """测试正午入射角余弦最大（接近1）"""
        decl = self.est.solar_declination(172)
        ha = self.est.hour_angle(12)
        elev = self.est.solar_elevation(decl, ha)
        az = self.est.solar_azimuth(decl, ha, elev)
        cos_theta = self.est.incidence_angle(elev, az)
        self.assertGreater(cos_theta, 0.7, f"正午入射角余弦应较大: {cos_theta}")

    def test_incidence_nonnegative(self):
        """测试入射角余弦非负"""
        decl = self.est.solar_declination(172)
        for hour in range(6, 19):
            ha = self.est.hour_angle(hour)
            elev = self.est.solar_elevation(decl, ha)
            if elev > 0.01:
                az = self.est.solar_azimuth(decl, ha, elev)
                cos_theta = self.est.incidence_angle(elev, az)
                self.assertGreaterEqual(cos_theta, 0)


# ============================================================================
# 温度损失测试
# ============================================================================

class TestTemperatureLoss(unittest.TestCase):
    """测试温度损失修正"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_cell_temp_increases_with_irradiance(self):
        """测试组件温度随辐照度升高"""
        t_low = self.est.cell_temperature(25.0, 200)
        t_high = self.est.cell_temperature(25.0, 1000)
        self.assertGreater(t_high, t_low)

    def test_cell_temp_formula(self):
        """测试组件温度公式正确性"""
        # T_cell = T_amb + (NOCT - 20)/800 * G
        # monocrystalline NOCT=45
        expected = 25.0 + (45.0 - 20) / 800 * 1000
        actual = self.est.cell_temperature(25.0, 1000)
        self.assertAlmostEqual(actual, expected, places=1)

    def test_efficiency_decreases_at_high_temp(self):
        """测试高温效率降低"""
        cool = self.est.temperature_efficiency(25.0)
        hot = self.est.temperature_efficiency(50.0)
        self.assertLess(hot, cool, "高温效率应更低")

    def test_efficiency_at_stc(self):
        """测试STC条件(25°C)效率修正为1"""
        eta = self.est.temperature_efficiency(25.0)
        self.assertAlmostEqual(eta, 1.0)


# ============================================================================
# 云量遮挡测试
# ============================================================================

class TestCloudAttenuation(unittest.TestCase):
    """测试云量遮挡损失"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_clear_sky(self):
        """测试晴空(云量=0)透过率接近1"""
        factor = self.est.cloud_attenuation(0)
        self.assertAlmostEqual(factor, 1.0)

    def test_overcast(self):
        """测试阴天(云量=100)透过率较低"""
        factor = self.est.cloud_attenuation(100)
        self.assertLess(factor, 0.5)

    def test_partial_cloud(self):
        """测试部分云量在晴空和阴天之间"""
        factor = self.est.cloud_attenuation(50)
        self.assertGreater(factor, self.est.cloud_attenuation(100))
        self.assertLess(factor, self.est.cloud_attenuation(0))

    def test_out_of_range_clipped(self):
        """测试超出范围的云量被裁剪"""
        self.assertEqual(self.est.cloud_attenuation(-10), self.est.cloud_attenuation(0))
        self.assertEqual(self.est.cloud_attenuation(150), self.est.cloud_attenuation(100))


# ============================================================================
# 大气透射率测试
# ============================================================================

class TestAtmosphericTransmittance(unittest.TestCase):
    """测试大气透射率"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_high_sun_more_transmission(self):
        """测试太阳越高透射率越大"""
        tau_high = self.est.atmospheric_transmittance(math.radians(60))
        tau_low = self.est.atmospheric_transmittance(math.radians(10))
        self.assertGreater(tau_high, tau_low)

    def test_zero_elevation(self):
        """测试太阳在地平线时透射率为0"""
        self.assertEqual(self.est.atmospheric_transmittance(0), 0.0)

    def test_transmittance_range(self):
        """测试透射率在合理范围"""
        for angle in [10, 30, 60, 90]:
            tau = self.est.atmospheric_transmittance(math.radians(angle))
            self.assertGreater(tau, 0)
            self.assertLessEqual(tau, 1.0)


# ============================================================================
# 晴空辐照度测试
# ============================================================================

class TestClearSkyIrradiance(unittest.TestCase):
    """测试晴空辐照度"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_nighttime_zero(self):
        """测试夜间晴空辐照度为0"""
        g = self.est.clear_sky_irradiance(0)
        self.assertEqual(g, 0.0)

    def test_noon_maximum(self):
        """测试正午辐照度最大"""
        g_noon = self.est.clear_sky_irradiance(math.radians(60))
        g_morning = self.est.clear_sky_irradiance(math.radians(20))
        self.assertGreater(g_noon, g_morning)

    def test_reasonable_range(self):
        """测试辐照度在物理合理范围"""
        g = self.est.clear_sky_irradiance(math.radians(60))
        self.assertGreater(g, 200)
        self.assertLess(g, 1200)


# ============================================================================
# 单小时估算测试
# ============================================================================

class TestHourlyEstimation(unittest.TestCase):
    """测试单小时估算"""

    def setUp(self):
        self.est = PVGenerationEstimator(installed_capacity_mw=500)

    def test_nighttime_zero(self):
        """测试夜间发电为0"""
        ts = datetime(2025, 7, 23, 2, 0)  # 凌晨2点
        power, eff, unc = self.est.estimate_hourly(
            shortwave_radiation=0,
            cloud_cover=50,
            temperature_2m=15,
            timestamp=ts,
        )
        self.assertEqual(power, 0.0)

    def test_noontime_positive(self):
        """测试正午发电为正"""
        ts = datetime(2025, 7, 23, 12, 0)  # 正午
        power, eff, unc = self.est.estimate_hourly(
            shortwave_radiation=800,
            cloud_cover=20,
            temperature_2m=30,
            timestamp=ts,
        )
        self.assertGreater(power, 0)

    def test_power_not_exceed_capacity(self):
        """测试发电不超过装机容量"""
        ts = datetime(2025, 7, 23, 12, 0)
        power, _, _ = self.est.estimate_hourly(
            shortwave_radiation=1000,
            cloud_cover=0,
            temperature_2m=25,
            timestamp=ts,
        )
        self.assertLessEqual(power, self.est.installed_capacity * 1.1)

    def test_uncertainty_positive(self):
        """测试不确定性为正"""
        ts = datetime(2025, 7, 23, 12, 0)
        _, _, unc = self.est.estimate_hourly(
            shortwave_radiation=800,
            cloud_cover=20,
            temperature_2m=30,
            timestamp=ts,
        )
        self.assertGreaterEqual(unc, 0)

    def test_cloud_reduces_power(self):
        """测试云量增加降低发电"""
        ts = datetime(2025, 7, 23, 12, 0)
        # 使用 None 触发模型计算（晴空模型 + 云量修正）
        power_clear, _, _ = self.est.estimate_hourly(
            shortwave_radiation=None,
            cloud_cover=0,
            temperature_2m=25,
            timestamp=ts,
        )
        power_cloudy, _, _ = self.est.estimate_hourly(
            shortwave_radiation=None,
            cloud_cover=80,
            temperature_2m=25,
            timestamp=ts,
        )
        self.assertGreater(power_clear, power_cloudy, "晴天应发电更多")

    def test_high_temp_reduces_power(self):
        """测试高温降低发电"""
        ts = datetime(2025, 7, 23, 12, 0)
        power_cool, _, _ = self.est.estimate_hourly(
            shortwave_radiation=800,
            cloud_cover=20,
            temperature_2m=20,
            timestamp=ts,
        )
        power_hot, _, _ = self.est.estimate_hourly(
            shortwave_radiation=800,
            cloud_cover=20,
            temperature_2m=40,
            timestamp=ts,
        )
        self.assertGreater(power_cool, power_hot, "低温应发电更多")


# ============================================================================
# 24小时预测测试
# ============================================================================

class TestDailyForecast(unittest.TestCase):
    """测试24小时预测"""

    def setUp(self):
        self.est = PVGenerationEstimator(installed_capacity_mw=500)
        self.weather = make_mock_weather()

    def test_result_structure(self):
        """测试结果结构完整"""
        result = self.est.estimate_24h(self.weather)

        self.assertIsInstance(result, PVForecastResult)
        self.assertEqual(len(result.hourly_generation_mw), 24)
        self.assertEqual(len(result.hourly_efficiency), 24)
        self.assertEqual(len(result.hourly_uncertainty), 24)
        self.assertEqual(len(result.sun_elevation), 24)
        self.assertEqual(len(result.cell_temperature), 24)
        self.assertEqual(len(result.timestamps), 24)

    def test_total_daily_mwh(self):
        """测试日总发电量为正"""
        result = self.est.estimate_24h(self.weather)
        self.assertGreater(result.total_daily_mwh, 0)

    def test_capacity_factor_range(self):
        """测试容量因子在合理范围 (0-30%)"""
        result = self.est.estimate_24h(self.weather)
        self.assertGreater(result.capacity_factor, 0)
        self.assertLess(result.capacity_factor, 0.5)

    def test_nighttime_hours_zero(self):
        """测试夜间时段发电为0"""
        result = self.est.estimate_24h(self.weather)
        # 找到夜间时段 (辐射=0的位置)
        night_hours = np.where(self.weather["shortwave_radiation"] == 0)[0]
        for h in night_hours:
            self.assertEqual(result.hourly_generation_mw[h], 0.0,
                             f"夜间 {h}:00 应为0")

    def test_daytime_hours_positive(self):
        """测试白天时段发电为正"""
        result = self.est.estimate_24h(self.weather)
        day_hours = np.where(self.weather["shortwave_radiation"] > 0)[0]
        for h in day_hours:
            self.assertGreater(result.hourly_generation_mw[h], 0,
                               f"白天 {h}:00 应为正")

    def test_to_dict(self):
        """测试结果转字典"""
        result = self.est.estimate_24h(self.weather)
        d = result.to_dict()

        self.assertIn("hourly_generation_mw", d)
        self.assertIn("hourly_efficiency", d)
        self.assertIn("total_daily_mwh", d)
        self.assertIn("capacity_factor", d)


# ============================================================================
# 效率曲线测试
# ============================================================================

class TestEfficiencyCurve(unittest.TestCase):
    """测试效率曲线"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_curve_structure(self):
        """测试曲线数据结构"""
        curve = self.est.efficiency_curve()
        self.assertIn("irradiance_w_m2", curve.columns)
        self.assertIn("efficiency", curve.columns)
        self.assertIn("power_mw", curve.columns)

    def test_efficiency_decreases_at_high_irradiance(self):
        """测试高辐照度效率降低（温度效应）"""
        curve = self.est.efficiency_curve(temperature=40.0)
        # 高辐照度时温度更高，效率更低
        self.assertLess(
            curve["efficiency"].iloc[-1],
            curve["efficiency"].iloc[10],
            "高辐照度时温度效应应降低效率"
        )

    def test_power_increases_with_irradiance(self):
        """测试发电量随辐照度增加"""
        curve = self.est.efficiency_curve(temperature=25.0)
        self.assertGreater(curve["power_mw"].iloc[-1], curve["power_mw"].iloc[0])


# ============================================================================
# 多组件类型测试
# ============================================================================

class TestPanelTypes(unittest.TestCase):
    """测试多种光伏组件类型"""

    def test_all_types_available(self):
        """测试所有组件类型可用"""
        self.assertIn("monocrystalline", PANEL_TYPES)
        self.assertIn("polycrystalline", PANEL_TYPES)
        self.assertIn("cdte", PANEL_TYPES)
        self.assertIn("cigs", PANEL_TYPES)

    def test_mono_more_efficient_than_poly(self):
        """测试单晶硅效率高于多晶硅"""
        mono = PANEL_TYPES["monocrystalline"]
        poly = PANEL_TYPES["polycrystalline"]
        self.assertGreater(mono.efficiency_stc, poly.efficiency_stc)

    def test_thin_film_better_temp_coeff(self):
        """测试薄膜温度系数优于晶硅"""
        cdte = PANEL_TYPES["cdte"]
        mono = PANEL_TYPES["monocrystalline"]
        # 温度系数为负，绝对值越小越好
        self.assertLess(abs(cdte.temperature_coeff), abs(mono.temperature_coeff))

    def test_unknown_type_raises(self):
        """测试未知组件类型抛出异常"""
        with self.assertRaises(ValueError):
            PVGenerationEstimator(panel_type="unknown_type")

    def test_different_panels_different_output(self):
        """测试不同组件产生不同发电量"""
        weather = make_mock_weather()
        results = {}
        for ptype in ["monocrystalline", "polycrystalline", "cdte"]:
            est = PVGenerationEstimator(panel_type=ptype)
            results[ptype] = est.estimate_24h(weather).total_daily_mwh

        self.assertNotEqual(results["monocrystalline"], results["cdte"])


# ============================================================================
# 边界情况测试
# ============================================================================

class TestEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.est = PVGenerationEstimator()

    def test_all_zero_input(self):
        """测试全零输入"""
        ts = datetime(2025, 7, 23, 12, 0)
        power, eff, unc = self.est.estimate_hourly(0, 0, 0, ts)
        self.assertEqual(power, 0.0)

    def test_negative_radiation(self):
        """测试负辐射值"""
        ts = datetime(2025, 7, 23, 12, 0)
        power, _, _ = self.est.estimate_hourly(-100, 0, 25, ts)
        self.assertEqual(power, 0.0)

    def test_extreme_cloud_cover(self):
        """测试极端云量"""
        ts = datetime(2025, 7, 23, 12, 0)
        # 云量=100但使用模型计算
        power, _, _ = self.est.estimate_hourly(None, 100, 25, ts)
        self.assertGreaterEqual(power, 0)

    def test_winter_day(self):
        """测试冬季日（太阳高度角低）"""
        ts = datetime(2025, 12, 21, 12, 0)
        power, _, _ = self.est.estimate_hourly(400, 30, -5, ts)
        self.assertGreaterEqual(power, 0)
        self.assertLess(power, self.est.installed_capacity)

    def test_compatibility_estimate(self):
        """测试兼容旧接口"""
        power = self.est.estimate(1000, 25)
        self.assertGreaterEqual(power, 0)


# ============================================================================
# 新英格兰地区特性测试
# ============================================================================

class TestNewEnglandAdaptation(unittest.TestCase):
    """测试新英格兰地区特性适配"""

    def test_default_boston_location(self):
        """测试默认波士顿位置"""
        est = PVGenerationEstimator()
        self.assertAlmostEqual(math.degrees(est.lat), 42.36, places=1)

    def test_default_tilt_near_latitude(self):
        """测试默认倾角接近纬度"""
        est = PVGenerationEstimator()
        # 倾角约等于纬度是新英格兰最佳
        self.assertAlmostEqual(math.degrees(est.tilt), 42.0, places=1)

    def test_south_facing(self):
        """测试面板朝南"""
        est = PVGenerationEstimator()
        self.assertAlmostEqual(math.degrees(est.azimuth), 180.0, places=1)

    def test_summer_more_than_winter(self):
        """测试夏季发电量高于冬季"""
        # 夏季 7/23
        summer_weather = make_mock_weather()
        summer_est = PVGenerationEstimator()
        summer_result = summer_est.estimate_24h(summer_weather)

        # 冬季 12/21
        winter_ts = datetime(2025, 12, 21, 0)
        winter_weather = pd.DataFrame({
            "timestamp": [winter_ts + timedelta(hours=i) for i in range(24)],
            "shortwave_radiation": [
                max(0, 300 * math.sin((ts.hour - 7) * math.pi / 10))
                if 7 <= ts.hour <= 17 else 0
                for ts in [winter_ts + timedelta(hours=i) for i in range(24)]
            ],
            "cloud_cover": [40] * 24,
            "temperature_2m": [-5 + 5 * math.sin((ts.hour - 7) * math.pi / 10)
                               if 7 <= ts.hour <= 17 else -5
                               for ts in [winter_ts + timedelta(hours=i) for i in range(24)]],
        })
        winter_est = PVGenerationEstimator()
        winter_result = winter_est.estimate_24h(winter_weather)

        self.assertGreater(summer_result.total_daily_mwh, winter_result.total_daily_mwh,
                           "夏季应发电量多于冬季")


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
