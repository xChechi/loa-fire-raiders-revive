"""The new-player guide: 5_2041 SaveGuideIdReq.

The guide sends nothing else. NewGuideManager:check reads
g_roleData.player.guide_id, follows that row jump_id when it has one, and
resumes there, so this one column is what makes the tutorial run once.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.net.registry import Registry
from server.net.server import Handler, Session
from server.settings import Settings

log = logging.getLogger("loa.guide")


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection
) -> dict[tuple[int, int], Handler]:
    def save_guide_id(session: Session, req):
        player_id = session.player_id
        if player_id is None:
            row = db.find_player(conn, settings.username)
            player_id = None if row is None else int(row["id"])
        if player_id is None:
            log.warning("5_2041 guide_id %d before any character exists", req.guide_id)
            return registry.message_class("SaveGuideIdRes")(status=1)
        db.set_guide_id(conn, player_id, int(req.guide_id))
        log.info("guide_id %d saved for player %d", req.guide_id, player_id)
        return registry.message_class("SaveGuideIdRes")(status=0)

    return {(5, 2041): save_guide_id}
