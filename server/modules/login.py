"""Login and session handlers: 194_2001, 3_2005, 3_2015, 3_2001, 3_2003, 3_2009."""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import datetime

from server import db
from server.config import Config
from server.net.registry import Registry
from server.net.server import Handler, Session
from server.settings import Settings

log = logging.getLogger("loa.login")

STATUS_OK = 0
# LoginSocketData:loginReceiveHdr reads this value as "this account has no
# character yet" and answers with GameplayReq — but only if it ever sees it.
# It does not: on 21-10-2026 the emulator's own dump printed
# `"status" = 327682` for our LoginRes and the handler still took its
# `rs.status == 0` branch (docs/protocol.md, open question 1). Kept as the
# documented value of the status the server cannot deliver; not sent.
STATUS_NO_ROLE = 327682


def _tz_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return 0 if offset is None else int(offset.total_seconds())


def _variable(cfg: Config, key: str) -> str:
    """A variables.db value, or a failure that names the key.

    A silently empty kit is worse than a crash at creation time: the character
    would exist with no gold and no hero, and LineFrame:startFight refuses to
    start a stage with no hero on the field.
    """
    raw = cfg.variable(key)
    if raw is None or raw == "":
        raise KeyError(f"variables.{key} is missing from the client config")
    return raw


def _variable_int(cfg: Config, key: str) -> int:
    _variable(cfg, key)  # presence first, so a missing key names itself
    return cfg.variable_int(key, 0)


def starting_kit(cfg: Config) -> dict:
    """Everything a fresh character owns, from variables.db."""
    items: list[tuple[int, int]] = []
    for part in (p for p in _variable(cfg, "PLAYER_ITEMS_INIT").split(",") if p):
        entry, _, amount = part.partition("|")
        items.append((int(entry), int(amount or 1)))
    hero_entry = _variable_int(cfg, "HERO_FIRST_ENTRY")
    # The lowest hero_quality row, not hero_info.quality: hero 100000 reads
    # quality 0 there, and a quality with no hero_quality row crashes
    # ClientHero:getNpcProperty on the client.
    qualities = cfg.hero_qualities(hero_entry)
    if not qualities:
        raise KeyError(f"hero_quality has no row for hero {hero_entry}")
    return {
        "gold": _variable_int(cfg, "HERO_GOLD_INIT"),
        "diamond": _variable_int(cfg, "HERO_DIAMOND_INIT"),
        "energy": _variable_int(cfg, "ENERGY_INIT"),
        "max_energy": _variable_int(cfg, "ENERGY_MAX_INIT"),
        "hero_entry": hero_entry,
        "hero_quality": int(qualities[0]["quality"]),
        "items": items,
    }


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def srv_info(session: Session, req):
        log.info("server info asked for server_id=%r", req.server_id)
        # Live port from the Session, never settings.port: tests bind port 0 and
        # the fake client of Task 15 really dials this address.
        return registry.message_class("QuerySrvInfoRes")(
            district=1, addr=f"{settings.host}:{session.bound_port}"
        )

    def protocol(session: Session, req):
        # CONFIG_DEVELOP=1 makes the client ignore both halves; it only splits
        # on the colon, so the colon is the whole contract.
        return registry.message_class("ProtocolRes")(
            issue_required=f"{req.issue}:0"
        )

    def srv_state(session: Session, req):
        return registry.message_class("QuerySrvStateRes")(
            state=0, time_zone_offset=_tz_offset_seconds()
        )

    def _session_fields(cls_name: str, status: int, token: str):
        return registry.message_class(cls_name)(
            status=status,
            token=token,
            session=random.randrange(1, 2**31),
            time_zone_offset=_tz_offset_seconds(),
            timestamp=int(time.time()),
        )

    def _player_id(sent_username: str) -> int:
        # One player, one account: the name is settings.toml's, never the
        # client's. A client reconnecting after a server restart sends an empty
        # username, and with the name taken from the request that minted a
        # second, nameless character (seen live 21-10-2026).
        username = settings.username
        if sent_username != username:
            log.info("login as %r, serving the %r account", sent_username, username)
        row = db.find_player(conn, username)
        if row is not None:
            return int(row["id"])
        kit = starting_kit(cfg)
        player_id = db.create_player(
            conn, username, username, settings.guide_id,
            gold=kit["gold"], diamond=kit["diamond"],
            energy=kit["energy"], max_energy=kit["max_energy"],
        )
        db.grant_hero(
            conn, player_id, kit["hero_entry"], kit["hero_quality"], star=1, level=1
        )
        for entry, amount in kit["items"]:
            db.grant_item(conn, player_id, entry, amount)
        log.info(
            "created character %r as player id %d with hero %d, %d gold, %d diamonds",
            username, player_id, kit["hero_entry"], kit["gold"], kit["diamond"],
        )
        return player_id

    def login(session: Session, req):
        # STATUS_NO_ROLE never reaches the client's gate, so the server creates
        # the character itself rather than wait for a 3_2003 that never comes.
        session.player_id = _player_id(req.username)
        log.info("login ok, player id %d", session.player_id)
        return _session_fields("LoginRes", STATUS_OK, req.token)

    def gameplay(session: Session, req):
        session.player_id = _player_id(req.username)
        return _session_fields("GameplayRes", STATUS_OK, req.token)

    def heartbeat(session: Session, req):
        return registry.message_class("HeartbeatRes")(
            status=STATUS_OK, time=int(time.time())
        )

    return {
        (194, 2001): srv_info,
        (3, 2005): protocol,
        (3, 2015): srv_state,
        (3, 2001): login,
        (3, 2003): gameplay,
        (3, 2009): heartbeat,
    }
