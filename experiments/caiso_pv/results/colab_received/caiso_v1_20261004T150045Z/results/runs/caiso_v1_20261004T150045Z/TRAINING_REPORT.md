# CAISO 光伏预测模型训练报告

预测目标：CAISO OASIS Solar Actual Generation（MW）。
已确认标签定义：CAISO OASIS Solar Actual Generation
保留 signed Solar 原值；本实验口径为 OASIS Solar Actual，不代表全州所有光伏或屋顶光伏。
未来天气口径：forecast_fixed_lead_day2
模型选择：Validation MAE；最终模型 gru；Test 未参与调参或选择。
输入：(batch,96,36) + (batch,24,35)；输出：(batch,24,1)。
白天阈值：181.291 MW，仅由 Train 定义。
总训练耗时：770.4 秒；有效 batch=64。

保存配置：Adam，loss=huber，初始learning_rate=0.001，dropout=0.15，L2=1e-05，hidden_units=128，max_epochs=100，EarlyStopping patience=12。
标签来源：caiso_oasis_solar_actual；不是CAISO Forecast。
标签使用官方 OASIS ACTUAL + Solar 小时 MW；完整且唯一的 NP15/SP15/ZP26 记录求和，未混用 Forecast 或 Today's Outlook。
时间区间、原始完整性及 source 定义见数据检查记录与 feature_config.json。
请求标签轴：2024-01-01T08:00:00+00:00 至 2026-10-04T07:00:00+00:00（结束不含，UTC）。
最后完整当地日期：2026-09-27；有效 origin 范围：{'train': {'first_origin_utc': '2024-01-21T08:00:00+00:00', 'last_origin_utc': '2026-06-29T07:00:00+00:00'}, 'val': {'first_origin_utc': '2026-06-30T07:00:00+00:00', 'last_origin_utc': '2026-07-29T07:00:00+00:00'}, 'test': {'first_origin_utc': '2026-07-30T07:00:00+00:00', 'last_origin_utc': '2026-09-27T07:00:00+00:00'}}。
未来天气：Open-Meteo gfs_global；['fixed_48h_offset_plus_assumed_6h_release_delay']。
历史天气：['historical_reanalysis']；historical reconstruction may be revised after forecast origin; it is not an archived live input snapshot。
输入文件与校验值：[{'path': 'D:\\GitHub\\OOOOOO\\experiments\\caiso_pv\\data\\processed\\labels_caiso_oasis_solar_actual_2024-01-01_2026-10-03_20261004T143346982407Z.csv', 'sha256': '0d90f7cf311017ad7cdf2c05e5302d49847561ed5b23499de5350c8d0c5338b4'}, {'path': 'D:\\GitHub\\OOOOOO\\experiments\\caiso_pv\\data\\processed\\weather\\weather_20261004_gfs_day2_v1\\history.parquet', 'sha256': 'd1910ae0924a145c4140cecd064268b7f3f36cfbacea77164102d8b0988d1e97'}, {'path': 'D:\\GitHub\\OOOOOO\\experiments\\caiso_pv\\data\\processed\\weather\\weather_20261004_gfs_day2_v1\\future_day2.parquet', 'sha256': 'f46a31341abf1ea83a35804569dca31558c009337773f586e888a6e1ccf1fcfc'}, {'path': 'D:\\GitHub\\OOOOOO\\experiments\\caiso_pv\\data\\processed\\weather\\weather_20261004_gfs_day2_v1\\manifest.json', 'sha256': '117a8716c3fdc01d560a1233413b9fd6c47bde51aec4174240f294bb519c0ac8'}]；冻结 dataset.npz SHA256=7ed08a1a55d79280b406d30eeb90db0aa5647a68a225602fae854c0a18670f4d。

| 分区 | 当地开始（含） | 当地结束（不含） | 样本数 | 目标预测实例数 |
|---|---|---|---:|---:|
| train | 2024-01-21T00:00:00-08:00 | 2026-06-30T00:00:00-07:00 | 17101 | 410424 |
| val | 2026-06-30T00:00:00-07:00 | 2026-07-30T00:00:00-07:00 | 697 | 16728 |
| test | 2026-07-30T00:00:00-07:00 | 2026-09-28T00:00:00-07:00 | 882 | 21168 |

拒绝窗口（不使用假值补齐）：
- train：{'missing_labels_or_history': 4259, 'missing_available_forecast': 0}。
- val：{'missing_labels_or_history': 0, 'missing_available_forecast': 0}。
- test：{'missing_labels_or_history': 535, 'missing_available_forecast': 0}。

过去特征：solar_actual_mw, temperature_2m__mean, relative_humidity_2m__mean, cloud_cover__mean, shortwave_radiation__mean, direct_radiation__mean, diffuse_radiation__mean, direct_normal_irradiance__mean, wind_speed_10m__mean, surface_pressure__mean, shortwave_radiation__std, cloud_cover__std, shortwave_radiation__kern_west, shortwave_radiation__fresno_kings, shortwave_radiation__mojave, shortwave_radiation__riverside_east, shortwave_radiation__imperial, shortwave_radiation__san_diego_east, shortwave_radiation__central_coast, cloud_cover__kern_west, cloud_cover__fresno_kings, cloud_cover__mojave, cloud_cover__riverside_east, cloud_cover__imperial, cloud_cover__san_diego_east, cloud_cover__central_coast, hour_sin, hour_cos, day_of_year_sin, day_of_year_cos, dow_sin, dow_cos, coszen_mean, solar_elevation_mean, sun_up_any, sun_up_fraction
未来特征：temperature_2m__mean, relative_humidity_2m__mean, cloud_cover__mean, shortwave_radiation__mean, direct_radiation__mean, diffuse_radiation__mean, direct_normal_irradiance__mean, wind_speed_10m__mean, surface_pressure__mean, shortwave_radiation__std, cloud_cover__std, shortwave_radiation__kern_west, shortwave_radiation__fresno_kings, shortwave_radiation__mojave, shortwave_radiation__riverside_east, shortwave_radiation__imperial, shortwave_radiation__san_diego_east, shortwave_radiation__central_coast, cloud_cover__kern_west, cloud_cover__fresno_kings, cloud_cover__mojave, cloud_cover__riverside_east, cloud_cover__imperial, cloud_cover__san_diego_east, cloud_cover__central_coast, hour_sin, hour_cos, day_of_year_sin, day_of_year_cos, dow_sin, dow_cos, coszen_mean, solar_elevation_mean, sun_up_any, sun_up_fraction
未来输入不含实际Solar；站点与太阳位置算法来源见feature_config.json。

| 模型 | 参数量 | 最佳 epoch | 训练秒数 | Test MAE MW | Test RMSE MW | Test R² | 白天 MAPE % |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | -- | -- | -- | 602.3229966618396 | 1258.6478043902957 | 0.9746271016462921 | 11.853895592384252 |
| gru | 198017 | 21 | 133.41687588399998 | 814.8282508106571 | 1373.4513973345286 | 0.969787391322509 | 13.702173202814219 |
| tcn_gru | 448097 | 21 | 291.78472043799997 | 719.870819713931 | 1184.0890435400918 | 0.9775441054787692 | 13.871958031192918 |
| tcn_gru_attention | 514401 | 23 | 342.299158582 | 937.621789813715 | 1245.3084098043466 | 0.9751620655559841 | 21.097596894885946 |

| 提前量（物理小时） | MAE MW | RMSE MW | R² | 白天 MAPE % |
|---:|---:|---:|---:|---:|
| 1 | 807.9133903112792 | 1274.3225795833116 | 0.9739963704677974 | 14.413769249944774 |
| 2 | 835.3473264241144 | 1338.0550356703554 | 0.9714171615837398 | 13.874755357598373 |
| 3 | 796.4923814336145 | 1331.785263146058 | 0.9717022666462245 | 12.928314685062444 |
| 4 | 803.8039581284638 | 1348.3544043657337 | 0.9709719962849253 | 13.156696879413058 |
| 5 | 821.9373180462054 | 1375.1539244540156 | 0.9697493516072915 | 13.647321180163802 |
| 6 | 838.5527273914931 | 1399.7277489923647 | 0.9686084113893358 | 14.025498545257609 |
| 7 | 849.2251966343136 | 1414.595563514987 | 0.9678838703461581 | 14.157856830513909 |
| 8 | 858.8756713846019 | 1427.3496465713604 | 0.9673036910958072 | 14.26199591604402 |
| 9 | 856.4316032998878 | 1431.9395416067052 | 0.9671402417687953 | 14.128150275582833 |
| 10 | 849.0640529710423 | 1427.8029548922448 | 0.96736623142113 | 14.03315744362404 |
| 11 | 837.364118265182 | 1417.3514615502197 | 0.9678745567000536 | 13.991798782370356 |
| 12 | 827.8066149080842 | 1404.9431773485298 | 0.9684567424635085 | 14.001471506071377 |
| 13 | 818.8423222072668 | 1394.1858112291372 | 0.9689381817176745 | 13.575582109887952 |
| 14 | 810.8502896393859 | 1386.4740598331095 | 0.9692540611405311 | 13.34112320340852 |
| 15 | 805.8963561362759 | 1383.7734941265423 | 0.969312345571885 | 13.207635010814958 |
| 16 | 806.5496668320042 | 1388.1352760804887 | 0.9690421147061629 | 13.293151218545308 |
| 17 | 804.8288970634198 | 1388.0410505910995 | 0.9689768261516651 | 13.584295194021278 |
| 18 | 799.8973817897333 | 1379.2172206288571 | 0.9693527841058883 | 13.59029980853719 |
| 19 | 792.226507429697 | 1360.497436525735 | 0.9702235672247795 | 13.628145815364826 |
| 20 | 785.7462019839138 | 1345.7016204420574 | 0.9709315355990512 | 13.502542518561073 |
| 21 | 784.5374227528143 | 1336.1911054569043 | 0.9713657245885983 | 13.594036697395723 |
| 22 | 785.824369564776 | 1330.9332690984738 | 0.9716319144091936 | 13.673096505456478 |
| 23 | 786.6727779612896 | 1329.3803910643169 | 0.9717596095490814 | 13.571607354097672 |
| 24 | 791.1914668969122 | 1335.5571995215516 | 0.9715599190680254 | 13.644193957634473 |

| 当地时段 | 预测实例数 | MAE MW | RMSE MW | R² | 白天 MAPE % |
|---|---:|---:|---:|---:|---:|
| morning_06_10 | 3528 | 1131.0395563044574 | 1663.6197533499505 | 0.9304361668728108 | 16.618786073932455 |
| midday_10_16 | 5292 | 1808.3759955610778 | 2129.205366286049 | -0.34119368928586646 | 10.496868035451378 |
| evening_16_20 | 3528 | 867.0501273517303 | 1315.0798731249527 | 0.9532340556010106 | 15.885520874262005 |
| night_other | 8820 | 71.32633114645525 | 91.37494377466884 | -12.056713147895001 | 101.08471341231196 |

天气分组依据未来预报云量，不能当作实况天气类别；高波动组按云量每物理小时变化≥25个百分点定义。

| 天气预报云量组 | 预测实例数 | MAE MW | RMSE MW | R² | 白天 MAPE % |
|---|---:|---:|---:|---:|---:|
| clear_le_20pct | 11688 | 745.1773040235348 | 1247.017108283969 | 0.9769101600926045 | 11.085691817635778 |
| cloudy_ge_80pct | 355 | 997.066663299506 | 1805.9345287189644 | 0.8950908261289943 | 35.37541250171205 |
| high_change_ge_25pp_per_hour | 656 | 1064.997189967154 | 1693.712794124727 | 0.9567700368202351 | 14.699765228833057 |

过拟合检查（loss差异是提示，跨时段分布变化也会影响比值）：
- gru：最佳epoch Train=0.012082 / Val=0.014731，ratio=1.2192488586449521；未触发2倍loss差距警示，仍需结合曲线判断。
- tcn_gru：最佳epoch Train=0.015939 / Val=0.020973，ratio=1.3158162279765355；未触发2倍loss差距警示，仍需结合曲线判断。
- tcn_gru_attention：最佳epoch Train=0.016858 / Val=0.023574，ratio=1.3983866288030877；未触发2倍loss差距警示，仍需结合曲线判断。

误差按预测实例统计；重叠目标小时保留相同 origin/horizon 索引。
持久性基线为24物理小时滞后；DST变化时不强称同一当地墙钟小时。
详细提前量/早中晚/天气组指标见 metrics.json；Train/Val/Test 时间与样本数见 split_info.json。
本实验只保存独立CAISO研究资产，未接入生产 API。
时间索引没有未来越界，不等于历史Solar在origin已发布。OASIS ACTUAL可能次日发布，
当前数据没有逐条first-publication记录；紧贴origin的96h Solar在线可得性尚未验证。

最终模型：/content/caiso_pv_formal_caiso_v1_20261004T150045Z/results/runs/caiso_v1_20261004T150045Z/models/caISO_pv_final.keras。
Scaler：/content/caiso_pv_formal_caiso_v1_20261004T150045Z/results/runs/caiso_v1_20261004T150045Z/scalers；预测 CSV：/content/caiso_pv_formal_caiso_v1_20261004T150045Z/results/runs/caiso_v1_20261004T150045Z/results/test_predictions.csv。
新 Python 进程重载验证：PASS（reload_check.json）。
【CAISO PV Final Model：PASS（离线研究模型资产与重载检查）】
是否已具备实时接入条件：尚未验证。须核验同口径及时Solar接口或明确发布延迟策略，
并使用与训练一致的未来预报和特征，不能仅依据重载PASS宣称online ready。
