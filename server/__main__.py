"""py -3.14 -m server"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from server import db
from server.config import Config
from server.modules import gacha, guide, login, player
from server.net.registry import Registry
from server.net.server import Server
from server.settings import load


log = logging.getLogger("loa")


async def serve_and_announce(server: Server, settings) -> None:
    """Start the listener, then say which address the client will be sent to.

    QuerySrvInfoRes hands the client settings.host:settings.port, which is the
    address the phone or emulator dials - not the bind address. Getting it wrong
    is the single most common reason the login burst never arrives, so it goes
    in the log right under the listening line.
    """
    ready = asyncio.Event()
    task = asyncio.create_task(server.serve(ready))
    await ready.wait()
    log.info(
        "advertising game address %s:%d in QuerySrvInfoRes (edit settings.toml "
        "and restart the server if the phone is on another network)",
        settings.host,
        settings.port,
    )
    await task


def build_handlers(registry: Registry, settings) -> dict:
    conn = db.connect(settings.db_path)
    cfg = Config.load(settings.stock_dir)
    handlers: dict = {}
    handlers.update(login.handlers(registry, settings, conn, cfg))
    handlers.update(player.handlers(registry, settings, conn, cfg))
    handlers.update(guide.handlers(registry, settings, conn))
    handlers.update(gacha.handlers(registry, settings, conn, cfg))
    return handlers


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )
    settings = load(Path("settings.toml"))
    registry = Registry.load(settings.stock_dir)
    server = Server(
        registry, settings, build_handlers(registry, settings), bind_host=settings.bind
    )
    try:
        asyncio.run(serve_and_announce(server, settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
