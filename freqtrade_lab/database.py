from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from freqtrade_lab.settings import DATABASE_PATH, ensure_runtime_directories


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    class_name TEXT,
    file_path TEXT NOT NULL UNIQUE,
    source_folder TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timeframe TEXT,
    hyperopt_spaces TEXT,
    trailing_stop INTEGER NOT NULL DEFAULT 0,
    protections_enabled INTEGER NOT NULL DEFAULT 0,
    can_short INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    parse_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    parent_run_id INTEGER,
    run_type TEXT NOT NULL,
    config_hash TEXT,
    resolved_config_path TEXT,
    timerange TEXT,
    pairset TEXT,
    scenario_json TEXT,
    phase TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    status_message TEXT,
    log_path TEXT,
    exit_code INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(strategy_id) REFERENCES strategies(id),
    FOREIGN KEY(parent_run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_strategy_id ON runs(strategy_id, created_at);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    metric_scope TEXT NOT NULL,
    profit_total REAL,
    profit_abs REAL,
    drawdown REAL,
    sharpe REAL,
    sortino REAL,
    winrate REAL,
    profit_factor REAL,
    trade_count INTEGER,
    avg_trade_duration TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    param_name TEXT NOT NULL,
    param_value TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def adapt_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


@contextmanager
def connect(readonly: bool = False) -> Iterable[sqlite3.Connection]:
    ensure_runtime_directories()
    database_uri = str(DATABASE_PATH)
    if readonly and Path(DATABASE_PATH).exists():
        database_uri = f"file:{DATABASE_PATH}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=readonly and Path(DATABASE_PATH).exists())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000;")
    connection.execute("PRAGMA foreign_keys=ON;")
    try:
        yield connection
        if not readonly:
            connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)


def upsert_strategy(strategy: dict[str, Any]) -> None:
    payload = (
        strategy.get("name"),
        strategy.get("class_name"),
        strategy["file_path"],
        strategy["source_folder"],
        strategy["market_type"],
        strategy.get("timeframe"),
        adapt_json(strategy.get("hyperopt_spaces", [])),
        int(bool(strategy.get("trailing_stop"))),
        int(bool(strategy.get("protections_enabled"))),
        int(bool(strategy.get("can_short"))),
        strategy["status"],
        strategy.get("parse_error"),
        utcnow(),
    )
    query = """
    INSERT INTO strategies (
        name, class_name, file_path, source_folder, market_type, timeframe,
        hyperopt_spaces, trailing_stop, protections_enabled, can_short,
        status, parse_error, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(file_path) DO UPDATE SET
        name = excluded.name,
        class_name = excluded.class_name,
        source_folder = excluded.source_folder,
        market_type = excluded.market_type,
        timeframe = excluded.timeframe,
        hyperopt_spaces = excluded.hyperopt_spaces,
        trailing_stop = excluded.trailing_stop,
        protections_enabled = excluded.protections_enabled,
        can_short = excluded.can_short,
        status = excluded.status,
        parse_error = excluded.parse_error,
        updated_at = excluded.updated_at
    """
    with connect() as connection:
        connection.execute(query, payload)


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with connect(readonly=True) as connection:
        return list(connection.execute(query, params).fetchall())


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with connect(readonly=True) as connection:
        return connection.execute(query, params).fetchone()


def create_run(
    strategy_id: int,
    run_type: str,
    timerange: str,
    pairset: list[str],
    scenario: dict[str, Any],
) -> int:
    timestamp = utcnow()
    query = """
    INSERT INTO runs (
        strategy_id, run_type, timerange, pairset, scenario_json, phase,
        updated_at, status, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with connect() as connection:
        cursor = connection.execute(
            query,
            (
                strategy_id,
                run_type,
                timerange,
                adapt_json(pairset),
                adapt_json(scenario),
                "queued",
                timestamp,
                "queued",
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [run_id]
    query = f"UPDATE runs SET {assignments} WHERE id = ?"
    with connect() as connection:
        connection.execute(query, values)


def add_event(run_id: int, event_type: str, message: str) -> None:
    with connect() as connection:
        try:
            connection.execute(
                """
                INSERT INTO events (run_id, event_type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, message, utcnow()),
            )
        except sqlite3.IntegrityError:
            return


def add_artifact(run_id: int, artifact_type: str, file_path: str) -> None:
    with connect() as connection:
        try:
            connection.execute(
                """
                INSERT INTO artifacts (run_id, artifact_type, file_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, artifact_type, file_path, utcnow()),
            )
        except sqlite3.IntegrityError:
            return


def replace_metrics(run_id: int, metric_scope: str, metrics: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM metrics WHERE run_id = ? AND metric_scope = ?",
            (run_id, metric_scope),
        )
        connection.execute(
            """
            INSERT INTO metrics (
                run_id, metric_scope, profit_total, profit_abs, drawdown, sharpe,
                sortino, winrate, profit_factor, trade_count, avg_trade_duration, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                metric_scope,
                metrics.get("profit_total"),
                metrics.get("profit_abs"),
                metrics.get("drawdown"),
                metrics.get("sharpe"),
                metrics.get("sortino"),
                metrics.get("winrate"),
                metrics.get("profit_factor"),
                metrics.get("trade_count"),
                metrics.get("avg_trade_duration"),
                utcnow(),
            ),
        )


def replace_parameters(run_id: int, parameters: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM parameters WHERE run_id = ?", (run_id,))
        connection.executemany(
            """
            INSERT INTO parameters (run_id, param_name, param_value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [(run_id, key, adapt_json(value), utcnow()) for key, value in parameters.items()],
        )
