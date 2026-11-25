"""The single-player SQLite store. No ORM, one connection, per-request commits."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("loa.db")

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
-- One angel per entry: AngelManager keys its roster by angel_entry.
CREATE UNIQUE INDEX IF NOT EXISTS angels_player_entry ON angels(player_id, angel_entry);
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
-- Wave 1 (Plan B2). `attachments` is a JSON list of prize triples.
CREATE TABLE IF NOT EXISTS mails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    entry       INTEGER NOT NULL DEFAULT 0,
    sender      TEXT    NOT NULL DEFAULT '',
    subject     TEXT    NOT NULL DEFAULT '',
    body        TEXT    NOT NULL DEFAULT '',
    attachments TEXT    NOT NULL DEFAULT '[]',
    created     INTEGER NOT NULL DEFAULT 0,
    expires     INTEGER NOT NULL DEFAULT 0,
    checked     INTEGER NOT NULL DEFAULT 0,
    claimed     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS checkins (
    player_id    INTEGER PRIMARY KEY REFERENCES players(id),
    month        INTEGER NOT NULL DEFAULT 0,
    normal_flags INTEGER NOT NULL DEFAULT 0,
    vip_flags    INTEGER NOT NULL DEFAULT 0,
    append_used  INTEGER NOT NULL DEFAULT 0,
    total_times  INTEGER NOT NULL DEFAULT 0,
    total_award  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry     INTEGER NOT NULL,
    progress  INTEGER NOT NULL DEFAULT 0,
    done      INTEGER NOT NULL DEFAULT 0,
    claimed   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, entry)
);
-- `slots` is a JSON list of the store's merchandise slots.
CREATE TABLE IF NOT EXISTS stores (
    player_id    INTEGER NOT NULL REFERENCES players(id),
    store        INTEGER NOT NULL,
    lastupdate   INTEGER NOT NULL DEFAULT 0,
    slots        TEXT    NOT NULL DEFAULT '[]',
    refresh_used INTEGER NOT NULL DEFAULT 0,
    refresh_day  TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (player_id, store)
);
-- Wave 2 A4: one row per opened training slot (train_info.entry). refer_type
-- 1 hero / 2 angel, refer_id the hero or angel entry (0 = empty); cal_time
-- is the epoch the passive xp is settled up to, addxp the xp settled since
-- the last op-2 query (O-W2-8, O-W2-10).
CREATE TABLE IF NOT EXISTS trains (
    player_id  INTEGER NOT NULL REFERENCES players(id),
    train      INTEGER NOT NULL,
    quality    INTEGER NOT NULL DEFAULT 1,
    refer_type INTEGER NOT NULL DEFAULT 0,
    refer_id   INTEGER NOT NULL DEFAULT 0,
    cal_time   INTEGER NOT NULL DEFAULT 0,
    addxp      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, train)
);
-- Wave 2 A6 (B7): one row per levelled rune; idx 0..4 is the hero_rune_info
-- column rune0..rune4. A missing row is a level-0 rune with no rune_val.
CREATE TABLE IF NOT EXISTS runes (
    player_id INTEGER NOT NULL REFERENCES players(id),
    hero      INTEGER NOT NULL,
    idx       INTEGER NOT NULL,
    level     INTEGER NOT NULL DEFAULT 0,
    rune_val  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, hero, idx)
);
-- Wave 2 A6 (B6): the angel-trials tower, one row per player, reset at
-- day_key(ANGELTRIALS_RANK_TIME). The JSON columns follow stores.slots.
CREATE TABLE IF NOT EXISTS angeltrials (
    player_id          INTEGER PRIMARY KEY REFERENCES players(id),
    opened             INTEGER NOT NULL DEFAULT 0,
    level              INTEGER NOT NULL DEFAULT 0,
    points             INTEGER NOT NULL DEFAULT 0,
    stars              INTEGER NOT NULL DEFAULT 0,
    crash_level        INTEGER NOT NULL DEFAULT 0,
    treasure_cum_count INTEGER NOT NULL DEFAULT 0,
    flag               INTEGER NOT NULL DEFAULT 0,
    day                TEXT    NOT NULL DEFAULT '',
    buffs              TEXT    NOT NULL DEFAULT '[]',
    units              TEXT    NOT NULL DEFAULT '[]',
    pending            TEXT    NOT NULL DEFAULT '{}'
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
    # Single-draw counters, not flags: the stock interval rules
    # (GOLD_SINGLE_GACHA_NORMAL_INTERVAL and friends) are expressed in draw
    # counts, so Plan B2 reads the same two columns. A migrated Plan A/B1 row
    # starts at 0 and therefore gets the scripted tutorial draw once more on
    # its next single draw; that is accepted (the emulator re-run starts from a
    # fresh data/player.db per the Task 17 ruling).
    ("players", "gold_single_draws", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "diamond_single_draws", "INTEGER NOT NULL DEFAULT 0"),
    # Wave 1 (Plan B2): six gear slots per hero (ClientHero.items, item0..item5
    # in HERO_FIELDS), the 7-day login gift bits, and the daily purchase
    # counters that ensure_today zeroes on a new ISO day.
    ("heroes", "item0", "INTEGER NOT NULL DEFAULT 0"),
    ("heroes", "item1", "INTEGER NOT NULL DEFAULT 0"),
    ("heroes", "item2", "INTEGER NOT NULL DEFAULT 0"),
    ("heroes", "item3", "INTEGER NOT NULL DEFAULT 0"),
    ("heroes", "item4", "INTEGER NOT NULL DEFAULT 0"),
    ("heroes", "item5", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "login_award", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "login_days", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "last_login_day", "TEXT NOT NULL DEFAULT ''"),
    ("players", "daily_day", "TEXT NOT NULL DEFAULT ''"),
    ("players", "buy_energy_used", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "buy_gold_used", "INTEGER NOT NULL DEFAULT 0"),
    # Prize categories 51 (arena coin) and 52 (goddess-trial coin),
    # ClientPlayer.lua:35-37,150-151: login gift days 5 and 3 pay them.
    ("players", "arena_point", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "angel_money", "INTEGER NOT NULL DEFAULT 0"),
    # Wave 2 A1: the day_key(5) of the last free supreme draw (O-W2-1).
    ("players", "diamond_free_day", "TEXT NOT NULL DEFAULT ''"),
    # Wave 2 A2: supreme ten-pulls made; 0 rolls FIRST_TEN_TIMES_DIAMOND_GACHA.
    ("players", "diamond_ten_draws", "INTEGER NOT NULL DEFAULT 0"),
    # Wave 2 A3: skill levels, not ids (O-W2-6); hero.spell_at_level resolves
    # the id from the current prototype's base, so a level survives quality-up.
    ("heroes", "spell0_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("heroes", "spell1_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("heroes", "spell2_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("heroes", "spell3_lv", "INTEGER NOT NULL DEFAULT 1"),
    # Wave 2 A6, the Phase B groundwork. B2: the last elite stage cleared
    # (ClientPlayer.last_elite, LevelManager.lua:427-444).
    ("players", "last_elite", "INTEGER NOT NULL DEFAULT 0"),
    # B3, O-W2-11: energy spent since the last appearance, the appearance
    # epoch and its stay, and the day the two daily counters below belong to
    # (ClientDailyStats.show_store_times = mystery_shown, energy_use).
    ("players", "mystery_energy", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "mystery_appear", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "mystery_stay", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "mystery_day", "TEXT NOT NULL DEFAULT ''"),
    ("players", "mystery_shown", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "energy_use", "INTEGER NOT NULL DEFAULT 0"),
    # B4: runs today, today's damage ("今日累计伤害", x02003: the client adds
    # each run's damage, AssistantData.lua:658), the prize-ladder bits
    # (RoleData.lua:819-830) and the day all three belong to.
    ("players", "gold_trails_times", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "gold_trails_best", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "gold_trails_prize", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "gold_trails_day", "TEXT NOT NULL DEFAULT ''"),
    # B5: runs per vocation today and the epoch each cooldown ends.
    ("players", "herotrials_zs", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_fs", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_ss", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_zs_cd", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_fs_cd", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_ss_cd", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "herotrials_day", "TEXT NOT NULL DEFAULT ''"),
    # B1, O-W2-6: angel spell and aura levels, not ids.
    ("angels", "spell0_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "spell1_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura0_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura1_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura2_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura3_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura4_lv", "INTEGER NOT NULL DEFAULT 1"),
    ("angels", "aura5_lv", "INTEGER NOT NULL DEFAULT 1"),
    # E2: the day_key(5) a daily-task row's progress belongs to.
    ("events", "day", "TEXT NOT NULL DEFAULT ''"),
)


def day_key(hour: int, now: float | None = None) -> str:
    """The local ISO date of `now` minus `hour` hours: the day a daily counter
    belongs to when the day starts at hour:00 (O-W2-1, 05:00 for the free
    draw, daily tasks and angel trials)."""
    now = time.time() if now is None else float(now)
    return datetime.fromtimestamp(now - int(hour) * 3600).date().isoformat()


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


def take_item(
    conn: sqlite3.Connection, player_id: int, entry: int, amount: int
) -> int:
    """Remove `amount` of an item and return the new absolute amount. Raises
    ValueError, writing nothing, when fewer are owned; callers check first and
    refuse with 327942. A row that reaches 0 is deleted: the client drops a
    stock at 0 (RoleData:updateItemNum, RoleData.lua:1275-1287) but would list
    a 0-amount ClientStock sent at login (RoleData.lua:1021-1024)."""
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
        (int(player_id), int(entry)),
    ).fetchone()
    have = int(row["amount"]) if row else 0
    if int(amount) < 0 or have < int(amount):
        raise ValueError(f"item {entry}: have {have}, need {amount}")
    if have == int(amount):
        conn.execute(
            "DELETE FROM items WHERE player_id = ? AND entry = ?",
            (int(player_id), int(entry)),
        )
    else:
        conn.execute(
            "UPDATE items SET amount = amount - ? WHERE player_id = ? AND entry = ?",
            (int(amount), int(player_id), int(entry)),
        )
    conn.commit()
    return have - int(amount)


def spend(
    conn: sqlite3.Connection, player_id: int, gold: int = 0, diamond: int = 0
) -> None:
    """Take gold and diamonds together. Raises ValueError, writing nothing, when
    either balance is too low."""
    row = conn.execute(
        "SELECT gold, diamond FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    if row is None:
        raise ValueError(f"player {player_id} not found")
    if int(gold) < 0 or int(diamond) < 0:
        raise ValueError(f"negative spend gold {gold} diamond {diamond}")
    if int(row["gold"]) < int(gold) or int(row["diamond"]) < int(diamond):
        raise ValueError(
            f"player {player_id}: gold {row['gold']}/{gold},"
            f" diamond {row['diamond']}/{diamond}"
        )
    conn.execute(
        "UPDATE players SET gold = gold - ?, diamond = diamond - ? WHERE id = ?",
        (int(gold), int(diamond), int(player_id)),
    )
    conn.commit()


def ensure_today(conn: sqlite3.Connection, player_id: int, today_iso: str) -> None:
    """On the first call of a new day (ISO YYYY-MM-DD), zero the daily purchase
    counters. Later calls the same day change nothing."""
    conn.execute(
        "UPDATE players SET buy_energy_used = 0, buy_gold_used = 0, daily_day = ?"
        " WHERE id = ? AND daily_day != ?",
        (str(today_iso), int(player_id), str(today_iso)),
    )
    conn.commit()


def set_hero_items(conn: sqlite3.Connection, hero_id: int, items: list[int]) -> None:
    """Write the six gear slots item0..item5 of one heroes row."""
    values = [int(v) for v in items]
    if len(values) != 6:
        raise ValueError(f"a hero has six gear slots, got {len(values)}")
    conn.execute(
        "UPDATE heroes SET item0 = ?, item1 = ?, item2 = ?, item3 = ?, item4 = ?,"
        " item5 = ? WHERE id = ?",
        (*values, int(hero_id)),
    )
    conn.commit()


def angels_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM angels WHERE player_id = ? ORDER BY id", (int(player_id),)
        )
    )


def grant_angel(
    conn: sqlite3.Connection, player_id: int, entry: int, level: int, star: int
) -> int:
    """Insert one angel. The (player_id, angel_entry) index makes a second grant
    of the same entry raise sqlite3.IntegrityError."""
    cur = conn.execute(
        "INSERT INTO angels (player_id, angel_entry, level, exp, star)"
        " VALUES (?, ?, ?, 0, ?)",
        (int(player_id), int(entry), int(level), int(star)),
    )
    conn.commit()
    return int(cur.lastrowid)


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


def add_angel_xp(
    conn: sqlite3.Connection, cfg, player_id: int, angel_entry: int, amount: int
) -> tuple[int, int] | None:
    """stage_info.angel_xp for the fielded angel, levelled through
    xp_for_level.angel_xp_for_next_level and capped at angel_info.max_level.
    LevelOutReq.angel is the angel_entry (BattleFactoryLevel.lua:361-369),
    0 when none fought. Returns the new (level, exp), or None for no angel."""
    if not angel_entry:
        return None
    row = conn.execute(
        "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
        (player_id, angel_entry),
    ).fetchone()
    if row is None:
        log.warning(
            "5_2203 names angel %d, which player %d does not own; no angel xp",
            angel_entry, player_id,
        )
        return None
    info = cfg.angel_by_star(angel_entry, int(row["star"]))
    if info is None:
        raise KeyError(
            f"angel_info has no row for angel {angel_entry} star {row['star']}"
        )
    cap = int(info["max_level"])
    level, exp = int(row["level"]), int(row["exp"]) + int(amount)
    while level < cap:
        need_row = cfg.xp_for_level(level)
        need = int(need_row["angel_xp_for_next_level"] or 0) if need_row else 0
        if need <= 0 or exp < need:
            break
        exp -= need
        level += 1
    conn.execute(
        "UPDATE angels SET level = ?, exp = ? WHERE id = ?",
        (level, exp, int(row["id"])),
    )
    conn.commit()
    return level, exp
