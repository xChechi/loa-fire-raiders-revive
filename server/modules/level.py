"""Campaign stages: 5_2201 LevelIntoReq (and, from Task 14, 5_2203 and friends).

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
from server.modules import drops, notify
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
        rolled = drops.roll(cfg, _required(stage, "visible_drops", lvl), rng=rng)
        rolled += drops.roll(cfg, _required(stage, "invisible_drops", lvl), rng=rng)
        session.data.setdefault(PENDING_KEY, {})[lvl] = rolled

        res = registry.message_class("LevelIntoRes")(flag=FLAG_OK, star=0)
        for value in roll_urandom(rng):
            res.urandom.append(value)
        for entry in drops.to_prize_entries(registry, rolled):
            res.drop.add().CopyFrom(entry)
        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        notify.player_changed(registry, session, {"energy": int(fresh["energy"])})
        log.info(
            "stage %d entered by player %d, %d energy spent, drops %s",
            lvl, int(row["id"]), cost, drops.as_triples(rolled),
        )
        fill_required(res)
        return res

    return {(5, 2201): level_into}
