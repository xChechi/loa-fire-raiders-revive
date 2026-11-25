"""Wave 2 B2: elite stages (chapter_info.type 2) and the elite item sweep.

Stage 110000 (first elite stage, chapter 110000): energy 12, maxcount 3,
relation_level 10000, gold 1036, player_xp 12. Stage 110010 relates to 10012.
"""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player
from server.modules import level, notify
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
ELITE = 110000
FUTURE = 2 ** 31            # a deadline that has not passed yet


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind="127.0.0.1", port=0, username="stefan", guide_id=0,
    )


@pytest.fixture
def world(settings, cfg, reg):
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = level.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _into(handlers, session, reg, lvl):
    return handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=lvl))


def _fight(handlers, session, reg, lvl, star):
    _into(handlers, session, reg, lvl)
    req = reg.message_class("LevelOutReq")(level=lvl, star=star, angel=0)
    return handlers[(5, 2203)](session, req)


def _set_progress(conn, pid, lvl, star, count=0, clean=0, deadline=FUTURE):
    conn.execute(
        "INSERT INTO levels (player_id, level, star, count, clean_elite_count,"
        " deadline) VALUES (?, ?, ?, ?, ?, ?)",
        (pid, lvl, star, count, clean, deadline),
    )
    conn.commit()


def _progress(conn, pid, lvl):
    return conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = ?", (pid, lvl)
    ).fetchone()


def _player_notifies(session):
    return [m for (s, c, m) in session.outbox if (s, c) == (5, 2008) and m.ident == 1]


def test_first_elite_stage_is_110000_after_10000_played(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    assert level.frontier(cfg, find_player(conn, "stefan"), 2) == ELITE
    assert _fight(handlers, session, reg, 10000, star=1).status == 0
    res = _into(handlers, session, reg, ELITE)
    assert res.flag == level.FLAG_OK
    assert len(res.urandom) == level.URANDOM_SIZE
    # 60 - 6 (stage 10000) - 12 (the elite entry)
    assert int(find_player(conn, "stefan")["energy"]) == 42


def test_elite_locked_until_relation_level_played(reg, cfg, world, caplog) -> None:
    """LevelManager.lua:867-879: the elite frontier is status 4 (locked) until
    its relation_level normal stage has star > 0."""
    conn, pid, handlers, session = world
    res = _into(handlers, session, reg, ELITE)
    assert res.flag == level.FLAG_STAGE_CHANGED
    assert "328193" in caplog.text
    assert int(find_player(conn, "stefan")["energy"]) == 60
    assert session.outbox == []
    # A lost relation stage (star 0) does not open it either.
    _set_progress(conn, pid, 10000, star=0, count=1)
    assert _into(handlers, session, reg, ELITE).flag == level.FLAG_STAGE_CHANGED


def test_elite_clear_sets_last_elite_and_notifies(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, 10000, star=3)
    session.outbox.clear()
    res = _fight(handlers, session, reg, ELITE, star=3)
    assert res.status == 0
    row = find_player(conn, "stefan")
    assert int(row["last_elite"]) == ELITE
    assert int(row["last_level"]) == 10000          # the normal frontier stays
    assert int(row["gold"]) == 1280000 + 516 + 1036
    bit = notify.flags_for(["last_elite"])
    assert any(m.flags & bit for m in _player_notifies(session))
    assert level.frontier(cfg, row, 2) == 110010
    assert level.frontier(cfg, row) == 10010
    # 110010 relates to 10012, which is not played: still locked.
    assert _into(handlers, session, reg, 110010).flag == level.FLAG_STAGE_CHANGED
    res.SerializeToString()


def test_elite_maxcount_3_flag_2(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _set_progress(conn, pid, 10000, star=3, count=1)
    _set_progress(conn, pid, ELITE, star=3, count=3)
    res = _into(handlers, session, reg, ELITE)
    assert res.flag == level.FLAG_MAX_TIMES
    assert res.star == 3
    assert int(find_player(conn, "stefan")["energy"]) == 60
