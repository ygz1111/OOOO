# 风电功率预测功能 — 计划书

> 基于物理模型的新英格兰地区风电功率预测，与现有光伏预测和负荷预测系统无缝集成

---

## 1. 项目背景

### 1.1 现有系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    智能电网预测系统                        │
├──────────────┬──────────────┬───────────────────────────┤
│  负荷预测     │  光伏预测     │    ⬅ 新增：风电预测       │
│  (4 ML模型)  │  (物理模型)  │    (物理模型)             │
├──────────────┼──────────────┼───────────────────────────┤
│  LSTM        │  pv_estimator│  wind_estimator           │
│  BiGRU       │  .py         │  .py                      │
│  TCN         │              │                           │
│  Transformer │              │                           │
├──────────────┴──────────────┴───────────────────────────┤
│              net_load_calculator.py                      │
│  Net_Load = Load_Forecast - PV_Generation - Wind_Gen    │
├──────────────────────────────────────────────────────────┤
│                    FastAPI (app.py)                       │
├──────────────────────────────────────────────────────────┤
│              React Frontend (多页面)                      │
│  Dashboard │ LoadForecast │ SolarGeneration │ WindGen   │
└──────────────────────────────────────────────────────────┘
```

### 1.2 新英格兰地区风电现状

| 参数 | 值 | 来源 |
|------|----|------|
| 风电装机容量 | 1,500 MW | ISO-NE 发电组合 |
| 主要风电类型 | 陆上风力发电 | 新英格兰地形 |
| 平均容量因子 | 30-35% | DOE EIA 数据 |
| 风电成本 | $5/MWh | 边际成本极低 |
| 占比 | ~8% 总发电 | ISO-NE 2024 |

---

## 2. 物理模型设计

### 2.1 核心公式

#### 风功率基本方程

```
P = 0.5 × ρ × A × v³ × Cp × η

其中:
  P   = 风机输出功率 (W)
  ρ   = 空气密度 (kg/m³)
  A   = 风轮扫掠面积 (m²), A = π × R²
  v   = 轮毂高度风速 (m/s)
  Cp  = 功率系数 (贝兹极限 0.593, 实际 0.35-0.45)
  η   = 机电效率 (齿轮箱 + 发电机, ~0.90-0.95)
```

#### 风切变高度修正

```
v_h = v_ref × (h / h_ref)^α

其中:
  v_h    = 轮毂高度风速 (m/s)
  v_ref  = 参考高度风速 (m/s, Open-Meteo 提供 10m 风速)
  h      = 轮毂高度 (m, 典型 80-100m)
  h_ref  = 参考高度 (m, 10m)
  α      = 风切变指数
           - 开阔地形: 0.15-0.20
           - 森林/丘陵: 0.25-0.35
           - 新英格兰混合地形: 0.22 (默认)
```

#### 空气密度修正

```
ρ = ρ_0 × (T_0 / T) × (P / P_0)

其中:
  ρ_0 = 1.225 kg/m³ (标准海平面空气密度, 15°C, 1013.25 hPa)
  T_0 = 288.15 K (15°C)
  T   = 273.15 + T_amb (实际温度 K)
  P   = 实际气压 (hPa)
  P_0 = 1013.25 hPa (标准海平面气压)
```

#### 功率曲线模型

采用分段线性功率曲线模型：

```
         ⎧ 0                           v < v_cut_in  (3 m/s)
         ⎪
P(v) =   ⎨ P_rated × ((v - v_cut_in) / (v_rated - v_cut_in))³
         ⎪     v_cut_in ≤ v < v_rated
         ⎪
         ⎩ P_rated                    v_rated ≤ v < v_cut_out
         ⎪
         ⎩ 0                           v ≥ v_cut_out  (25 m/s)
```

典型 2MW 风机参数:
- 切入风速: 3 m/s
- 额定风速: 12 m/s
- 切出风速: 25 m/s
- 额定功率: 2 MW

#### 风电场尾流损失

```
P_farm = N × P_turbine × (1 - wake_loss)

其中:
  N           = 风机数量
  wake_loss   = 尾流效率损失 (典型 5-15%)
              - 单排: 5%
              - 多排: 10-15% (取决于风向和间距)
```

### 2.2 不确定性估计

```
σ_wind = P × √[(σ_v/v)² × (3σ_v/v)²]  (风速误差传播, v³ 放大3倍)

主要误差源:
  - 风速预测误差: ±1.5 m/s (24h)
  - 风切变不确定性: ±10%
  - 尾流模型不确定性: ±5%
  - 总不确定性: ~±20%
```

---

## 3. 模块架构设计

### 3.1 文件结构

```
realtime_api/
├── wind_estimator.py          # ⬅ 新增：风电功率物理估算器
├── pv_estimator.py            # 现有：光伏估算器
├── net_load_calculator.py     # 修改：净负荷 = 负荷 - PV - Wind
├── app.py                     # 修改：集成风电估算 + API 端点
└── openmeteo_client.py        # 修改：增加 wind_direction_10m 参数

src/pages/
├── WindGeneration.tsx         # ⬅ 新增：风电预测前端页面
└── SolarGeneration.tsx        # 现有：光伏页面
```

### 3.2 wind_estimator.py 类设计

```python
class WindPowerEstimator:
    """风电功率物理估算器"""

    def __init__(self, ...):
        # 风机参数、风场配置、地形参数

    def wind_shear_correction(self, v_10m, h_hub, alpha):
        """风切变高度修正"""

    def air_density_correction(self, temperature, pressure):
        """空气密度修正"""

    def turbine_power_curve(self, v_hub):
        """分段功率曲线"""

    def wake_loss(self, wind_direction, wind_speed):
        """尾流损失计算"""

    def estimate_hourly(self, wind_speed_10m, temperature, pressure, ...):
        """单小时风电估算"""

    def estimate_24h(self, weather_df):
        """24小时风电预测"""

    def power_curve_chart(self):
        """生成功率曲线图表数据"""
```

### 3.3 数据流

```
Open-Meteo API
  │
  ├─ wind_speed_10m (m/s)    ──→ wind_estimator
  ├─ wind_direction_10m (°)  ──→ wind_estimator (尾流计算)
  ├─ temperature_2m (°C)     ──→ wind_estimator (空气密度)
  ├─ surface_pressure (hPa)  ──→ wind_estimator (空气密度)
  │
  ▼
wind_estimator.estimate_24h()
  │
  ├─ 高度修正: 10m → 80m 轮毂高度
  ├─ 空气密度: 温度+气压修正
  ├─ 功率曲线: 分段模型
  ├─ 尾流损失: 风向相关
  │
  ▼
wind_generation_mw[24]  ──→ app.py
  │
  ├─→ /api/wind-generation (新端点)
  ├─→ net_load_calculator (Net = Load - PV - Wind)
  └─→ 前端 WindGeneration.tsx
```

---

## 4. 系统参数配置

### 4.1 风机参数

| 参数 | 值 | 说明 |
|------|----|------|
| 额定功率 | 2.0 MW | 单台风机 |
| 风轮直径 | 80 m | 扫掠面积 5027 m² |
| 轮毂高度 | 80 m | 典型陆上风机 |
| 切入风速 | 3 m/s | 最低发电风速 |
| 额定风速 | 12 m/s | 达到额定功率 |
| 切出风速 | 25 m/s | 安全停机 |
| 功率系数 Cp | 0.40 | 贝兹极限的 67% |
| 机电效率 | 0.92 | 齿轮箱+发电机 |

### 4.2 风电场参数

| 参数 | 值 | 说明 |
|------|----|------|
| 总装机容量 | 1,500 MW | 新英格兰地区 |
| 风机数量 | 750 台 | 1500MW / 2MW |
| 尾流损失 | 10% | 多排布置 |
| 可用率 | 95% | 运维停机 |

### 4.3 新英格兰地形参数

| 参数 | 值 |
|------|----|
| 风切变指数 α | 0.22 (混合地形) |
| 平均海拔 | 300 m |
| 空气密度 | ~1.18 kg/m³ (修正后) |

---

## 5. API 端点设计

### 5.1 新增端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/wind-generation` | GET | 获取当前风电预测 |
| `/api/wind-generation/power-curve` | GET | 获取风机功率曲线 |

### 5.2 响应格式

```json
{
  "status": "success",
  "hourly_generation_mw": [12.5, 15.3, ...],
  "hourly_wind_speed_ms": [6.2, 7.1, ...],
  "hourly_efficiency": [0.38, 0.42, ...],
  "hourly_uncertainty_mw": [2.5, 3.1, ...],
  "total_daily_mwh": 8420.5,
  "capacity_factor": 0.234,
  "turbine_type": "2MW Onshore",
  "installed_capacity_mw": 1500,
  "timestamp": "2024-01-15T10:00:00-05:00"
}
```

### 5.3 修改现有端点

`/api/predict` 响应中的 `HourlyPrediction` 增加 `wind_estimation_mw` 字段：

```json
{
  "hour": 0,
  "timestamp": "...",
  "load_forecast_mw": 12000,
  "pv_estimation_mw": 0,
  "wind_estimation_mw": 350,
  "net_load_mw": 11650
}
```

---

## 6. 净负荷计算修改

### 6.1 修改前

```
Net_Load = Load_Forecast - PV_Generation
```

### 6.2 修改后

```
Net_Load = Load_Forecast - PV_Generation - Wind_Generation
```

### 6.3 储能调度优化

风电具有**反周期特性**（夜间风电通常更强），与光伏形成互补：
- 白天: PV 高 + Wind 低 → 净负荷降低
- 夜间: PV = 0 + Wind 高 → 净负荷进一步降低
- 储能策略需要同时考虑 PV 和 Wind 的波动

---

## 7. 前端设计

### 7.1 WindGeneration.tsx 页面

- **顶部指标卡片**: 日总发电量、峰值功率、容量因子、平均风速
- **24小时功率曲线**: 风电功率 + 风速双 Y 轴图表
- **风机功率曲线**: 展示 P-v 特性曲线
- **风资源评估**: 风速分布、Weibull 分布拟合
- **物理模型说明**: 展示计算公式和参数

### 7.2 导航集成

在侧边栏添加"风电预测"导航项，位于"光伏发电"下方。

---

## 8. 实现步骤

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1 | `wind_estimator.py` | 实现物理模型 |
| 2 | `app.py` | 集成到预测管线 + API 端点 |
| 3 | `net_load_calculator.py` | 修改净负荷公式 |
| 4 | `WindGeneration.tsx` | 前端页面 |
| 5 | 路由 + 导航 | 集成到前端导航 |

---

## 9. 验证标准

| 验证项 | 预期值 | 说明 |
|--------|--------|------|
| 风速 < 3 m/s | 功率 = 0 | 切入风速以下 |
| 风速 = 12 m/s | 功率 = 额定 | 达到额定功率 |
| 风速 > 25 m/s | 功率 = 0 | 切出停机 |
| 容量因子 | 25-35% | 新英格兰地区典型 |
| 夜间风电 > 白天 | ✓ | 风电反周期特性 |
| 净负荷 = 负荷 - PV - Wind | ✓ | 公式正确 |
