"""Stage only independent CAISO scripts/data in a fresh Colab workspace and train."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
import zipfile

DATA_FILES = {"dataset.npz", "past_scaler.json", "future_scaler.json", "target_scaler.json",
              "feature_config.json", "split_info.json", "data_approval.json"}
REQUIRED_SCRIPTS = {"models.py", "train.py", "evaluate.py", "infer.py", "reload_check.py", "colab_run.py"}
TRAIN_DEFAULTS = {"batch_size": 64, "epochs": 100, "patience": 12, "seed": 42,
                  "learning_rate": 0.001, "dropout": 0.15, "loss": "huber"}


def validate_bundle(archive: Path, dataset_relative: str) -> list[zipfile.ZipInfo]:
    dataset = PurePosixPath(dataset_relative)
    if (len(dataset.parts) != 3 or dataset.parts[:2] != ("data", "processed")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", dataset.parts[-1])):
        raise ValueError("dataset_relative must be data/processed/<safe_dataset_id>")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        found = set()
        for member in members:
            path = PurePosixPath(member.filename)
            if ("\\" in member.filename or path.is_absolute() or ".." in path.parts
                    or member.filename.rstrip("/") in found or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError("Bundle contains an unsafe, duplicate or symbolic-link path")
            found.add(member.filename.rstrip("/"))
            if member.is_dir():
                allowed = path == PurePosixPath("scripts") or path in (PurePosixPath("data"), PurePosixPath("data/processed"), dataset)
            else:
                allowed = (len(path.parts) == 2 and path.parts[0] == "scripts" and path.suffix in (".py", ".md"))
                allowed |= path.parent == dataset and path.name in DATA_FILES
            if not allowed:
                raise ValueError(f"Bundle must contain only independent scripts and the chosen frozen dataset: {path}")
        required = {f"scripts/{name}" for name in REQUIRED_SCRIPTS} | {str(dataset / name) for name in DATA_FILES}
        if not required.issubset(found):
            raise ValueError(f"Incomplete formal bundle: missing {sorted(required - found)}")
        if sum(member.file_size for member in members) > 12 * 1024 ** 3:
            raise ValueError("Bundle exceeds the 12 GiB independent workspace extraction limit")
        return members


def stage_bundle(archive: Path, workspace: Path, dataset_relative: str) -> dict:
    members = validate_bundle(archive, dataset_relative)
    workspace.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for member in members:
            destination = workspace.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    npz = workspace / dataset_relative / "dataset.npz"
    with zipfile.ZipFile(npz) as arrays:
        compressed = sum(member.compress_size for member in arrays.infolist())
        uncompressed = sum(member.file_size for member in arrays.infolist())
    return {"bundle_bytes": archive.stat().st_size, "dataset_npz_bytes": npz.stat().st_size,
            "array_compressed_bytes": compressed, "array_uncompressed_bytes": uncompressed,
            "uncompressed_training_ram_note": "Arrays plus TensorFlow activations; not a GPU memory guarantee"}


def archive_outputs(workspace: Path, output: Path, *, logs_only: bool) -> None:
    # Every archive name is unique. Snapshots contain live logs/config, never a half-written checkpoint.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for source in sorted(workspace.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts or "data" in source.relative_to(workspace).parts:
                continue
            if logs_only and source.suffix != ".json" and source.suffix != ".txt":
                continue
            if logs_only and source.suffix == ".json" and source.name not in (
                    "epoch_log.json", "training_plan.json", "hardware.json", "feature_config.json", "split_info.json",
                    "job_config.json", "job_status.json", "bundle_inventory.json", "dependencies.json",
                    "past_scaler.json", "future_scaler.json", "target_scaler.json", "data_approval.json"):
                continue
            bundle.write(source, source.relative_to(workspace).as_posix())


def run(config: dict) -> Path:
    run_id = config["run_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError("run_id must be a safe unique identifier")
    workspace = Path(config["workspace"]).resolve()
    if workspace.parent != Path("/content").resolve() or workspace.name != f"caiso_pv_formal_{run_id}":
        raise ValueError("Formal workspace must be /content/caiso_pv_formal_<run_id>")
    final_archive = workspace.parent / f"{workspace.name}_results.zip"
    if workspace.exists() or final_archive.exists():
        raise FileExistsError("Refusing to overwrite a previous workspace or result archive")
    training = config.get("training", TRAIN_DEFAULTS)
    if set(training) != set(TRAIN_DEFAULTS):
        raise ValueError(f"training must explicitly contain {sorted(TRAIN_DEFAULTS)}; no unknown or hidden overrides")
    if (training["batch_size"] < 8 or training["epochs"] < 1 or training["patience"] < 1
            or not 0 <= training["dropout"] < 1 or training["learning_rate"] <= 0
            or training["loss"] not in ("huber", "mse")):
        raise ValueError("Invalid explicit training configuration")
    interval = config.get("snapshot_interval_seconds", 300)
    if interval < 30:
        raise ValueError("Log snapshot interval must be at least 30 seconds")
    try:
        inventory = stage_bundle(Path(config["archive_path"]), workspace, config["dataset_relative"])
    except Exception as error:
        if workspace.exists():
            failure_logs = workspace / "logs"
            failure_logs.mkdir(exist_ok=True)
            (failure_logs / "job_status.json").write_text(json.dumps({"status": "FAIL", "stage": "bundle_extraction",
                "error_type": type(error).__name__, "error": str(error)}, indent=2), encoding="utf-8")
            archive_outputs(workspace, final_archive, logs_only=False)
            print(json.dumps({"event": "formal_result_archive", "status": "FAIL", "path": str(final_archive)}), flush=True)
        raise
    logs = workspace / "logs"
    logs.mkdir(exist_ok=False)
    (logs / "job_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (logs / "bundle_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    dataset = workspace / config["dataset_relative"]
    run_directory = workspace / "results" / "runs" / run_id
    command = [sys.executable, "-u", str(workspace / "scripts" / "colab_run.py"),
               "--dataset-dir", str(dataset), "--run-dir", str(run_directory)]
    for name, value in training.items():
        command.extend([f"--{name.replace('_', '-')}", str(value)])
    environment = {**os.environ, "PYTHONUNBUFFERED": "1", "MPLBACKEND": "Agg"}
    process = None
    reader = None
    status = {"status": "RUNNING", "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat()}
    (logs / "job_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    try:
        # Record existing Colab versions. Never replace or upgrade TensorFlow implicitly.
        versions = {name: importlib.metadata.version(name) for name in ("tensorflow", "keras", "numpy", "matplotlib")}
        (logs / "dependencies.json").write_text(json.dumps({"python": sys.version, "packages": versions}, indent=2), encoding="utf-8")
        (logs / "requirements-lock.txt").write_text("\n".join(f"{name}=={version}" for name, version in versions.items()) + "\n", encoding="utf-8")
        if versions["tensorflow"] != "2.20.0":
            raise RuntimeError(f"Formal job requires the recorded TensorFlow 2.20.0 contract; detected {versions['tensorflow']}. No automatic upgrade is performed")
        print(json.dumps({"event": "formal_bundle_staged", **inventory, "dependencies": versions}), flush=True)
        process = subprocess.Popen(command, cwd=workspace, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)

        def stream_output():
            with (logs / "train_stdout.txt").open("x", encoding="utf-8") as target:
                for line in process.stdout:
                    target.write(line)
                    target.flush()
                    print(line, end="", flush=True)

        reader = threading.Thread(target=stream_output, daemon=True)
        reader.start()
        last_snapshot = time.monotonic()
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic() - last_snapshot >= interval:
                snapshot = workspace.parent / f"{workspace.name}_logs_{time.time_ns()}.zip"
                archive_outputs(workspace, snapshot, logs_only=True)
                print(json.dumps({"event": "log_snapshot_available", "path": str(snapshot)}), flush=True)
                last_snapshot = time.monotonic()
        reader.join()
        status.update(returncode=process.returncode, status="PASS" if process.returncode == 0 else "FAIL")
        if process.returncode:
            raise RuntimeError(f"Formal training exited with {process.returncode}; see logs/train_stdout.txt")
    except BaseException as error:
        status.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        if reader is not None:
            reader.join()
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        (logs / "job_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        archive_outputs(workspace, final_archive, logs_only=False)
        print(json.dumps({"event": "formal_result_archive", "status": status["status"], "path": str(final_archive)}), flush=True)
    return final_archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Explicit JSON job configuration")
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
