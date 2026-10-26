"""Campaign stages: 5_2201 LevelIntoReq, 5_2203 LevelOutReq, the chapter star
chest 5_2209, and explicit refusals for 5_2205 sweep and 5_2207 reset.

Wire shape per spec section 4: the server validates the unlock, spends the
energy, rolls 64 randoms and pre-rolls the drops, and the client fights.
LevelIntoRes has no status field (fields: drop, urandom, flag, star), so a
refusal is flag: 1 makes the client float z00224 and reopen the campaign UI,
2 floats z00225 (LevelLine.lua:37-60). The real language.db code goes to the
log, which is the only place it can be said.
"""

from __future__ import annotations

import logging
import random
import sqlite3

from server import db
from server.config import Config
from server.modules import drops, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.level")

# BattleAlthm.MAX_URANDOM_SIZE and SCALE (BattleAlthm.lua:14, 27). Any other
# length makes NewAlgorithm return nil and the battle never starts.
URANDOM_SIZE = 64
URANDOM_SCALE = 10000

FLAG_OK = 0
FLAG_STAGE_CHANGED = 1     # z00224, client reopens the campaign UI
FLAG_MAX_TIMES = 2         # z00225

STATUS_NOT_ENOUGH_ENERGY = 327939   # language.db 体力不足, cannot be delivered on 5_2202
STATUS_STAGE_LOCKED = 328193        # language.db 关卡未开启
STATUS_NOT_ENTERED = 328196         # language.db 没有进入关卡
STATUS_ALREADY_CLAIMED = 328194     # language.db 关卡不可重复刷
STATUS_NOT_ENOUGH_STARS = 328197    # language.db 星级不够
STATUS_RESET_LIMIT = 328202         # language.db 达到关卡重置限制

PENDING_KEY = "level_pending"

_default_rng = random.SystemRandom()


def roll_urandom(rng: random.Random | None = None) -> list[int]:
    rng = _default_rng if rng is None else rng
    return [rng.randrange(URANDOM_SCALE) for _ in range(URANDOM_SIZE)]


def frontier(cfg: Config, row: sqlite3.Row) -> int:
    """The one stage the player may newly clear."""
    last = int(row["last_level"])
    return cfg.next_stage(last) if last else cfg.first_stage()


def is_unlocked(
    cfg: Config, conn: sqlite3.Connection, row: sqlite3.Row, lvl: int
) -> bool:
    if lvl == frontier(cfg, row):
        return True
    return db.level_progress(conn, int(row["id"]), lvl) is not None


def chapter_stars(
    cfg: Config, conn: sqlite3.Connection, player_id: int, chapter: int
) -> int:
    """The stars the player holds across one chapter's stages."""
    entries = {int(r["entry"]) for r in cfg.stages_in_chapter(chapter)}
    return sum(
        int(r["star"]) for r in db.levels_of(conn, player_id)
        if int(r["level"]) in entries
    )


def _required(stage: sqlite3.Row, column: str, lvl: int) -> int:
    """A stage_info value the handler cannot work without. A stage the client
    invented is a refusal; a stage the config knows but cannot describe is a
    config gap, and those fail loud naming the entry (Task 11 rule)."""
    value = stage[column]
    if value is None or value == "":
        raise KeyError(f"stage_info row {lvl} has no {column}")
    return int(value)


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _refused(flag: int, star: int = 0):
        res = registry.message_class("LevelIntoRes")(flag=flag, star=star)
        fill_required(res)
        return res

    def level_into(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        if row is None or stage is None:
            log.warning(
                "5_2201 for stage %d: no such stage (%d)", lvl, STATUS_STAGE_LOCKED
            )
            return _refused(FLAG_STAGE_CHANGED)
        session.player_id = int(row["id"])
        row = db.refresh_energy(conn, cfg, row)
        progress = db.level_progress(conn, int(row["id"]), lvl)

        if not is_unlocked(cfg, conn, row, lvl):
            log.warning("5_2201 stage %d is locked (%d)", lvl, STATUS_STAGE_LOCKED)
            return _refused(FLAG_STAGE_CHANGED)
        if progress is not None and int(stage["once"] or 0) == 1 and int(
            progress["star"]
        ) > 0:
            log.info("5_2201 stage %d is a once-only stage already cleared", lvl)
            return _refused(FLAG_STAGE_CHANGED, star=int(progress["star"]))
        maxcount = int(stage["maxcount"] or 0)
        if maxcount and progress is not None and int(progress["count"]) >= maxcount:
            return _refused(FLAG_MAX_TIMES, star=int(progress["star"]))

        cost = _required(stage, "energy", lvl)
        if int(row["energy"]) < cost:
            log.warning(
                "5_2201 stage %d needs %d energy, player has %d; the client cannot be "
                "told status %d on 5_2202 (no status field), answering flag 1",
                lvl, cost, int(row["energy"]), STATUS_NOT_ENOUGH_ENERGY,
            )
            return _refused(
                FLAG_STAGE_CHANGED, star=0 if progress is None else int(progress["star"])
            )

        # Past here nothing can refuse, so the writes are safe to make.
        if cost:
            db.spend_energy(conn, int(row["id"]), cost)
        visible = drops.roll(cfg, _required(stage, "visible_drops", lvl), rng=rng)
        invisible = drops.roll(cfg, _required(stage, "invisible_drops", lvl), rng=rng)
        # One flat list for the whole entry: level_out grants it all at once.
        rolled = visible + invisible
        session.data.setdefault(PENDING_KEY, {})[lvl] = rolled

        res = registry.message_class("LevelIntoRes")(flag=FLAG_OK, star=0)
        for value in roll_urandom(rng):
            res.urandom.append(value)
        # Only the visible roll goes out on entry: FightData.drops (FightData.lua:33)
        # are the items that visibly fall during the fight. The full list, visible
        # plus invisible, reaches the end screen from LevelOutRes.drop
        # (BattleFactoryLevel:forceResult).
        for entry in drops.to_prize_entries(registry, visible):
            res.drop.add().CopyFrom(entry)
        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        notify.player_changed(registry, session, {"energy": int(fresh["energy"])})
        log.info(
            "stage %d entered by player %d, %d energy spent, visible drops %s,"
            " invisible %s",
            lvl, int(row["id"]), cost, drops.as_triples(visible),
            drops.as_triples(invisible),
        )
        fill_required(res)
        return res

    def level_out(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        pending = session.data.get(PENDING_KEY, {})
        if row is None or stage is None:
            res = registry.message_class("LevelOutRes")(status=STATUS_STAGE_LOCKED)
            fill_required(res)
            return res
        if lvl not in pending:
            log.warning(
                "5_2203 for stage %d with no matching 5_2201 on this session, "
                "answering %d", lvl, STATUS_NOT_ENTERED,
            )
            res = registry.message_class("LevelOutRes")(status=STATUS_NOT_ENTERED)
            fill_required(res)
            return res

        # Popped before anything is granted: the client retries 5_2203 twice
        # more after a 6 s timeout (BattleFactoryBase.lua:871-930).
        rolled = pending.pop(lvl)
        player_id = int(row["id"])
        star = max(0, min(3, int(req.star)))
        won = star > 0

        granted = {"gold": int(row["gold"]), "diamond": int(row["diamond"]), "items": []}
        hero_xp: list[tuple[int, int, int]] = []
        xp_change = {"before": None, "after": None, "levelled": False}
        prizes: list[tuple[int, int, int]] = []
        if won:
            prizes = drops.as_triples(rolled)
            prizes.append((item.CATEGORY_GOLD, 0, int(stage["gold"] or 0)))
            # grant_prizes vets the whole list before it writes anything, so it
            # runs before this handler's own irreversible writes (Task 11). If
            # it raises, the pending entry goes back and the retry can replay.
            try:
                granted = item.grant_prizes(conn, cfg, player_id, prizes)
            except Exception:
                pending[lvl] = rolled
                raise

        # Past this line the drops are paid and the pending entry is already
        # popped. Putting it back would re-pay them on the client's retry, and a
        # transaction across these four writes is Plan B2, so the only honest
        # answer to a failure here is an ERROR carrying every fact needed to
        # repair the row by hand, and the exception going up.
        try:
            db.upsert_level(conn, player_id, lvl, star=star, count_delta=1)
            if won:
                xp_change = db.add_player_xp(
                    conn, cfg, player_id, int(stage["player_xp"] or 0)
                )
                hero_xp = db.add_hero_xp(
                    conn, cfg, player_id, list(req.heroes), int(stage["unit_xp"] or 0)
                )
                if lvl == frontier(cfg, row):
                    db.set_last_level(conn, player_id, lvl)
        except Exception:
            log.error(
                "stage %d: payout granted to player %d (star %d, prizes %s) but a"
                " later write failed; the stage is paid and NOT recorded",
                lvl, player_id, star, prizes, exc_info=True,
            )
            raise

        res = registry.message_class("LevelOutRes")(status=0, star=star)

        if won:
            for entry in drops.to_prize_entries(registry, rolled):
                res.drop.add().CopyFrom(entry)
            gold_entry = res.drop.add()
            gold_entry.category = item.CATEGORY_GOLD
            gold_entry.refer = 0
            gold_entry.amount = int(stage["gold"] or 0)

        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        # BattleEndLayer reads owner.xp and owner.level; refer is unused there.
        res.owner.refer = player_id
        res.owner.level = int(fresh["level"])
        res.owner.xp = int(fresh["xp"])
        for entry, hlevel, hxp in hero_xp:
            # refer is the hero entry: toExpInfo keys heroes by v.refer and
            # BattleEndLayer looks them up by the unit entry.
            client_xp = res.heroes.add()
            client_xp.refer = entry
            client_xp.level = hlevel
            client_xp.xp = hxp

        if won:
            notify.items_changed(registry, session, granted["items"])
            notify.player_changed(registry, session, {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "xp": int(fresh["xp"]), "level": int(fresh["level"]),
                "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
                "last_level": int(fresh["last_level"]),
            })
            if xp_change["levelled"]:
                before = xp_change["before"]
                after = xp_change["after"]
                notify.level_up(
                    registry, session,
                    (before[0], before[2], before[3]), (after[0], after[2], after[3]),
                )
        log.info(
            "stage %d finished by player %d with %d star(s), won=%s", lvl, player_id,
            star, won,
        )
        fill_required(res)
        return res

    def chapter_prize(session: Session, req):
        chapter = int(req.chapter)
        row = _player(session)
        info = cfg.chapter(chapter)
        if row is None or info is None:
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_STAGE_LOCKED, chapter=chapter
            )
            fill_required(res)
            return res
        player_id = int(row["id"])
        claimed = {
            int(c["chapter"]): int(c["award"]) for c in db.chapters_of(conn, player_id)
        }
        if claimed.get(chapter):
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_ALREADY_CLAIMED, chapter=chapter
            )
            fill_required(res)
            return res
        # The threshold is chapter_info.star_req0, never a literal: chapter 1
        # has 5 stages, so 15 stars are on offer and the chest asks for 9.
        need = int(info["star_req0"] or 0)
        have = chapter_stars(cfg, conn, player_id, chapter)
        if have < need:
            log.info(
                "chapter %d chest needs %d stars, player has %d", chapter, need, have
            )
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_NOT_ENOUGH_STARS, chapter=chapter
            )
            fill_required(res)
            return res

        # grant_prizes vets the whole list before it writes, so it runs before
        # the irreversible set_chapter_award (Task 11 lesson): an award that
        # cannot be paid leaves the chest claimable.
        rolled = drops.roll(cfg, int(info["award0"] or 0), rng=rng)
        granted = item.grant_prizes(conn, cfg, player_id, drops.as_triples(rolled))
        db.set_chapter_award(conn, player_id, chapter, 1)
        notify.items_changed(registry, session, granted["items"])
        notify.player_changed(registry, session, {
            "gold": granted["gold"], "diamond": granted["diamond"],
        })
        log.info(
            "chapter %d chest paid to player %d: %s", chapter, player_id,
            drops.as_triples(rolled),
        )
        # The client renders the reward panel itself from chapter_info.award0;
        # it only needs status 0 and the chapter back (LevelBoxStarPanel.lua:78).
        res = registry.message_class("LevelChapterPrizeRes")(status=0, chapter=chapter)
        fill_required(res)
        return res

    def level_clean(session: Session, req):
        # Sweep is not in Plan B1. LevelCleanRes field 1 is flag, not status, so
        # this cannot float an error text; flag 2 is the client's own "max
        # times". The handler exists so the log is honest about the refusal
        # instead of the zero stub claiming success.
        log.info("5_2205 sweep of stage %s is not implemented in Plan B1", req.level)
        res = registry.message_class("LevelCleanRes")(flag=FLAG_MAX_TIMES, times=0)
        fill_required(res)
        return res

    def level_reset(session: Session, req):
        # Reset is not in Plan B1 either; 328202 floats 达到关卡重置限制 and
        # DesBuyPanel:onReset ignores the rest.
        log.info("5_2207 reset of stage %s is not implemented in Plan B1", req.level)
        res = registry.message_class("LevelResetRes")(
            status=STATUS_RESET_LIMIT, reset_count=0
        )
        fill_required(res)
        return res

    return {
        (5, 2201): level_into,
        (5, 2203): level_out,
        (5, 2205): level_clean,
        (5, 2207): level_reset,
        (5, 2209): chapter_prize,
    }
