"""py -3.14 -m server"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from server.net.registry import Registry
from server.net.server import Server
from server.settings import load


def build_handlers(registry: Registry, settings) -> dict:
    handlers: dict = {}
    return handlers


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )
    settings = load(Path("settings.toml"))
    registry = Registry.load(settings.stock_dir)
    server = Server(registry, settings, build_handlers(registry, settings))
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
