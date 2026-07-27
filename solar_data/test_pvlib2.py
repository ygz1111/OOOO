# -*- coding: utf-8 -*-
"""验证 PVLib 关键 API (修正版)"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pvlib
import pandas as pd
import numpy as np

print("=" * 60)
print("PVLib API 验证测试 (修正版)")
print("=" * 60)

# 1. 数据库
print("\n[1] PVLib 数据库:")
cec_mods = pvlib.pvsystem.retrieve_sam('cecmod')
print(f"  CEC 组件数: {len(cec_mods.columns)}")

sandia_mods = pvlib.pvsystem.retrieve_sam('sandiamod')
print(f"  Sandia/SAPM 组件数: {len(sandia_mods.columns)}")

cec_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
print(f"  CEC 逆变器数: {len(cec_inverters.columns)}")

sandia_inverters = pvlib.pvsystem.retrieve_sam('sandiainverter')
print(f"  Sandia 逆变器数: {len(sandia_inverters.columns)}")

# 2. 查找 Canadian Solar 组件
print("\n[2] 查找 Canadian Solar 组件 (CEC):")
cs_mods = [c for c in cec_mods.columns if 'Canadian' in c]
print(f"  Canadian Solar 组件数: {len(cs_mods)}")
if cs_mods:
    mod_name = cs_mods[0]
    mod = cec_mods[mod_name]
    print(f"  选择: {mod_name}")
    print(f"    STC功率: {mod['STC']:.0f} W")
    print(f"    面积: {mod['A_c']:.2f} m^2")
    print(f"    效率: {mod['STC'] / (mod['A_c'] * 1000) * 100:.1f}%")
    print(f"    温度系数 gamma_r: {mod['gamma_r']:.4f} /°C")
    print(f"    Vmp: {mod['V_mp_ref']:.1f} V")
    print(f"    Imp: {mod['I_mp_ref']:.1f} A")

# 3. 查找大功率逆变器
print("\n[3] 查找大功率逆变器:")
big_invs = [(c, cec_inverters[c]['Paco']) for c in cec_inverters.columns if cec_inverters[c]['Paco'] >= 100000]
big_invs.sort(key=lambda x: x[1])
print(f"  100kW+ 逆变器数: {len(big_invs)}")
if big_invs:
    inv_name = big_invs[0][0]
    inv = cec_inverters[inv_name]
    print(f"  选择: {inv_name}")
    print(f"    额定AC功率: {inv['Paco']:.0f} W ({inv['Paco']/1000:.0f} kW)")
    print(f"    额定DC功率: {inv['Pdco']:.0f} W")
    print(f"    效率: {inv['Paco']/inv['Pdco']:.3f}")

# 4. 太阳位置计算
print("\n[4] 太阳位置计算:")
tz = 'America/New_York'
times = pd.date_range('2023-06-15 12:00', periods=1, freq='h', tz=tz)
sp = pvlib.solarposition.get_solarposition(times, 42.3601, -71.0589)
print(f"  Boston 2023-06-15 12:00 EST:")
print(f"  高度角: {sp['elevation'].values[0]:.1f}°")
print(f"  方位角: {sp['azimuth'].values[0]:.1f}°")
print(f"  天顶角: {sp['zenith'].values[0]:.1f}°")

# 5. POA 辐照度
print("\n[5] POA 辐照度分解 (Perez模型):")
poa = pvlib.irradiance.get_total_irradiance(
    surface_tilt=42, surface_azimuth=180,
    solar_zenith=25, solar_azimuth=180,
    dni=700, ghi=800, dhi=120,
    model='perez',
)
print(f"  输入: GHI=800, DNI=700, DHI=120, 天顶=25°")
print(f"  POA直射: {poa['poa_direct'].values[0]:.1f} W/m^2")
print(f"  POA散射: {poa['poa_diffuse'].values[0]:.1f} W/m^2")
print(f"  POA总量: {poa['poa_global'].values[0]:.1f} W/m^2")

# 6. 组件温度
print("\n[6] 组件温度 (SAPM模型):")
t_cell = pvlib.temperature.sapm_cell(
    poa_global=800, temp_air=25, wind_speed=5,
    a=-3.56, b=-0.075, deltaT=3,
)
print(f"  环境温度=25°C, POA=800W/m², 风速=5m/s")
print(f"  组件温度: {t_cell:.1f}°C")

# 7. 完整 ModelChain 测试
print("\n[7] ModelChain 完整流程测试:")
try:
    mod = cec_mods[cs_mods[0]]
    inv = cec_inverters[big_invs[0][0]]
    
    # 计算串并联数: 假设500kW系统
    # 每个组件约275W, 逆变器500kW
    target_power = 500000  # 500kW
    module_power = mod['STC']
    total_modules = int(target_power / module_power)
    modules_per_string = 20
    strings_per_inverter = total_modules // modules_per_string
    print(f"  目标功率: {target_power/1000:.0f} kW")
    print(f"  组件功率: {module_power:.0f} W")
    print(f"  总组件数: {total_modules}")
    print(f"  每串组件: {modules_per_string}")
    print(f"  串数: {strings_per_inverter}")
    
    system = pvlib.pvsystem.PVSystem(
        surface_tilt=42,
        surface_azimuth=180,
        module_parameters=mod,
        inverter_parameters=inv,
        temperature_model_parameters={
            'a': -3.56, 'b': -0.075, 'deltaT': 3
        },
        modules_per_string=modules_per_string,
        strings_per_inverter=strings_per_inverter,
    )
    
    location = pvlib.location.Location(
        latitude=42.3601, longitude=-71.0589, tz=tz
    )
    
    mc = pvlib.modelchain.ModelChain(
        system, location,
        spectral_model='no_loss',
        airmass_model='no_loss',
    )
    
    # 测试数据 (一个夏季日)
    weather = pd.DataFrame({
        'ghi': [0, 0, 0, 0, 0, 50, 200, 400, 600, 750, 800, 800, 750, 600, 400, 200, 50, 0, 0, 0, 0, 0, 0, 0],
        'dni': [0, 0, 0, 0, 0, 40, 150, 350, 550, 700, 750, 750, 700, 550, 350, 150, 40, 0, 0, 0, 0, 0, 0, 0],
        'dhi': [0, 0, 0, 0, 0, 30, 80, 100, 120, 130, 130, 130, 130, 120, 100, 80, 30, 0, 0, 0, 0, 0, 0, 0],
        'temp_air': [15, 14, 13, 13, 14, 15, 17, 19, 21, 23, 25, 26, 27, 27, 26, 24, 22, 20, 18, 17, 16, 15, 15, 14],
        'wind_speed': [3, 3, 2, 2, 2, 3, 3, 4, 4, 5, 5, 5, 5, 5, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3],
    }, index=pd.date_range('2023-06-15 00:00', periods=24, freq='h', tz=tz))
    
    mc.run_model(weather)
    
    print(f"\n  仿真结果 (24小时):")
    print(f"  {'时间':>8s} {'GHI':>6s} {'POA':>6s} {'Tcell':>6s} {'DC(W)':>8s} {'AC(W)':>8s}")
    for i, ts in enumerate(weather.index):
        ghi = weather['ghi'].iloc[i]
        poa_val = mc.results.total_irradiance['poa_global'].iloc[i] if hasattr(mc.results, 'total_irradiance') and mc.results.total_irradiance is not None else 0
        t_c = mc.results.cell_temperature.iloc[i] if hasattr(mc.results, 'cell_temperature') else 0
        dc = mc.results.dc.iloc[i] if hasattr(mc.results, 'dc') else 0
        ac = mc.results.ac.iloc[i] if hasattr(mc.results, 'ac') else 0
        
        # 处理可能是数组的情况
        if hasattr(poa_val, '__len__'):
            poa_val = float(poa_val.iloc[0]) if hasattr(poa_val, 'iloc') else float(poa_val[0])
        if hasattr(t_c, '__len__'):
            t_c = float(t_c.iloc[0]) if hasattr(t_c, 'iloc') else float(t_c[0])
        if hasattr(dc, '__len__'):
            dc = float(dc.iloc[0]) if hasattr(dc, 'iloc') else float(dc[0])
        if hasattr(ac, '__len__'):
            ac = float(ac.iloc[0]) if hasattr(ac, 'iloc') else float(ac[0])
        
        if ghi > 0 or ac > 0:
            print(f"  {ts.strftime('%H:%M'):>8s} {ghi:6.0f} {float(poa_val):6.0f} {float(t_c):6.1f} {float(dc):8.0f} {float(ac):8.0f}")
    
    total_kwh = float(mc.results.ac.sum()) / 1000
    print(f"\n  日总发电量: {total_kwh:.1f} kWh")
    print(f"  峰值功率: {float(mc.results.ac.max()):.0f} W ({float(mc.results.ac.max())/1000:.1f} kW)")
    print(f"  容量因子: {total_kwh / (500 * 24):.1%}")
    
    print("\n  => PVLib ModelChain 完整流程验证通过!")
    
except Exception as e:
    print(f"  错误: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
