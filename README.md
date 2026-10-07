# 基于 TensorFlow 的智能电网负荷预测系统

Windows 本地运行的毕业设计项目。ISO-NE 页面提供负荷、电价、光伏预测、历史回测和误差分析。

## 首次准备环境

需要 Node.js 24（24.15.0 或更新的 24.x）、Conda Python 3.10 / 3.11 环境和已运行的 MySQL。已有环境可以直接使用。

```powershell
conda create -n smartgrid-tf python=3.10
conda activate smartgrid-tf
python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

填写 `.env` 中的 `MYSQL_*` 和 `AUTH_JWT_SECRET_KEY`，并初始化项目数据库（结构见 `docker/init-db.sql`）。已有 `.env` 请保留，避免覆盖当前配置。生产模型使用已提交的 `backend/models/tf_assets/` 权重与冻结 Scaler，无需先训练。

## 启动

在项目根目录运行：

```powershell
.\start.ps1
```

前端为 `http://localhost:3000`，后端为 `http://localhost:8000`。关闭本项目服务：

```powershell
.\stop.ps1
```

启动脚本使用已有 `smartgrid-tf` 环境，检查模型资产和 MySQL 结构，并核验本项目进程。配置保留在根目录 `.env`，配置示例为 `.env.example`。

## 文件位置

| 目录 | 内容 |
| --- | --- |
| `frontend/` | React 页面、组件、样式、公开素材、前端测试与依赖 |
| `backend/realtime_api/` | FastAPI 接口、认证、数据获取、特征构造和推理服务 |
| `backend/models/` | 生产模型定义、权重、Scaler 和冻结验收资产 |
| `backend/scripts/`、`backend/tests/` | 后端维护/验收脚本及测试 |
| `scripts/` | Windows 启停进程核验及启动验收工具 |
| `Word/` | 论文、开题报告、配套事实资料、图片、制作工具及源版本 |
| `docs/` | 项目说明、验收记录、审核材料和保留的验收证据 |
| `MMXX/` | ISO-NE 训练工程、原始数据、实验结果和论文候选图 |
| `experiments/caiso_pv/` | 保留的独立 CAISO 训练、数据、三模型比较及最终 GRU 资产；不接入应用页面和接口 |
| `solar_data/`、`processed/` | 已有光伏研究数据和训练预处理数据 |
| `docker/`、`deploy/` | 数据库/监控配置与已有部署打包方案 |
| `backups/` | 数据库备份及独有历史数据记录 |
| `logs/`、`backend/cache/` | 当前运行日志、预测缓存及输入归档 |

训练目录和数据路径保留原位置，避免破坏训练、Colab 上传和论文复现的路径约定。根目录的启停脚本、环境配置和容器编排也保留兼容入口。

## 详细资料

- [项目说明](docs/README.md)
- [论文与配套材料](Word/README.md)
- [训练环境约定](docs/模型训练与验证环境约定.md)：本地开发/小规模验证，正式训练优先 Colab T4。
- [本次整理记录](docs/maintenance/项目清理与目录整理-2026-10-06.md)
- [CAISO 页面与接口移除记录](docs/maintenance/CAISO功能移除-2026-10-06.md)

模型、训练数据、论文和现有数据库均保留。测试缓存、旧打包目录、一次性诊断产物和不可达的旧前端组件已清理；独有内容的恢复备份位于项目外，详情见整理记录。

## 验证与发布范围

```powershell
# 只读检查已有模型，不训练或保存权重
python backend/scripts/validate_tf_assets.py --runtime
cd frontend
npm run type-check
npm test
npm run build
```

GitHub 保存源码、当前生产模型、必要的小型研究配置、论文和项目说明。`.env`、数据库备份、运行日志、预测输入归档、本地依赖环境及大型中间序列仍保留本地，不上传。正式训练优先使用 Colab T4，详细配置见上述训练环境约定。

NREL 研究脚本从 `NREL_API_KEY` 环境变量读取密钥。不要把实际密钥写入源码或提交到 Git。
