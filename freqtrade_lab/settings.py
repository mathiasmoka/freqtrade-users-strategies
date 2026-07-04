from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = ROOT_DIR / "Strategies"
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = Path(os.getenv("FREQTRADE_DATA_DIR", ROOT_DIR / "data"))

EXPERIMENTS_DIR = ROOT_DIR / "experiments"
CONFIG_OUTPUT_DIR = EXPERIMENTS_DIR / "configs"
DATABASE_DIR = EXPERIMENTS_DIR / "database"
RUNS_DIR = EXPERIMENTS_DIR / "runs"
RESULTS_DIR = EXPERIMENTS_DIR / "results"
LOGS_DIR = EXPERIMENTS_DIR / "logs"
DATABASE_PATH = Path(os.getenv("FREQTRADE_DB_PATH", DATABASE_DIR / "results.sqlite"))

SOURCE_FOLDERS = {"root", "futures", "berlinguyinca", "Ninja", "lookahead_bias"}


def ensure_runtime_directories() -> None:
    for path in (
        DATA_DIR,
        CONFIG_OUTPUT_DIR,
        DATABASE_DIR,
        RUNS_DIR,
        RESULTS_DIR,
        LOGS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def relative_to_root(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT_DIR))


def detect_source_folder(path: Path) -> str:
    relative_path = path.resolve().relative_to(STRATEGIES_DIR.resolve())
    if len(relative_path.parts) == 1:
        return "root"
    return relative_path.parts[0]


def detect_market_type(path: Path) -> str:
    return "futures" if detect_source_folder(path) == "futures" else "spot"

