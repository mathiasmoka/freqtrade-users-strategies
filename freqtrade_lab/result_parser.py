from __future__ import annotations

import json
from json import JSONDecoder
from pathlib import Path
from typing import Any


METRIC_KEY_MAP = {
    "profit_total": ("profit_total", "profit_total_pct", "total_profit", "profit_mean_pct"),
    "profit_abs": ("profit_total_abs", "profit_abs", "total_profit_abs"),
    "drawdown": ("max_drawdown_account", "drawdown", "max_relative_drawdown"),
    "sharpe": ("sharpe", "sharpe_ratio"),
    "sortino": ("sortino", "sortino_ratio"),
    "profit_factor": ("profit_factor",),
    "trade_count": ("total_trades", "trade_count", "trades"),
    "avg_trade_duration": ("holding_avg", "avg_trade_duration", "trade_duration_avg"),
}


def _iter_dicts(payload: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        results.append(payload)
        for value in payload.values():
            results.extend(_iter_dicts(value))
    elif isinstance(payload, list):
        for item in payload:
            results.extend(_iter_dicts(item))
    return results


def _score_candidate(candidate: dict[str, Any]) -> int:
    score = 0
    for aliases in METRIC_KEY_MAP.values():
        if any(alias in candidate for alias in aliases):
            score += 1
    return score


def _normalize_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for target, aliases in METRIC_KEY_MAP.items():
        for alias in aliases:
            if alias in candidate:
                normalized[target] = candidate[alias]
                break

    wins = candidate.get("wins")
    trade_count = normalized.get("trade_count") or candidate.get("losses")
    if wins is not None and trade_count:
        normalized["winrate"] = wins / trade_count
    elif "winrate" in candidate:
        normalized["winrate"] = candidate["winrate"]

    return normalized


def parse_backtest_metrics(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    candidates = _iter_dicts(payload)
    if not candidates:
        return None

    best_candidate = max(candidates, key=_score_candidate)
    if _score_candidate(best_candidate) == 0:
        return None

    return _normalize_metrics(best_candidate)


def extract_last_json_object(text: str) -> dict[str, Any] | list[Any] | None:
    decoder = JSONDecoder()
    index = 0
    last_object: dict[str, Any] | list[Any] | None = None
    while index < len(text):
        character = text[index]
        if character not in "[{":
            index += 1
            continue
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        last_object = payload
        index += end
    return last_object


def _flatten(prefix: str, value: Any, output: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            _flatten(child_prefix, child, output)
        return
    output[prefix] = value


def parse_hyperopt_parameters(text: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = extract_last_json_object(text)
    if payload is None or not isinstance(payload, dict):
        return {}, None

    flattened: dict[str, Any] = {}
    _flatten("", payload, flattened)
    return flattened, payload

