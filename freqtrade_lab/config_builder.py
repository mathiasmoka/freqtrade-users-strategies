from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from freqtrade_lab.settings import CONFIG_DIR, CONFIG_OUTPUT_DIR, DATA_DIR


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_resolved_config(run_id: int, strategy: dict[str, Any], scenario: dict[str, Any]) -> tuple[Path, str, dict[str, Any]]:
    base = _load_json(CONFIG_DIR / "base_config.json")
    override_name = "futures.overrides.json" if strategy["market_type"] == "futures" else "spot.overrides.json"
    merged = _deep_merge(base, _load_json(CONFIG_DIR / override_name))

    timeframe = scenario.get("timeframe") or strategy.get("timeframe") or merged.get("timeframe") or "5m"
    pairs = scenario.get("pairs") or merged["exchange"]["pair_whitelist"]
    exchange_name = scenario.get("exchange_name") or os.getenv("FREQTRADE_EXCHANGE", merged["exchange"]["name"])

    merged["exchange"]["name"] = exchange_name
    merged["exchange"]["pair_whitelist"] = pairs
    merged["timeframe"] = timeframe
    merged["stake_currency"] = scenario.get("stake_currency", merged["stake_currency"])
    merged["stake_amount"] = scenario.get("stake_amount", merged["stake_amount"])
    merged["dry_run"] = True
    merged["user_data_dir"] = str(DATA_DIR)
    merged["datadir"] = str(DATA_DIR)
    merged["bot_name"] = f"run-{run_id}"

    output_path = CONFIG_OUTPUT_DIR / f"run_{run_id:05d}.json"
    rendered = json.dumps(merged, indent=2, sort_keys=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")
    config_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return output_path, config_hash, merged

