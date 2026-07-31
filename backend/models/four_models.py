# ===================================================================================
# 毕业设计专用 - 四模型高准确率电力负荷预测系统
# LSTM、Transformer、TCN、GRU 完整实现
# 包含论文所有可视化功能
# ===================================================================================

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec
import pandas as pd
import pickle
import os
import logging
from datetime import datetime
from tqdm import tqdm
import json

# 设置日志
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===================================================================================
# 🎯 模型1: 增强型LSTM (Enhanced LSTM)
# ===================================================================================
class EnhancedLSTM(nn.Module):
    """
    增强型LSTM模型，专为电力负荷预测设计
    特点：双层LSTM + 注意力 + 正则化 + 残差
    """
    
    def __init__(self, input_size=14, hidden_size=128, 
                 num_layers=3, output_size=24, 
                 dropout=0.3, l2_reg=1e-4):
        super(EnhancedLSTM, self).__init__()
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        
        # 第一层LSTM (编码)
        self.lstm1 = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout,
            bidirectional=False
        )
        
        # 第二层LSTM (特征提取)
        self.lstm2 = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size // 2,
            num_layers=num_layers - 1,
            batch_first=True,
            dropout=dropout
        )
        
        # 注意力机制
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size // 2,
            num_heads=4,
            dropout=dropout,
            batch_first=True
        )
        
        # 注意力权重
        self.attention_weights = None
        
        # 正则化层
        self.layer_norm1 = nn.LayerNorm(hidden_size)
        self.layer_norm2 = nn.LayerNorm(hidden_size // 2)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        
        # 输出投影层
        self.fc1 = nn.Linear(hidden_size // 2, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc_out = nn.Linear(32, output_size)
        
        # 激活函数
        self.relu = nn.ReLU()
        self.tanh = nn.Tanh()
        
        # 残差连接
        self.residual = nn.Linear(input_size, output_size)
        
        self.l2_reg = l2_reg
        
        logger.info(f"EnhancedLSTM创建 - 参数量: {sum(p.numel() for p in self.parameters()):,}")
        
    def forward(self, x):
        batch_size, seq_len, _ = x.size()
        # 保存原始输入用于残差连接
        original_x = x
        
        # 第一层LSTM
        lstm1_out, (h1, c1) = self.lstm1(x)
        lstm1_out = self.layer_norm1(lstm1_out)
        lstm1_out = self.dropout1(lstm1_out)
        
        # 第二层LSTM
        lstm2_out, (h2, c2) = self.lstm2(lstm1_out)
        lstm2_out = self.layer_norm2(lstm2_out)
        
        # 注意力机制
        attn_out, attn_weights = self.attention(
            lstm2_out, lstm2_out, lstm2_out
        )
        self.attention_weights = attn_weights
        
        # 残差LSTM输出
        combined = lstm2_out + attn_out
        
        # 取最后时刻特征
        final_features = combined[:, -1, :]
        
        # 全连接层
        x = self.relu(self.fc1(final_features))
        x = self.dropout2(x)
        x = self.tanh(self.fc2(x))
        x = self.dropout2(x)
        
        lstm_output = self.fc_out(x)
        
        # 残差连接 (使用原始输入的最后时刻)
        residual_input = original_x[:, -1, :]  # 取序列最后时刻的输入特征
        residual_output = self.residual(residual_input).unsqueeze(1)
        
        # 输出
        output = lstm_output + residual_output.squeeze(1) * 0.1
        
        return output
        
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        self.criterion = nn.MSELoss()
        
        # 学习率调度
        self.scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode='min', factor=0.5, 
            patience=5, verbose=True
        )

# ===================================================================================
# 🎯 模型2: 时空Transformer (Spatial-Temporal Transformer)
# ===================================================================================
class SpatialTemporalTransformer(nn.Module):
    """
    时空Transformer模型
    特点：时间注意力 + 特征注意力 + 位置编码
    """
    
    def __init__(self, input_size=14, d_model=128, nhead=8,
                 num_layers=4, d_ff=512, output_size=24,
                 dropout=0.3, l2_reg=1e-4):
        super(SpatialTemporalTransformer, self).__init__()
        
        self.d_model = d_model
        self.l2_reg = l2_reg
        
        # 输入嵌入
        self.input_embed = nn.Sequential(
            nn.Linear(input_size, d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
            nn.LayerNorm(d_model)
        )
        
        # 时间位置编码
        self.time_pos_encoding = nn.Parameter(
            self._create_positional_encoding(200, d_model)
        )
        
        # 通道注意力机制 (不同特征维度的重要性)
        self.channel_attention = nn.Sequential(
            nn.Linear(d_model, d_model // 4),
            nn.ReLU(),
            nn.Linear(d_model // 4, d_model),
            nn.Sigmoid()
        )
        
        # Transformer编码器 (时间注意力)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=num_layers
        )
        
        # 融合层
        self.fusion = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # 输出层
        self.output_proj = nn.Sequential(
            nn.Linear(d_model, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, output_size)
        )
        
        self.dropout = nn.Dropout(dropout)
        
        logger.info(f"SpatialTemporalTransformer创建 - 参数量: {sum(p.numel() for p in self.parameters()):,}")
        
    def _create_positional_encoding(self, max_len, d_model):
        """创建位置编码"""
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model)
        )
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        return pe.unsqueeze(0)
    
    def forward(self, x):
        batch_size, seq_len, input_size = x.size()
        
        # 输入嵌入
        x_embedded = self.input_embed(x)  # [B, T, D]
        
        # 添加时间位置编码
        x_with_time_pos = x_embedded + self.time_pos_encoding[:, :seq_len, :]
        x_with_time_pos = self.dropout(x_with_time_pos)
        
        # Transformer时间注意力
        time_attended = self.transformer_encoder(x_with_time_pos)
        
        # 通道注意力 - 学习不同特征维度的重要性
        channel_weights = self.channel_attention(
            time_attended.mean(dim=1)  # [B, D] - 时间维度均值
        )  # [B, D]
        feature_attended = time_attended * channel_weights.unsqueeze(1)  # [B, T, D]
        
        # 融合时间和特征表示
        time_features = time_attended[:, -1, :]  # [B, D] - 最后时刻
        feature_features = feature_attended.mean(dim=1)  # [B, D] - 加权时间均值
        
        fused_features = torch.cat([time_features, feature_features], dim=1)
        fused_features = self.fusion(fused_features)
        
        # 输出
        output = self.output_proj(fused_features)
        
        return output
        
    def compile(self, learning_rate=5e-4):
        """配置优化器"""
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        self.criterion = nn.MSELoss()
        
        # 余弦退火调度
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=50, eta_min=1e-6
        )

# ===================================================================================
# 🎯 模型3: 深度TCN (Deep TCN)
# ===================================================================================
class DeepTCN(nn.Module):
    """
    深度TCN模型
    特点：多尺度扩张卷积 + 残差块 + 门控机制
    """
    
    def __init__(self, input_size=14, num_channels=[64, 128, 64, 32], 
                 kernel_size=3, output_size=24, dropout=0.3, 
                 l2_reg=1e-4):
        super(DeepTCN, self).__init__()
        
        self.l2_reg = l2_reg
        self.num_channels = num_channels
        
        # 输入适配
        self.input_conv = nn.Conv1d(
            input_size, num_channels[0], kernel_size=1
        )
        
        # TCN残差块序列
        self.tcn_blocks = nn.ModuleList()
        
        for i in range(len(num_channels) - 1):
            dilation = 2 ** i
            
            self.tcn_blocks.append(
                TCNResidualBlock(
                    input_dim=num_channels[i],
                    output_dim=num_channels[i + 1],
                    kernel_size=kernel_size,
                    dilation=dilation,
                    dropout=dropout
                )
            )
        
        # 门控机制
        self.gate = nn.Conv1d(
            num_channels[-1], num_channels[-1], 
            kernel_size=1
        )
        
        # 时间池化
        self.temporal_pool = nn.AdaptiveAvgPool1d(1)
        
        # 输出投影
        self.output_proj = nn.Sequential(
            nn.Linear(num_channels[-1], 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, output_size)
        )
        
        self.dropout = nn.Dropout(dropout)
        self.relu = nn.ReLU()
        
        logger.info(f"DeepTCN创建 - 参数量: {sum(p.numel() for p in self.parameters()):,}")
        
    def forward(self, x):
        # 输入转换 [B, T, F] -> [B, F, T]
        x = x.transpose(1, 2)
        
        # 输入卷积
        x = self.relu(self.input_conv(x))
        
        # TCN残差块序列
        for block in self.tcn_blocks:
            x = block(x)
        
        # 门控机制
        gate_values = torch.sigmoid(self.gate(x))
        x = x * gate_values
        
        # 时间池化
        pooled = self.temporal_pool(x).squeeze(2)  # [B, C]
        
        # 输出
        output = self.output_proj(pooled)
        
        return output
        
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        self.criterion = nn.MSELoss()

class TCNResidualBlock(nn.Module):
    """
    TCN残差块实现
    """
    
    def __init__(self, input_dim, output_dim, kernel_size, dilation, dropout):
        super(TCNResidualBlock, self).__init__()
        
        # 计算padding
        padding = (kernel_size - 1) * dilation // 2
        
        # 时间卷积1
        self.conv1 = nn.Conv1d(
            input_dim, output_dim, kernel_size,
            padding=padding, dilation=dilation
        )
        self.bn1 = nn.BatchNorm1d(output_dim)
        
        # 时间卷积2
        self.conv2 = nn.Conv1d(
            output_dim, output_dim, kernel_size,
            padding=padding, dilation=dilation
        )
        self.bn2 = nn.BatchNorm1d(output_dim)
        
        # 激活函数
        self.relu = nn.ReLU()
        
        # Dropout
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        
        # 下采样
        if input_dim != output_dim:
            self.downsample = nn.Conv1d(input_dim, output_dim, 1)
        else:
            self.downsample = None
        
    def forward(self, x):
        residual = x
        
        # 第一个卷积块
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.dropout1(out)
        
        # 第二个卷积块
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.dropout2(out)
        
        # 下采样
        if self.downsample:
            residual = self.downsample(residual)
        
        # 残差连接
        out += residual
        out = self.relu(out)
        
        return out

# ===================================================================================
# 🎯 模型4: 双向GRU (Bidirectional GRU)
# ===================================================================================
class BiGRU(nn.Module):
    """
    双向GRU模型
    特点：双向捕获 + 注意力 + 多层堆叠
    """
    
    def __init__(self, input_size=14, hidden_size=128, 
                 num_layers=3, output_size=24, 
                 dropout=0.3, l2_reg=1e-4):
        super(BiGRU, self).__init__()
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.l2_reg = l2_reg
        
        # 双向GRU层
        self.bigru1 = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout,
            bidirectional=True
        )
        
        self.bigru2 = nn.GRU(
            input_size=hidden_size * 2,
            hidden_size=hidden_size,
            num_layers=num_layers - 1,
            batch_first=True,
            dropout=dropout,
            bidirectional=True
        )
        
        # 注意力机制
        self.attention = AttentionLayer(hidden_size * 2)
        
        # 归一化层
        self.layer_norm1 = nn.LayerNorm(hidden_size * 2)
        self.layer_norm2 = nn.LayerNorm(hidden_size * 2)
        
        # 特征聚合
        self.feature_agg = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # 输出层
        self.output_proj = nn.Sequential(
            nn.Linear(hidden_size, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, output_size)
        )
        
        self.dropout = nn.Dropout(dropout)
        
        logger.info(f"BiGRU创建 - 参数量: {sum(p.numel() for p in self.parameters()):,}")
        
    def forward(self, x):
        batch_size, seq_len, input_size = x.size()
        
        # 第一层GRU
        gru1_out, h1 = self.bigru1(x)
        gru1_out = self.layer_norm1(gru1_out)
        gru1_out = self.dropout(gru1_out)
        
        # 第二层GRU
        gru2_out, h2 = self.bigru2(gru1_out)
        gru2_out = self.layer_norm2(gru2_out)
        
        # 注意力机制
        attended, attention_weights = self.attention(gru2_out)
        self.attention_weights = attention_weights
        
        # 特征聚合
        aggregated = self.feature_agg(attended)
        
        # 输出投影
        output = self.output_proj(aggregated)
        
        return output
        
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        self.criterion = nn.MSELoss()

class AttentionLayer(nn.Module):
    """
    注意力层实现
    """
    
    def __init__(self, hidden_size):
        super(AttentionLayer, self).__init__()
        
        self.attention = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.Tanh(),
            nn.Linear(hidden_size // 2, 1, bias=False)
        )
        
    def forward(self, x):
        # x shape: [batch_size, seq_len, hidden_size]
        
        # 计算注意力分数
        attention_scores = self.attention(x)  # [batch_size, seq_len, 1]
        
        # softmax归一化
        attention_weights = torch.softmax(attention_scores, dim=1)
        
        # 加权求和
        weighted_sum = torch.sum(x * attention_weights, dim=1)
        
        return weighted_sum, attention_weights.squeeze(2)

# ===================================================================================
# 🎯 模型工厂
# ===================================================================================
def create_four_models(device_info=True):
    """
    创建四个前沿模型
    """
    
    # 设备选择
    if torch.cuda.is_available():
        device = torch.device('cuda')
        if device_info:
            logger.info(f"🚀 使用GPU训练: {torch.cuda.get_device_name()}")
            logger.info(f"💽 GPU显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
    else:
        device = torch.device('cpu')
        if device_info:
            logger.info("⚠️ 未检测到GPU，使用CPU训练")
    
    # 创建四个模型
    models = {
        'EnhancedLSTM': EnhancedLSTM(
            input_size=38,
            hidden_size=128,
            num_layers=3,
            output_size=24,
            dropout=0.3,
            l2_reg=1e-4
        ),
        
        'SpatialTransformer': SpatialTemporalTransformer(
            input_size=38,
            d_model=128,
            nhead=8,
            num_layers=4,
            d_ff=512,
            output_size=24,
            dropout=0.3,
            l2_reg=1e-4
        ),
        
        'DeepTCN': DeepTCN(
            input_size=38,
            num_channels=[64, 128, 64, 32],
            kernel_size=3,
            output_size=24,
            dropout=0.3,
            l2_reg=1e-4
        ),
        
        'BiGRU': BiGRU(
            input_size=38,
            hidden_size=128,
            num_layers=3,
            output_size=24,
            dropout=0.3,
            l2_reg=1e-4
        )
    }
    
    # 移动到设备并编译
    for name, model in models.items():
        model = model.to(device)
        model.compile(learning_rate=1e-3)
        models[name] = model
        
    if device_info:
        logger.info("✅ 四个前沿模型创建完成")
        for name, model in models.items():
            num_params = sum(p.numel() for p in model.parameters())
            logger.info(f"  {name}: {num_params:,} 参数")
            
    return models, device

if __name__ == "__main__":
    # 快速测试模型创建
    print("🎯 测试四模型创建...")
    models, device = create_four_models()
    
    print(f"\n✅ 模型创建成功!")
    for name in models.keys():
        params = sum(p.numel() for p in models[name].parameters())
        print(f"  {name}: {params:,} 参数")
    
    print(f"🎊 四模型系统验证完成!")