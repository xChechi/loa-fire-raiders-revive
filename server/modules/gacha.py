"""Hero summon: 5_2121 GachaInfoReq, 5_2123 GachaReq.

The tutorial draws banner 1200000 (guide 10061) and 2400000 (guide 10081);
TavernFace:onBtnClick sends the entry of the card it sits on. gacha_info gives
the cost and the drop id, and the drop id rolls through drop_group / drop_base
exactly like a stage drop.

Every number comes out of gacha_info: cost, cost_type, drop_id, free_times.
Nothing about a banner is hardcoded here, except which two entries are the
single draws (see SINGLE_DRAW_BANNERS).
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from collections.abc import Callable

from server import db
from server.config import Config
from server.modules import drops, events, hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.gacha")

STATUS_OK = 0
STATUS_NOT_ENOUGH_GOLD = 327937      # language.db 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938   # language.db 钻石不足
# language.db 系统内部错误: the banner the client asked for is not in
# gacha_info, or its drop id has no pool at all (3000000 has drop_id 0).
STATUS_INTERNAL_ERROR = 327681

COST_GOLD = 1
COST_DIAMOND = 9

# The two single-draw banners. The client sends only the banner id
# (TavernFace.lua:248/252), and the ten-pulls are their own entries
# (1300000, 2500000; TavernFg.lua:157-161), so "single" is a property of
# the banner. gacha_info has no column for it.
SINGLE_DRAW_BANNERS = {1200000: COST_GOLD, 2400000: COST_DIAMOND}
# The original server scripts the first single draw of each currency through
# variables.db: 188000 is hero 104000, 189000 is hero 210000, which is the
# tutorial team stage 10000 is tuned for.
FIRST_DRAW_VARIABLE = {COST_GOLD: "FIRST_GOLD_GACHA", COST_DIAMOND: "FIRST_DIAMOND_GACHA"}
DRAW_COUNT_COLUMN = {COST_GOLD: "gold_single_draws", COST_DIAMOND: "diamond_single_draws"}

# The supreme card's single draw (TavernFace idx 4). Its free draw is "the
# first draw after 05:00 each day" (z00512 每日5:00后首抽免费,
# Language_cn.lua:696; TavernFace.lua:58-75): the client still sends
# 5_2123 {gacha = 2400000} and only marks the draw free on its side
# (TavernFace.lua:171-191).
SUPREME_SINGLE = 2400000
FREE_DRAW_DAY_HOUR = 5


def _variable(cfg: Config, key: str) -> int:
    """A variables.db value the draw sequence cannot work without."""
    raw = cfg.variable(key)
    if raw is None or raw == "":
        raise KeyError(f"variables.{key} is missing")
    return int(float(raw))


def _supreme_guaranteed(cfg: Config, k: int) -> bool:
    """O-W2-3: 182100 at k = 1 + FIRST_INTERVAL, then every NORMAL_INTERVAL."""
    first = 1 + _variable(cfg, "DIAMOND_SINGLE_GACHA_FIRST_INTERVAL")
    normal = _variable(cfg, "DIAMOND_SINGLE_GACHA_NORMAL_INTERVAL")
    return k >= first and (k - first) % normal == 0


def supreme_single_drop(cfg: Config, k: int, banner_drop: int) -> int:
    """The drop id of the supreme single draw made with k earlier ones."""
    if k == 0:
        return _variable(cfg, FIRST_DRAW_VARIABLE[COST_DIAMOND])
    if k == 1:
        return _variable(cfg, "FIRST_DIAMOND_GACHA_AFTER_NEWGUIDE")
    if _supreme_guaranteed(cfg, k):
        return _variable(cfg, "DIAMOND_GACHA_HERO_GACHA")
    return int(banner_drop)


def supreme_next(cfg: Config, k: int) -> int:
    """GachaInfoRes.next: 0 at k = 1 (the "first draw -> 2-star hero" tip,
    TavernFace4.lua:105-111), otherwise the draws left until the next
    guaranteed k, inclusive ("再抽 N 次必得英雄", TavernFace4.lua:65-79)."""
    if k == 1:
        return 0
    first = 1 + _variable(cfg, "DIAMOND_SINGLE_GACHA_FIRST_INTERVAL")
    normal = _variable(cfg, "DIAMOND_SINGLE_GACHA_NORMAL_INTERVAL")
    if k <= first:
        target = first
    else:
        target = first + -(-(k - first) // normal) * normal
    return target - k + 1


def _counters(cfg: Config, row) -> dict[str, int]:
    """The tavern tip fields both Res carry; TavernUI:synData copies them from
    every GachaRes (TavernUI.lua:190-198)."""
    k = int(row["diamond_single_draws"]) if row is not None else 0
    return {"diamond_gacha": 1 if k >= 1 else 0, "next": supreme_next(cfg, k)}


def build_gacha_info(registry: Registry, cfg: Config, row=None, now: float | None = None):
    res = registry.message_class("GachaInfoRes")(
        status=STATUS_OK, week=0, gold_next=0,
        gold_gacha=0, diamond_ten_gacha=0, **_counters(cfg, row),
    )
    # Open question F of the plan: todays stays empty and week stays 0. The
    # daily/weekly soul counters are not tracked in Plan B1, and TavernBase
    # tolerates their absence.
    for banner in cfg.gachas():
        info = res.gachaInfos.add()
        info.gacha = int(banner["entry"])
        # cooldown drives nothing: every branch that reads it is commented
        # out (TavernUtil.lua:198-207, TavernCD.lua:44-64).
        info.cooldown = 0
        if info.gacha == SUPREME_SINGLE:
            k = int(row["diamond_single_draws"]) if row is not None else 0
            used = row["diamond_free_day"] if row is not None else ""
            # O-W2-2: the tutorial draw (k = 0) never uses the day's free draw.
            free = k == 0 or used != db.day_key(FREE_DRAW_DAY_HOUR, now)
            info.freetimes = 1 if free else 0
        else:
            info.freetimes = int(banner["free_times"] or 0)
    fill_required(res)
    return res


def _required(row, column: str, gacha_id: int) -> int:
    """A gacha_info value the handler cannot work without. Fail loud, naming
    the banner, rather than silently drawing from drop id 0."""
    value = row[column]
    if value is None or value == "":
        raise KeyError(f"gacha_info row {gacha_id} has no {column}")
    return int(value)


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _refused(status: int):
        res = registry.message_class("GachaRes")(status=status)
        fill_required(res)
        return res

    def gacha_info(session: Session, req):
        return build_gacha_info(registry, cfg, _player(session), now_of())

    def gacha(session: Session, req):
        gacha_id = int(req.gacha)
        row = _player(session)
        banner = cfg.gacha(gacha_id)
        if row is None or banner is None:
            log.warning("5_2123 for unknown banner %s", gacha_id)
            return _refused(STATUS_INTERNAL_ERROR)

        cost = _required(banner, "cost", gacha_id)
        cost_type = _required(banner, "cost_type", gacha_id)
        if cost_type not in (COST_GOLD, COST_DIAMOND):
            raise ValueError(
                f"gacha_info row {gacha_id} has cost_type {cost_type},"
                " which is not implemented in Plan B1"
            )
        player_id = int(row["id"])
        drop_id = _required(banner, "drop_id", gacha_id)
        single_draw_column = None
        free_day = None
        supreme = None
        if gacha_id == SUPREME_SINGLE:
            single_draw_column = DRAW_COUNT_COLUMN[COST_DIAMOND]
            k = int(row[single_draw_column])
            drop_id = supreme_single_drop(cfg, k, drop_id)
            today = db.day_key(FREE_DRAW_DAY_HOUR, now_of())
            # O-W2-2: k = 0 is free and keeps the day's free draw; otherwise
            # the first draw of the day is free and uses it up.
            free = k == 0 or row["diamond_free_day"] != today
            if free:
                cost = 0
                if k > 0:
                    free_day = today
            supreme = (k, free)
        elif gacha_id in SINGLE_DRAW_BANNERS:
            single_draw_column = DRAW_COUNT_COLUMN[cost_type]
            if int(row[single_draw_column]) == 0:
                key = FIRST_DRAW_VARIABLE[cost_type]
                scripted = cfg.variable(key)
                if scripted is None or scripted == "":
                    raise KeyError(f"variables.{key} is missing")
                drop_id = int(scripted)
                log.info(
                    "first %s single draw for player %d: drop id %s from"
                    " variables.%s",
                    "gold" if cost_type == COST_GOLD else "diamond",
                    player_id, drop_id, key,
                )
        if cost_type == COST_GOLD and int(row["gold"]) < cost:
            return _refused(STATUS_NOT_ENOUGH_GOLD)
        if cost_type == COST_DIAMOND and int(row["diamond"]) < cost:
            return _refused(STATUS_NOT_ENOUGH_DIAMOND)
        if supreme is not None:
            log.info(
                "supreme single k=%d for player %d: drop %d, free=%s",
                supreme[0], player_id, drop_id, supreme[1],
            )
        rolled = drops.roll(cfg, drop_id, rng=rng)
        if not rolled:
            # TavernUI hands items to g_tools:randomTable, so never answer
            # status 0 with an empty list: fall back to the first row of the
            # first group of this drop id.
            groups = cfg.drop_groups(drop_id)
            rows = cfg.drop_rows(int(groups[0]["drop_group_id"])) if groups else []
            if rows:
                first = rows[0]
                log.warning(
                    "banner %s drop id %s rolled nothing, falling back to its"
                    " first row %s", gacha_id, drop_id, first,
                )
                rolled = [
                    drops.Drop(first["drop_type"], first["item_id"], first["amount"])
                ]
        if not rolled:
            log.warning(
                "banner %s drop id %s has no pool at all, refusing the draw",
                gacha_id, drop_id,
            )
            return _refused(STATUS_INTERNAL_ERROR)

        # The grant runs first: it validates the whole prize list before it
        # writes anything, so a raise in there (unknown category, an item or
        # hero id with no config row) leaves the player's balances untouched
        # instead of charging for prizes that never arrive.
        changed = item.grant_prizes(conn, cfg, player_id, drops.as_triples(rolled))
        if cost or single_draw_column or free_day:
            # Every column name below is a literal from this module, never
            # request data.
            sets, params = [], []
            if cost:
                column = "gold" if cost_type == COST_GOLD else "diamond"
                sets.append(f"{column} = {column} - ?")
                params.append(cost)
            if single_draw_column:
                # Scripted or rolled, a single draw counts; a refusal or a
                # raised grant never gets here.
                sets.append(f"{single_draw_column} = {single_draw_column} + 1")
            if free_day:
                sets.append("diamond_free_day = ?")
                params.append(free_day)
            conn.execute(
                f"UPDATE players SET {', '.join(sets)} WHERE id = ?",
                (*params, player_id),
            )
            conn.commit()
            # grant_prizes read the balances before the charge, so re-read the
            # absolute values the client has to end up with.
            charged = conn.execute(
                "SELECT gold, diamond FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            changed["gold"] = int(charged["gold"])
            changed["diamond"] = int(charged["diamond"])
        after = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        res = registry.message_class("GachaRes")(
            status=STATUS_OK, gold_next=0,
            gold_gacha=0, diamond_ten_gacha=0, **_counters(cfg, after),
        )
        for entry in drops.to_prize_entries(registry, rolled):
            res.items.add().CopyFrom(entry)
        item.mark_converted(res.items, changed)
        item.announce(registry, session, changed)

        for hero_row_id in changed["heroes"]:
            hero_row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (hero_row_id,)
            ).fetchone()
            notify.hero_added(
                registry, session, hero.build_client_hero(registry, cfg, hero_row)
            )
        notify.items_changed(registry, session, changed["items"])
        # grant_prizes returns absolute balances, which is what
        # RoleData:onPlayerInfoChange assigns.
        notify.player_changed(
            registry, session,
            {"gold": changed["gold"], "diamond": changed["diamond"]},
        )
        events.refresh(conn, cfg, registry, session, player_id)
        log.info(
            "banner %s drawn for player %d: %s", gacha_id, player_id,
            [(d.category, d.refer, d.amount) for d in rolled],
        )
        fill_required(res)
        return res

    return {(5, 2121): gacha_info, (5, 2123): gacha}
