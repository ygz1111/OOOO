# -*- coding: utf-8 -*-
"""验证 PVLib 关键 API 是否正常工作"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pvlib
import pandas as pd
import numpy as np
from pytz import timezone

print("=" * 60)
print("PVLib API 验证测试")
print("=" * 60)

# 1. 检查 PVLib 可用的模块
print("\n[1] PVLib 子模块:")
print(f"  pvlib.solarposition: {hasattr(pvlib, 'solarposition')}")
print(f"  pvlib.irradiance: {hasattr(pvlib, 'irradiance')}")
print(f"  pvlib.pvsystem: {hasattr(pvlib, 'pvsystem')}")
print(f"  pvlib.temperature: {hasattr(pvlib, 'temperature')}")
print(f"  pvlib.modelchain: {hasattr(pvlib, 'modelchain')}")
print(f"  pvlib.tracking: {hasattr(pvlib, 'tracking')}")

# 2. 检查 SAPM 组件和逆变器数据库
print("\n[2] PVLib 数据库:")
sapm_mods = pvlib.pvsystem.retrieve_sam('SAPM')
print(f"  SAPM 组件数: {len(sapm_mods.columns)}")
print(f"  SAPM 组件示例: {list(sapm_mods.columns[:3])}")

cec_mods = pvlib.pvsystem.retrieve_sam('CECMod')
print(f"  CEC 组件数: {len(cec_mods.columns)}")

cec_inverters = pvlib.pvsystem.retrieve_sam('CECInverter')
print(f"  CEC 逆变器数: {len(cec_inverters.columns)}")

# 3. 太阳位置计算测试
print("\n[3] 太阳位置计算 (Boston, 2023-06-15 12:00):")
tz = 'America/New_York'
times = pd.date_range('2023-06-15 12:00', periods=1, freq='h', tz=tz)
sp = pvlib.solarposition.get_solarposition(times, 42.3601, -71.0589)
print(sp.to_string())
print(f"  高度角: {sp['elevation'].values[0]:.1f}°")
print(f"  方位角: {sp['azimuth'].values[0]:.1f}°")

# 4. POA辐照度分解测试
print("\n[4] POA 辐照度分解:")
# 模拟一个晴天中午的数据
ghi = 800  # W/m^2
dni = 700
dhi = 120
elevation = 65  # 度
azimuth = 180  # 度

poa = pvlib.irradiance.get_total_irradiance(
    surface_tilt=42,          # 面板倾角
    surface_azimuth=180,      # 正南
    solar_zenith=90 - elevation,
    solar_azimuth=azimuth,
    dni=dni,
    ghi=ghi,
    dhi=dhi,
    model='perez',            # Perez各向异性模型
)
print(f"  输入: GHI={ghi}, DNI={dni}, DHI={dhi}")
print(f"  POA直射: {poa['poa_direct'].values[0]:.1f} W/m^2")
print(f"  POA散射: {poa['poa_diffuse'].values[0]:.1f} W/m^2")
print(f"  POA总量: {poa['poa_global'].values[0]:.1f} W/m^2")

# 5. 组件温度模型测试
print("\n[5] 组件温度模型 (SAPM cell temperature):")
t_cell = pvlib.temperature.sapm_cell(
    poa_global=800,
    temp_air=25,
    wind_speed=5,
    a=-3.56,
    b=-0.075,
    deltaT=3,
)
print(f"  环境温度=25°C, POA=800W/m^2, 风速=5m/s")
print(f"  组件温度: {t_cell:.1f}°C")

# 6. 选择一个真实的组件和逆变器
print("\n[6] 选择光伏组件和逆变器:")
# 选择 Canadian Solar 组件 (常见工业级)
module_name = 'Canadian_Solar_CS6X_275P' 
inverter_name = 'ABB__MICRO_0_25_I_OUTD_US_208__208V_'

if module_name in cec_mods.columns:
    print(f"  组件: {module_name}")
    mod = cec_mods[module_name]
    print(f"    STC功率: {mod['STC']:.0f} W")
    print(f"    效率: {mod['STC'] / (mod['A_c'] * 1000) * 100:.1f}%")
    print(f"    温度系数: {mod['gamma_r']:.4f} /°C")
    print(f"    面积: {mod['A_c']:.2f} m^2")
else:
    # 找一个可用的
    print(f"  {module_name} 不存在, 查找可用的...")
    cs_mods = [c for c in cec_mods.columns if 'Canadian' in c][:5]
    print(f"  Canadian Solar 组件: {cs_mods}")
    module_name = cs_mods[0]
    mod = cec_mods[module_name]
    print(f"  使用: {module_name}")
    print(f"    STC功率: {mod['STC']:.0f} W")

if inverter_name in cec_inverters.columns:
    inv = cec_inverters[inverter_name]
    print(f"  逆变器: {inverter_name}")
    print(f"    额定功率: {inv['Paco']:.0f} W")
else:
    # 找一个大功率逆变器
    print(f"  {inverter_name} 不存在, 查找大功率逆变器...")
    big_invs = [c for c in cec_inverters.columns if cec_inverters[c]['Paco'] >= 100000][:5]
    print(f"  大功率逆变器: {big_invs}")

# 7. ModelChain 测试
print("\n[7] ModelChain 完整流程测试:")
try:
    # 使用 SAPM 组件 (更简单)
    sapm_mods = pvlib.pvsystem.retrieve_sam('SAPM')
    sapm_mod_name = [c for c in sapm_mods.columns if 'Canadian' in c][0]
    sapm_inv_name = [c for c in pvlib.pvsystem.retrieve_sam('SandiaInverter').columns if 'ABB' in c or 'SMA' in c][0]
    
    sapm_module = sapm_mods[sapm_mod_name]
    sapm_inverter = pvlib.pvsystem.retrieve_sam('SandiaInverter')[sapm_inv_name]
    
    print(f"  SAPM组件: {sapm_mod_name}")
    print(f"    STC功率: {sapm_module['Impo']*sapm_module['Vmpo']:.0f} W")
    print(f"  逆变器: {sapm_inv_name}")
    
    # 创建PV系统
    system = pvlib.pvsystem.PVSystem(
        surface_tilt=42,
        surface_azimuth=180,
        module_parameters=sapm_module,
        inverter_parameters=sapm_inverter,
        temperature_model_parameters={
            'a': -3.56, 'b': -0.075, 'deltaT': 3
        },
        modules_per_string=20,
        strings_per_inverter=10,
    )
    
    location = pvlib.location.Location(
        latitude=42.3601, longitude=-71.0589, tz=tz
    )
    
    # 创建ModelChain
    mc = pvlib.modelchain.ModelChain(
        system, location,
        spectral_model='no_loss',
        airmass_model='no_loss',
    )
    
    # 运行测试数据
    weather = pd.DataFrame({
        'ghi': [0, 100, 500, 800, 500, 100, 0],
        'dni': [0, 80, 400, 700, 400, 80, 0],
        'dhi': [0, 30, 100, 120, 100, 30, 0],
        'temp_air': [10, 12, 18, 22, 20, 15, 10],
        'wind_speed': [3, 4, 5, 6, 5, 4, 3],
    }, index=pd.date_range('2023-06-15 06:00', periods=7, freq='h', tz=tz))
    
    mc.run_model(weather)
    
    print(f"\n  仿真结果:")
    print(f"  {'时间':>20s} {'AC功率(W)':>10s} {'DC功率(W)':>10s} {'组件温度':>8s}")
    for i, ts in enumerate(weather.index):
        ac = mc.results.ac.iloc[i] if hasattr(mc.results, 'ac') else 0
        dc = mc.results.dc.iloc[i] if hasattr(mc.results, 'dc') else 0
        cell_t = mc.results.cell_temperature.iloc[i] if hasattr(mc.results, 'cell_temperature') else 0
        if hasattr(ac, '__len__'):
            ac = ac[0] if len(ac) > 0 else 0
        if hasattr(dc, '__len__'):
            dc = dc[0] if len(dc) > 0 else 0
        if hasattr(cell_t, '__len__'):
            cell_t = cell_t[0] if len(cell_t) > 0 else 0
        print(f"  {str(ts):>20s} {float(ac):10.1f} {float(dc):10.1f} {float(cell_t):8.1f}")
    
    print("\n  => ModelChain API 正常工作!")
    
except Exception as e:
    print(f"  ModelChain错误: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
