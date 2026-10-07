# 本科毕业论文终审审计报告

## 审计对象与范围

- 论文文件：`Word/本科毕业论文_基于TensorFlow的智能电网负荷预测系统设计与实现_初始化.docx`
- 对照材料：[THESIS_PROJECT_FACTS.md](THESIS_PROJECT_FACTS.md)、[THESIS_EXPERIMENT_RESULTS.md](THESIS_EXPERIMENT_RESULTS.md)、[THESIS_FIGURES_TABLES.md](THESIS_FIGURES_TABLES.md)、当前训练脚本、后端源码、数据库初始化脚本、模型资产元数据及论文渲染结果。
- 本轮未修改论文正文、章节结构或图表内容，仅生成本审计报告。

## 1. 参考文献真实性检查结果

逐条核对结果如下。链接指向 DOI、出版社/会议页面或论文原始预印本页面；未补造 DOI、页码或出版信息。

| 编号 | 文献 | 核查结果 | 可检索来源 |
|---|---|---|---|
| [1] | Hong T, Fan S. *Probabilistic electric load forecasting: A tutorial review*. International Journal of Forecasting, 2016, 32(3): 914–938. | 已核验；作者、题名、期刊、年份、卷期、页码和 DOI 一致。 | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0169207015001508)，[DOI](https://doi.org/10.1016/j.ijforecast.2015.11.011) |
| [2] | Weron R. *Electricity price forecasting: A review of the state-of-the-art with a look into the future*. International Journal of Forecasting, 2014, 30(4): 1030–1081. | 已核验；作者、题名、期刊、年份、卷期、页码和 DOI 一致。 | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0169207014001083)，[DOI](https://doi.org/10.1016/j.ijforecast.2014.08.008) |
| [3] | Cho K, van Merriënboer B, Gülçehre Ç, et al. *Learning phrase representations using RNN encoder-decoder for statistical machine translation*. arXiv:1406.1078, 2014. | 已核验；题名、作者、预印本编号和年份一致。该条属于 arXiv 电子文献，没有期刊卷期和页码。 | [arXiv](https://arxiv.org/abs/1406.1078) |
| [4] | Bai S, Kolter J Z, Koltun V. *An empirical evaluation of generic convolutional and recurrent networks for sequence modeling*. arXiv:1803.01271, 2018. | 已核验；题名、作者、预印本编号和年份一致。该条属于 arXiv 电子文献，没有期刊卷期和页码。 | [arXiv](https://arxiv.org/abs/1803.01271) |
| [5] | Vaswani A, Shazeer N, Parmar N, et al. *Attention is all you need*. In: Advances in Neural Information Processing Systems 30, 2017. | 已核验；作者、题名、会议论文集和年份一致。现条目未列论文集页码；DBLP 所列页码为 5998–6008，是否补入应按学校参考文献格式执行，不得仅凭常识补写。 | [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2017/hash/3f5ee243547dee91fbd053c1c4a845aa-Abstract.html)，[DBLP](https://dblp.uni-trier.de/rec/conf/nips/VaswaniSPUJGKP17.html) |
| [6] | Antonanzas J, Osorio N, Escobar R, et al. *Review of photovoltaic power forecasting*. Solar Energy, 2016, 136: 78–111. | 已核验；作者、题名、期刊、年份、卷号、页码和 DOI 一致。 | [ScienceDirect/DOI](https://doi.org/10.1016/j.solener.2016.06.069) |
| [7] | Salinas D, Flunkert V, Gasthaus J, Januschowski T. *DeepAR: Probabilistic forecasting with autoregressive recurrent networks*. International Journal of Forecasting, 2020, 36(3): 1181–1191. | 已核验；作者、题名、期刊、年份、卷期、页码和 DOI 一致。 | [ScienceDirect/DOI](https://doi.org/10.1016/j.ijforecast.2019.07.001) |

### 1.1 无法验证的参考文献

没有发现完全无法检索的条目。需要处理的是 [5] 的出版项不完整问题，而不是真实性问题；[3]、[4] 为 arXiv 预印本，缺少卷期页码属于文献类型特征。

## 2. 正文引用与参考文献对应检查

- 正文实际出现了 `[1]`–`[7]`，每一条参考文献均至少被引用一次，没有发现参考文献列表中的孤立条目。
- 未发现完全重复的参考文献，也未发现同一文献以两种不同书写方式重复列出。
- 引用编号首次出现顺序为：`[1] → [2] → [6] → [3] → [4] → [5] → [7]`，与参考文献表按 `[1]`–`[7]` 的排列顺序不一致。若学校要求按正文首次出现顺序编号，这是必须修改的问题。建议重排为：Hong–Fan、Weron、Antonanzas、Cho、Bai、Vaswani、Salinas，并同步修改正文引文编号。

## 3. 实验指标冲突

对照 [THESIS_EXPERIMENT_RESULTS.md](THESIS_EXPERIMENT_RESULTS.md)、论文第6章表格和文字，未发现同一模型同一测试集指标前后不一致。论文已出现的主要指标均能在实验结果文件找到对应值：

- 负荷模型 `tf_load_split_v1`：MAE 305.40 MW、RMSE 476.14 MW、MAPE 1.922%、R² 0.97739、Bias +91.49 MW、峰值 MAE 567.18 MW。
- 负荷基线 DA Demand：MAE 759.34 MW、RMSE 956.63 MW、MAPE 5.227%。
- 电价模型 `tf_price_split_v1`：P50 MAE 13.266 USD/MWh、P50 RMSE 26.494 USD/MWh、Bias −3.713 USD/MWh、条件 MAPE 22.072%、P10–P90 覆盖率 66.93%。
- PV v2（seed 42）：全时段 MAE 236.1834 MW、RMSE 474.2500 MW；白天 MAE 412.4804 MW、白天 RMSE 627.1846 MW、白天 WAPE 17.0532%、条件 MAPE 20.3424%、能量误差 14.8323%、峰值误差 610.2447 MW。

第6章中“PV 训练/验证/测试行数”和“验证/测试 origin 数”分别用于数据行和滑动窗口统计，语义不同，不构成指标冲突。

## 4. 模型参数冲突

- 论文内部未发现输入窗口、预测步长、输入维度、GRU 层数、隐藏单元、Dropout、损失函数、优化器和学习率的互相矛盾。当前口径为：负荷/电价 168 h 输入、24 h 输出；PV v2 96 h 输入、24 h 输出；TensorFlow 2.16.1、Keras 3.3.3；负荷/电价使用独立模型，PV v2 使用 TCN-GRU-多头注意力结构。
- **冲突位置A：** `MMXX/smart-grid/scripts/train_pv_v2.py` 和 `backend/realtime_api/tf_pv_v2_service.py` 的可执行后处理使用 `sun_up > 0.5` 判断白天并保留预测。
- **冲突位置B：** `backend/models/tf_assets/pv_v2/metadata.json` 及 [THESIS_PROJECT_FACTS.md](THESIS_PROJECT_FACTS.md) 的文字描述为仅在 `sun_up == 0` 时置零；论文部分段落使用了 `>0.5`。
- **真实依据文件：** 上述训练脚本、推理服务、模型元数据和事实文件。
- **建议采用值：** 以当前可执行训练/推理代码的 `sun_up > 0.5` 为实现口径，并同步修正元数据与事实文件，避免论文、资产说明和生产推理行为不一致。
- 论文第4章对旧版 `backend/realtime_api/app.py` 中“四个模型加权集成”和“辐射物理估算”的说明已标为过时 TODO；当前生产链由 `container.py`、`tf_split_service.py` 和 `tf_pv_v2_service.py` 体现的三个独立 TensorFlow 模型组成。该旧说明应在定稿前清除或明确标注为历史代码。
- 第5章使用服务属性名 `tf_pv_service`，而实现类为 `TFPVV2Service`。这不是功能冲突，但建议首次出现时同时写明“服务属性 `tf_pv_service`（类 `TFPVV2Service`）”。

## 5. 数据时间范围冲突

未发现论文内部冲突。当前可核对的时间口径为：

- 负荷与电价：数据范围 2017-01-01 至 2026-08-01；训练集截至 2026-04-30 23:00，验证集为 2026-05-01 至 2026-06-30，测试集为 2026-07-01 至 2026-08-01；168 h→24 h。
- PV v2：数据范围 2025-02-01 至 2026-09-10；训练集截至 2026-06-30，验证集为 2026-07-01 至 2026-08-15，测试集为 2026-08-16 至 2026-09-10；96 h→24 h。
- PV 的 `12360/1104/624` 是训练、验证、测试数据行数，`1080/600` 是验证、测试滑动窗口 origin 数；论文当前区分了两种统计量。

## 6. 图表编号与引用顺序

- 当前图号按章节连续：图3-1；图4-1～图4-2；图5-1～图5-2；图6-1～图6-6。未发现图6-3后跳至图6-5等断号。
- 当前表号按章节连续：表3-1～表3-2；表4-1；表5-1～表5-3；表6-1～表6-8。未发现断号。
- **正文未先引用再出现：** 图3-1、图4-1、图4-2；表3-1、表3-2、表4-1。建议在各小节正文中增加一句事实性引导，再保留图/表。
- 其余图表均能在图表出现前找到正文引用。图题和表题总体统一，但“表3-1”与“表 6-1”等存在空格风格差异，应按学校模板统一。
- 图5-2与图6-6复用了同一张负荷预测页面截图。若学校不允许同一截图重复出现，应保留一次并在另一处改为文字引用；若保留两处，应在图题或正文说明其用途不同。
- 未发现占位图片、模拟实验曲线或临时截图。已插入图像可在当前项目媒体和系统截图中找到依据。

## 7. 公式检查

- 公式编号连续为（4-1）～（4-7），未发现断号；正文相邻段落对变量和参数作了说明，并能与 `train_tf_split_models.py`、`train_pv_v2.py` 的实现对应。
- 分位数损失使用 pinball loss，PV 多目标损失包含点预测、能量和峰值项，形式与训练代码一致；未发现 MAE、RMSE、MAPE、R² 公式的实质性错误。
- 公式排版、字体、编号位置和交叉引用仍受论文中的 TODO 约束（第2章相关段落）。这是定稿前必须清除的排版占位项，不属于数学实现错误。

## 8. 章节与目录检查

- 第1章至第7章连续，一级、二级和三级标题与目录文本一致；未发现重复的主要章节或目录漏项。
- 目录页码与当前渲染文档一致：第1章1页、第2章5页、第3章9页、第4章15页、第5章22页、第6章31页、第7章41页，参考文献44页，附录A～E为45～49页。
- 附录A“核心特征列表”、附录B“主要API表”、附录C“模型参数和生产资产指纹”、附录D“补充实验图”、附录E“系统运行与环境变量说明”当前为只有标题的空白页，属于占位内容。需补入真实材料、删除附录标题，或明确说明附录暂不提供。
- “成果声明”和“致谢”页保留模板签名/填写区域，属于学校模板字段，不判定为事实错误，但提交前应按学校要求填写。

## 9. TODO / 占位内容

论文正文仍存在以下显式 TODO：

1. 第1章研究现状：核对参考文献数据库、卷期页码和学校格式（本报告已完成来源核查，但论文内 TODO 仍需更新）。
2. 第1章技术路线：补绘或确认与当前“三个独立模型/PV v2”一致的技术路线图。
3. 第2章：确认学校公式字体、编号和交叉引用样式。
4. 第2章、第4章：精确 GPU、CUDA/cuDNN、Python 环境未归档；当前第6章已如实说明未记录，不能自行补写。
5. 第3章：最终时间切分审计 JSON 尚未固化。
6. 第4章：旧版 `app.py` 模型链说明和可复现实验提交版本仍待清理/归档。
7. 第6章：逐预测步长误差数组及24小时误差曲线尚未固化。
8. 第6章：代表性历史回测日期尚未冻结。
9. 附录A～E为空白标题页。

## 10. 必须修改的问题

1. 按正文首次出现顺序重排参考文献编号并同步修改正文引用。
2. 清除或逐项处理正文中的显式 TODO，尤其是参考文献格式、技术路线图、公式格式、环境归档、时间切分审计、误差数组和回测日期。
3. 对附录A～E作出明确处理：补入真实内容、删除标题，或按学校要求标注暂不提供。
4. 在图3-1、图4-1、图4-2以及表3-1、表3-2、表4-1出现前补充正文引用。
5. 统一 PV `sun_up` 后处理口径；建议采用可执行代码中的 `sun_up > 0.5`，并同步资产元数据和事实文件。
6. 明确图5-2与图6-6的重复截图用途，或删除一处。

## 11. 建议修改但不影响事实的问题

- 若学校格式要求完整会议论文出版项，可将 [5] 的页码补为 5998–6008；[3]、[4] 不应虚构卷期页码。
- 统一图题、表题中的空格、连字符和 P10–P90 书写风格。
- 在后端设计首次出现处同时给出 `tf_pv_service` 属性名和 `TFPVV2Service` 类名。
- 将训练日志、指标 JSON/CSV、模型数组和环境信息的文件路径作为附录或归档清单，便于复核；不得新增未实际记录的环境参数。

## 12. 审计依据

- [THESIS_PROJECT_FACTS.md](THESIS_PROJECT_FACTS.md)
- [THESIS_EXPERIMENT_RESULTS.md](THESIS_EXPERIMENT_RESULTS.md)
- [THESIS_FIGURES_TABLES.md](THESIS_FIGURES_TABLES.md)
- `MMXX/smart-grid/scripts/train_tf_split_models.py`
- `MMXX/smart-grid/scripts/train_pv_v2.py`
- `backend/realtime_api/tf_pv_v2_service.py`
- `backend/realtime_api/services/container.py`
- `backend/realtime_api/routers/`
- `docker/init-db.sql`
- `docker/mysql/scripts/create-auth-tables.sql`
- `backend/models/tf_assets/pv_v2/metadata.json`
- 论文 DOCX 解包后的段落、表格、媒体资源及渲染页图像。

## 13. 风险分级

**C：存在事实或引用问题，暂时不能定稿。**

分级依据不是实验指标失真，而是：参考文献首次引用顺序不符合按首次出现编号的常见学校要求；正文仍有显式 TODO；附录A～E为空白占位页；部分图表缺少“先引用后出现”的引导；PV `sun_up` 阈值在可执行代码、元数据和事实文件之间存在口径歧义；另有重复截图和旧版模型链说明需要清理。上述问题处理并复核后，才建议进入最终排版。
