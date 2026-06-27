"""Run the Artemis brain FastAPI app as a local uvicorn process."""

from __future__ import annotations

import uvicorn

from artemis.config import get_settings


def main() -> None:
    """Launch the brain on the loopback interface."""
    settings = get_settings()
    uvicorn.run(
        "artemis.main:app",
        host="127.0.0.1",
        port=settings.brain_port,
        reload=False,
    )
