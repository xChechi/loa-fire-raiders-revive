"""5_2201 LevelIntoReq. Stage rows are quoted in the plan: chapter 1 is
10000, 10010, 10012, 10020, 10022, each costing 6 energy."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, set_last_level, upsert_level
from server.modules import level
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")


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


def test_the_frontier_of_a_fresh_player_is_stage_one_one(cfg, world) -> None:
    conn, pid, _h, _s = world
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10000


def test_the_frontier_follows_last_level(cfg, world) -> None:
    conn, pid, _h, _s = world
    set_last_level(conn, pid, 10000)
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10010


def test_urandom_is_64_values_under_10000(world, reg) -> None:
    """Review Focus 4: BattleAlthm.NewAlgorithm refuses any other length and
    Random() divides by SCALE 10000."""
    values = level.roll_urandom(random.Random(0))
    assert len(values) == 64
    assert all(0 <= v < 10000 for v in values)
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert len(res.urandom) == 64
    assert all(0 <= v < 10000 for v in res.urandom)


def test_entering_stage_one_one_spends_six_energy_and_pre_rolls_the_drops(
    reg, cfg, world
) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0
    assert int(find_player(conn, "stefan")["energy"]) == 54
    # visible_drops 10000 is certain: 粗布头巾 x2
    assert (20, 10000, 2) in [(d.category, d.refer, d.amount) for d in res.drop]
    assert session.data[level.PENDING_KEY][10000]
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008)]
    res.SerializeToString()


def test_a_locked_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10022))
    assert res.flag == 1
    assert int(find_player(conn, "stefan")["energy"]) == 60      # nothing spent
    assert level.PENDING_KEY not in session.data or not session.data[level.PENDING_KEY]


def test_an_unknown_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=999999))
    assert res.flag == 1


def test_a_cleared_stage_can_be_replayed_when_once_is_zero(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    set_last_level(conn, pid, 10000)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0                                   # stage_info.once is 0


def test_a_cleared_once_stage_is_refused_with_flag_one_and_its_star(
    reg, cfg, world
) -> None:
    """stage 10010 has once = 1 (open question C in the plan)."""
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10010, star=2, count_delta=1)
    set_last_level(conn, pid, 10010)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10010))
    assert res.flag == 1
    assert res.star == 2


def test_too_little_energy_is_refused_and_logged_with_the_real_code(
    reg, cfg, world, caplog
) -> None:
    conn, pid, handlers, session = world
    # energy_at in 2038 parks the regeneration clock in the future, so
    # refresh_energy adds nothing and the player really has 2 energy.
    conn.execute("UPDATE players SET energy = 2, energy_at = ? WHERE id = ?",
                 (2 ** 31, pid))
    conn.commit()
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 1
    assert "327939" in caplog.text
    assert int(find_player(conn, "stefan")["energy"]) == 2


def test_a_refusal_writes_nothing_at_all(reg, cfg, world) -> None:
    """Every refusal path leaves the db and the session untouched: no energy
    spent, no pending entry, no notification queued."""
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET energy = 2, energy_at = ? WHERE id = ?",
                 (2 ** 31, pid))
    conn.commit()
    for entry in (10022, 999999, 10000):        # locked, unknown, no energy
        res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=entry))
        assert res.flag == 1
        assert list(res.drop) == []
        assert list(res.urandom) == []
    assert int(find_player(conn, "stefan")["energy"]) == 2
    assert session.data.get(level.PENDING_KEY, {}) == {}
    assert session.outbox == []
