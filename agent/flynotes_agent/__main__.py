from __future__ import annotations

import uvicorn

from .config import AgentConfig
from .single_instance import AlreadyRunning, SingleInstance


def main() -> None:
    config = AgentConfig.from_env()
    config.ensure_directories()
    try:
        with SingleInstance():
            uvicorn.run(
                "flynotes_agent.api:app",
                host=config.host,
                port=config.port,
                reload=False,
                log_level="info",
            )
    except AlreadyRunning as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
