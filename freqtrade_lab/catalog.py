from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from freqtrade_lab.database import upsert_strategy
from freqtrade_lab.settings import STRATEGIES_DIR, detect_market_type, detect_source_folder, relative_to_root


@dataclass
class StrategyMetadata:
    name: str | None
    class_name: str | None
    file_path: str
    source_folder: str
    market_type: str
    timeframe: str | None
    hyperopt_spaces: list[str]
    trailing_stop: bool
    protections_enabled: bool
    can_short: bool
    status: str
    parse_error: str | None = None


def _base_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _is_strategy_class(node: ast.ClassDef) -> bool:
    base_names = {_base_name(base) for base in node.bases}
    if "IStrategy" in base_names:
        return True
    method_names = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
    return "populate_indicators" in method_names and "populate_buy_trend" in method_names


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _parse_class_metadata(node: ast.ClassDef) -> dict[str, Any]:
    timeframe = None
    hyperopt_spaces: set[str] = set()
    trailing_stop = False
    can_short = False
    protections_enabled = False

    for item in node.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "timeframe":
                    value = _literal(item.value)
                    if isinstance(value, str):
                        timeframe = value
                elif target.id == "trailing_stop":
                    trailing_stop = bool(_literal(item.value))
                elif target.id == "can_short":
                    can_short = bool(_literal(item.value))
                elif target.id == "protections":
                    protections_enabled = True
                elif target.id.endswith("_params"):
                    space_name = target.id.replace("_params", "")
                    if space_name in {"buy", "sell"}:
                        hyperopt_spaces.add(space_name)
        elif isinstance(item, ast.FunctionDef) and item.name == "protections":
            protections_enabled = True

        value = item.value if isinstance(item, ast.Assign) else None
        if isinstance(value, ast.Call):
            function_name = None
            if isinstance(value.func, ast.Name):
                function_name = value.func.id
            elif isinstance(value.func, ast.Attribute):
                function_name = value.func.attr
            if function_name and function_name.endswith("Parameter"):
                for keyword in value.keywords:
                    if keyword.arg == "space":
                        space = _literal(keyword.value)
                        if isinstance(space, str):
                            hyperopt_spaces.add(space)

    return {
        "timeframe": timeframe,
        "hyperopt_spaces": sorted(hyperopt_spaces),
        "trailing_stop": trailing_stop,
        "protections_enabled": protections_enabled,
        "can_short": can_short,
    }


def _metadata_for_file(path: Path) -> StrategyMetadata:
    source_folder = detect_source_folder(path)
    market_type = detect_market_type(path)
    file_path = relative_to_root(path)

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError as error:
        return StrategyMetadata(
            name=path.stem,
            class_name=None,
            file_path=file_path,
            source_folder=source_folder,
            market_type=market_type,
            timeframe=None,
            hyperopt_spaces=[],
            trailing_stop=False,
            protections_enabled=False,
            can_short=False,
            status="parse_error",
            parse_error=str(error),
        )

    strategy_class = next((node for node in tree.body if isinstance(node, ast.ClassDef) and _is_strategy_class(node)), None)
    if strategy_class is None:
        return StrategyMetadata(
            name=path.stem,
            class_name=None,
            file_path=file_path,
            source_folder=source_folder,
            market_type=market_type,
            timeframe=None,
            hyperopt_spaces=[],
            trailing_stop=False,
            protections_enabled=False,
            can_short=False,
            status="ignored",
            parse_error="No strategy class detected",
        )

    parsed = _parse_class_metadata(strategy_class)
    if parsed["can_short"] and market_type != "futures":
        market_type = "futures"

    return StrategyMetadata(
        name=strategy_class.name,
        class_name=strategy_class.name,
        file_path=file_path,
        source_folder=source_folder,
        market_type=market_type,
        timeframe=parsed["timeframe"],
        hyperopt_spaces=parsed["hyperopt_spaces"],
        trailing_stop=parsed["trailing_stop"],
        protections_enabled=parsed["protections_enabled"],
        can_short=parsed["can_short"],
        status="ready",
    )


def discover_strategies() -> list[StrategyMetadata]:
    strategies: list[StrategyMetadata] = []
    for path in sorted(STRATEGIES_DIR.rglob("*.py")):
        if path.name.startswith("__"):
            continue
        metadata = _metadata_for_file(path)
        strategies.append(metadata)
        upsert_strategy(metadata.__dict__)
    return strategies

