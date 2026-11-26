"""Angel Radiance (圣辉): 5_2909 AngelGloryQueryReq, 5_2911 AngelGloryUpgradeReq,
5_2913 AngelGloryInheritReq. The glory stone is item 2800 (COST_STONE_ID,
AngelShengHui.lua:17); angel_glory_info row (0, 0) costs 1 at rate 1, row
(0, 5) costs 5 at rate 1, row (100, 0) is the top marker (property_id 0,
property 0); ANGEL_GLORY_INHERIT_COST = 1000 diamonds."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_angel, grant_item, items_of
from server.modules import angelglory
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
STONE = 2800


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
    grant_angel(conn, pid, 500000, level=49, star=1)
    grant_angel(conn, pid, 500001, level=49, star=1)
    handlers = angelglory.handlers(reg, settings, conn, cfg, rng=random.Random(7))
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _set_glory(conn, pid, entry, level, star):
    conn.execute(
        "UPDATE angels SET glory_level = ?, glory_star = ? WHERE player_id = ?"
        " AND angel_entry = ?",
        (level, star, pid, entry),
    )
    conn.commit()


def _glory(conn, pid, entry):
    row = conn.execute(
        "SELECT glory_level, glory_star FROM angels WHERE player_id = ?"
        " AND angel_entry = ?",
        (pid, entry),
    ).fetchone()
    return int(row["glory_level"]), int(row["glory_star"])


def _stones(conn, pid) -> int:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}.get(STONE, 0)


def _diamond(conn, pid) -> int:
    return int(
        conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()[0]
    )


def _light(reg, handlers, session, entry=500000):
    return handlers[(5, 2911)](
        session, reg.message_class("AngelGloryUpgradeReq")(angel_entry=entry)
    )


def _inherit(reg, handlers, session, to_entry, from_entry):
    # AngelShengHuiInheritancePanel.lua:150: angel_entry_1 = the current angel
    # (receives), angel_entry_2 = the chosen one (gives).
    return handlers[(5, 2913)](
        session,
        reg.message_class("AngelGloryInheritReq")(
            angel_entry_1=to_entry, angel_entry_2=from_entry
        ),
    )


def test_light_one_star_costs_row_cost(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    row = cfg.angel_glory(0, 0)
    assert int(row["cost"]) == 1 and float(row["rate"]) == 1
    grant_item(conn, pid, STONE, 10)
    res = _light(reg, handlers, session)
    assert (res.angel_glory.level, res.angel_glory.star) == (0, 1)
    assert _glory(conn, pid, 500000) == (0, 1)
    assert _stones(conn, pid) == 9
    assert res.SerializeToString() is not None


def test_star_rollover_raises_level(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    assert cfg.angel_glory(0, 6) is None
    _set_glory(conn, pid, 500000, 0, 5)
    grant_item(conn, pid, STONE, 5)
    res = _light(reg, handlers, session)
    assert (res.angel_glory.level, res.angel_glory.star) == (1, 0)
    assert _glory(conn, pid, 500000) == (1, 0)
    assert _stones(conn, pid) == 0


def test_failed_roll_takes_cost_and_keeps_glory(reg, cfg, settings, world) -> None:
    conn, pid, _, session = world
    assert float(cfg.angel_glory(99, 5)["rate"]) < 1

    class Always:
        def random(self):
            return 0.999

    handlers = angelglory.handlers(reg, settings, conn, cfg, rng=Always())
    _set_glory(conn, pid, 500000, 99, 5)
    grant_item(conn, pid, STONE, 60)
    res = _light(reg, handlers, session)
    assert (res.angel_glory.level, res.angel_glory.star) == (99, 5)
    assert _stones(conn, pid) == 60 - int(cfg.angel_glory(99, 5)["cost"])


def test_top_refused_338163(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_glory(conn, pid, 500000, 100, 0)
    grant_item(conn, pid, STONE, 100)
    with caplog.at_level("WARNING", logger="loa.angelglory"):
        res = _light(reg, handlers, session)
    assert (res.angel_glory.level, res.angel_glory.star) == (100, 0)
    assert _stones(conn, pid) == 100
    assert "338163" in caplog.text


def test_short_stones_answer_unchanged(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_glory(conn, pid, 500000, 0, 5)
    grant_item(conn, pid, STONE, 4)
    with caplog.at_level("WARNING", logger="loa.angelglory"):
        res = _light(reg, handlers, session)
    assert (res.angel_glory.level, res.angel_glory.star) == (0, 5)
    assert _glory(conn, pid, 500000) == (0, 5)
    assert _stones(conn, pid) == 4
    assert "327942" in caplog.text


def test_unknown_angel_logs_328457_and_answers_zero(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 10)
    with caplog.at_level("WARNING", logger="loa.angelglory"):
        res = _light(reg, handlers, session, entry=999999)
    assert (res.angel_glory.level, res.angel_glory.star) == (0, 0)
    assert _stones(conn, pid) == 10
    assert "328457" in caplog.text


def test_query_answers_stored_glory(reg, world) -> None:
    conn, pid, handlers, session = world
    _set_glory(conn, pid, 500000, 3, 4)
    res = handlers[(5, 2909)](
        session, reg.message_class("AngelGloryQueryReq")(angel_entry=500000)
    )
    assert (res.angel_glory.level, res.angel_glory.star) == (3, 4)


def test_inherit_moves_glory_and_costs_1000(reg, world) -> None:
    conn, pid, handlers, session = world
    _set_glory(conn, pid, 500001, 5, 2)
    before = _diamond(conn, pid)
    res = _inherit(reg, handlers, session, to_entry=500000, from_entry=500001)
    assert res.SerializeToString() == b""
    assert _glory(conn, pid, 500000) == (5, 2)
    assert _glory(conn, pid, 500001) == (0, 0)
    assert _diamond(conn, pid) == before - 1000


def test_inherit_low_to_high_refused_338164(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_glory(conn, pid, 500000, 5, 2)
    _set_glory(conn, pid, 500001, 1, 0)
    before = _diamond(conn, pid)
    with caplog.at_level("WARNING", logger="loa.angelglory"):
        _inherit(reg, handlers, session, to_entry=500000, from_entry=500001)
    assert _glory(conn, pid, 500000) == (5, 2)
    assert _glory(conn, pid, 500001) == (1, 0)
    assert _diamond(conn, pid) == before
    assert "338164" in caplog.text


def test_inherit_short_diamonds_logs_327938(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET diamond = 999 WHERE id = ?", (pid,))
    conn.commit()
    _set_glory(conn, pid, 500001, 5, 2)
    with caplog.at_level("WARNING", logger="loa.angelglory"):
        _inherit(reg, handlers, session, to_entry=500000, from_entry=500001)
    assert _glory(conn, pid, 500000) == (0, 0)
    assert _glory(conn, pid, 500001) == (5, 2)
    assert _diamond(conn, pid) == 999
    assert "327938" in caplog.text
