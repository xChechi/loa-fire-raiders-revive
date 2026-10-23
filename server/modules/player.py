"""QueryMyselfRes and the main-city burst."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from server import db
from server.config import Config
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.player")

# RPGGame sets g_roleData.cspvpState = 99 as "off season" before it asks.
MAGIC_STATE_OFF_SEASON = 99


def _end_of_today() -> int:
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(tomorrow.timestamp())


def build_client_player(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("ClientPlayer")(
        id=int(row["id"]),
        username=row["username"],
        nickname=row["nickname"],
        level=int(row["level"]),
        xp=int(row["xp"]),
        gold=int(row["gold"]),
        diamond=int(row["diamond"]),
        vip=int(row["vip"]),
        energy=int(row["energy"]),
        max_energy=int(row["max_energy"]),
        avatar=int(row["avatar"]),
        guide_id=int(row["guide_id"]),
    )
    # Optional in the proto, but ClientPlayer:updateData concatenates these
    # into a print, so an absent value kills the Lua VM right after login.
    msg.nobility_level = 0
    msg.nobility_exp = 0
    msg.guild_id = 0
    # Everything else required gets the proto2 zero.
    fill_required(msg)
    return msg


def build_daily_stats(registry: Registry):
    msg = registry.message_class("ClientDailyStats")(deadline=_end_of_today())
    fill_required(msg)
    return msg


def build_query_myself_res(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("QueryMyselfRes")(status=0, guild=0, mail_new=0)
    msg.player.CopyFrom(build_client_player(registry, row))
    msg.stats.CopyFrom(build_daily_stats(registry))
    # RoleData:updateData reads d.gold_trails.prize with no nil check, so the
    # sub-message must be present even though both its fields are optional.
    msg.gold_trails.SetInParent()
    fill_required(msg)
    return msg


def build_bt_cards(registry: Registry, cfg: Config):
    """variables.BT_CARD_AWARD is 100000|950816,100100|950811: entry|drop_id per
    privilege card. RechangeCardPanel:_init builds its reward boxes from exactly
    that key, and RoleData:updateRechangeCardsList measures the repeated field
    with #, so both entries are always sent, owned by nobody yet."""
    res = registry.message_class("QueryBtCardRecordRes")()
    raw = cfg.variable("BT_CARD_AWARD") or ""
    for part in (p for p in raw.split(",") if p):
        entry = int(part.split("|")[0])
        card = res.btCards.add()
        card.entry = entry
        card.isActivation = False
        card.isAward = False
    fill_required(res)
    return res


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _row(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        # Single-player server: the account name is fixed in settings.toml, and
        # the client may legitimately send 5_2005 on a reconnect before 3_2001.
        return db.find_player(conn, settings.username)

    def query_myself(session: Session, req):
        row = _row(session)
        if row is None:
            log.warning("5_2005 before any character exists, answering status 1")
            res = registry.message_class("QueryMyselfRes")(status=1)
            fill_required(res)
            return res
        session.player_id = int(row["id"])
        log.info("sending QueryMyselfRes for player id %d", session.player_id)
        return build_query_myself_res(registry, row)

    def game_ready(session: Session, req):
        return registry.message_class("GameReadyRes")()

    def push_messages(session: Session, req):
        return registry.message_class("QueryMyPushMessageRes")()

    def bt_cards(session: Session, req):
        return build_bt_cards(registry, cfg)

    def magic_state(session: Session, req):
        return registry.message_class("MagicStateRes")(
            match_state=MAGIC_STATE_OFF_SEASON
        )

    def season_state(session: Session, req):
        return registry.message_class("TounamentQuerySeasonStateRes")(
            season_state=0, season_state_end_time=0
        )

    return {
        (5, 2005): query_myself,
        (5, 2317): game_ready,
        (5, 2801): push_messages,
        (5, 2943): bt_cards,
        (153, 2001): magic_state,
        (151, 2041): season_state,
    }
