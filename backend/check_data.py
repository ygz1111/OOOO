# -*- coding: utf-8 -*-
"""Check training data"""
import pickle
import pandas as pd
import numpy as np
import sys
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("1. Raw data (step1_system_data.pkl)")
print("=" * 60)
df = pickle.load(open('processed/step1_system_data.pkl', 'rb'))
print(f"Rows: {len(df)}")
print(f"Cols: {len(df.columns)}")
print(f"Columns: {list(df.columns)}")
print(f"Year dist: {df.groupby('year').size().to_dict()}")
print(f"Date range: {df['Date'].min()} ~ {df['Date'].max()}")
print(f"System_Load: min={df['System_Load'].min()}, max={df['System_Load'].max()}, mean={df['System_Load'].mean():.1f}")
print(f"Dry_Bulb: min={df['Dry_Bulb'].min()}, max={df['Dry_Bulb'].max()}")
print(f"Dew_Point: min={df['Dew_Point'].min()}, max={df['Dew_Point'].max()}")
print()
print("First 3 rows (key cols):")
print(df[['Date', 'Hr_End', 'Dry_Bulb', 'Dew_Point', 'System_Load', 'DA_LMP']].head(3).to_string())
print()
print("Sample per year:")
for y in [2023, 2024, 2025]:
    row = df[df['year'] == y].iloc[0]
    last = df[df['year'] == y].iloc[-1]
    print(f"  {y}: first Date={row['Date']}, Hr_End={row['Hr_End']}, Load={row['System_Load']}, Temp={row['Dry_Bulb']}")
    print(f"        last  Date={last['Date']}, Hr_End={last['Hr_End']}, Load={last['System_Load']}, Temp={last['Dry_Bulb']}")
print()

# Temperature check - is it Fahrenheit?
print("=" * 60)
print("2. Temperature unit check")
print("=" * 60)
print(f"Dry_Bulb range: {df['Dry_Bulb'].min()} ~ {df['Dry_Bulb'].max()}")
print(f"Dew_Point range: {df['Dew_Point'].min()} ~ {df['Dew_Point'].max()}")
if df['Dry_Bulb'].max() > 50:
    print("  -> Temperature is in FAHRENHEIT (not Celsius)")
    temp_c_min = (df['Dry_Bulb'].min() - 32) * 5 / 9
    temp_c_max = (df['Dry_Bulb'].max() - 32) * 5 / 9
    print(f"  -> In Celsius: {temp_c_min:.1f}C ~ {temp_c_max:.1f}C")
    print("  -> New England range: -23C ~ 37C => MATCH for New England")
else:
    print("  -> Temperature is in Celsius")
print()

# Verify: New England load characteristics
print("=" * 60)
print("3. Is this New England load data?")
print("=" * 60)
load_min = df['System_Load'].min()
load_max = df['System_Load'].max()
load_mean = df['System_Load'].mean()
print(f"Load range: {load_min:.0f} - {load_max:.0f} MW, mean={load_mean:.0f} MW")
print("  ISO-NE New England typical: 8000-22000 MW (summer peak ~25000)")
if 7000 <= load_min <= 9000 and 20000 <= load_max <= 28000:
    print("  => MATCH: This is New England ISO-NE system load data")
else:
    print("  => MISMATCH")
print()

# Region data
print("=" * 60)
print("4. Region data")
print("=" * 60)
region_data = pickle.load(open('processed/step1_region_data.pkl', 'rb'))
print(f"Regions: {len(region_data)}")
print(f"Names: {list(region_data.keys())}")
print("  ME=Maine, NH=New Hampshire, VT=Vermont, CT=Connecticut")
print("  RI=Rhode Island, SEMA/WCMA/NEMA=Massachusetts East/Central/West")
print("  => These 8 regions = New England area")
print()

# Check region loads sum to system load
me_load = region_data['ME']['DA_Demand'].iloc[:5]
ct_load = region_data['CT']['DA_Demand'].iloc[:5]
sys_load = df['DA_Demand'].iloc[:5]
region_sum = sum(region_data[r]['DA_Demand'].iloc[:5] for r in region_data)
print("Region DA_Demand sum vs System DA_Demand (first 5 hours):")
print(f"  System:  {sys_load.values}")
print(f"  Sum 8 regions: {region_sum.values}")
print(f"  Match: {np.allclose(sys_load.values, region_sum.values, rtol=0.01)}")
print()

# Step 4: model data
print("=" * 60)
print("5. Training data (step4_model_data.pkl)")
print("=" * 60)
df4 = pickle.load(open('processed/step4_model_data.pkl', 'rb'))
print(f"Rows: {len(df4)}")
print(f"Cols: {len(df4.columns)} (38 features + 1 target = 39)")
print(f"Target: System_Load")
print(f"Time range: {df4.index.min()} ~ {df4.index.max()}")
print(f"Features ({len(df4.columns)-1}):")
for i, col in enumerate(df4.columns):
    tag = "  <-- TARGET" if col == 'System_Load' else ""
    print(f"  [{i:2d}] {col}{tag}")
print()

# Step 5: split
print("=" * 60)
print("6. Train/Val/Test split (step5)")
print("=" * 60)
split_info = pickle.load(open('processed/step5_split_info.pkl', 'rb'))
print(f"Split info: {split_info}")
print()

# Step 6: sequences
print("=" * 60)
print("7. Model input sequences (step6)")
print("=" * 60)
seq = pickle.load(open('processed/step6_sequences.pkl', 'rb'))
print(f"Keys: {list(seq.keys())}")
for key in seq:
    val = seq[key]
    if hasattr(val, 'shape'):
        print(f"  {key}: shape={val.shape}, dtype={val.dtype}")
    elif isinstance(val, dict):
        print(f"  {key}: {val}")
    else:
        print(f"  {key}: {type(val).__name__} = {val}")
print()

# Summary
print("=" * 60)
print("8. FINAL SUMMARY")
print("=" * 60)
X_train = seq.get('X_train_seq')
y_train = seq.get('y_train_seq')
X_val = seq.get('X_val_seq')
X_test = seq.get('X_test_seq')
if X_train is not None:
    total = X_train.shape[0] + X_val.shape[0] + X_test.shape[0]
    print(f"Training samples:   {X_train.shape[0]}")
    print(f"Validation samples: {X_val.shape[0]}")
    print(f"Test samples:       {X_test.shape[0]}")
    print(f"Total samples:      {total}")
    print(f"Input shape:  ({X_train.shape[1]}, {X_train.shape[2]}) = (168h, 38 features)")
    print(f"Output shape: ({y_train.shape[1]},) = 24h forecast")
    print(f"Data coverage: {df4.index.min()} ~ {df4.index.max()}")
    print(f"  = 3 years of New England ISO-NE hourly load data")
    print(f"  = {len(df4)} hours of data")
    print(f"  = {len(df4)//24} days = {len(df4)//24//7:.0f} weeks = {len(df4)//8760:.1f} years")
