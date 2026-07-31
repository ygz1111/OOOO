# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 光伏发电 ML 推理服务

基于训练好的 4 模型集成 (LSTM + BiGRU + TCN + Transformer)，
使用 Open-Meteo 实时气象数据预测未来 24 小时光伏发电量。

模型训练数据: new_england_pv_dataset.csv (6 城市 × 6 年, PVLib 仿真)
训练设备: NVIDIA RTX 3050 (GPU 大模型配置)
推理设备: CPU / GPU 自动选择

特征映射 (Open-Meteo → 模型 21 特征):
  shortwave_radiation    → ghi
  direct_radiation       → dni
  diffuse_radiation      → dhi
  temperature_2m         → temperature
  relative_humidity_2m   → humidity
  wind_speed_10m         → wind_speed
  wind_direction_10m     → wind_direction
  surface_pressure       → pressure
  (dew_point_2m 估算)    → precipitable_water
  (默认 0)               → cloud_type
  cloud_cover_low        → cloud_low
  cloud_cover_mid        → cloud_mid
  cloud_cover_high       → cloud_high
  station lat/lon        → latitude / longitude
  timestamp              → hour_sin/cos, month_sin/cos, doy_sin/cos

作者: 毕业设计项目
"""

import os
import sys
import time
import math
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

import torch
import torch.nn as nn

# ============================================================================
# 日志
# ============================================================================

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

# ============================================================================
# 路径配置
# ============================================================================

# 模型文件目录 (优先使用 backend 内置副本，回退到训练输出目录)
_LOCAL_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pv_models")
_TRAINING_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "solar_data2", "pv_training", "saved_models"
)
_TRAINING_SCALER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "solar_data2", "pv_training", "processed"
)

# 自动选择存在的模型目录
if os.path.isdir(_LOCAL_MODEL_DIR) and any(f.endswith('.pth') for f in os.listdir(_LOCAL_MODEL_DIR)):
    MODEL_DIR = _LOCAL_MODEL_DIR
    SCALER_DIR = _LOCAL_MODEL_DIR
elif os.path.isdir(_TRAINING_MODEL_DIR):
    MODEL_DIR = _TRAINING_MODEL_DIR
    SCALER_DIR = _TRAINING_SCALER_DIR
else:
    MODEL_DIR = _LOCAL_MODEL_DIR
    SCALER_DIR = _LOCAL_MODEL_DIR

# 训练脚本目录 (用于导入模型定义)
PV_TRAINING_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "solar_data2", "pv_training"
)

# ============================================================================
# 模型定义 (从训练脚本导入，如果路径不可用则内联定义)
# ============================================================================

def _import_model_classes():
    """尝试从训练脚本导入模型类，失败则使用内联定义"""
    try:
        if os.path.isdir(PV_TRAINING_DIR):
            sys.path.insert(0, PV_TRAINING_DIR)
            from models import LSTMModel, BiGRUModel, TCNModel, TransformerModel
            logger.info(f"从训练脚本加载模型定义: {PV_TRAINING_DIR}")
            return LSTMModel, BiGRUModel, TCNModel, TransformerModel
    except Exception as e:
        logger.warning(f"无法从训练脚本导入模型: {e}，使用内联定义")

    # 内联模型定义 (与训练脚本 models.py 一致)
    class LSTMModel(nn.Module):
        def __init__(self, input_size=21, hidden_size=64, num_layers=2,
                     output_size=24, dropout=0.2, bidirectional=True):
            super().__init__()
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                                dropout=dropout if num_layers > 1 else 0,
                                batch_first=True, bidirectional=bidirectional)
            lstm_out_size = hidden_size * (2 if bidirectional else 1)
            self.attention = nn.Linear(lstm_out_size, 1)
            self.fc1 = nn.Linear(lstm_out_size, 64)
            self.fc2 = nn.Linear(64, output_size)
            self.dropout = nn.Dropout(dropout)
            self.layer_norm = nn.LayerNorm(lstm_out_size)

        def forward(self, x):
            lstm_out, _ = self.lstm(x)
            lstm_out = self.layer_norm(lstm_out)
            attn_weights = torch.softmax(self.attention(lstm_out), dim=1)
            context = torch.sum(attn_weights * lstm_out, dim=1)
            x = torch.relu(self.fc1(context))
            x = self.dropout(x)
            return self.fc2(x)

    class BiGRUModel(nn.Module):
        def __init__(self, input_size=21, hidden_size=64, num_layers=2,
                     output_size=24, dropout=0.2, bidirectional=True):
            super().__init__()
            self.gru = nn.GRU(input_size, hidden_size, num_layers,
                              dropout=dropout if num_layers > 1 else 0,
                              batch_first=True, bidirectional=bidirectional)
            gru_out_size = hidden_size * (2 if bidirectional else 1)
            self.fc1 = nn.Linear(gru_out_size, 64)
            self.fc2 = nn.Linear(64, output_size)
            self.dropout = nn.Dropout(dropout)
            self.layer_norm = nn.LayerNorm(gru_out_size)

        def forward(self, x):
            gru_out, _ = self.gru(x)
            gru_out = self.layer_norm(gru_out)
            last = gru_out[:, -1, :]
            x = torch.relu(self.fc1(last))
            x = self.dropout(x)
            return self.fc2(x)

    class TCNBlock(nn.Module):
        def __init__(self, in_ch, out_ch, kernel_size, dilation, dropout):
            super().__init__()
            padding = (kernel_size - 1) * dilation // 2
            self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.bn1 = nn.BatchNorm1d(out_ch)
            self.bn2 = nn.BatchNorm1d(out_ch)
            self.dropout1 = nn.Dropout(dropout)
            self.dropout2 = nn.Dropout(dropout)
            self.relu = nn.ReLU()
            self.downsample = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None

        def forward(self, x):
            residual = x
            out = self.relu(self.dropout1(self.bn1(self.conv1(x))))
            out = self.dropout2(self.bn2(self.conv2(out)))
            if self.downsample:
                residual = self.downsample(residual)
            return self.relu(out + residual)

    class TCNModel(nn.Module):
        def __init__(self, input_size=21, num_channels=[32, 64, 32],
                     kernel_size=3, dilations=[1, 2, 4, 8],
                     output_size=24, dropout=0.2):
            super().__init__()
            layers = []
            in_ch = input_size
            for i, out_ch in enumerate(num_channels):
                d = dilations[i] if i < len(dilations) else 2 ** i
                layers.append(TCNBlock(in_ch, out_ch, kernel_size, d, dropout))
                in_ch = out_ch
            self.tcn = nn.Sequential(*layers)
            self.adaptive_pool = nn.AdaptiveAvgPool1d(1)
            self.fc1 = nn.Linear(num_channels[-1], 64)
            self.fc2 = nn.Linear(64, output_size)
            self.dropout = nn.Dropout(dropout)

        def forward(self, x):
            out = self.tcn(x.transpose(1, 2))
            pooled = self.adaptive_pool(out).squeeze(2)
            x = torch.relu(self.fc1(pooled))
            x = self.dropout(x)
            return self.fc2(x)

    class TransformerModel(nn.Module):
        def __init__(self, input_size=21, d_model=64, nhead=4, num_layers=2,
                     d_ff=128, output_size=24, dropout=0.2):
            super().__init__()
            self.input_proj = nn.Linear(input_size, d_model)
            self.pos_encoding = nn.Parameter(torch.zeros(100, d_model))
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=d_ff,
                dropout=dropout, batch_first=True)
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self.fc1 = nn.Linear(d_model, 64)
            self.fc2 = nn.Linear(64, output_size)
            self.dropout = nn.Dropout(dropout)
            self.layer_norm = nn.LayerNorm(d_model)

        def forward(self, x):
            seq_len = x.size(1)
            x = self.input_proj(x)
            x = x + self.pos_encoding[:seq_len, :].unsqueeze(0)
            x = self.dropout(x)
            encoded = self.layer_norm(self.encoder(x))
            final = encoded[:, -1, :]
            x = torch.relu(self.fc1(final))
            x = self.dropout(x)
            return self.fc2(x)

    logger.info("使用内联模型定义")
    return LSTMModel, BiGRUModel, TCNModel, TransformerModel


# ============================================================================
# 模型配置
# ============================================================================

# 特征列 (与训练脚本 config.py 一致, 顺序不能变)
FEATURE_COLUMNS = [
    "ghi", "dni", "dhi",
    "temperature", "humidity", "wind_speed", "wind_direction",
    "pressure", "precipitable_water",
    "cloud_type", "cloud_low", "cloud_mid", "cloud_high",
    "latitude", "longitude",
    "hour_sin", "hour_cos",
    "month_sin", "month_cos",
    "doy_sin", "doy_cos",
]

N_FEATURES = len(FEATURE_COLUMNS)  # 21
LOOKBACK = 24  # 回看窗口: 24 小时
HORIZON = 24   # 预测步长: 24 小时

# 新英格兰 6 城市坐标 (用于多站点预测)
NEW_ENGLAND_CITIES = {
    "Boston":      {"lat": 42.3601, "lon": -71.0589},
    "Hartford":    {"lat": 41.7637, "lon": -72.6851},
    "Portland":    {"lat": 43.6615, "lon": -70.2553},
    "Manchester":  {"lat": 42.9956, "lon": -71.4548},
    "Providence":  {"lat": 41.8240, "lon": -71.4128},
    "Burlington":  {"lat": 44.4759, "lon": -73.2121},
}

# 总装机容量 (MW) — 6 个城市各 500MW
TOTAL_CAPACITY_MW = 500.0


# ============================================================================
# 光伏 ML 推理服务
# ============================================================================

class PVInferenceService:
    """
    光伏发电 ML 预测服务

    使用训练好的 4 模型集成预测未来 24 小时光伏发电量。

    核心功能:
      - load_models(): 加载 4 个模型权重 + 集成权重 + Scaler
      - predict(): 从气象数据预测 24h 光伏发电量
      - get_model_info(): 获取模型信息
    """

    # 模型类映射
    MODEL_CLASSES = None  # 在 __init__ 中初始化

    def __init__(self, model_dir: str = MODEL_DIR):
        self.model_dir = model_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models: Dict[str, nn.Module] = {}
        self.model_configs: Dict[str, Dict] = {}
        self.ensemble_weights: Dict[str, float] = {}
        self.feature_scaler = None
        self.target_scaler = None
        self._loaded = False
        self._inference_count = 0
        self._total_inference_time_ms = 0.0

        # 导入模型类
        if PVInferenceService.MODEL_CLASSES is None:
            PVInferenceService.MODEL_CLASSES = _import_model_classes()

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load_models(self) -> None:
        """加载所有模型权重、集成权重和 Scaler"""
        logger.info("=" * 60)
        logger.info("加载光伏 ML 预测模型")
        logger.info(f"  模型目录: {self.model_dir}")
        logger.info(f"  推理设备: {self.device}")
        logger.info("=" * 60)

        LSTMModel, BiGRUModel, TCNModel, TransformerModel = self.MODEL_CLASSES
        class_map = {
            "LSTM": LSTMModel,
            "BiGRU": BiGRUModel,
            "TCN": TCNModel,
            "Transformer": TransformerModel,
        }

        # 加载 4 个模型
        model_files = {
            "LSTM": "lstm_best.pth",
            "BiGRU": "bigru_best.pth",
            "TCN": "tcn_best.pth",
            "Transformer": "transformer_best.pth",
        }

        for name, filename in model_files.items():
            path = os.path.join(self.model_dir, filename)
            if not os.path.exists(path):
                raise FileNotFoundError(f"模型文件不存在: {path}")

            checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            config = checkpoint["config"]
            model_cls = class_map[name]
            model = model_cls(**config)
            model.load_state_dict(checkpoint["model_state_dict"])
            model.to(self.device)
            model.eval()

            self.models[name] = model
            self.model_configs[name] = config

            param_count = sum(p.numel() for p in model.parameters())
            logger.info(
                f"  {name:>12s}: params={param_count:,}, "
                f"val_loss={checkpoint['best_val_loss']:.6f}, "
                f"epochs={checkpoint['epochs_trained']}"
            )

        # 加载集成权重
        weights_path = os.path.join(self.model_dir, "ensemble_weights.pkl")
        with open(weights_path, "rb") as f:
            ew = pickle.load(f)
        self.ensemble_weights = {
            name: float(w) for name, w in zip(ew["model_names"], ew["weights"])
        }
        logger.info(f"  集成权重: {self.ensemble_weights}")

        # 加载 Scaler
        scaler_path = os.path.join(SCALER_DIR, "pv_scalers.pkl")
        with open(scaler_path, "rb") as f:
            scalers = pickle.load(f)
        self.feature_scaler = scalers["feature_scaler"]
        self.target_scaler = scalers["target_scaler"]
        logger.info(
            f"  Scaler: feature(n={self.feature_scaler.n_features_in_}), "
            f"target_range=[{self.target_scaler.data_min_[0]:.1f}, "
            f"{self.target_scaler.data_max_[0]:.1f}] kW"
        )

        self._loaded = True
        logger.info("✅ 光伏 ML 模型加载完成")
        logger.info("=" * 60)

    # ========================================================================
    # 特征工程: Open-Meteo 数据 → 模型输入特征
    # ========================================================================

    @staticmethod
    def _estimate_precipitable_water(dew_point_c: float) -> float:
        """
        从露点温度估算可降水量 (mm)

        使用 Bevis (1992) 近似公式:
          PW ≈ 10 * exp(17.27 * Td / (237.3 + Td))

        Args:
            dew_point_c: 露点温度 (°C)

        Returns:
            可降水量 (mm)
        """
        if dew_point_c < -50:
            return 0.0
        pw = 10.0 * math.exp(17.27 * dew_point_c / (237.3 + dew_point_c))
        return max(0.0, min(60.0, pw))

    @staticmethod
    def _time_encoding(timestamp: pd.Timestamp) -> Dict[str, float]:
        """计算时间周期编码"""
        hour = timestamp.hour + timestamp.minute / 60.0
        month = timestamp.month
        day_of_year = timestamp.timetuple().tm_yday

        return {
            "hour_sin": float(np.sin(2 * np.pi * hour / 24)),
            "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
            "month_sin": float(np.sin(2 * np.pi * month / 12)),
            "month_cos": float(np.cos(2 * np.pi * month / 12)),
            "doy_sin": float(np.sin(2 * np.pi * day_of_year / 365)),
            "doy_cos": float(np.cos(2 * np.pi * day_of_year / 365)),
        }

    def _build_features(
        self,
        weather_df: pd.DataFrame,
        latitude: float,
        longitude: float,
    ) -> np.ndarray:
        """
        从 Open-Meteo 气象数据构建模型输入特征矩阵

        Args:
            weather_df: 气象数据 DataFrame, 必须包含 timestamp 列
            latitude: 纬度
            longitude: 经度

        Returns:
            features: (n_hours, 21) 特征矩阵
        """
        df = weather_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        n = len(df)

        # 初始化特征矩阵
        features = np.zeros((n, N_FEATURES), dtype=np.float32)

        for i, (_, row) in enumerate(df.iterrows()):
            ts = pd.Timestamp(row["timestamp"])

            # 气象参数映射 (带默认值)
            ghi = float(row.get("shortwave_radiation", 0) or 0)
            dni = float(row.get("direct_radiation", 0) or 0)
            dhi = float(row.get("diffuse_radiation", 0) or 0)
            temp = float(row.get("temperature_2m", 20) or 20)
            humidity = float(row.get("relative_humidity_2m", 50) or 50)
            wind_spd = float(row.get("wind_speed_10m", 0) or 0)
            wind_dir = float(row.get("wind_direction_10m", 270) or 270)
            pressure = float(row.get("surface_pressure", 1013) or 1013)
            dew_point = float(row.get("dew_point_2m", temp - 5) or (temp - 5))

            # 云层参数 (Open-Meteo: 0-100%, 训练数据: 0-100%)
            cloud_low = float(row.get("cloud_cover_low", row.get("cloud_cover", 0)) or 0)
            cloud_mid = float(row.get("cloud_cover_mid", row.get("cloud_cover", 0)) or 0)
            cloud_high = float(row.get("cloud_cover_high", row.get("cloud_cover", 0)) or 0)

            # 估算可降水量
            pw = self._estimate_precipitable_water(dew_point)

            # cloud_type: 无直接数据源, 使用 0 (默认)
            cloud_type = 0.0

            # 时间编码
            tc = self._time_encoding(ts)

            # 按 FEATURE_COLUMNS 顺序填充
            features[i] = [
                ghi, dni, dhi,
                temp, humidity, wind_spd, wind_dir,
                pressure, pw,
                cloud_type, cloud_low, cloud_mid, cloud_high,
                latitude, longitude,
                tc["hour_sin"], tc["hour_cos"],
                tc["month_sin"], tc["month_cos"],
                tc["doy_sin"], tc["doy_cos"],
            ]

        return features

    # ========================================================================
    # 推理
    # ========================================================================

    def predict(
        self,
        weather_df: pd.DataFrame,
        start_time: Optional[datetime] = None,
        latitude: float = 42.36,
        longitude: float = -71.06,
    ) -> Dict[str, Any]:
        """
        预测未来 24 小时光伏发电量

        流程:
          1. 从气象数据构建 24h 特征序列 (lookback)
          2. 归一化
          3. 4 模型集成推理
          4. 反归一化 → kW → MW

        Args:
            weather_df: 气象数据 DataFrame (至少 24 行)
            start_time: 预测起始时间 (默认取最后一条数据时间)
            latitude: 纬度
            longitude: 经度

        Returns:
            dict: {
                "hourly_pv_mw": List[float],    # 24h 预测 (MW)
                "hourly_pv_kw": List[float],    # 24h 预测 (kW)
                "total_mwh": float,             # 总发电量 (MWh)
                "peak_mw": float,               # 峰值功率 (MW)
                "capacity_factor": float,       # 容量因子
                "model_info": Dict,             # 模型信息
                "inference_time_ms": float,     # 推理耗时
            }
        """
        if not self._loaded:
            raise RuntimeError("模型未加载，请先调用 load_models()")

        infer_start = time.perf_counter()

        if start_time is None:
            start_time = datetime.now()

        # 构建 24h 特征序列
        features = self._build_features(weather_df, latitude, longitude)

        # 取最后 24h 作为 lookback 输入
        if len(features) >= LOOKBACK:
            input_seq = features[-LOOKBACK:]
        else:
            # 数据不足, 前面补 0
            padding = np.zeros((LOOKBACK - len(features), N_FEATURES), dtype=np.float32)
            input_seq = np.vstack([padding, features])
            logger.warning(f"气象数据不足 ({len(features)} < {LOOKBACK})，前面补零")

        # 归一化
        input_2d = input_seq.reshape(-1, N_FEATURES)
        input_norm = self.feature_scaler.transform(input_2d).reshape(1, LOOKBACK, N_FEATURES)

        # 转为 tensor
        input_tensor = torch.FloatTensor(input_norm).to(self.device)

        # 4 模型集成推理
        ensemble_pred = np.zeros((1, HORIZON), dtype=np.float32)
        individual_preds = {}

        with torch.no_grad():
            for name, model in self.models.items():
                pred = model(input_tensor)
                pred_np = pred.cpu().numpy()
                individual_preds[name] = pred_np

                weight = self.ensemble_weights.get(name, 0.25)
                ensemble_pred += pred_np * weight

        # 反归一化 (归一化值 → kW)
        ensemble_kw = self.target_scaler.inverse_transform(
            ensemble_pred.reshape(-1, 1)
        ).flatten()

        # 物理约束: 不为负
        ensemble_kw = np.maximum(ensemble_kw, 0.0)

        # kW → MW (训练数据中 pv_power_kw 最大约 480kW, 对应单站 500MW 装机)
        # 训练数据是单站 PVLib 仿真, 需要按装机容量缩放
        # 训练数据 max ≈ 480 kW (PVLib 仿真参数), 实际装机 500 MW
        # 缩放系数 = 500 MW / 0.48 MW = ~1042
        # 但更合理的做法: 直接用 kW 值作为单站输出, 乘以城市数得到区域总输出
        # 训练数据: 单站 PVLib 仿真, 峰值约 480 kW
        # 实际部署: 6 站 × 500 MW/站 = 3000 MW 区域总装机
        # 这里我们按单站 500 MW 装机进行缩放
        scale_factor = TOTAL_CAPACITY_MW / max(self.target_scaler.data_max_[0], 1.0)  # ~500/480 ≈ 1.04
        ensemble_mw = ensemble_kw * scale_factor

        # 统计
        total_mwh = float(ensemble_mw.sum())
        peak_mw = float(ensemble_mw.max())
        capacity_factor = total_mwh / (TOTAL_CAPACITY_MW * HORIZON)

        infer_time = (time.perf_counter() - infer_start) * 1000
        self._inference_count += 1
        self._total_inference_time_ms += infer_time

        # 生成时间戳
        timestamps = [
            (start_time + timedelta(hours=h)).isoformat()
            for h in range(HORIZON)
        ]

        return {
            "hourly_pv_mw": [round(float(v), 2) for v in ensemble_mw],
            "hourly_pv_kw": [round(float(v), 2) for v in ensemble_kw],
            "timestamps": timestamps,
            "total_mwh": round(total_mwh, 2),
            "peak_mw": round(peak_mw, 2),
            "capacity_factor": round(capacity_factor, 4),
            "model_info": self.get_model_info(),
            "ensemble_weights": self.ensemble_weights,
            "inference_time_ms": round(infer_time, 1),
            "device": str(self.device),
            "feature_count": N_FEATURES,
            "lookback": LOOKBACK,
            "horizon": HORIZON,
        }

    def predict_multi_station(
        self,
        weather_df: pd.DataFrame,
        start_time: Optional[datetime] = None,
        stations: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """
        多站点光伏预测: 对每个城市分别预测, 然后汇总

        Args:
            weather_df: 包含多站点气象数据的 DataFrame
                        需包含 location/name 列区分站点
            start_time: 预测起始时间
            stations: 站点坐标字典 {name: {lat, lon}}

        Returns:
            dict: 汇总预测结果
        """
        if stations is None:
            stations = NEW_ENGLAND_CITIES

        if start_time is None:
            start_time = datetime.now()

        all_station_preds = {}
        total_hourly_mw = np.zeros(HORIZON)

        for station_name, coords in stations.items():
            # 筛选该站点的数据
            station_mask = (
                weather_df.get("location", pd.Series([""] * len(weather_df))).str.contains(station_name, case=False)
                | weather_df.get("name", pd.Series([""] * len(weather_df))).str.contains(station_name, case=False)
            )

            if station_mask.any():
                station_df = weather_df[station_mask].copy()
            else:
                # 没有该站点数据, 使用全部数据的均值
                station_df = weather_df.copy()

            result = self.predict(
                station_df,
                start_time=start_time,
                latitude=coords["lat"],
                longitude=coords["lon"],
            )

            all_station_preds[station_name] = result
            total_hourly_mw += np.array(result["hourly_pv_mw"])

        # 汇总
        total_mwh = float(total_hourly_mw.sum())
        peak_mw = float(total_hourly_mw.max())
        total_capacity = TOTAL_CAPACITY_MW * len(stations)
        capacity_factor = total_mwh / (total_capacity * HORIZON)

        timestamps = [
            (start_time + timedelta(hours=h)).isoformat()
            for h in range(HORIZON)
        ]

        return {
            "hourly_pv_mw": [round(float(v), 2) for v in total_hourly_mw],
            "timestamps": timestamps,
            "total_mwh": round(total_mwh, 2),
            "peak_mw": round(peak_mw, 2),
            "capacity_factor": round(capacity_factor, 4),
            "station_count": len(stations),
            "station_results": {
                name: {
                    "hourly_pv_mw": r["hourly_pv_mw"],
                    "total_mwh": r["total_mwh"],
                    "peak_mw": r["peak_mw"],
                }
                for name, r in all_station_preds.items()
            },
            "model_info": self.get_model_info(),
            "ensemble_weights": self.ensemble_weights,
            "device": str(self.device),
        }

    # ========================================================================
    # 信息查询
    # ========================================================================

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        info = {}
        for name, model in self.models.items():
            param_count = sum(p.numel() for p in model.parameters())
            info[name] = {
                "weight": self.ensemble_weights.get(name, 0.25),
                "num_params": param_count,
                "loaded": True,
                "config": self.model_configs.get(name, {}),
            }
        return info

    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        avg_time = (
            self._total_inference_time_ms / self._inference_count
            if self._inference_count > 0 else 0
        )
        return {
            "loaded": self._loaded,
            "device": str(self.device),
            "model_count": len(self.models),
            "total_inferences": self._inference_count,
            "average_inference_time_ms": round(avg_time, 2),
            "ensemble_weights": self.ensemble_weights,
            "feature_count": N_FEATURES,
            "lookback": LOOKBACK,
            "horizon": HORIZON,
        }
