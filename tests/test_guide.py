"""5_2041 SaveGuideIdReq: the guide id the client saves must survive a restart.

NewGuideManager sends this at four sites (NewGuideManager.lua:234, 331, 404, 725)
and it is the only request the new-player guide makes. RPGGame:init (RPGGame.lua:78)
opens the main scene directly when player.guide_id is not 0, so persisting this
value is exactly what stops the tutorial replaying.
"""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, set_guide_id
from server.modules import guide, player
from server.net.registry import Registry
from server.net.server import Server
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"

# The players table exactly as Plan A created it (server/db.py at d946f3c).
# A real character of Stefan's lives in a database of this shape.
PLAN_A_PLAYERS = """
CREATE TABLE players (
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


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg():
    conf = Config.load(STOCK)
    yield conf
    conf.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind=BIND, port=0, username="stefan", guide_id=0,
    )


def test_save_guide_id_persists_and_answers_status_zero(reg, settings, cfg) -> None:
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)

    async def scenario() -> None:
        handlers = {}
        handlers.update(guide.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn, cfg))
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        body = reg.message_class("SaveGuideIdReq")(guide_id=10041).SerializeToString()
        await client.send(5, 2041, body)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2042)
        res = reg.message_class("SaveGuideIdRes")()
        res.ParseFromString(frame.body)
        assert res.status == 0
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
    assert int(find_player(conn, "stefan")["guide_id"]) == 10041


def test_a_later_guide_id_overwrites_an_earlier_one(reg, settings) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 10041)
    set_guide_id(conn, pid, 10160)
    assert int(find_player(conn, "stefan")["guide_id"]) == 10160


def test_query_myself_reports_the_saved_guide_id(reg, settings) -> None:
    """The client seeds NewGuideManager from QueryMyselfRes.player.guide_id."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 10160)
    res = player.build_query_myself_res(reg, find_player(conn, "stefan"))
    assert res.player.guide_id == 10160


def test_a_plan_a_players_row_survives_and_keeps_its_data(settings) -> None:
    """Opening a Plan A database must not rebuild or touch the existing row."""
    raw = sqlite3.connect(settings.db_path)
    raw.executescript(PLAN_A_PLAYERS)
    raw.execute(
        "INSERT INTO players (username, nickname, level, xp, gold, diamond, vip,"
        " energy, max_energy, avatar, guide_id, created_at)"
        " VALUES ('stefan', 'Stefan', 7, 310, 1234, 55, 1, 48, 72, 3, 0,"
        " '2026-10-21T12:31:00+00:00')"
    )
    raw.commit()
    raw.close()

    conn = connect(settings.db_path)
    row = find_player(conn, "stefan")
    assert (row["nickname"], row["level"], row["xp"], row["gold"]) == (
        "Stefan", 7, 310, 1234
    )
    assert (row["diamond"], row["vip"], row["energy"], row["max_energy"]) == (
        55, 1, 48, 72
    )
    assert row["avatar"] == 3
    assert row["created_at"] == "2026-10-21T12:31:00+00:00"

    set_guide_id(conn, int(row["id"]), 10160)
    after = find_player(conn, "stefan")
    assert int(after["guide_id"]) == 10160
    assert (after["nickname"], after["level"], after["gold"]) == ("Stefan", 7, 1234)
