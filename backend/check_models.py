# -*- coding: utf-8 -*-
import torch
import sys
sys.stdout.reconfigure(encoding='utf-8')

models = ['enhancedlstm', 'bigru', 'deeptcn', 'spatialtransformer']
print("=" * 70)
print("4 Models Test Results Comparison")
print("=" * 70)
print(f"{'Model':<25} {'Params':>10} {'MAPE(%)':>10} {'R2':>8} {'RMSE':>10} {'MAE':>10}")
print("-" * 70)

for m in models:
    ckpt = torch.load(f"outputs/{m}_best_model.pth", map_location="cpu", weights_only=False)
    tr = ckpt.get("test_results", {})
    sd = ckpt.get("model_state_dict", {})
    params = sum(v.numel() for v in sd.values())
    mape = tr.get("mape", 0)
    r2 = tr.get("r2", 0)
    rmse = tr.get("rmse", 0)
    mae = tr.get("mae", 0)
    name = ckpt.get("model_name", m)
    print(f"{name:<25} {params:>10,} {mape:>10.2f} {r2:>8.4f} {rmse:>10.4f} {mae:>10.4f}")

print()
print("Note: MAPE/RMSE/MAE are in normalized space (0-1 scale)")
print("      R2 = 1.0 means perfect prediction, R2 > 0.6 is acceptable")
