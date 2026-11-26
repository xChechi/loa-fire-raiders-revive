"""QueryMyselfRes and the main-city burst."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta

from server import db
from server.config import Config
from server.modules import angel, breakthrough, events, guide, hero, item, mystery
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.player")

# 5_2039 logs its "nothing to send" line once per process.
_red_point_logged = False

# RPGGame sets g_roleData.cspvpState = 99 as "off season" before it asks.
MAGIC_STATE_OFF_SEASON = 99

SIGNET_DAY_HOUR = 5     # signet buys reset at 05:00 (O-W3-9)


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
        guide_id=guide.REPORTED_AS_FINISHED.get(
            int(row["guide_id"]), int(row["guide_id"])
        ),
    )
    # Optional in the proto, but ClientPlayer:updateData concatenates these
    # into a print, so an absent value kills the Lua VM right after login.
    msg.nobility_level = 0
    msg.nobility_exp = 0
    msg.guild_id = 0
    # LevelManager:readLastLevelInfo: 0 means a fresh account and the client
    # starts the player at the first stage of chapter 1. Otherwise it is the
    # stage entry of the last stage cleared and the client computes the unlock
    # frontier from it.
    msg.last_level = int(row["last_level"])
    # Bits 1-7 claimable, bits 9-15 claimed (RoleData.lua:1699-1713).
    msg.login_award = int(row["login_award"])
    # ClientPlayer.lua:360-363 sets angel_money only when arena_point is present.
    msg.arena_point = int(row["arena_point"])
    msg.angel_money = int(row["angel_money"])
    # LevelManager.lua:427-444: 0 = elite just opened, else the last elite
    # stage cleared, the same contract as last_level.
    msg.last_elite = int(row["last_elite"])
    # Wave 3 A5: the master-dungeon frontier (LevelManager.lua:446-457, the
    # same contract as last_level), the coins of categories 75 and 86, the
    # divine-ruins progress and the artifact smelt points. signet_fight_cnt
    # needs the config and is set by build_query_myself_res.
    msg.last_signet = int(row["last_signet"])
    msg.signet_essence = int(row["signet_essence"])
    msg.pet_money = int(row["pet_money"])
    msg.last_god_level = int(row["last_god_level"])
    msg.last_god_chest = int(row["last_god_chest"])
    msg.is_draw = int(row["god_is_draw"])
    msg.artifact_smelt = int(row["artifact_smelt"])
    # A5b: category 70 reaches the client as guildlevel_point
    # (ClientPlayer.lua:436, gve_money = d.guildlevel_point).
    msg.guildlevel_point = int(row["gve_money"])
    # Everything else required gets the proto2 zero.
    fill_required(msg)
    return msg


def build_daily_stats(
    registry: Registry, row: sqlite3.Row | None = None, today: str | None = None
):
    """`row` is a players row already passed through db.ensure_today, so its
    purchase counters are today's. The Wave 2 counters are reset by their own
    modules on their next write, so here a counter whose day column is not
    `today` (ISO, defaults to the local date) reads 0; nothing is written."""
    msg = registry.message_class("ClientDailyStats")(deadline=_end_of_today())
    if row is not None:
        today = today or date.today().isoformat()
        msg.buy_energy = int(row["buy_energy_used"])
        msg.buy_gold = int(row["buy_gold_used"])
        if row["mystery_day"] == today:
            msg.show_store_times = int(row["mystery_shown"])
            msg.energy_use = int(row["energy_use"])
        if row["gold_trails_day"] == today:
            msg.gold_trails_times = int(row["gold_trails_times"])
        # Signet buys roll at 05:00 (O-W3-9), not with `today`.
        if row["signet_day"] == db.day_key(SIGNET_DAY_HOUR):
            msg.signet_buy_cnt = int(row["signet_buy_cnt"])
    fill_required(msg)
    return msg


def signet_fight_count(cfg: Config, row: sqlite3.Row, now: float) -> int:
    """SIGNET_MAX_CNT minus the fights used, after one fight comes back per
    SIGNET_CNT_RECOVER_CYCLE seconds since signet_cnt_at. Read-only: B5
    settles the recovery into the row when it spends or buys. Bought fights
    are a negative `used` and do not recover (signet.settle_fights)."""
    cap = cfg.variable_int("SIGNET_MAX_CNT", 0)
    used = int(row["signet_cnt_used"])
    cycle = cfg.variable_int("SIGNET_CNT_RECOVER_CYCLE", 0)
    if used > 0 and cycle > 0:
        used = max(0, used - max(0, int(now) - int(row["signet_cnt_at"])) // cycle)
    return cap - used


def build_signet_info(registry: Registry, row: sqlite3.Row):
    """SignetInfo from a signets row; attributes not rolled yet go out empty."""
    msg = registry.message_class("SignetInfo")(
        id=int(row["id"]), entry=int(row["entry"]), level=int(row["level"]),
        equip=int(row["hero"]) != 0,
    )
    for field in ("main_attrs", "sub_attrs"):
        for attr in json.loads(row[field] or "[]"):
            getattr(msg, field).add(
                attr_type=int(attr["attr_type"]), attr_value=float(attr["attr_value"])
            )
    fill_required(msg)
    return msg


def build_client_level(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("ClientLevel")(
        level=int(row["level"]),
        star=int(row["star"]),
        count=int(row["count"]),
        deadline=int(row["deadline"]),
        reset_count=int(row["reset_count"]),
        clean_elite_count=int(row["clean_elite_count"]),
    )
    fill_required(msg)
    return msg


def build_query_myself_res(
    registry: Registry, cfg: Config, conn: sqlite3.Connection, row: sqlite3.Row,
    today: str | None = None,
):
    """`today` is the ISO day the daily counters belong to (injectable for
    tests); it defaults to the server's local date."""
    player_id = int(row["id"])
    today = today or date.today().isoformat()
    db.ensure_today(conn, player_id, today)
    # Monday 05:00 clears the breakthrough scores before the heroes go out.
    breakthrough.ensure_week(conn, player_id, time.time())
    row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    now = int(time.time())
    unread = conn.execute(
        "SELECT 1 FROM mails WHERE player_id = ? AND checked = 0 AND expires > ?"
        " LIMIT 1", (player_id, now),
    ).fetchone()
    msg = registry.message_class("QueryMyselfRes")(
        status=0, guild=0, mail_new=1 if unread else 0
    )
    msg.player.CopyFrom(build_client_player(registry, row))
    msg.player.signet_fight_cnt = signet_fight_count(cfg, row, now)
    msg.stats.CopyFrom(build_daily_stats(registry, row, today))
    for signet_row in conn.execute(
        "SELECT * FROM signets WHERE player_id = ? ORDER BY id", (player_id,)
    ):
        msg.signets.add().CopyFrom(build_signet_info(registry, signet_row))
    # The client counts only paid shop refreshes here (AllShopUI.lua:736-739);
    # a stores row from an older day has had no refresh yet today.
    for store_row in conn.execute(
        "SELECT store, refresh_used FROM stores WHERE player_id = ? AND refresh_day = ?",
        (player_id, today),
    ):
        store, info = int(store_row["store"]), cfg.store(int(store_row["store"]))
        field = f"store_refresh_times_{store}"
        if info is None or field not in msg.stats.DESCRIPTOR.fields_by_name:
            continue
        paid = max(0, int(store_row["refresh_used"]) - int(info["free_refresh"]))
        setattr(msg.stats, field, paid)
    # RoleData:updateData reads d.gold_trails.prize with no nil check, so the
    # sub-message must be present even though both its fields are optional.
    # Both are today's ("今日累计伤害", x02003), so another day reads 0.
    msg.gold_trails.SetInParent()
    gold_today = row["gold_trails_day"] == today
    msg.gold_trails.damage = int(row["gold_trails_best"]) if gold_today else 0
    msg.gold_trails.prize = int(row["gold_trails_prize"]) if gold_today else 0
    for hero_row in db.heroes_of(conn, int(row["id"])):
        msg.heroes.add().CopyFrom(hero.build_client_hero_with_runes(
            registry, cfg, hero_row, hero.runes_of(conn, hero_row), conn=conn
        ))
    for stock in item.build_inventory(registry, conn, int(row["id"])):
        msg.inventory.add().CopyFrom(stock)
    # AngelManager:parseAngel overlays these on its angel_info roster
    # (AngelManager.lua:73-108).
    for angel_row in db.angels_of(conn, player_id):
        msg.angels.add().CopyFrom(angel.build_client_angel(registry, cfg, angel_row))
    for event_row in conn.execute(
        "SELECT entry, progress, done FROM events WHERE player_id = ? AND claimed = 0"
        " ORDER BY entry", (player_id,),
    ):
        event = msg.events.add()
        event.entry = int(event_row["entry"])
        event.cur_progress = int(event_row["progress"])
        event.done = int(event_row["done"])
    for level_row in db.levels_of(conn, player_id):
        msg.levels.add().CopyFrom(build_client_level(registry, level_row))
    for chapter_row in db.chapters_of(conn, player_id):
        chapter = int(chapter_row["chapter"])
        if cfg.chapter(chapter) is None:
            # LevelManager:readBoxInfo would index a nil chapter and kill the VM.
            log.warning("chapter %d is not in chapter_info, not sent", chapter)
            continue
        entry = msg.chapters.add()
        entry.chapter = chapter
        entry.award = int(chapter_row["award"])
    fill_required(msg)
    return msg


def build_bt_cards(registry: Registry, cfg: Config):
    """variables.BT_CARD_AWARD is 100000|950816,100100|950811: entry|drop_id per
    privilege card. RechangeCardPanel:_init builds its reward boxes from exactly
    that key, and RoleData:updateRechangeCardsList measures the repeated field
    with #, so both entries are always sent, owned by nobody yet."""
    res = registry.message_class("QueryBtCardRecordRes")()
    raw = cfg.variable("BT_CARD_AWARD")
    if raw is None or raw == "":
        raise KeyError("variables.BT_CARD_AWARD is missing")
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
        # Energy regenerates lazily, so the cap and the recovered amount are
        # recomputed on the way out instead of on a timer.
        row = db.refresh_energy(conn, cfg, row)
        events.refresh(conn, cfg, registry, None, session.player_id)
        log.info("sending QueryMyselfRes for player id %d", session.player_id)
        res = build_query_myself_res(registry, cfg, conn, row)
        # A merchant whose stay ran out while the player was away is told to
        # leave after the Res: the 5_2022 listener reads g_roleData.player
        # (RPGGame.lua:937-945), which this Res fills.
        mystery.expire(registry, session, row, time.time())
        return res

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

    def level_reporters(session: Session, req):
        """5_2623 LevelReporterQueryReq (DesFlagPanel.lua:62-63): other
        players' clears of a stage. The listener draws cells only `if
        firstReporter` (DesFlagPanel.lua:66-75), so the single player's empty
        answer is harmless (plan B2 Wave 3 A4, O-W3-4)."""
        res = registry.message_class("LevelReporterQueryRes")()
        fill_required(res)
        return res

    def sync_red_point(session: Session, req):
        """5_2039 SyncRedPointReq (GameToolsBtnPanel.lua:102-120, every 60 s
        in the city) has no Res: return None so the server sends nothing and
        stops logging "no handler" (O-W3-4)."""
        global _red_point_logged
        if not _red_point_logged:
            _red_point_logged = True
            log.debug("5_2039 SyncRedPointReq has no Res; nothing to send")
        return None

    return {
        (5, 2005): query_myself,
        (5, 2039): sync_red_point,
        (5, 2317): game_ready,
        (5, 2623): level_reporters,
        (5, 2801): push_messages,
        (5, 2943): bt_cards,
        (153, 2001): magic_state,
        (151, 2041): season_state,
    }
