# 智能电网负荷预测 —— 数据勘察分析与训练方案报告

> 任务：未来 24 小时逐时负荷预测（24-step multi-step hourly load forecasting）
> 数据：`C:\MMXX\datas`（3 个 Excel） | 训练环境：WSL2 Ubuntu 22.04 + Python 3.10 venv（`/home/wy/ai-projects/tensorflow-env`）+ RTX 3050 Laptop GPU
> 生成日期：2026-09-04（会话时点，UTC+8） | 2026 年数据经用户确认为**真实发布数据** | 本报告由分析脚本产出，未修改任何项目代码

---

## 0. 重要事实与前置说明

1. **数据不是 CSV，而是 3 个 `.xlsx` 工作簿**（ISO New England 公开 SMD 数据，Notes 页注明 "ISO New England Public"）。已用 pandas+openpyxl 完整解析。
2. **本会话无法访问 WSL/Ubuntu 侧**（`wsl.exe` 返回 `E_ACCESSDENIED`，`\\wsl.localhost` 不存在）。因此：
   - `/home/wy/ai-projects/smart-grid`（含既有代码/模型）**本次无法读取**，分析完全基于 Windows 侧数据副本；
   - GPU 预检不能由我代跑，**需你在 Ubuntu 内执行**（脚本已给出，见 §6）。
3. 所有分析脚本位于 `C:\MMXX\analysis\`，结果 JSON 在 `C:\MMXX\analysis\out\`（含 3 个 `*_qa.json`、`anomalies.json`、`baselines_seasonality.json`），可复核。

---

## 1. 文件与数据结构勘察

| 文件 | 大小 | 控制区(21列) | 8 个负荷分区(14列) | 行数/表 | 覆盖区间 |
|---|---|---|---|---|---|
| `2024_smd_hourly.xlsx` | 7.4 MB | ISO NE CA | ME, NH, VT, CT, RI, SEMA, WCMA, NEMA | 8784 | 2024-01-01 → 2024-12-31（闰年）|
| `2025_smd_hourly.xlsx` | 7.4 MB | ISO NE CA | 同上 | 8760 | 2025-01-01 → 2025-12-31 |
| `2026_smd_hourly.xlsx` | 4.4 MB | ISO NE CA | 同上 | 5087 | 2026-01-01 → **2026-07-31**（截至 07-31 24 时）|

每本含 `Notes` 说明页 + 9 个数据表。**分区合计与控制区 RT_Demand 完全一致**（最大偏差 0.002 MW），因此分区与总量可互为校验。

### 字段字典（来自 Notes）

通用 14 列（9 个表都有）：
- `Date` 日期；`Hr_End` 结束时刻制小时 1–24（秋季回拨日多一行 `02X`）
- 负荷：`DA_Demand`（日前出清需求 MW，含虚拟交易净值，**可为负**）、`RT_Demand`（实时结算需求 MW，非负）
- 价格：`DA_LMP/DA_EC/DA_CC/DA_MLC`（日前 LMP 及其能量/阻塞/网损分量）、`RT_LMP/RT_EC/RT_CC/RT_MLC`；`ISO NE CA` 页的 LMP 为 **Trading Hub** 值
- 气象：`Dry_Bulb`（干球温度 °F）、`Dew_Point`（露点 °F）——每个分区对应代表站，CA 为按售电量加权值（权重表见 Notes：BOS/BDR/BTV/CON/PWM/PVD/BDL/ORH）

控制区 ISO NE CA 独有 7 列：`System_Load`（实际系统负荷，规划口径）、`Reg_Service_Price`、`Reg_Capacity_Price`、`Min/Max_5min_RSP`、`Min/Max_5min_RCP`（调频市场结算价）。

### 时间语义（重要）
- 数据采用 **hour-ending（结束时刻）** 约定：`Date=2024-01-01, Hr_End=01` 表示 00:00–01:00 这一小时。
- 春季 DST 跳小时日该日仅 23 行（如 2025-03-09）；秋季回拨日多一行，ISO 用 `Hr_End="02X"` 标记重复的第 2 个 02 时（2024-11-03、2025-11-02 各有 1 行）。

---

## 2. 数据质量检查结论

### 2.1 缺失与重复 —— 干净
- 9 个数据表 × 3 年：**数值列 0 缺失**（气象、价格、负荷全部无 NaN）；无整行重复、无重复时间键。
- 每年唯一的"缺口"恰为 DST 春季被跳过的那一小时（23 行日），唯一的"额外行"恰为秋季 `02X` —— 均属 ISO-NE 正常约定，**非数据丢失**。
- 气象取值范围合理：干球温度 0–98 °F，露点 −17–76 °F，无异常值。

### 2.2 异常/特殊值定位（无需删除，处理规则见 §4.3）
| 现象 | 位置 | 性质判定 |
|---|---|---|
| `DA_Demand<0` | VT：2024-04~06(26 行, 最低 −64)；2025-03~05/09(16 行)；2026-04~07(17 行)；ME：2026-03~07(40 行, 最低 −283.8)，且都出现在 11–16 时前后 | 日前出清"净需求"含虚拟投标与光伏/表后净计量抵消的**市场机制产物**，真实存在。目标列不用 DA；如作特征需 clip≥0 |
| 2026-01 DA_LMP≈143–173 / RT_LMP≈76–122 | 2026 年 1 月整月 | **非列错位**。2026-01 是严冬高电价月：DA 中位 123.4 / RT 中位 121.6，p95 达 DA 496 / RT 373，DA−RT 价差 p95≈±218；新年凌晨几小时 DA 高于 RT ~100 落在此分布内，属高波动场景。若不做电价预测可忽略 |
| RT_Demand 尖峰(z>6) | 2024:6 处、2025:4 处、2026:34 处 | 集中在热夜（2024-05-23、2025-10-06/07、2026-05-19~21/28 深夜负荷高 20–40%），与干热天气吻合，为真实天气事件（2026 年 5 月明显偏热，CA 最高 92 °F），非坏点 |
| `System_Load` vs `RT_Demand` | CA 全时段 | corr=0.9998+，System_Load≈RT_Demand+(240–300 MW)（口径差异：含储能/DR 处理不同）。两者都可作目标，推荐 RT_Demand（口径统一、=分区之和） |

### 2.3 时间连续性 —— 结论
以"物理小时"为轴逐年完整：2024=366×24h、2025=365×24h、2026=212×24h−1(DST)。**无需插值填补**；只需在建立索引时处理 3 类 DST 特例（见 §4.2）。

---

## 3. 问题规模与基线（决定"好模型"的门槛）

目标：ISO NE CA 的 `RT_Demand`（MW）。样本量：2024+2025 ≈ 1.75 万小时用于训练，2026 前 7 个月约 0.51 万小时可用作验证。

### 3.1 序列基本统计（CA RT_Demand）
| 年 | 均值 | 中位 | 标准差 | 峰谷差(周内典型) |
|---|---|---|---|---|
| 2024 | 13058 | 12740 | 2570 | 工作日均值 13301 vs 周末 12448（低 ~6.4%）|
| 2025 | 13204 | 12885 | 2694 | 晚高峰 18 时约 15.6k，凌晨约 9–12k |
| 2026 | 13442 | 13108 | 2724 | 逐年 ~+1.5% 增长 |

工作日 18 时均值中位 ~15600 MW vs 凌晨 ~9000–12000 MW → **日双峰/晚峰明显，周季节明显**。

### 3.2 无训练基线（越简单基线，越体现难度）
| 基线（24h 提前） | RMSE (MW) | MAE (MW) | MAPE |
|---|---|---|---|
| 周小时剖面(2024 学习) | 2025: 2228 / 2026: 2366 | 1745 / 1870 | 13.1% / 13.9% |
| 同小时上周(naive-168) | 2025: 2041 / 2026: 2101 | 1410 / 1552 | 10.3% / 11.3% |
| 昨日同小时(naive-24) | 2025: 1384 / 2026: 1349 | 958 / 990 | 7.2% / 7.4% |
| **DA_Demand 当日前出清值直接当预测** | 2025: 843 / 2026: 823 | 631 / 635 | **4.9%** |

> 含义：**DA_Demand（日前市场自己的负荷预测）是天然的强基线**（MAE≈630 MW，即实际负荷与日前出清值平均差 ~5%）。任何新模型的价值判定 = 是否显著低于此 MAE/RMSE。注意 DA_Demand 是"日前出清量"，真值仍是 RT_Demand；两者差 DA−RT：MAE 631/635、σ 703/732。

### 3.3 温度—负荷相关性（CA）
CDD65 与 RT 相关 0.48–0.64（夏季制冷主导）；HDD65 相关弱（冬季采暖在 65°F 平衡点下不线性）；原始干球温度相关非单调（U 形）。→ 特征侧用**派生度日 + 非线性模型**（GBM/深度网络）比线性相关更合适；露点可表征湿热夜间负荷。

---

## 4. 数据处理流程设计（未来 24h 负荷预测）

### 4.1 目标与输入设定（默认方案）
- **预测对象**：ISO NE CA 的 RT_Demand（可扩展到 8 分区多输出，见 §5）。
- **输出**：一次预测未来 24 个逐时值（multi-step，直接多步输出，非滚动自回归），步长 Δh=1..24 物理小时。
- **决策时点** t0（"现在"）：输入仅用 t0 及之前可知信息 + t0+1..t0+24 的气象**预报**与日历信息。

### 4.2 统一时间轴（DST 处理，核心步骤）
推荐"本地钟表小时为主轴"：
1. `ts = Date(00:00) + Hr_End`（`02X`→ 解析为本地钟第 2 小时，作普通一小时）排序；
2. **训练样本统一到每个本地钟小时 0–23 一格**：春季缺的那格不存在（当日 23 格）、秋季 `02X` 行丢弃或作为可选重复样本（每年仅 1 行，可接受）；
3. 时变特征（hour_of_day / dow / month / 节日 / DST flag）按**本地钟**编码——保证模型学到稳定日模式；
4. 部署时把预测的本地钟小时经时区规则映射回物理时刻（跳过的钟点剔除、重复钟点展开）。
   备选方案：纯物理小时轴（UTC）建模——时间严格等距但日特征需再映射，增加复杂度；不推荐为首选。

### 4.3 清洗规则
- 数值列天然无缺失；若未来接入新数据出现 NaN：负荷/气象按"同钟点前 7 天中位"插补，>24h 连续缺失置标志位。
- `DA_Demand` 负值 **clip≥0** 后作为特征（或直接不用）。
- 负荷不做离群删除（尖峰是真实天气事件，需模型学）；仅剔除物理不可能值（<0 或 >3×同季峰值），本数据未触发。
- 不重采样/不平滑原始序列（避免抹掉峰谷信息）；需要时用中位窗做鲁棒统计特征。

### 4.4 特征工程（分三组）
**A. 日历/趋势（必选，全可提前精确已知）**
- hour_of_day(0–23) 正弦+余弦或 one-hot；day_of_week；is_weekend；US/ISO-NE 节假日 flag（新英格兰假日对负荷影响大，如感恩节/圣诞节/7-4）及节前节后偏移日；DST flag；day_of_year 周期项；线性趋势项（年增长 ~1.5%）。

**B. 负荷历史（t0 已知，滑动窗/延迟）**
- 最近 24h 原始负荷（如 168–720h 视窗裁剪）；
- 对每个目标小时 h：`RT(t0+h−24)`（昨日同钟点）、`RT(t0+h−168)`（上周同钟点）、近 3h 均值/斜率；
- t0 时刻滚动统计：过去 24/168h 均值、峰谷、std；
- 可选强信号通道：当日 `DA_Demand(h)` 曲线（t0 前已知的日前出清轨迹）——作为"先验曲线"输入，让模型学 **RT−DA 修正残差**；**同时保留无 DA 输入的消融配置**（模型须独立可用）。

**C. 气象（t0 已知实况 + 未来 24h 预报曲线）**
- 目标小时 h 的干球温度、露点（部署时为预报值，训练时用实况 = "完美预报"上界，见风险 R3）；
- 派生：HDD/CDD（平衡点用 62–68°F 内拟合/按季选择）、温度与昨日同钟温差、湿度交互；
- 可选：负荷滞后温度响应（制冷惯性），用过去 6–24h 温度均值/最高温。

### 4.5 序列化与切分（无泄漏原则）
1. 特征/目标由同一物理时间排序构建；滑动窗口步长 1h，`X`(历史+预报曲线) → `Y`(未来24)。
2. **切分（时间顺序，杜绝 shuffle 越界）**：
   - 训练：2024-01-01 → 2026-05-31
   - 验证：2026-06（调超参/早停）
   - 测试：2026-07-01 → 2026-07-31（最后一个月，含仲夏热负荷，最接近部署形态）
   - 数据边界处（每年 1-2 月、DST、节假日前后）专门抽查。
3. 归一化：目标 z-score（μ/σ 只从训练段估计）；连续/周期特征分别标准化；**同一缩放器序列化保存**供推理复用。
4. 存储：合并为 parquet/feather + 训练用 `tf.data` 窗口/批数据集（shuffle 仅限训练段内）。
5. 特征/目标跨年一致性校验：列名 schema 固定、`ts` 单调且唯一。

### 4.6 推荐的工程目录（Ubuntu 侧 `/home/wy/ai-projects/smart-grid`）
```
smart-grid/
├── data/raw/            # ln -s /mnt/c/MMXX/datas
├── data/processed/      # merged.parquet, scalers.json, windows.npz
├── scripts/
│   ├── preflight_gpu.py        # GPU 预检（§6）
│   ├── preprocess.py           # §4.2–4.4 → processed
│   ├── build_windows.py        # §4.5 切分/序列化
│   ├── baselines.py            # §3.2 基线复算
│   ├── train_lgbm.py           # 方案①
│   ├── train_seq2seq.py        # 方案②
│   └── evaluate.py             # §5.4 指标/图形
└── runs/                # 模型权重、tensorboard、metrics.json
```

---

## 5. 训练方案（分阶段，逐级加码）

> 原则：先基线 → 经典 ML 上限 → 深度模型；每个阶段都可独立评估、留档，避免"一上来训大网络却输给 DA 基线"。

### 阶段 0 复算基线（半天）
在 Ubuntu 内复算 §3.2 各基线 + 记录 naive-24/DA_Demand 分钟点、分小时误差（为公平对比留底）。

### 阶段 1 梯度提升直推多步（强烈推荐先做）
- 24 个并行单步模型（或 1 模型 + horizon 特征），LightGBM/XGBoost；
- 输入：§4.4 特征 + 负荷滞后（同钟点 −24/−168h 等）；目标 RMSE/MAE/MAPE；
- 预期：可显著低于 DA 基线（MAE 630→ 500±）或至少持平；CPU 即可，GPU 留给深度模型；
- 附带产出：特征重要性（校验 DA 曲线/温度/历史负荷的相对价值，指导阶段 2 架构）。

### 阶段 2 深度多步模型（RTX 3050 适配）
GPU 仅 4GB VRAM，控制在数百万参数内、batch 128–512、FP32/混合精度(mixed_float16) 视情况。
- **候选 A：CNN+BiGRU Seq2Seq（推荐起步）**：编码器吃 168–336h 输入（负荷+天气+日历），解码器直接并行输出 24h（或 teacher-forcing + scheduled sampling 训练、推理自回归/并行二选一对比）。
- **候选 B：Transformer 多步**（因果自注意力 + 位置编码；d_model 64–128，4–6 层，目标直接 24 输出），小规模即可；若样本仍偏少，加 dropout/weight decay。
- **候选 C：多输出扩展**：一次输出 [CA + 8 分区]×24（输出 216 维）共享编码器——利用分区负荷同源相关性；属可选加分项，不作为一期范围。
- 损失：MAE 或 Huber；辅助逐时损失权重（晚高峰 1.2×）；优化器 AdamW、CosineAnnealing、early-stop on 验证 RMSE。
- 若拟合不足/过拟合：检查特征时序泄漏、dropout、样本量（约 2.4 万 24h 样本，深度模型需谨慎），必要时退为单分区逐小时模式。

### 阶段 3 残差/集成（可选）
`深度模型 + GBM` 平均或 Stacking；若目标是"超过 DA 基线即交付"，则阶段 1–2 达到即可收尾。

### 5.4 评估协议（统一）
- 主指标：**测试段 RMSE、MAE、MAPE、峰值小时(17–20 时) MAE、日最大负荷误差**；
- 必须与 4 个基线同表对比（naive-24、naive-168、周剖面、DA_Demand）；
- 诊断图：按小时/星期/节假日/温度分箱的误差曲线；Q-Q、残差自相关（检验是否仍有可用滞后信息）；滚动原点回测（最后 14 天每天滚动预测 24h）；
- 推理速度与模型体积记录（部署可行性）。

---

## 6. GPU 预检（须在 Ubuntu 内执行 —— 我已准备好脚本）

**本会话无法访问 WSL**，请你在 WSL2 Ubuntu 终端执行以下内容：

```bash
source /home/wy/ai-projects/tensorflow-env/bin/activate
python -c "import sys; print(sys.version)"
nvidia-smi                       # 应显示 RTX 3050 Laptop GPU，驱动/CUDA 版本正常
```

随后运行预检脚本（内容已存为 `C:\MMXX\analysis\preflight_gpu.py`，复制进 Ubuntu 执行）：
```python
import time, os
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf

print("TF version:", tf.__version__)
print("Build:", tf.sysconfig.get_build_info().get("cuda_version"), "| cuDNN:",
      tf.sysconfig.get_build_info().get("cudnn_version"))
print("GPU devices:", tf.config.list_physical_devices("GPU"))
if not tf.config.list_physical_devices("GPU"):
    raise SystemExit("GPU NOT available - fix driver/CUDA before training")

# device placement + matmul benchmark
a = tf.random.normal([2048, 2048]); b = tf.random.normal([2048, 2048])
def bench(dev):
    with tf.device(dev):
        tf.matmul(a, b)  # warmup
        t0 = time.perf_counter()
        for _ in range(10): tf.matmul(a, b)
        return (time.perf_counter() - t0) / 10
print(f"GPU matmul: {bench('/GPU:0')*1e3:.1f} ms  | CPU matmul: {bench('/CPU:0')*1e3:.1f} ms")
print("GPU OK:", tf.test.is_gpu_available(cuda_only=True))
```
通过标准：打印出 GPU 设备、matmul GPU 明显快于 CPU、is_gpu_available=True。若失败，按 [NVIDIA WSL 文档](https://docs.nvidia.com/cuda/wsl-user-guide/index.html) 检查 Windows 侧驱动与 WSL 内 CUDA 工具链。

---

## 7. 风险与建议

| 编号 | 风险 | 应对 |
|---|---|---|
| R1 | 本会话无法读取 Ubuntu 项目内既有代码/模型（"已有模型"无法核验、不重训） | 请你把 `smart-grid` 关键文件（或整个目录清单+`requirements/venv 包清单`）拷贝到 `C:\MMXX` 或授权本会话访问 WSL；在获得明确指令前**不触碰任何已有代码** |
| R2 | ~~2026 疑似模拟数据~~（已澄清：2026 为真实发布数据） | 2026-01 高电价与 2026-05 热浪为真实事件；如需与官方口径核对，可对照 ISO-NE 官网 SMD 页面复核 |
| R3 | 训练用"完美气象预报"（实况），部署用真实预报会掉点 | 训练时给温度加噪声增广，或留"气象不确定性"评估（用 ±5°F 扰动看误差敏感性） |
| R4 | DA_Demand 作输入时若部署拿不到同日 DA 曲线则模型失效 | 保持"有/无 DA"双配置，交付时明确模型输入契约 |
| R5 | 4GB VRAM 限制大模型 | 阶段 2 规模上限约束；必要时 CPU offload 特征工程、GPU 只跑训练 |
| R6 | DST/节假日造成模式跳变 | 日历特征显式编码 + 对 11 月/3 月/节假日前后做专项误差检查 |

**下一步建议顺序**：① 你在 WSL 跑 GPU 预检；② 我产出 `preprocess.py`（§4）+ `baselines.py` 跑出 Ubuntu 侧基线；③ 阶段 1 GBM → 阶段 2 Seq2Seq，全部在你确认后才写入 smart-grid。

---

## 附：本会话已生成的分析文件
- `C:\MMXX\analysis\01_peek_workbook.py` 结构初探
- `C:\MMXX\analysis\02_qa_report.py` + `out/*_qa.json` 全面质检（字段/缺失/连续性/统计）
- `C:\MMXX\analysis\03_junk_and_notes.py` 定位 02X 行 & 输出 Notes 字典
- `C:\MMXX\analysis\04_anomaly_scan.py` + `out/anomalies.json` 异常定位与一致性
- `C:\MMXX\analysis\05_baselines.py` + `out/baselines_seasonality.json` 基线/相关性/季节画像
- `C:\MMXX\analysis\preflight_gpu.py` Ubuntu GPU 预检脚本
- 本报告 `C:\MMXX\analysis\report_analysis_and_training_plan.md`

（分析用 Windows Python 3.11 + pandas 3.0.3 执行；正式处理/训练脚本将面向 Ubuntu Python 3.10 + TF，兼容写法已在方案中约定。）
