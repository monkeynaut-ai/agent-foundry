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
`archipelago-demo` (or anything).

The UI does not display the experiment ID prominently. To find it:

- **From the URL**: click into the experiment from the experiment list. The
  URL becomes `http://localhost:5000/#/experiments/<ID>` — the number after
  `/experiments/` is the ID. (`Default` is always `0`; new experiments start
  at `1`.)
- **From the API**:
  ```bash
  curl -s http://localhost:5000/api/2.0/mlflow/experiments/search \
    -X POST -H 'Content-Type: application/json' -d '{}' \
    | jq '.experiments[] | {id: .experiment_id, name: .name}'
  ```

## Run the example

See `main.py` for the end-to-end example product. Set the experiment ID
once via `AF_MLFLOW_EXPERIMENT_ID` — `main.py` uses that single value for
both the trace-side OTLP header and the Run-side `mlflow.set_experiment`
call:

```bash
export AF_MLFLOW_EXPERIMENT_ID=<id>
pdm run python examples/mlflow_demo/main.py
```

If MLflow is bound somewhere other than `http://localhost:5000`, override
with `AF_MLFLOW_BASE_URL`:

```bash
export AF_MLFLOW_BASE_URL=http://mlflow.local:5000
```

## Tear it down

```bash
docker compose down
```

Volumes persist data across restarts. Add `-v` to wipe them:

```bash
docker compose down -v
```
