# test_openmeteo_archive.py - Test Open-Meteo Archive API for solar data
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json

print("Open-Meteo Archive API - Solar Radiation Data Test")
print("=" * 60)

# Open-Meteo Archive API
url = "https://archive-api.open-meteo.com/v1/archive"

# Test with Boston coordinates
params = {
    "latitude": 42.3601,
    "longitude": -71.0589,
    "start_date": "2023-06-01",
    "end_date": "2023-06-02",
    "hourly": [
        "shortwave_radiation",           # GHI (W/m^2)
        "direct_radiation",              # DNI (W/m^2)
        "diffuse_radiation",             # DHI (W/m^2)
        "direct_normal_irradiance",      # DNI normal (W/m^2)
        "temperature_2m",                # Temperature (C)
        "relative_humidity_2m",          # Humidity (%)
        "wind_speed_10m",                # Wind speed (m/s)
        "wind_direction_10m",            # Wind direction (deg)
        "surface_pressure",              # Pressure (hPa)
        "cloud_cover",                   # Cloud cover (%)
        "total_column_precipitable_water",  # Precipitable water (mm)
    ],
    "timezone": "America/New_York",
}

try:
    r = requests.get(url, params=params, timeout=30)
    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"Keys: {list(data.keys())}")

        hourly = data.get("hourly", {})
        print(f"\nHourly variables ({len(hourly)} ):")
        for k, v in hourly.items():
            vals = v[:3] if isinstance(v, list) else v
            print(f"  {k}: {vals}")

        # Check data completeness
        time_list = hourly.get("time", [])
        print(f"\nTime samples: {time_list[:3]} ... {time_list[-2:]}")
        print(f"Total hours: {len(time_list)}")

        # Check for None values
        print("\nNull value check:")
        for k, v in hourly.items():
            if isinstance(v, list):
                nulls = sum(1 for x in v if x is None)
                if nulls > 0:
                    print(f"  {k}: {nulls} nulls out of {len(v)}")
                else:
                    print(f"  {k}: no nulls OK")

        print("\n=> Open-Meteo Archive API works! Can use as NSRDB alternative.")
        print("   Provides: GHI(shortwave_radiation), DNI(direct_radiation), DHI(diffuse_radiation)")
        print("   Plus: temperature, humidity, wind, pressure, cloud cover, precipitable water")

    elif r.status_code == 400:
        print(f"Error 400: {r.text[:500]}")
        # Try with comma-separated string instead of list
        params["hourly"] = ",".join(params["hourly"])
        r = requests.get(url, params=params, timeout=30)
        print(f"Retry with comma string: Status {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            hourly = data.get("hourly", {})
            print(f"Hourly variables: {list(hourly.keys())}")
            print(f"First time: {hourly.get('time', ['N/A'])[:2]}")

except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
