"""Login and session handlers: 194_2001, 3_2005, 3_2015, 3_2001, 3_2003, 3_2009."""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import datetime

from server import db
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


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection
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
        player_id = db.create_player(conn, username, username, settings.guide_id)
        log.info("created character %r as player id %d", username, player_id)
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
