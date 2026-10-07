#!/usr/bin/env python3
"""检查 TensorFlow 生产模型资产是否完整。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_ASSETS = [
    ("backend/models/tf_assets/tf_split_v1/load_best.weights.h5", "负荷模型权重"),
    ("backend/models/tf_assets/tf_split_v1/load_scalers.json", "负荷 Scaler"),
    ("backend/models/tf_assets/tf_split_v1/price_best.weights.h5", "电价模型权重"),
    ("backend/models/tf_assets/tf_split_v1/price_scalers.json", "电价 Scaler"),
    ("backend/models/tf_assets/tf_split_v1/ca_features.parquet", "负荷/电价特征资产"),
    ("backend/models/tf_assets/pv_v2/pv_v2_best.weights.h5", "光伏模型权重"),
    ("backend/models/tf_assets/pv_v2/metadata.json", "光伏训练元数据与 Scaler"),
    ("backend/models/tf_assets/pv_v2/pv_tail.parquet", "光伏特征资产"),
    (".env", "环境变量配置"),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    missing = []
    print("TensorFlow 运行资产完整性检查")
    print(f"项目根目录: {PROJECT_ROOT}")
    for relative_path, description in REQUIRED_ASSETS:
        path = PROJECT_ROOT / relative_path
        if path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            print(f"  ✅ {description}: {relative_path} ({size_mb:.1f} MB)")
        else:
            print(f"  ❌ {description}: {relative_path}")
            missing.append((relative_path, description))

    if missing:
        print(f"\n缺失 {len(missing)} 项必需资产，后端无法完整加载三套 TensorFlow 模型。")
        return 1
    print("\n✅ TensorFlow 运行资产检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
