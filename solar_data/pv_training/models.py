# -*- coding: utf-8 -*-
"""
PV 光伏预测 — 模型定义
4 个 CPU 优化模型: LSTM, BiGRU, TCN, Transformer
"""

import torch
import torch.nn as nn
import math
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 1. LSTM (BiLSTM + Attention)
# ============================================================================

class LSTMModel(nn.Module):
    """BiLSTM + Attention + Dense"""
    
    def __init__(self, input_size=21, hidden_size=64, num_layers=2,
                 output_size=24, dropout=0.2, bidirectional=True):
        super().__init__()
        
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional,
        )
        
        lstm_out_size = hidden_size * (2 if bidirectional else 1)
        
        # 注意力
        self.attention = nn.Linear(lstm_out_size, 1)
        
        # 输出层
        self.fc1 = nn.Linear(lstm_out_size, 64)
        self.fc2 = nn.Linear(64, output_size)
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(lstm_out_size)
        
    def forward(self, x):
        # x: (batch, seq_len, input_size)
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden*2)
        lstm_out = self.layer_norm(lstm_out)
        
        # Attention
        attn_weights = torch.softmax(self.attention(lstm_out), dim=1)  # (batch, seq_len, 1)
        context = torch.sum(attn_weights * lstm_out, dim=1)  # (batch, hidden*2)
        
        # Dense
        x = torch.relu(self.fc1(context))
        x = self.dropout(x)
        output = self.fc2(x)
        
        return output


# ============================================================================
# 2. BiGRU
# ============================================================================

class BiGRUModel(nn.Module):
    """BiGRU + Dense (轻量级, 训练快)"""
    
    def __init__(self, input_size=21, hidden_size=64, num_layers=2,
                 output_size=24, dropout=0.2, bidirectional=True):
        super().__init__()
        
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional,
        )
        
        gru_out_size = hidden_size * (2 if bidirectional else 1)
        
        self.fc1 = nn.Linear(gru_out_size, 64)
        self.fc2 = nn.Linear(64, output_size)
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(gru_out_size)
        
    def forward(self, x):
        gru_out, _ = self.gru(x)
        gru_out = self.layer_norm(gru_out)
        
        # 取最后时刻
        last = gru_out[:, -1, :]  # (batch, hidden*2)
        
        x = torch.relu(self.fc1(last))
        x = self.dropout(x)
        output = self.fc2(x)
        
        return output


# ============================================================================
# 3. TCN (Temporal Convolutional Network)
# ============================================================================

class TCNBlock(nn.Module):
    """TCN 残差块"""
    
    def __init__(self, in_channels, out_channels, kernel_size, dilation, dropout):
        super().__init__()
        padding = (kernel_size - 1) * dilation // 2
        
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size,
                               padding=padding, dilation=dilation)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size,
                               padding=padding, dilation=dilation)
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.bn2 = nn.BatchNorm1d(out_channels)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.relu = nn.ReLU()
        
        self.downsample = nn.Conv1d(in_channels, out_channels, 1) \
            if in_channels != out_channels else None
    
    def forward(self, x):
        residual = x
        
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.dropout1(out)
        
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.dropout2(out)
        
        if self.downsample:
            residual = self.downsample(residual)
        
        out += residual
        out = self.relu(out)
        return out


class TCNModel(nn.Module):
    """TCN + Dense"""
    
    def __init__(self, input_size=21, num_channels=[32, 64, 32],
                 kernel_size=3, dilations=[1, 2, 4, 8],
                 output_size=24, dropout=0.2):
        super().__init__()
        
        layers = []
        in_ch = input_size
        for i, out_ch in enumerate(num_channels):
            dilation = dilations[i] if i < len(dilations) else 2 ** i
            layers.append(TCNBlock(in_ch, out_ch, kernel_size, dilation, dropout))
            in_ch = out_ch
        
        self.tcn = nn.Sequential(*layers)
        self.adaptive_pool = nn.AdaptiveAvgPool1d(1)
        self.fc1 = nn.Linear(num_channels[-1], 64)
        self.fc2 = nn.Linear(64, output_size)
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, x):
        # x: (batch, seq_len, input_size) → (batch, input_size, seq_len)
        out = self.tcn(x.transpose(1, 2))
        pooled = self.adaptive_pool(out).squeeze(2)
        
        x = torch.relu(self.fc1(pooled))
        x = self.dropout(x)
        output = self.fc2(x)
        return output


# ============================================================================
# 4. Transformer
# ============================================================================

class TransformerModel(nn.Module):
    """Transformer Encoder + Dense"""
    
    def __init__(self, input_size=21, d_model=64, nhead=4, num_layers=2,
                 d_ff=128, output_size=24, dropout=0.2):
        super().__init__()
        
        self.input_proj = nn.Linear(input_size, d_model)
        
        # 可学习位置编码
        self.pos_encoding = nn.Parameter(torch.zeros(100, d_model))
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        self.fc1 = nn.Linear(d_model, 64)
        self.fc2 = nn.Linear(64, output_size)
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(d_model)
        
    def forward(self, x):
        # x: (batch, seq_len, input_size)
        seq_len = x.size(1)
        
        x = self.input_proj(x)
        x = x + self.pos_encoding[:seq_len, :].unsqueeze(0)
        x = self.dropout(x)
        
        encoded = self.encoder(x)
        encoded = self.layer_norm(encoded)
        
        # 取最后时刻
        final = encoded[:, -1, :]
        
        x = torch.relu(self.fc1(final))
        x = self.dropout(x)
        output = self.fc2(x)
        return output


# ============================================================================
# 模型工厂
# ============================================================================

def create_model(model_name, config):
    """创建模型"""
    models = {
        "LSTM": LSTMModel,
        "BiGRU": BiGRUModel,
        "TCN": TCNModel,
        "Transformer": TransformerModel,
    }
    
    if model_name not in models:
        raise ValueError(f"未知模型: {model_name}, 可选: {list(models.keys())}")
    
    model = models[model_name](**config)
    param_count = sum(p.numel() for p in model.parameters())
    logger.info(f"  {model_name}: {param_count:,} 参数 ({param_count * 4 / 1024:.1f} KB)")
    
    return model


def create_all_models(configs):
    """创建所有模型"""
    logger.info("创建模型:")
    models = {}
    for name, cfg in configs.items():
        models[name] = create_model(name, cfg)
    return models


# ============================================================================
# 测试
# ============================================================================
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    logging.basicConfig(level=logging.INFO)
    
    from config import MODEL_CONFIGS
    
    models = create_all_models(MODEL_CONFIGS)
    
    print("\n模型构建测试:")
    dummy = torch.randn(4, 24, 21)  # batch=4, seq=24, features=21
    
    for name, model in models.items():
        out = model(dummy)
        params = sum(p.numel() for p in model.parameters())
        print(f"  {name:12s}: 输入{dummy.shape} → 输出{out.shape}, 参数{params:,}")
    
    print("\n所有模型测试通过!")
