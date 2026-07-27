# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np

df = pd.read_csv('d:/GitHub/OOOOOO/solar_data/new_england_pv_dataset.csv')

print("=" * 70)
print("PVLib PVWatts 仿真结果验证")
print("=" * 70)

print(f"\n总行数: {len(df):,}")
print(f"城市: {sorted(df['city'].unique())}")
print(f"年份: {df['year'].min()}-{df['year'].max()}")
print(f"列数: {len(df.columns)}")

print("\n" + "=" * 70)
print("各城市发电统计")
print("=" * 70)
print(f"{'城市':>12s} {'年均MWh':>10s} {'峰值kW':>8s} {'容量因子':>8s} {'白昼CF':>8s}")

for city in sorted(df['city'].unique()):
    d = df[df['city'] == city]
    annual_mwh = d['pv_power'].sum() / 1e6 / 6
    peak_kw = d['pv_power_kw'].max()
    cf = annual_mwh * 1000 / (500 * 8760)
    daylight = d[d['ghi'] > 0]
    daylight_cf = daylight['pv_power_kw'].mean() / 500 if len(daylight) > 0 else 0
    print(f"{city:>12s} {annual_mwh:10.1f} {peak_kw:8.0f} {cf:8.1%} {daylight_cf:8.1%}")

print("\n" + "=" * 70)
print("物理合理性验证")
print("=" * 70)

# 夜间功率
night = df[df['ghi'] == 0]
print(f"夜间最大功率: {night['pv_power'].max():.1f} W (应为0)")

# 峰值功率
max_p = df['pv_power_kw'].max()
print(f"峰值功率: {max_p:.1f} kW ({max_p/500:.1%} of 500kWp)")

# 容量因子
overall_mwh = df['pv_power'].sum() / 1e6 / 6 / 6
cf = overall_mwh * 1000 / (500 * 8760)
print(f"整体容量因子: {cf:.1%} (新英格兰预期 12-16%)")

# POA
dl = df[df['ghi'] > 10]
print(f"白天POA>0比例: {(dl['poa_irradiance'] > 0).mean():.1%}")

# 温差
dl2 = df[df['ghi'] > 100]
t_diff = (dl2['cell_temperature'] - dl2['temperature']).mean()
print(f"白天组件-环境温差: {t_diff:.1f}°C (通常 10-30°C)")

# NREL PVWatts 对比
print(f"\nNREL PVWatts Calculator 对比:")
print(f"  Boston 500kW DC, tilt=37°, PVWatts v5 预期: ~620-650 MWh")
boston = df[df['city'] == 'Boston']
boston_mwh = boston['pv_power'].sum() / 1e6 / 6
print(f"  PVLib 仿真 Boston 年均: {boston_mwh:.0f} MWh")
diff = (boston_mwh - 635) / 635 * 100
print(f"  偏差: {diff:+.1f}% (ERA5数据与TMY3有差异, ±15%内正常)")

# 样例数据
print("\n" + "=" * 70)
print("样例数据: Boston 2023-06-15 (夏季典型日)")
print("=" * 70)
sample = df[(df['city'] == 'Boston') & (df['year'] == 2023) & (df['month'] == 6) & (df['day'] == 15)]
cols = ['hour', 'ghi', 'dni', 'dhi', 'temperature', 'wind_speed', 'poa_irradiance', 'cell_temperature', 'pv_power_kw']
print(sample[cols].to_string(index=False))

# 冬季样例
print("\n样例数据: Boston 2023-12-15 (冬季典型日)")
sample2 = df[(df['city'] == 'Boston') & (df['year'] == 2023) & (df['month'] == 12) & (df['day'] == 15)]
print(sample2[cols].to_string(index=False))

# 数据完整性
print("\n" + "=" * 70)
print("数据完整性检查")
print("=" * 70)
print(f"pv_power NaN: {df['pv_power'].isna().sum()}")
print(f"pv_power 负值: {(df['pv_power'] < 0).sum()}")
print(f"pv_power > 600kW: {(df['pv_power_kw'] > 600).sum()} (应为0, 逆变器限制)")
print(f"cell_temperature NaN: {df['cell_temperature'].isna().sum()}")
print(f"poa_irradiance NaN: {df['poa_irradiance'].isna().sum()}")
print(f"行数检查: {len(df)} (预期 315,648)")

# 相关性
print("\n" + "=" * 70)
print("关键变量相关性 (pv_power_kw vs)")
print("=" * 70)
corr_vars = ['ghi', 'dni', 'dhi', 'temperature', 'wind_speed', 'humidity', 'cloud_type', 'poa_irradiance', 'cell_temperature']
correlations = df[corr_vars + ['pv_power_kw']].corr()['pv_power_kw'].drop('pv_power_kw').sort_values(ascending=False)
for var, corr in correlations.items():
    print(f"  {var:>20s}: {corr:+.3f}")
