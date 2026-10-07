"""Train the three CAISO candidates; choose by Validation, evaluate Test once."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tensorflow as tf

try:
    from .models import MODEL_NAMES, ModelConfig, build_model, configure_tensorflow
    from .evaluate import daylight_threshold, evaluate_run, inverse_target, metrics, read_json, write_json
except ImportError:
    from models import MODEL_NAMES, ModelConfig, build_model, configure_tensorflow
    from evaluate import daylight_threshold, evaluate_run, inverse_target, metrics, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
PARTITIONS = ("train", "val", "test")


def inside_experiment(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"New experiment assets must remain inside {ROOT}")
    return resolved


def validate_dataset(dataset: dict, features: dict, scalers: dict, split: dict) -> None:
    if features.get("past_hours") != 96 or features.get("horizon_hours") != 24:
        raise ValueError("Dataset must use 96 past and 24 future physical hours")
    if features.get("timezone") != "America/Los_Angeles":
        raise ValueError("Feature timezone must be America/Los_Angeles")
    if features.get("future_weather_kind") not in ("forecast_single_run", "forecast_fixed_lead_day2"):
        raise ValueError("Training requires an explicitly declared historical forecast kind, not future observed weather")
    if "solar_actual_mw" not in features["past_features"] or "solar_actual_mw" in features["future_features"]:
        raise ValueError("Observed Solar belongs in past only; future actual Solar is forbidden")
    boundaries = split.get("partitions", {})
    if set(boundaries) != set(PARTITIONS):
        raise ValueError("Split metadata must define Train/Validation/Test half-open boundaries")
    train_start = _utc_seconds(boundaries["train"]["start_utc"])
    train_end = _utc_seconds(boundaries["train"]["end_exclusive_utc"])
    for name, scaler in scalers.items():
        if scaler.get("kind") != "standard" or scaler.get("fitted_partition") != "train":
            raise ValueError(f"{name} must be a Train-only standard scaler")
        mean, scale = np.asarray(scaler.get("mean"), float), np.asarray(scaler.get("scale"), float)
        if mean.ndim != 1 or mean.shape != scale.shape or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
            raise ValueError(f"Invalid {name} scaler parameters")
        expected = ["solar_actual_mw"] if name == "target" else features[f"{name}_features"]
        if scaler.get("feature_names") != expected or len(mean) != len(expected):
            raise ValueError(f"{name} scaler feature order disagrees with Feature Config")
        if _utc_seconds(scaler["fitted_start"]) != train_start or _utc_seconds(scaler["fitted_end"]) != train_end:
            raise ValueError(f"{name} scaler must declare exactly the Train fitting interval")
    last_end = None
    for partition in PARTITIONS:
        past, future, target = (np.asarray(dataset[f"{prefix}_{partition}"])
                                for prefix in ("X_past", "X_future", "y"))
        times, origins, baseline = (np.asarray(dataset[f"{prefix}_{partition}"])
                                    for prefix in ("target_ts", "origin_ts", "baseline"))
        count = len(past)
        if not count or past.shape != (count, 96, len(features["past_features"])) or future.shape != (count, 24, len(features["future_features"])) or target.shape != (count, 24, 1):
            raise ValueError(f"Invalid or empty {partition} window shapes")
        if baseline.shape != target.shape or times.shape != (count, 24) or origins.shape != (count,):
            raise ValueError(f"Baseline and timestamps must share the {partition} target index")
        if any(not np.isfinite(value).all() for value in (past, future, target, baseline)):
            raise ValueError(f"Nonfinite {partition} features/labels/baseline")
        solar_column = features["past_features"].index("solar_actual_mw")
        expected_baseline = (past[:, -24:, solar_column].astype(np.float64)
                             * scalers["past"]["scale"][solar_column] + scalers["past"]["mean"][solar_column])
        if not np.allclose(baseline[..., 0], expected_baseline, rtol=1e-5, atol=0.02):
            raise ValueError(f"{partition} baseline must be the same sample's previous 24 physical-hour Solar MW")
        if not np.all(np.diff(times, axis=1) == 3600) or not np.array_equal(times[:, 0], origins):
            raise ValueError(f"{partition} targets must start at origin and advance by physical hours, including DST")
        if np.any(np.diff(origins) <= 0):
            raise ValueError(f"{partition} origins must be strictly chronological")
        start, end = int(times.min()), int(times.max())
        boundary = boundaries[partition]
        if start < _utc_seconds(boundary["start_utc"]) or end + 3600 > _utc_seconds(boundary["end_exclusive_utc"]):
            raise ValueError(f"All 24 {partition} targets must stay within the half-open partition")
        if boundary.get("samples") != count:
            raise ValueError(f"{partition} sample count disagrees with split provenance")
        available = dataset.get(f"forecast_available_upper_bound_ts_{partition}")
        if available is None or available.shape != times.shape or not np.all(available <= origins[:, None]):
            raise ValueError(f"{partition} recorded forecast bounds must be available at each forecast origin; source assumptions remain disclosed")
        if last_end is not None and start <= last_end:
            raise ValueError("Entire target windows must stay in separate chronological partitions")
        last_end = end
        print(f"{partition.upper()}: {datetime.fromtimestamp(start, timezone.utc).isoformat()} -> "
              f"{datetime.fromtimestamp(end, timezone.utc).isoformat()}, samples={count:,}")


def _utc_seconds(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Split and scaler timestamps must be timezone-aware")
    return int(parsed.timestamp())


class EpochLog(tf.keras.callbacks.Callback):
    def __init__(self, destination: Path):
        super().__init__()
        self.destination = destination
        self.records: list[dict] = []
        self.started = time.perf_counter()
        self.epoch_started = self.started

    def on_epoch_begin(self, epoch, logs=None):
        self.epoch_started = time.perf_counter()

    def on_epoch_end(self, epoch, logs=None):
        self.records.append({"epoch": int(epoch + 1), **{name: float(value) for name, value in (logs or {}).items()},
            "learning_rate": float(tf.keras.backend.get_value(self.model.optimizer.learning_rate)),
            "epoch_seconds": time.perf_counter() - self.epoch_started,
            "elapsed_seconds": time.perf_counter() - self.started})
        # This log is owned by the newly created run; checkpoint/log updates are intentional.
        self.destination.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event": "epoch_complete", "model": self.model.name, **self.records[-1]}), flush=True)


def _fit_candidates(dataset: dict, run_dir: Path, config: ModelConfig, *, batch_size: int,
                    epochs: int, patience: int, seed: int, threshold: float, target_scaler: dict) -> tuple[dict, Path]:
    attempt = run_dir / "attempts" / f"batch_{batch_size}"
    attempt.mkdir(parents=True, exist_ok=False)
    summaries = {}
    histories = {}
    for name in MODEL_NAMES:
        tf.keras.backend.clear_session()
        tf.keras.utils.set_random_seed(seed)
        destination = attempt / name
        destination.mkdir()
        model = build_model(name, dataset["X_past_train"].shape[-1], dataset["X_future_train"].shape[-1], config)
        epoch_log = EpochLog(destination / "epoch_log.json")
        callbacks = [
            tf.keras.callbacks.ModelCheckpoint(str(destination / "best.keras"), monitor="val_loss", mode="min", save_best_only=True),
            tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=patience, mode="min", restore_best_weights=True),
            tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=5, min_lr=1e-6),
            tf.keras.callbacks.TerminateOnNaN(), epoch_log,
        ]
        started = time.perf_counter()
        history = model.fit(
            {"past": dataset["X_past_train"], "future": dataset["X_future_train"]}, dataset["y_train"],
            validation_data=({"past": dataset["X_past_val"], "future": dataset["X_future_val"]}, dataset["y_val"]),
            batch_size=batch_size, epochs=epochs, callbacks=callbacks, shuffle=False, verbose=2,
        )
        losses = np.asarray(history.history["val_loss"], float)
        if not losses.size or not np.isfinite(losses).all() or not (destination / "best.keras").is_file():
            raise ValueError(f"{name} failed finite best-Validation checkpoint verification")
        # All candidates select their checkpoint by the same Validation criterion.
        best = tf.keras.models.load_model(destination / "best.keras", compile=False)
        standardized = best.predict({"past": dataset["X_past_val"], "future": dataset["X_future_val"]}, batch_size=batch_size, verbose=0)
        validation = metrics(inverse_target(dataset["y_val"], target_scaler), inverse_target(standardized, target_scaler), threshold)
        histories[name] = {"epochs": epoch_log.records, "keras_history": {key: list(map(float, values)) for key, values in history.history.items()}}
        summaries[name] = {"parameters": model.count_params(), "best_epoch": int(np.argmin(losses) + 1),
                           "best_val_loss": float(losses.min()), "validation": validation,
                           "training_seconds": time.perf_counter() - started, "batch_size": batch_size}
        write_json(destination / "training_history.json", histories[name])
        del model, best
    write_json(attempt / "training_history.json", histories)
    write_json(attempt / "validation_metrics.json", summaries)
    return summaries, attempt


def train(args: argparse.Namespace) -> Path:
    dataset_dir, run_dir = inside_experiment(args.dataset_dir), inside_experiment(args.run_dir)
    approval = read_json(dataset_dir / "data_approval.json")
    if approval.get("status") != "approved" or not approval.get("approved_at") or not approval.get("official_label"):
        raise ValueError("Official actual-label/weather samples must be confirmed before formal training")
    features, split = read_json(dataset_dir / "feature_config.json"), read_json(dataset_dir / "split_info.json")
    scalers = {name: read_json(dataset_dir / f"{name}_scaler.json") for name in ("past", "future", "target")}
    with np.load(dataset_dir / "dataset.npz", allow_pickle=False) as archive:
        dataset = {key: archive[key] for key in archive.files}
    validate_dataset(dataset, features, scalers, split)
    if run_dir.exists():
        raise FileExistsError(f"Refusing to overwrite an existing run: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    for folder in ("models", "scalers", "results", "figures", "logs"):
        (run_dir / folder).mkdir()
    for filename in ("feature_config.json", "split_info.json", "data_approval.json"):
        shutil.copy2(dataset_dir / filename, run_dir / filename)
    for name in scalers:
        shutil.copy2(dataset_dir / f"{name}_scaler.json", run_dir / "scalers" / f"{name}_scaler.json")
    config = ModelConfig(dropout=args.dropout, learning_rate=args.learning_rate, loss=args.loss)
    hardware = configure_tensorflow(args.seed)
    write_json(run_dir / "hardware.json", hardware)
    threshold = daylight_threshold(inverse_target(dataset["y_train"], scalers["target"]))
    model_config = {**config.to_dict(), "models": list(MODEL_NAMES), "seed": args.seed,
                    "max_epochs": args.epochs, "patience": args.patience,
                    "daylight_threshold_mw": threshold,
                    "daylight_threshold_definition": "max(1 MW, 1% of Train positive-Solar 99th percentile)",
                    "target_name": "CAISO OASIS Solar Actual Generation",
                    "label_definition": "CAISO OASIS Solar Actual Generation",
                    "approved_label_definition": approval["official_label"],
                    "future_weather_kind": features["future_weather_kind"],
                    "input_availability": {
                        "mathematical_time_guard": "Past intervals precede origin; all 24 targets stay in one partition",
                        "future_weather": "Recorded forecast availability upper bounds <= origin; conservative release assumptions are disclosed in Feature Config, not independently proved publication times",
                        "past_solar_publication": "UNVERIFIED: source may publish ACTUAL next day; historical first-publication times unavailable",
                        "past_weather_publication": features.get("historical_weather_note", "Historical weather input vintage not verified"),
                        "online_readiness": "NOT_VERIFIED",
                    },
                    "dataset_sha256": _file_sha256(dataset_dir / "dataset.npz"),
                    "selection_protocol": "Validation MAE only; Test once after all training"}
    # The exact plan is available during a long-running Colab job, before fit starts.
    write_json(run_dir / "training_plan.json", {**model_config, "initial_batch_size": args.batch_size})
    # Baseline exists before deep learning; avoid touching Test until final evaluation.
    write_json(run_dir / "baseline_validation_metrics.json", {
        "lag_hours": 24, "time_axis": "Physical UTC hours (not a fixed local-clock hour on DST)",
        "train": metrics(inverse_target(dataset["y_train"], scalers["target"]), dataset["baseline_train"], threshold),
        "validation": metrics(inverse_target(dataset["y_val"], scalers["target"]), dataset["baseline_val"], threshold)})
    started = time.perf_counter()
    batch = args.batch_size
    try:
        while True:
            try:
                summaries, attempt = _fit_candidates(dataset, run_dir, config, batch_size=batch,
                    epochs=args.epochs, patience=args.patience, seed=args.seed, threshold=threshold, target_scaler=scalers["target"])
                break
            except tf.errors.ResourceExhaustedError:
                if batch <= 8:
                    raise
                # Preserve the unsuccessful attempt and restart all three at one shared batch size.
                write_json(run_dir / "logs" / f"oom_batch_{batch}.json", {"batch_size": batch, "next_batch_size": max(8, batch // 2)})
                batch = max(8, batch // 2)
                tf.keras.backend.clear_session()
        selected = min(MODEL_NAMES, key=lambda name: summaries[name]["validation"]["mae_mw"])
        model_config.update(selected_model=selected, effective_batch_size=batch, candidates=summaries,
                            training_seconds=time.perf_counter() - started)
        write_json(run_dir / "model_config.json", model_config)
        shutil.copy2(attempt / "training_history.json", run_dir / "training_history.json")
        shutil.copy2(attempt / "validation_metrics.json", run_dir / "validation_metrics.json")
        for name in MODEL_NAMES:
            (run_dir / "models" / name).mkdir()
            shutil.copy2(attempt / name / "best.keras", run_dir / "models" / name / "best.keras")
        shutil.copy2(run_dir / "models" / selected / "best.keras", run_dir / "models" / "caISO_pv_final.keras")
        shutil.copy2(run_dir / "models" / "caISO_pv_final.keras", run_dir / "models" / "final.keras")
        _loss_plot(run_dir)
        test_metrics = evaluate_run(run_dir, dataset_dir, batch_size=batch)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "reload_check.py"), "--run-dir", str(run_dir)], check=True)
        _report(run_dir, model_config, split, features, test_metrics)
        write_json(run_dir / "completed.json", {"status": "PASS", "completed_at": datetime.now(timezone.utc).isoformat()})
    except Exception as error:
        write_json(run_dir / "logs" / "failed.json", {"status": "FAIL", "type": type(error).__name__, "reason": str(error)})
        raise
    return run_dir


def _loss_plot(run_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    histories = read_json(run_dir / "training_history.json")
    figure, axes = plt.subplots(1, 3, figsize=(15, 4))
    for axis, (name, history) in zip(axes, histories.items()):
        axis.plot(history["keras_history"]["loss"], label="Train")
        axis.plot(history["keras_history"]["val_loss"], label="Validation")
        axis.set(title=name, xlabel="Epoch", ylabel="Standardized-target loss")
        axis.legend()
    figure.tight_layout()
    figure.savefig(run_dir / "figures" / "loss_curves.png", dpi=160)
    plt.close(figure)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report(run_dir: Path, config: dict, split: dict, features: dict, test_metrics: dict) -> None:
    selected = config["selected_model"]
    rows = ["# CAISO 光伏预测模型训练报告", "", f"预测目标：{config['target_name']}（MW）。",
            f"已确认标签定义：{config['approved_label_definition']}",
            "保留 signed Solar 原值；本实验口径为 OASIS Solar Actual，不代表全州所有光伏或屋顶光伏。",
            f"未来天气口径：{features['future_weather_kind']}",
            f"模型选择：Validation MAE；最终模型 {selected}；Test 未参与调参或选择。",
            f"输入：(batch,96,{len(features['past_features'])}) + (batch,24,{len(features['future_features'])})；输出：(batch,24,1)。",
            f"白天阈值：{config['daylight_threshold_mw']:.3f} MW，仅由 Train 定义。",
            f"总训练耗时：{config['training_seconds']:.1f} 秒；有效 batch={config['effective_batch_size']}。", "",
            f"保存配置：Adam，loss={config['loss']}，初始learning_rate={config['learning_rate']}，dropout={config['dropout']}，L2={config['l2']}，hidden_units={config['hidden_units']}，max_epochs={config['max_epochs']}，EarlyStopping patience={config['patience']}。",
            f"标签来源：{features.get('solar_label_source_id', '见data_approval.json官方来源记录')}；不是CAISO Forecast。",
            "标签使用官方 OASIS ACTUAL + Solar 小时 MW；完整且唯一的 NP15/SP15/ZP26 记录求和，未混用 Forecast 或 Today's Outlook。",
            "时间区间、原始完整性及 source 定义见数据检查记录与 feature_config.json。",
            f"请求标签轴：{features.get('requested_label_axis_start_utc', '--')} 至 {features.get('requested_label_axis_end_exclusive_utc', '--')}（结束不含，UTC）。",
            f"最后完整当地日期：{split.get('latest_complete_local_date', '--')}；有效 origin 范围：{features.get('effective_admitted_origins', {})}。",
            f"未来天气：Open-Meteo {features.get('future_weather_model', '--')}；{features.get('future_availability_basis', [])}。",
            f"历史天气：{features.get('historical_weather_kind', [])}；{features.get('historical_weather_note', '--')}。",
            f"输入文件与校验值：{features.get('input_sources', [])}；冻结 dataset.npz SHA256={config['dataset_sha256']}。",
            "", "| 分区 | 当地开始（含） | 当地结束（不含） | 样本数 | 目标预测实例数 |",
            "|---|---|---|---:|---:|"]
    for name, boundary in split["partitions"].items():
        rows.append(f"| {name} | {boundary['start_local']} | {boundary['end_exclusive_local']} | "
                    f"{boundary['samples']} | {boundary['target_points']} |")
    rows += ["", "拒绝窗口（不使用假值补齐）："]
    for name, boundary in split["partitions"].items():
        rows.append(f"- {name}：{boundary.get('rejected_windows', {})}。")
    rows += ["", f"过去特征：{', '.join(features['past_features'])}",
             f"未来特征：{', '.join(features['future_features'])}",
             "未来输入不含实际Solar；站点与太阳位置算法来源见feature_config.json。", "",
            "| 模型 | 参数量 | 最佳 epoch | 训练秒数 | Test MAE MW | Test RMSE MW | Test R² | 白天 MAPE % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ("baseline", *MODEL_NAMES):
        entry = test_metrics["baseline"] if name == "baseline" else test_metrics["models"][name]
        overall = entry["overall"]
        candidate = config["candidates"].get(name, {})
        rows.append(f"| {name} | {candidate.get('parameters', '--')} | {candidate.get('best_epoch', '--')} | {candidate.get('training_seconds', '--')} | "
                    f"{overall['mae_mw']} | {overall['rmse_mw']} | {overall['r2']} | {overall['mape_daylight_pct']} |")
    rows += ["", "| 提前量（物理小时） | MAE MW | RMSE MW | R² | 白天 MAPE % |",
             "|---:|---:|---:|---:|---:|"]
    for point in test_metrics["models"][selected]["horizons"]:
        rows.append(f"| {point['horizon']} | {point['mae_mw']} | {point['rmse_mw']} | {point['r2']} | {point['mape_daylight_pct']} |")
    rows += ["", "| 当地时段 | 预测实例数 | MAE MW | RMSE MW | R² | 白天 MAPE % |",
             "|---|---:|---:|---:|---:|---:|"]
    for period, values in test_metrics["models"][selected]["local_periods"].items():
        rows.append(f"| {period} | {values['count']} | {values['mae_mw']} | {values['rmse_mw']} | {values['r2']} | {values['mape_daylight_pct']} |")
    weather_groups = test_metrics["models"][selected]["weather_groups"]
    if weather_groups.get("status") == "unavailable":
        rows += ["", f"天气分类未评价：{weather_groups['reason']}。"]
    else:
        rows += ["", "天气分组依据未来预报云量，不能当作实况天气类别；高波动组按云量每物理小时变化≥25个百分点定义。",
                 "", "| 天气预报云量组 | 预测实例数 | MAE MW | RMSE MW | R² | 白天 MAPE % |",
                 "|---|---:|---:|---:|---:|---:|"]
        for group, values in weather_groups.items():
            if isinstance(values, dict):
                rows.append(f"| {group} | {values['count']} | {values['mae_mw']} | {values['rmse_mw']} | {values['r2']} | {values['mape_daylight_pct']} |")
    histories = read_json(run_dir / "training_history.json")
    rows += ["", "过拟合检查（loss差异是提示，跨时段分布变化也会影响比值）："]
    for name, candidate in config["candidates"].items():
        best = candidate["best_epoch"] - 1
        train_loss = histories[name]["keras_history"]["loss"][best]
        val_loss = histories[name]["keras_history"]["val_loss"][best]
        ratio = val_loss / train_loss if train_loss > 0 else None
        caution = "需警惕明显验证差距" if ratio is not None and ratio >= 2 else "未触发2倍loss差距警示，仍需结合曲线判断"
        rows.append(f"- {name}：最佳epoch Train={train_loss:.6f} / Val={val_loss:.6f}，ratio={ratio}；{caution}。")
    rows += ["", "误差按预测实例统计；重叠目标小时保留相同 origin/horizon 索引。",
             "持久性基线为24物理小时滞后；DST变化时不强称同一当地墙钟小时。",
             "详细提前量/早中晚/天气组指标见 metrics.json；Train/Val/Test 时间与样本数见 split_info.json。",
             "本实验只保存独立CAISO研究资产，未接入生产 API。",
             "时间索引没有未来越界，不等于历史Solar在origin已发布。OASIS ACTUAL可能次日发布，",
             "当前数据没有逐条first-publication记录；紧贴origin的96h Solar在线可得性尚未验证。", "",
             f"最终模型：{(run_dir / 'models' / 'caISO_pv_final.keras').resolve()}。",
             f"Scaler：{(run_dir / 'scalers').resolve()}；预测 CSV：{(run_dir / 'results' / 'test_predictions.csv').resolve()}。",
             "新 Python 进程重载验证：PASS（reload_check.json）。",
             "【CAISO PV Final Model：PASS（离线研究模型资产与重载检查）】",
             "是否已具备实时接入条件：尚未验证。须核验同口径及时Solar接口或明确发布延迟策略，",
             "并使用与训练一致的未来预报和特征，不能仅依据重载PASS宣称online ready。"]
    (run_dir / "TRAINING_REPORT.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True, help="New directory inside experiments/caiso_pv; existing directories are rejected")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.15)
    parser.add_argument("--loss", choices=("huber", "mse"), default="huber")
    args = parser.parse_args()
    if args.batch_size < 8 or args.epochs < 1 or args.patience < 1:
        parser.error("batch-size >= 8, epochs >= 1 and patience >= 1 are required")
    print(train(args))


if __name__ == "__main__":
    main()
