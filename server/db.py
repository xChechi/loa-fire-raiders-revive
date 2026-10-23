"""The single-player SQLite store. No ORM, one connection, per-request commits."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    nickname   TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    gold       INTEGER NOT NULL DEFAULT 0,
    diamond    INTEGER NOT NULL DEFAULT 0,
    vip        INTEGER NOT NULL DEFAULT 0,
    -- 60 is the client's own level-1 value: table `xp_for_level` in
    -- .stock/assets/res/data/split/xp_for_level.db, row `lvl` = 1, column
    -- `max_energy` = 60 (105 rows, lvl 1..105, max_energy grows by 2 per
    -- level; verified 21-10-2026). Level 1 only, which is all Plan A creates;
    -- Plan B reads the per-level value from config instead of defaulting it.
    energy     INTEGER NOT NULL DEFAULT 60,
    max_energy INTEGER NOT NULL DEFAULT 60,
    avatar     INTEGER NOT NULL DEFAULT 0,
    guide_id   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS heroes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry     INTEGER NOT NULL,
    star      INTEGER NOT NULL DEFAULT 1,
    level     INTEGER NOT NULL DEFAULT 1,
    xp        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS angels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    angel_entry INTEGER NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    exp         INTEGER NOT NULL DEFAULT 0,
    star        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry     INTEGER NOT NULL,
    amount    INTEGER NOT NULL DEFAULT 0
);
"""

# The Plan A schema exactly as it shipped, for the migration test only. Keep it
# frozen: it is the shape a real player.db on disk has before this plan runs.
PLAN_A_SCHEMA_PROBE = """
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    nickname   TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    gold       INTEGER NOT NULL DEFAULT 0,
    diamond    INTEGER NOT NULL DEFAULT 0,
    vip        INTEGER NOT NULL DEFAULT 0,
    energy     INTEGER NOT NULL DEFAULT 60,
    max_energy INTEGER NOT NULL DEFAULT 60,
    avatar     INTEGER NOT NULL DEFAULT 0,
    guide_id   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
"""

# Columns added after Plan A. ALTER TABLE ADD COLUMN only, never a rebuild:
# Stefan's Plan A character must survive. last_level is added here together
# with energy_at so the migration happens once; Task 12 is what uses it.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("players", "energy_at", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "last_level", "INTEGER NOT NULL DEFAULT 0"),
)


def ensure_columns(conn: sqlite3.Connection) -> None:
    for table, column, decl in ADDED_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    ensure_columns(conn)
    return conn


def find_player(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM players WHERE username = ?", (username,)
    ).fetchone()


def create_player(
    conn: sqlite3.Connection, username: str, nickname: str, guide_id: int
) -> int:
    cur = conn.execute(
        "INSERT INTO players (username, nickname, guide_id, created_at)"
        " VALUES (?, ?, ?, ?)",
        (username, nickname, guide_id, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_guide_id(conn: sqlite3.Connection, player_id: int, guide_id: int) -> None:
    conn.execute(
        "UPDATE players SET guide_id = ? WHERE id = ?", (int(guide_id), int(player_id))
    )
    conn.commit()


def refresh_energy(
    conn: sqlite3.Connection, cfg, row: sqlite3.Row, now: int | None = None
) -> sqlite3.Row:
    """Lazy regeneration. variables.PLAYER_ENERGY_RECOVER (1) energy per
    PLAYER_ENERGY_RECOVER_CYCLE (360 s), capped at xp_for_level(level).max_energy.
    The client reads the same two keys for its own notification
    (MyGroupInfoData.lua:131-146); xp_for_level.levelup_recovery_energy is the
    level-up bonus, not the regen rate.

    `now` is injectable so the regeneration is testable without a real clock.
    A Plan A row migrated to energy_at = 0 therefore reads as idle since the
    epoch and fills to its cap on the first refresh, which is what a character
    left alone for weeks would have anyway.
    """
    now = int(time.time()) if now is None else int(now)
    cycle = cfg.variable_int("PLAYER_ENERGY_RECOVER_CYCLE", 360)
    per_cycle = cfg.variable_int("PLAYER_ENERGY_RECOVER", 1)
    # Config returns None for a level it does not know (xp_for_level stops at
    # 105); the stored cap stands in rather than crashing the login.
    level_row = cfg.xp_for_level(int(row["level"]))
    max_energy = int(level_row["max_energy"]) if level_row else int(row["max_energy"])
    energy = int(row["energy"])
    energy_at = int(row["energy_at"])
    cycles = 0 if cycle <= 0 else max(0, (now - energy_at) // cycle)
    if energy < max_energy and cycles:
        energy = min(max_energy, energy + cycles * per_cycle)
        # Only whole cycles are consumed: the remainder carries over.
        energy_at = energy_at + cycles * cycle
    if energy >= max_energy:
        energy = max_energy
        energy_at = now
    conn.execute(
        "UPDATE players SET energy = ?, max_energy = ?, energy_at = ? WHERE id = ?",
        (energy, max_energy, energy_at, int(row["id"])),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
    ).fetchone()


def spend_energy(conn: sqlite3.Connection, player_id: int, amount: int) -> None:
    conn.execute(
        "UPDATE players SET energy = MAX(0, energy - ?) WHERE id = ?",
        (int(amount), int(player_id)),
    )
    conn.commit()


def add_energy(conn: sqlite3.Connection, cfg, player_id: int, amount: int) -> None:
    row = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    level_row = cfg.xp_for_level(int(row["level"]))
    cap = int(level_row["max_energy"]) if level_row else int(row["max_energy"])
    conn.execute(
        "UPDATE players SET energy = MIN(?, energy + ?) WHERE id = ?",
        (cap, int(amount), int(player_id)),
    )
    conn.commit()
