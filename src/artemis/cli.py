"""Artemis dev CLI — stdin prompt loop over the Gateway.

Usage::

    uv run python -m artemis.cli

Type a question, get a streaming answer. ``/quit`` to exit.
"""

from __future__ import annotations

import asyncio
import sys

from artemis.config import get_settings
from artemis.gateway import Gateway, compose_brain


def main() -> None:
    """Run the REPL: read a line, send it to the Gateway, print the answer."""
    settings = get_settings()
    brain = compose_brain(settings)
    gateway = Gateway(brain)

    print("Artemis dev CLI — type your question, or /quit to exit.", flush=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                print("\n[interrupted]", flush=True)
                break

            if not line:
                # EOF
                break

            line = line.strip()
            if not line:
                continue
            if line == "/quit":
                break

            # Stream the response and print each chunk
            async def stream_and_print(text: str) -> None:
                async for chunk in gateway.handle_text_stream(text):
                    print(chunk, end="", flush=True)
                print(flush=True)

            loop.run_until_complete(stream_and_print(line))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
