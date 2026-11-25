"""py -3.14 -m server"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from server import db
from server.config import Config
from server.modules import (
    activity, angel, angeltrial, bag, buy, chat, checkin, events, gacha, goldtrial,
    guide, hero, herotrial, level, login, mail, player, rune, shop, team, train,
)
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


def config_root(settings) -> Path:
    """Where the config tables come from: the English copies when configured
    (so names, mail and status texts the server sends are English), else the
    stock tree. The stock .db files are never modified either way."""
    en = settings.english_dir
    if en is None:
        return settings.stock_dir
    if not (Path(en) / "assets/res/data/split").is_dir():
        raise SystemExit(
            f"english_dir {en} has no assets/res/data/split; "
            "run `py -3.14 -m localise.write` first"
        )
    return Path(en)


def build_handlers(registry: Registry, settings) -> dict:
    conn = db.connect(settings.db_path)
    cfg = Config.load(config_root(settings))
    handlers: dict = {}
    handlers.update(login.handlers(registry, settings, conn, cfg))
    handlers.update(player.handlers(registry, settings, conn, cfg))
    handlers.update(guide.handlers(registry, settings, conn, cfg))
    handlers.update(gacha.handlers(registry, settings, conn, cfg))
    handlers.update(level.handlers(registry, settings, conn, cfg))
    handlers.update(team.handlers(registry, settings, conn, cfg))
    handlers.update(angel.handlers(registry, settings, conn, cfg))
    handlers.update(hero.handlers(registry, settings, conn, cfg))
    handlers.update(chat.handlers(registry, settings, conn, cfg))
    handlers.update(checkin.handlers(registry, settings, conn, cfg))
    handlers.update(mail.handlers(registry, settings, conn, cfg))
    handlers.update(buy.handlers(registry, settings, conn, cfg))
    handlers.update(shop.handlers(registry, settings, conn, cfg))
    handlers.update(bag.handlers(registry, settings, conn, cfg))
    handlers.update(train.handlers(registry, settings, conn, cfg))
    handlers.update(activity.handlers(registry, settings, conn, cfg))
    handlers.update(events.handlers(registry, settings, conn, cfg))
    handlers.update(goldtrial.handlers(registry, settings, conn, cfg))
    handlers.update(herotrial.handlers(registry, settings, conn, cfg))
    handlers.update(angeltrial.handlers(registry, settings, conn, cfg))
    handlers.update(rune.handlers(registry, settings, conn, cfg))
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
