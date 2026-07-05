from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from freqtrade_lab.config_builder import build_resolved_config
from freqtrade_lab.database import (
    add_artifact,
    add_event,
    create_run,
    fetch_all,
    fetch_one,
    replace_metrics,
    replace_parameters,
    update_run,
    utcnow,
)
from freqtrade_lab.result_parser import find_backtest_result_file, parse_backtest_metrics, parse_hyperopt_parameters
from freqtrade_lab.settings import DATA_DIR, LOGS_DIR, ROOT_DIR, RUNS_DIR, USER_DATA_DIR, relative_to_root


class PipelineError(RuntimeError):
    pass


def _load_scenario(run_row: dict[str, Any]) -> dict[str, Any]:
    raw = run_row["scenario_json"]
    return json.loads(raw) if raw else {}


def _run_directory(run_id: int) -> Path:
    path = RUNS_DIR / f"run_{run_id:05d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _strategy_file(strategy: dict[str, Any]) -> Path:
    return ROOT_DIR / strategy["file_path"]


def _strategy_directory(strategy: dict[str, Any]) -> Path:
    return _strategy_file(strategy).parent


def enqueue_runs(
    timerange: str,
    pairs: list[str],
    epochs: int,
    spaces: list[str],
    hyperopt_loss: str,
    timeframe: str | None = None,
    market_type: str | None = None,
    source_folder: str | None = None,
    limit: int | None = None,
) -> list[int]:
    conditions = ["status = 'ready'"]
    params: list[Any] = []
    if market_type:
        conditions.append("market_type = ?")
        params.append(market_type)
    if source_folder:
        conditions.append("source_folder = ?")
        params.append(source_folder)

    query = f"""
    SELECT id, class_name, hyperopt_spaces, timeframe
    FROM strategies
    WHERE {' AND '.join(conditions)}
    ORDER BY source_folder, class_name
    """
    if limit:
        query += f" LIMIT {int(limit)}"

    scenario_ids: list[int] = []
    for row in fetch_all(query, tuple(params)):
        strategy_spaces = json.loads(row["hyperopt_spaces"] or "[]")
        run_spaces = spaces or strategy_spaces or ["buy", "sell"]
        scenario = {
            "pairs": pairs,
            "epochs": epochs,
            "spaces": run_spaces,
            "hyperopt_loss": hyperopt_loss,
            "timeframe": timeframe or row["timeframe"],
        }
        run_id = create_run(
            strategy_id=row["id"],
            run_type="pipeline",
            timerange=timerange,
            pairset=pairs,
            scenario=scenario,
        )
        scenario_ids.append(run_id)
    return scenario_ids


def _write_log(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")


def _command_to_string(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _execute_command(run_id: int, phase: str, command: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    add_event(run_id, "command", f"{phase}: {_command_to_string(command)}")
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT_DIR)
    _write_log(log_path, f"$ {_command_to_string(command)}")
    _write_log(log_path, result.stdout)
    _write_log(log_path, result.stderr)
    update_run(run_id, log_path=relative_to_root(log_path), exit_code=result.returncode)
    if result.returncode != 0:
        error_excerpt = (result.stderr or result.stdout).strip().splitlines()
        error_message = error_excerpt[-1] if error_excerpt else "Unknown freqtrade error"
        raise PipelineError(f"{phase} failed with exit code {result.returncode}: {error_message}")
    return result


def _assert_market_data_available() -> None:
    if not DATA_DIR.exists():
        raise PipelineError(
            f"No market data directory found at {DATA_DIR}. "
            "Download historical data before running backtests."
        )
    if not any(path.is_file() for path in DATA_DIR.rglob("*")):
        raise PipelineError(
            f"No market data files found under {DATA_DIR}. "
            "Download historical data before running backtests."
        )


def _create_optimized_strategy(run_id: int, strategy: dict[str, Any], payload: dict[str, Any]) -> tuple[Path, str]:
    strategy_name = strategy["class_name"]
    wrapper_name = f"{strategy_name}OptimizedRun{run_id}"
    wrapper_path = _run_directory(run_id) / f"{wrapper_name}.py"
    original_path = _strategy_file(strategy)

    override_lines = []
    for key in (
        "buy_params",
        "sell_params",
        "minimal_roi",
        "stoploss",
        "trailing_stop",
        "trailing_stop_positive",
        "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
        "max_open_trades",
    ):
        if key in payload:
            override_lines.append(f"    {key} = {json.dumps(payload[key], ensure_ascii=True, sort_keys=True)}")

    if not override_lines:
        raise PipelineError("Hyperopt completed but no reusable parameters were parsed")

    wrapper_source = [
        "import importlib.util",
        "from pathlib import Path",
        "",
        f"_ORIGINAL_PATH = Path(r\"{original_path}\")",
        "spec = importlib.util.spec_from_file_location('original_strategy_module', _ORIGINAL_PATH)",
        "module = importlib.util.module_from_spec(spec)",
        "assert spec.loader is not None",
        "spec.loader.exec_module(module)",
        f"BaseStrategy = module.{strategy_name}",
        "",
        f"class {wrapper_name}(BaseStrategy):",
        *override_lines,
        "",
    ]
    wrapper_path.write_text("\n".join(wrapper_source), encoding="utf-8")
    return wrapper_path, wrapper_name


def _store_artifact(run_id: int, artifact_type: str, path: Path) -> None:
    add_artifact(run_id, artifact_type, relative_to_root(path))


def process_run(run_id: int) -> None:
    run_row = fetch_one(
        """
        SELECT runs.*, strategies.class_name, strategies.file_path, strategies.market_type,
               strategies.timeframe AS strategy_timeframe, strategies.source_folder
        FROM runs
        JOIN strategies ON strategies.id = runs.strategy_id
        WHERE runs.id = ?
        """,
        (run_id,),
    )
    if run_row is None:
        raise PipelineError(f"Run {run_id} not found")
    if run_row["status"] not in {"queued", "running"}:
        return

    strategy = dict(run_row)
    scenario = _load_scenario(strategy)
    run_dir = _run_directory(run_id)
    log_path = LOGS_DIR / f"run_{run_id:05d}.log"

    update_run(
        run_id,
        status="running",
        phase="config",
        started_at=strategy["started_at"] or utcnow(),
        status_message="Building config",
    )
    add_event(run_id, "status", "Run started")
    _assert_market_data_available()

    config_path, config_hash, _ = build_resolved_config(run_id, strategy, scenario)
    update_run(
        run_id,
        resolved_config_path=relative_to_root(config_path),
        config_hash=config_hash,
        status_message="Config ready",
    )
    _store_artifact(run_id, "resolved_config", config_path)

    baseline_result_dir = run_dir / "baseline_backtest"
    final_result_dir = run_dir / "final_backtest"
    baseline_result_dir.mkdir(parents=True, exist_ok=True)
    final_result_dir.mkdir(parents=True, exist_ok=True)

    strategy_dir = _strategy_directory(strategy)
    backtest_command = [
        "freqtrade",
        "backtesting",
        "--userdir",
        str(USER_DATA_DIR),
        "--config",
        str(config_path),
        "--strategy",
        strategy["class_name"],
        "--strategy-path",
        str(strategy_dir),
        "--timerange",
        strategy["timerange"],
        "--export",
        "trades",
        "--backtest-directory",
        str(baseline_result_dir),
    ]

    update_run(run_id, phase="baseline_backtest", status_message="Running baseline backtest")
    _execute_command(run_id, "baseline_backtest", backtest_command, log_path)
    baseline_result_path = find_backtest_result_file(baseline_result_dir)
    if baseline_result_path:
        _store_artifact(run_id, "baseline_backtest", baseline_result_path)
    metrics = parse_backtest_metrics(baseline_result_dir)
    if metrics:
        replace_metrics(run_id, "baseline", metrics)
    else:
        add_event(run_id, "warning", "Baseline backtest finished but metrics could not be parsed")

    update_run(run_id, phase="hyperopt", status_message="Running hyperopt")
    hyperopt_command = [
        "freqtrade",
        "hyperopt",
        "--userdir",
        str(USER_DATA_DIR),
        "--config",
        str(config_path),
        "--strategy",
        strategy["class_name"],
        "--strategy-path",
        str(strategy_dir),
        "--timerange",
        strategy["timerange"],
        "--epochs",
        str(scenario["epochs"]),
        "--hyperopt-loss",
        scenario["hyperopt_loss"],
        "--print-json",
        "--spaces",
        *scenario["spaces"],
    ]
    hyperopt_result = _execute_command(run_id, "hyperopt", hyperopt_command, log_path)
    flattened_params, payload = parse_hyperopt_parameters(hyperopt_result.stdout)
    if flattened_params:
        replace_parameters(run_id, flattened_params)
    else:
        add_event(run_id, "warning", "Hyperopt finished but no JSON payload was parsed")

    if payload:
        payload_path = run_dir / "hyperopt_payload.json"
        payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _store_artifact(run_id, "hyperopt_payload", payload_path)

    update_run(run_id, phase="final_backtest", status_message="Preparing optimized strategy wrapper")

    final_strategy_path = None
    final_strategy_name = strategy["class_name"]
    if payload:
        try:
            final_strategy_path, final_strategy_name = _create_optimized_strategy(run_id, strategy, payload)
            _store_artifact(run_id, "optimized_strategy", final_strategy_path)
        except PipelineError as error:
            add_event(run_id, "warning", str(error))

    if final_strategy_path:
        final_command = [
            "freqtrade",
            "backtesting",
            "--userdir",
            str(USER_DATA_DIR),
            "--config",
            str(config_path),
            "--strategy",
            final_strategy_name,
            "--strategy-path",
            str(final_strategy_path.parent),
            "--timerange",
            strategy["timerange"],
            "--export",
            "trades",
            "--backtest-directory",
            str(final_result_dir),
        ]
        _execute_command(run_id, "final_backtest", final_command, log_path)
        final_result_path = find_backtest_result_file(final_result_dir)
        if final_result_path:
            _store_artifact(run_id, "final_backtest", final_result_path)
        final_metrics = parse_backtest_metrics(final_result_dir)
        if final_metrics:
            replace_metrics(run_id, "final", final_metrics)
        else:
            add_event(run_id, "warning", "Final backtest finished but metrics could not be parsed")
    else:
        add_event(run_id, "warning", "Final backtest skipped because optimized wrapper could not be generated")

    update_run(
        run_id,
        phase="completed",
        status="completed",
        status_message="Run completed",
        finished_at=utcnow(),
    )
    add_event(run_id, "status", "Run completed")


def process_next_queued_run() -> bool:
    run_row = fetch_one(
        """
        SELECT id
        FROM runs
        WHERE status = 'queued'
        ORDER BY created_at ASC
        LIMIT 1
        """
    )
    if run_row is None:
        return False

    run_id = int(run_row["id"])
    try:
        process_run(run_id)
    except Exception as error:
        update_run(
            run_id,
            status="failed",
            phase="failed",
            status_message=str(error),
            finished_at=utcnow(),
        )
        add_event(run_id, "error", str(error))
    return True


def run_worker_loop(poll_interval: int, once: bool = False) -> None:
    while True:
        processed = process_next_queued_run()
        if once:
            return
        if not processed:
            time.sleep(poll_interval)
