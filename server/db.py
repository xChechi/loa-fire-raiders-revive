"""The single-player SQLite store. No ORM, one connection, per-request commits."""

from __future__ import annotations

import sqlite3
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


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
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
