# MLflow Tracing Demo

Local MLflow server for the AF tracing verification demo.

## Requirements

- Docker
- Docker Compose v2

## Bring it up

```bash
cd examples/mlflow_demo
docker compose up -d
```

Server: http://localhost:5000

Backend: SQLite (required for OTLP trace ingest — file-store backend is unsupported).

## Create an experiment

Open http://localhost:5000 and click **Create Experiment**. Name it
`archipelago-demo` (or anything). Note the numeric **Experiment ID**.

## Run the example

See `main.py` for the end-to-end example product. It reads the experiment ID
from `AF_MLFLOW_EXPERIMENT_ID`:

```bash
export AF_MLFLOW_EXPERIMENT_ID=<id>
pdm run python examples/mlflow_demo/main.py
```

## Tear it down

```bash
docker compose down
```

Volumes persist data across restarts. Add `-v` to wipe them:

```bash
docker compose down -v
```
