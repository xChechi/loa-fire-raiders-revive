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
-- One row per (player, item entry): RoleData:updateItemNum looks an item up by
-- entry and the client keeps a single ClientStock for it, so grant_item can
-- upsert on this index.
CREATE UNIQUE INDEX IF NOT EXISTS items_player_entry ON items(player_id, entry);
-- One row per stage the player has played. `star` is the best of every clear
-- (LevelManager:readServerLevelInfo paints the three stars from it) and `count`
-- counts the plays, which is what the daily-limit check reads.
CREATE TABLE IF NOT EXISTS levels (
    player_id         INTEGER NOT NULL REFERENCES players(id),
    level             INTEGER NOT NULL,
    star              INTEGER NOT NULL DEFAULT 0,
    count             INTEGER NOT NULL DEFAULT 0,
    reset_count       INTEGER NOT NULL DEFAULT 0,
    clean_elite_count INTEGER NOT NULL DEFAULT 0,
    deadline          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, level)
);
-- Chapter prize boxes: `award` is the state LevelManager:readBoxInfo paints.
CREATE TABLE IF NOT EXISTS chapters (
    player_id INTEGER NOT NULL REFERENCES players(id),
    chapter   INTEGER NOT NULL,
    award     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, chapter)
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
    ("heroes", "quality", "INTEGER NOT NULL DEFAULT 0"),
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
    conn: sqlite3.Connection,
    username: str,
    nickname: str,
    guide_id: int,
    gold: int = 0,
    diamond: int = 0,
    energy: int = 60,
    max_energy: int = 60,
) -> int:
    cur = conn.execute(
        "INSERT INTO players (username, nickname, guide_id, gold, diamond,"
        " energy, max_energy, energy_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            username, nickname, guide_id, int(gold), int(diamond),
            int(energy), int(max_energy), int(time.time()),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def grant_hero(
    conn: sqlite3.Connection,
    player_id: int,
    entry: int,
    quality: int,
    star: int = 1,
    level: int = 1,
    xp: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO heroes (player_id, entry, quality, star, level, xp)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (int(player_id), int(entry), int(quality), int(star), int(level), int(xp)),
    )
    conn.commit()
    return int(cur.lastrowid)


def grant_item(
    conn: sqlite3.Connection, player_id: int, entry: int, amount: int
) -> int:
    """Upsert on (player_id, entry) and return the new absolute amount.

    The client keeps one ClientStock per item entry (RoleData:updateItemNum
    looks items up by entry), so the server does too.
    """
    conn.execute(
        "INSERT INTO items (player_id, entry, amount) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, entry) DO UPDATE SET amount = amount + ?",
        (int(player_id), int(entry), int(amount), int(amount)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
        (int(player_id), int(entry)),
    ).fetchone()
    return int(row["amount"])


def heroes_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? ORDER BY id", (int(player_id),)
        )
    )


def items_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM items WHERE player_id = ? ORDER BY id", (int(player_id),)
        )
    )


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


def level_progress(
    conn: sqlite3.Connection, player_id: int, level: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = ?",
        (int(player_id), int(level)),
    ).fetchone()


def levels_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM levels WHERE player_id = ? ORDER BY level",
            (int(player_id),),
        )
    )


def upsert_level(
    conn: sqlite3.Connection,
    player_id: int,
    level: int,
    star: int | None = None,
    count_delta: int = 0,
    reset_count: int | None = None,
) -> sqlite3.Row | None:
    """Stars only ever go up; count counts plays."""
    conn.execute(
        "INSERT INTO levels (player_id, level) VALUES (?, ?)"
        " ON CONFLICT(player_id, level) DO NOTHING",
        (int(player_id), int(level)),
    )
    if star is not None:
        conn.execute(
            "UPDATE levels SET star = MAX(star, ?) WHERE player_id = ? AND level = ?",
            (int(star), int(player_id), int(level)),
        )
    if count_delta:
        conn.execute(
            "UPDATE levels SET count = count + ? WHERE player_id = ? AND level = ?",
            (int(count_delta), int(player_id), int(level)),
        )
    if reset_count is not None:
        conn.execute(
            "UPDATE levels SET reset_count = ? WHERE player_id = ? AND level = ?",
            (int(reset_count), int(player_id), int(level)),
        )
    conn.commit()
    return level_progress(conn, player_id, level)


def chapters_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM chapters WHERE player_id = ? ORDER BY chapter",
            (int(player_id),),
        )
    )


def set_chapter_award(
    conn: sqlite3.Connection, player_id: int, chapter: int, award: int
) -> None:
    conn.execute(
        "INSERT INTO chapters (player_id, chapter, award) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, chapter) DO UPDATE SET award = ?",
        (int(player_id), int(chapter), int(award), int(award)),
    )
    conn.commit()


def set_last_level(conn: sqlite3.Connection, player_id: int, level: int) -> None:
    conn.execute(
        "UPDATE players SET last_level = ? WHERE id = ?", (int(level), int(player_id))
    )
    conn.commit()


def add_player_xp(conn: sqlite3.Connection, cfg, player_id: int, amount: int) -> dict:
    """xp_for_level.player_xp_for_next_level is the cost of the next level, and
    levelup_recovery_energy is the energy a level-up hands out (it is not the
    regeneration rate: that is variables.PLAYER_ENERGY_RECOVER)."""
    row = conn.execute("SELECT * FROM players WHERE id = ?", (int(player_id),)).fetchone()
    before = (int(row["level"]), int(row["xp"]), int(row["energy"]), int(row["max_energy"]))
    level, xp, energy, max_energy = before
    while True:
        need_row = cfg.xp_for_level(level)
        if need_row is None:
            break
        need = int(need_row["player_xp_for_next_level"] or 0)
        if need <= 0 or xp + amount < need:
            break
        amount -= need - xp
        xp = 0
        level += 1
        new_row = cfg.xp_for_level(level)
        if new_row is None:
            # The top of xp_for_level (lvl 105): there is no next level to go to.
            level -= 1
            break
        max_energy = int(new_row["max_energy"])
        energy = min(max_energy, energy + int(new_row["levelup_recovery_energy"] or 0))
    xp += amount
    conn.execute(
        "UPDATE players SET level = ?, xp = ?, energy = ?, max_energy = ? WHERE id = ?",
        (level, xp, energy, max_energy, int(player_id)),
    )
    conn.commit()
    after = (level, xp, energy, max_energy)
    return {"before": before, "after": after, "levelled": after[0] != before[0]}


def add_hero_xp(
    conn: sqlite3.Connection, cfg, player_id: int, entries, amount: int
) -> list[tuple[int, int, int]]:
    """One xp grant per hero entry that fought. A hero cannot pass
    xp_for_level(player level).hero_max_level."""
    player = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    caps = cfg.xp_for_level(int(player["level"]))
    cap = int(caps["hero_max_level"]) if caps else 1
    out: list[tuple[int, int, int]] = []
    for entry in {int(e) for e in entries if int(e)}:
        row = conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (int(player_id), entry),
        ).fetchone()
        if row is None:
            continue
        level, xp = int(row["level"]), int(row["xp"]) + int(amount)
        while level < cap:
            need_row = cfg.xp_for_level(level)
            need = int(need_row["hero_xp_for_next_level"] or 0) if need_row else 0
            if need <= 0 or xp < need:
                break
            xp -= need
            level += 1
        conn.execute(
            "UPDATE heroes SET level = ?, xp = ? WHERE id = ?", (level, xp, int(row["id"]))
        )
        out.append((entry, level, xp))
    conn.commit()
    return out
