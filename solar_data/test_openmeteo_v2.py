# test_openmeteo_v2.py - Fix variable names and test
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests

url = "https://archive-api.open-meteo.com/v1/archive"

# Try without precipitable_water first
params = {
    "latitude": 42.3601,
    "longitude": -71.0589,
    "start_date": "2023-06-01",
    "end_date": "2023-06-02",
    "hourly": "shortwave_radiation,direct_radiation,diffuse_radiation,direct_normal_irradiance,temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover",
    "timezone": "America/New_York",
}

print("Test 1: Without precipitable_water")
r = requests.get(url, params=params, timeout=30)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    hourly = data.get("hourly", {})
    print(f"  Variables: {list(hourly.keys())}")
    for k, v in hourly.items():
        if isinstance(v, list):
            print(f"    {k}: {v[:3]}")
    print("  => SUCCESS!")
else:
    print(f"  Error: {r.text[:300]}")

# Test with precipitable_water (correct name might be different)
print("\nTest 2: Try different precipitable water variable names")
for var_name in ["precipitable_water", "column_precipitable_water", "precipitable_water_column"]:
    params2 = params.copy()
    params2["hourly"] = params["hourly"] + f",{var_name}"
    r = requests.get(url, params=params2, timeout=15)
    status = "OK" if r.status_code == 200 else "FAIL"
    print(f"  {var_name}: {status} ({r.status_code})")
    if r.status_code == 200:
        print(f"    => Correct variable name: {var_name}")
        break
    elif r.status_code == 400:
        err = r.text[:120]
        print(f"    Error: {err}")

# Test 3: Check available variables from API docs
print("\nTest 3: Check cloud_cover_low/mid/high and other variables")
extra_vars = [
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "apparent_temperature", "precipitation", "rain", "snowfall",
    "weather_code", "sunshine_duration", "wet_bulb_temperature_2m",
    "diffuse_radiation_instant", "direct_normal_irradiance_instant",
    "shortwave_radiation_instant", "global_tilted_irradiance",
    "global_tilted_irradiance_instant", "terrestrial_radiation",
]
for var in extra_vars:
    params3 = params.copy()
    params3["hourly"] = f"shortwave_radiation,{var}"
    r = requests.get(url, params=params3, timeout=10)
    status = "OK" if r.status_code == 200 else "FAIL"
    print(f"  {var}: {status}")
