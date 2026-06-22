"""Boot the eval API server using settings from ``agent_foundry.config``.

Run with::

    python -m agent_foundry.evals.api

Reads the config file from the current working directory, resolves the
declared registry, and binds uvicorn to the host/port declared under
``[api]`` (defaults: ``127.0.0.1:8000``).
"""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from agent_foundry.evals.api.app import create_app
from agent_foundry.evals.api.config import load_config
from agent_foundry.evals.api.registry_loader import load_registry


def main() -> None:
    load_dotenv()
    config = load_config()
    registry = load_registry(config.registry)
    app = create_app(registry)
    uvicorn.run(app, host=config.api.host, port=config.api.port)


if __name__ == "__main__":
    main()
