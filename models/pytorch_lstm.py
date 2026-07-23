# ==========================================================================
# PyTorch LSTM模型 - 智能电网负荷预测
# ==========================================================================

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from tqdm import tqdm
import logging

logger = logging.getLogger(__name__)

class PyTorchLSTM(nn.Module):
    """
    PyTorch LSTM模型，带注意力机制
    """
    
    def __init__(self, input_size=14, hidden_size=64, num_layers=2, 
                 output_size=24, dropout=0.2, l2_reg=1e-4):
        """
        初始化LSTM模型
        
        Args:
            input_size: 输入特征数 (14)
            hidden_size: LSTM隐藏单元数
            num_layers: LSTM层数
            output_size: 输出维度 (预测序列长度, 24)
            dropout: dropout率
            l2_reg: L2正则化系数
        """
        super(PyTorchLSTM, self).__init__()
        
        # LSTM层
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
            bidirectional=False
        )
        
        # 注意力机制
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=4,
            dropout=dropout,
            batch_first=False
        )
        
        # 输出层
        self.fc1 = nn.Linear(hidden_size, 32)
        self.fc2 = nn.Linear(32, output_size)
        
        # 正则化
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(hidden_size)
        self.l2_reg = l2_reg
        
        # 激活函数
        self.relu = nn.ReLU()
        
        logger.info(f"PyTorch LSTM模型创建完成")
        
    def forward(self, x):
        """
        前向传播
        
        Args:
            x: 输入张量 [batch_size, seq_len, input_size]
            
        Returns:
            output: 预测结果 [batch_size, output_size]
        """
        batch_size = x.size(0)
        
        # LSTM层 [batch_size, seq_len, hidden_size] 
        lstm_out, (hidden, cell) = self.lstm(x)
        
        # 层归一化
        lstm_out = self.layer_norm(lstm_out)
        
        # 注意力机制 [seq_len, batch_size, hidden_size]
        attn_out, attn_weights = self.attention(
            lstm_out.transpose(0, 1),
            lstm_out.transpose(0, 1), 
            lstm_out.transpose(0, 1)
        )
        
        # 还原形状 [batch_size, seq_len, hidden_size]
        attn_out = attn_out.transpose(0, 1)
        
        # 取最后时刻输出 [batch_size, hidden_size]
        lstm_last = attn_out[:, -1, :]
        
        # 全连接层
        x = self.relu(self.fc1(lstm_last))
        x = self.dropout(x)
        output = self.fc2(x)
        
        return output
    
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        
        # 优化器
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        
        # 损失函数
        self.criterion = nn.MSELoss()
        
        logger.info(f"模型配置 - 学习率: {learning_rate}, L2正则化: {self.l2_reg}")

class PyTorchTransformer(nn.Module):
    """
    PyTorch Transformer模型 
    """
    
    def __init__(self, input_size=14, d_model=64, nhead=4, 
                 num_layers=2, d_ff=128, output_size=24, 
                 dropout=0.2, l2_reg=1e-4):
        """
        初始化Transformer模型
        
        Args:
            input_size: 输入特征数
            d_model: 模型维度
            nhead: 注意力头数
            num_layers: Transformer层数
            d_ff: 前馈网络维度
            output_size: 输出维度
            dropout: dropout率
            l2_reg: L2正则化系数
        """
        super(PyTorchTransformer, self).__init__()
        
        # 输入投影
        self.input_proj = nn.Linear(input_size, d_model)
        
        # 位置编码
        self.pos_encoding = nn.Parameter(torch.zeros(50, d_model))
        
        # Transformer编码器
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
        
        # 输出层
        self.fc1 = nn.Linear(d_model, 32)
        self.fc2 = nn.Linear(32, output_size)
        
        # 正则化
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(d_model)
        self.l2_reg = l2_reg
        
        # 激活函数
        self.relu = nn.ReLU()
        
        logger.info(f"PyTorch Transformer模型创建完成")
        
    def forward(self, x):
        """
        前向传播
        """
        # 输入投影
        x = self.input_proj(x)  # [batch_size, seq_len, d_model]
        
        # 添加位置编码
        x = x + self.pos_encoding[:x.size(1), :].unsqueeze(0)
        x = self.dropout(x)
        
        # Transformer编码器
        encoded = self.transformer_encoder(x)  # [batch_size, seq_len, d_model]
        
        # 层归一化
        encoded = self.layer_norm(encoded)
        
        # 取最后时刻输出
        final_state = encoded[:, -1, :]  # [batch_size, d_model]
        
        # 全连接层
        x = self.relu(self.fc1(final_state))  # [batch_size, 32]
        x = self.dropout(x)
        output = self.fc2(x)  # [batch_size, output_size]
        
        return output
        
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        
        # 优化器
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        
        # 损失函数
        self.criterion = nn.MSELoss()
        
        logger.info(f"模型配置 - 学习率: {learning_rate}, L2正则化: {self.l2_reg}")

class PyTorchTCN(nn.Module):
    """
    PyTorch TCN模型
    """
    
    def __init__(self, input_size=14, num_channels=[32, 64, 32], 
                 kernel_size=3, output_size=24, dropout=0.2, 
                 l2_reg=1e-4):
        """
        初始化TCN模型
        
        Args:
            input_size: 输入特征数
            num_channels: TCN通道列表
            kernel_size: 卷积核大小
            output_size: 输出维度
            dropout: dropout率
            l2_reg: L2正则化系数
        """
        super(PyTorchTCN, self).__init__()
        
        layers = []
        num_levels = len(num_channels)
        
        # TCN层
        input_dim = input_size
        for i in range(num_levels):
            output_dim = num_channels[i]
            dilation_size = 2 ** i
            
            # 残差块
            layers.append(
                TCNBlock(
                    input_dim=input_dim,
                    output_dim=output_dim,
                    kernel_size=kernel_size,
                    stride=1,
                    dilation=dilation_size,
                    dropout=dropout
                )
            )
            
            input_dim = output_dim
        
        self.tcn = nn.Sequential(*layers)
        
        # 输出适配层
        self.adapt = nn.AdaptiveAvgPool1d(1)
        self.fc1 = nn.Linear(num_channels[-1], 32)
        self.fc2 = nn.Linear(32, output_size)
        
        # 正则化
        self.dropout = nn.Dropout(dropout)
        self.l2_reg = l2_reg
        
        # 激活函数
        self.relu = nn.ReLU()
        
        logger.info(f"PyTorch TCN模型创建完成")
        
    def forward(self, x):
        """
        前向传播
        """
        # TCN处理 [batch_size, channels, seq_len]
        tcn_out = self.tcn(x.transpose(1, 2))
        
        # 全局平均池化 [batch_size, channels]
        pooled = self.adapt(tcn_out).squeeze(2)
        
        # 全连接层
        x = self.relu(self.fc1(pooled))
        x = self.dropout(x)
        output = self.fc2(x)
        
        return output
        
    def compile(self, learning_rate=1e-3):
        """配置优化器"""
        
        # 优化器  
        self.optimizer = optim.Adam(
            self.parameters(),
            lr=learning_rate,
            weight_decay=self.l2_reg
        )
        
        # 损失函数
        self.criterion = nn.MSELoss()
        
        logger.info(f"模型配置 - 学习率: {learning_rate}, L2正则化: {self.l2_reg}")

class TCNBlock(nn.Module):
    """
    TCN残差块
    """
    
    def __init__(self, input_dim, output_dim, kernel_size, stride, dilation, dropout):
        super(TCNBlock, self).__init__()
        
        # 设计算
        padding = (kernel_size - 1) * dilation // 2
        
        # 两个卷积层
        self.conv1 = nn.Conv1d(
            input_dim, output_dim, kernel_size,
            stride=stride, padding=padding, dilation=dilation
        )
        self.conv2 = nn.Conv1d(
            output_dim, output_dim, kernel_size,
            stride=stride, padding=padding, dilation=dilation
        )
        
        # 批归一化
        self.bn1 = nn.BatchNorm1d(output_dim)
        self.bn2 = nn.BatchNorm1d(output_dim)
        
        # 正则化
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        
        # 激活函数
        self.relu = nn.ReLU()
        
        # 下采样（如果维度不匹配）
        if input_dim != output_dim:
            self.downsample = nn.Conv1d(input_dim, output_dim, 1)
        else:
            self.downsample = None
        
    def forward(self, x):
        """前向传播"""
        residual = x
        
        # 第一层
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.dropout1(out)
        
        # 第二层
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

# 模型工厂
def create_pytorch_models(device_info=True):
    """
    创建PyTorch模型集合
    
    Args:
        device_info: 是否显示设备信息
        
    Returns:
        models: 模型字典
        device: PyTorch设备
    """
    
    # 选择设备
    if torch.cuda.is_available():
        device = torch.device('cuda')
        if device_info:
            logger.info(f"🚀 使用GPU: {torch.cuda.get_device_name()}")
            logger.info(f"💽 GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
            
    else:
        device = torch.device('cpu')
        if device_info:
            logger.info("⚠️ 未检测到可用的GPU，使用CPU训练")
    
    # 创建模型
    models = {}
    
    # LSTM模型
    models['LSTM'] = PyTorchLSTM(
        input_size=14,
        hidden_size=64,
        num_layers=2,
        output_size=24,
        dropout=0.2,
        l2_reg=1e-4
    )
    
    # Transformer模型
    models['Transformer'] = PyTorchTransformer(
        input_size=14,
        d_model=64,
        nhead=4,
        num_layers=2,
        d_ff=128,
        output_size=24,
        dropout=0.2,
        l2_reg=1e-4
    )
    
    # TCN模型 
    models['TCN'] = PyTorchTCN(
        input_size=14,
        num_channels=[32, 64, 32],
        kernel_size=3,
        output_size=24,
        dropout=0.2,
        l2_reg=1e-4
    )
    
    # 移动模型到设备并编译
    for name, model in models.items():
        models[name] = model.to(device)
        model.compile(learning_rate=1e-3)
    
    if device_info:
        logger.info("✅ 所有PyTorch模型创建并配置完成")
        
    return models, device

if __name__ == "__main__":
    # 测试模型创建
    print("🎯 测试PyTorch模型创建...")
    models, device = create_pytorch_models()
    
    print(f"\n✅ 模型创建成功!")
    print(f"💻 训练设备: {device}")
    for name in models.keys():
        print(f"📦 模型 {name}: {sum(p.numel() for p in models[name].parameters()):,} 参数")
        
    print(f"\n🎊 PyTorch环境验证完成!")