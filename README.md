[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Freqtrade](https://img.shields.io/badge/Freqtrade-FF6B35?logo=bitcoin&logoColor=white)](https://www.freqtrade.io/)

# Automated testing and comparisons of FreqTrade Crypto Bot Strategies

## Brief overview of the project:

This repository originally contained several hundred FreqTrade strategies (a Python library that facilitates the development of FreqTrade crypto bots, built on top of CCXT).

I wanted to quickly test all of these different strategies to determine which ones warranted further analysis.

So I built this project: an architecture that automates strategy testing and comparison, displaying the results in a dashboard.

The project uses Docker to simplify deployment.

To test new strategies, simply add them to the Strategy folder.

## Quick Start

1. Clone the repository

```shell
git clone https://github.com/AlexCryptoKing/freqtrade.git
```
2. Copy the selected Strategy files to the freqtrade Strategy directory

```
3. Download the data minimum 1 Month!

freqtrade download-data -c config/base_config.json --timerange 20240701-20240801 --timeframe 15m 30m 1h 2h 4h 8h 1d --erase

4. Hyperopt the Strategy!
freqtrade hyperopt --hyperopt-loss SharpeHyperOptLossDaily --spaces buy sell stoploss -c config/base_config.json --strategy haFbmS --timerange=20240601-20240914 --epochs 100
````

## MVP benchmark stack

The repository now contains a local MVP to benchmark many strategies with:

- SQLite as the source of truth for strategy metadata and run states,
- a queue-based runner that persists each step between backtest and hyperopt phases,
- a Streamlit dashboard that reads partial results in real time,
- Docker Compose for local execution.

### Main components

- `freqtrade_lab/` contains the Python CLI, SQLite schema, strategy discovery and pipeline runner.
- `dashboards/streamlit_app.py` shows queued, running, completed and failed runs directly from SQLite.
- `config/` contains base config templates for spot and futures.
- `docker-compose.yml` starts the `runner` worker and the `dashboard`.

### Start the MVP

Build and start the containers:

```shell
docker compose build
docker compose up -d dashboard runner
```

Initialize the database and discover the strategies:

```shell
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli init-db
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli discover
```

Queue a first batch:

```shell
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli enqueue \
  --timerange 20240101-20240301 \
  --pairs BTC/USDT,ETH/USDT,SOL/USDT \
  --epochs 20 \
  --spaces buy,sell,roi,stoploss \
  --limit 10
```

The worker service will pick queued runs automatically. The dashboard is available at:

```text
http://localhost:8501
```

### Notes

- Spot and futures are inferred from the strategy path. Files under `Strategies/futures/` are treated as futures. Other strategy folders default to spot.
- The runner writes incremental state to `experiments/database/results.sqlite`.
- Runtime artifacts are written to `experiments/configs/`, `experiments/runs/` and `experiments/logs/`.
- You still need market data compatible with your chosen pairs and timeframes for Freqtrade backtests to succeed.

## Précisions

Le vrai exécuteur est le service runner. Pour que ça tourne, il faut :

  1. démarrer le worker en arrière-plan avec docker compose up -d runner
  2. vérifier qu’il consomme la queue avec docker compose logs -f runner
  3. voir l’état des runs avec docker compose run --rm --entrypoint "" runner python -m
     freqtrade_lab.cli status

  Ce n’est probablement pas un problème de “config Freqtrade” au sens API keys. Pour du
  backtesting et du hyperopt, les clés exchange ne sont pas nécessaires dans ce MVP,
  car le config est généré automatiquement par run. Le point bloquant le plus probable
  est l’absence de données historiques dans user_data/data/. Sans données, le worker va échouer
  rapidement quand il appellera freqtrade backtesting.

  J’ai renforcé ça dans le code :

  - freqtrade_lab/runner.py vérifie maintenant explicitement que user_data/data/ contient des
    fichiers avant d’appeler Freqtrade

  - freqtrade_lab/cli.py a une commande status
  - README.md explique maintenant que enqueue s’arrête immédiatement par design

  La prochaine étape concrète est de charger des données, puis relancer le worker.

## Commandes

### Build et démarrage

```shell
docker compose build
docker compose up -d runner dashboard
docker compose ps
```

### Initialisation

```shell
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli init-db
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli discover
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli clear-runs
```

### Téléchargement des données spot

```shell
docker compose run --rm --entrypoint "" runner \
  freqtrade download-data \
  --userdir ./user_data \
  --config ./config/base_config.json \
  --exchange binance \
  --pairs BTC/USDT ETH/USDT SOL/USDT \
  --timeframes 5m 15m 1h \
  --timerange 20240101-20240301
```

### Téléchargement des données futures
--> modifier le fichier config de spot à futures avant

```shell
docker compose run --rm --entrypoint "" runner \
  freqtrade download-data \
  --userdir ./user_data \
  --config ./config/base_config.json \
  --trading-mode futures \
  --exchange binance \
  --pairs BTC/USDT:USDT ETH/USDT:USDT SOL/USDT:USDT \
  --timeframes 5m 15m 1h \
  --timerange 20240101-20240301
```

### Mise en queue d’un batch spot

```shell
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli enqueue \
  --timerange 20240101-20240301 \
  --pairs BTC/USDT,ETH/USDT,SOL/USDT \
  --epochs 20 \
  --spaces buy,sell,roi,stoploss \
  --market-type spot \
  --limit 10
```

### Mise en queue d’un batch futures

```shell
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli enqueue \
  --timerange 20240101-20240301 \
  --pairs BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT \
  --epochs 20 \
  --spaces buy,sell,roi,stoploss \
  --market-type futures \
  --limit 10
```

### Suivi d’exécution

```shell
docker compose logs -f runner
docker compose run --rm --entrypoint "" runner python -m freqtrade_lab.cli status --limit 20
```

### Dashboard

```text
http://localhost:8501
```

