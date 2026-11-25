"""The new-player guide: 5_2041 SaveGuideIdReq.

The guide sends nothing else. NewGuideManager:check reads
g_roleData.player.guide_id, follows that row jump_id when it has one, and
resumes there, so this one column is what makes the tutorial run once.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.config import Config
from server.net.registry import Registry
from server.net.server import Handler, Session
from server.settings import Settings

log = logging.getLogger("loa.guide")

# BattleEndLayer.lua:1041-1048 sends these after every fight through
# NewGuideManager:check(id, nil, true). With no guide playing, check takes the
# isFirst branch (NewGuideManager.lua:276-288) and skips the nextid test at
# :290-298, so all of them reach the server whatever step the guide is at.
BATTLE_END_GUIDE_IDS = frozenset(
    (10160, 10159, 10290, 10330, 10380, 10500, 10540, 10580)
)


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def save_guide_id(session: Session, req):
        player_id = session.player_id
        if player_id is None:
            row = db.find_player(conn, settings.username)
            player_id = None if row is None else int(row["id"])
        if player_id is None:
            log.warning("5_2041 guide_id %d before any character exists", req.guide_id)
            return registry.message_class("SaveGuideIdRes")(status=1)
        # CLIENT input: NewGuideManager:check resumes by looking the row up, so
        # an id with no new_player_guide_info row would strand the tutorial.
        # Refused, not raised. No monotonicity check: the guide legitimately
        # jumps backwards through jump_id.
        if cfg.guide(int(req.guide_id)) is None:
            log.warning(
                "5_2041 guide_id %d has no new_player_guide_info row, refused",
                req.guide_id,
            )
            return registry.message_class("SaveGuideIdRes")(status=1)
        gid = int(req.guide_id)
        if gid in BATTLE_END_GUIDE_IDS:
            # The test the client skips: a burst id is progress only when it
            # is the saved step itself or that step's nextid.
            saved = int(conn.execute(
                "SELECT guide_id FROM players WHERE id = ?", (player_id,)
            ).fetchone()[0])
            row = cfg.guide(saved)
            if gid != saved and (row is None or int(row["nextid"]) != gid):
                log.info(
                    "5_2041 guide_id %d from the battle-end burst is not the next"
                    " step of %d, not saved", gid, saved,
                )
                return registry.message_class("SaveGuideIdRes")(status=1)
        db.set_guide_id(conn, player_id, gid)
        log.info("guide_id %d saved for player %d", req.guide_id, player_id)
        return registry.message_class("SaveGuideIdRes")(status=0)

    return {(5, 2041): save_guide_id}
