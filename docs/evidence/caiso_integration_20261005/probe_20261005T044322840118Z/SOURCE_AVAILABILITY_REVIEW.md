# CAISO独立接入：真实最新输入探测

探测时刻：2026-10-05T04:43:32.181568+00:00。只读复用strict normalization；没有模型推理、训练或修改冻结实验资产。

- 当前最近共同可构造origin：2026-09-29T23:00:00+00:00 / 2026-09-29T16:00:00-07:00。
- 输入shape：past [96, 36] / future [24, 35]；目标真实标签完整小时 24/24。
- 最近14日三源均成功；七坐标multi-query返回七项，9变量及单位检查通过；end_date=2026-10-05成功。

| 来源 | 最新完整区间起点UTC | 最近14日缺/未完结小时 |
| --- | --- | ---: |
| solar | 2026-10-05T03:00:00+00:00 | 5 |
| history_weather | 2026-09-29T22:00:00+00:00 | 125 |
| future_weather | 2026-10-05T03:00:00+00:00 | 0 |

Solar ACTUAL严格为Solar + ACTUAL + RENEW_FCST_ACT_MW、NP15/SP15/ZP26三hub齐全同UTC区间求和，保留夜间负数。

- LA 2026-10-03：24/24官方Actual合格小时。
- LA 2026-10-04：21/24官方Actual合格小时。

当前LA日未结束，未来小时缺失不能叫已经发生的实测缺口。Solar当前日已经返回21小时，所以2017规范翌日发布表述不能用来断言现接口仅发布前日；实际采集证明这些小时在采集时已可得，但没有历史首次发布时间。

当前origin 2026-10-05T04:00:00+00:00 至 2026-10-06T04:00:00+00:00 的GFS previous_day2额外实测：24/24完整，shape [24, 35]，可用上界不晚于origin。这是固定48小时产品及明示6小时发布延迟假设；不是统一已验证issued_at的一个预报批次。

最小可实现范围：保持当前Solar Actual + ERA5 past + GFS day2 future契约，提供最新完整资料的历史回放与指定合格窗口回测；最新共同origin必须随真正完整数据动态发现。当前ERA5缺125小时是当前小时实时预测的明确阻断，不能悄悄换成IFS/GFS past，不能以预测/估计Solar补past。页面应标historical_replay、realtime_ready=false，并显示原始数据来源、采集时刻、目标时间、缺失原因。

官方文档：

- ERA5 daily with 5 days delay、7坐标列表返回、辐射值属于前一小时：https://open-meteo.com/en/docs/historical-weather-api
- previous_day2固定48小时及未来范围：https://open-meteo.com/en/docs/previous-runs-api
- OASIS SLD_REN_FCST可用ACTUAL，OASIS市场输出与Today Outlook telemetry不同：https://www.caiso.com/documents/oasis-frequently-asked-questions.pdf
- 2017范围/翌日发布说明（旧规范，不能覆盖本次当前日实际观测）：https://www.caiso.com/documents/oasis-interfacespecification_v5_1_1clean_fall2017release.pdf

原响应与source URL/SHA/collected_at保存在新backend/cache/caiso_solar/sources，可供根service复用；SHA检查全部通过。详细路径见latest_input_probe.json。当前额外未来24小时探测见current_future24_probe.json。
