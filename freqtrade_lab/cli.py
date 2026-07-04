from __future__ import annotations

import argparse

from freqtrade_lab.catalog import discover_strategies
from freqtrade_lab.database import connect, fetch_all, init_db
from freqtrade_lab.runner import enqueue_runs, run_worker_loop
from freqtrade_lab.settings import DATABASE_PATH, ensure_runtime_directories


def _csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def command_init_db(_: argparse.Namespace) -> None:
    ensure_runtime_directories()
    init_db()
    print(f"Initialized database at {DATABASE_PATH}")


def command_discover(_: argparse.Namespace) -> None:
    init_db()
    strategies = discover_strategies()
    print(f"Discovered {len(strategies)} strategy files")


def command_enqueue(args: argparse.Namespace) -> None:
    init_db()
    if not fetch_all("SELECT id FROM strategies LIMIT 1"):
        discover_strategies()

    run_ids = enqueue_runs(
        timerange=args.timerange,
        pairs=_csv_list(args.pairs),
        epochs=args.epochs,
        spaces=_csv_list(args.spaces),
        hyperopt_loss=args.hyperopt_loss,
        timeframe=args.timeframe,
        market_type=args.market_type,
        source_folder=args.source_folder,
        limit=args.limit,
    )
    print(f"Enqueued {len(run_ids)} runs")


def command_worker(args: argparse.Namespace) -> None:
    init_db()
    run_worker_loop(poll_interval=args.poll_interval, once=args.once)


def command_clear_runs(_: argparse.Namespace) -> None:
    init_db()
    with connect() as connection:
        connection.execute("DELETE FROM events")
        connection.execute("DELETE FROM artifacts")
        connection.execute("DELETE FROM parameters")
        connection.execute("DELETE FROM metrics")
        connection.execute("DELETE FROM runs")
    print("Cleared run state tables")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freqtrade strategy benchmark MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="Initialize SQLite schema")
    init_db_parser.set_defaults(func=command_init_db)

    discover_parser = subparsers.add_parser("discover", help="Scan strategy files")
    discover_parser.set_defaults(func=command_discover)

    enqueue_parser = subparsers.add_parser("enqueue", help="Create queued strategy runs")
    enqueue_parser.add_argument("--timerange", required=True, help="Freqtrade timerange, for example 20240101-20240301")
    enqueue_parser.add_argument("--pairs", default="BTC/USDT,ETH/USDT,SOL/USDT")
    enqueue_parser.add_argument("--epochs", type=int, default=30)
    enqueue_parser.add_argument("--spaces", default="")
    enqueue_parser.add_argument("--hyperopt-loss", default="SharpeHyperOptLossDaily")
    enqueue_parser.add_argument("--timeframe", default=None)
    enqueue_parser.add_argument("--market-type", choices=("spot", "futures"), default=None)
    enqueue_parser.add_argument("--source-folder", default=None)
    enqueue_parser.add_argument("--limit", type=int, default=None)
    enqueue_parser.set_defaults(func=command_enqueue)

    worker_parser = subparsers.add_parser("worker", help="Run queued jobs")
    worker_parser.add_argument("--poll-interval", type=int, default=10)
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.set_defaults(func=command_worker)

    clear_runs_parser = subparsers.add_parser("clear-runs", help="Clear run state while keeping discovered strategies")
    clear_runs_parser.set_defaults(func=command_clear_runs)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
