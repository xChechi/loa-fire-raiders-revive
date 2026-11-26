"""5_2701 HeroDevelopQueryReq, 5_2703 HeroDevelopReq, 5_2705 HeroDevelopEnsureReq.

hero_constellation_info idx 0: property_id0..3 = 3/5/1/16 (defence,
magic_defence, max_hp, tenacity_base), limits 1000/1000/10000/500, ladder step
0.002 below frac 0.1 and 0.0016 from frac 0.9 up. One roll from zero therefore
adds 2/2/20/1 (O-W3-5). Costs: HERO_DEVELOP_COMMON_STONE 1 x item 2000,
HERO_DEVELOP_GOLD_STONE 1 + HERO_DEVELOP_GOLD 10000, HERO_DEVELOP_DIAMOND 300,
HERO_DEVELOP_SPECIAL_PROPS_AMOUNT 1 x item 2200. HERO_QUALITY_OPEN
41|43|50|50|50|51|52|52; function 90040 opens at 46.
"""

import json
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, grant_item, heroes_of
from server.modules import herodevelop, notify
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
KNIGHT = 100000
STONE, SPECIAL = 2000, 2200


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


def _world(settings, cfg, reg, quality=41, level=46):
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=1000)
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (level, pid))
    conn.commit()
    grant_hero(conn, pid, KNIGHT, quality, star=1, level=40)
    handlers = herodevelop.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


@pytest.fixture
def world(settings, cfg, reg):
    return _world(settings, cfg, reg)


def _money(conn, pid) -> tuple[int, int]:
    row = conn.execute("SELECT gold, diamond FROM players WHERE id = ?", (pid,)).fetchone()
    return int(row["gold"]), int(row["diamond"])


def _amount(conn, pid, entry) -> int:
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
    ).fetchone()
    return int(row["amount"]) if row else 0


def _row(conn, pid, constellation=0):
    return conn.execute(
        "SELECT * FROM hero_develop WHERE player_id = ? AND hero = ? AND constellation = ?",
        (pid, KNIGHT, constellation),
    ).fetchone()


def _props(msg) -> tuple[float, float, float, float]:
    return (msg.property0, msg.property1, msg.property2, msg.property3)


def _query(reg, handlers, session):
    req = reg.message_class("HeroDevelopQueryReq")(entry=KNIGHT)
    res = handlers[(5, 2701)](session, req)
    res.SerializeToString()
    return res


def _roll(reg, handlers, session, method=1, times=1, constellation=0):
    req = reg.message_class("HeroDevelopReq")(
        entry=KNIGHT, constellation=constellation, method=method, times=times
    )
    res = handlers[(5, 2703)](session, req)
    res.SerializeToString()
    return res


def _ensure(reg, handlers, session, insure, constellation=0):
    req = reg.message_class("HeroDevelopEnsureReq")(
        insure=insure, entry=KNIGHT, constellation=constellation
    )
    res = handlers[(5, 2705)](session, req)
    res.SerializeToString()
    return res


def _notifies(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


BLOCKS = ("SP", "SZ", "ZZ", "MJ", "JX", "CN", "TC", "TX", "SS", "JN", "BY", "SY")


def test_query_returns_twelve_blocks_zeroed(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _query(reg, handlers, session)
    for name in BLOCKS:
        block = getattr(res, f"property{name}")
        assert len(block) == 1, name
        assert _props(block[0]) == (0, 0, 0, 0), name


def test_query_answers_stored_values(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute(
        "INSERT INTO hero_develop (player_id, hero, constellation, p0, p1, p2, p3)"
        " VALUES (?, ?, 2, 4, 6, 40, 2)", (pid, KNIGHT),
    )
    conn.commit()
    res = _query(reg, handlers, session)
    assert _props(res.propertyZZ[0]) == (4, 6, 40, 2)
    assert _props(res.propertySP[0]) == (0, 0, 0, 0)


def test_query_below_level46_answers_zeros(reg, cfg, settings) -> None:
    conn, pid, handlers, session = _world(settings, cfg, reg, level=45)
    res = _query(reg, handlers, session)
    assert all(_props(getattr(res, f"property{n}")[0]) == (0, 0, 0, 0) for n in BLOCKS)


def test_constellation0_needs_quality41(reg, cfg, settings) -> None:
    conn, pid, handlers, session = _world(settings, cfg, reg, quality=40)
    grant_item(conn, pid, STONE, 5)
    res = _roll(reg, handlers, session, method=1)
    assert _props(res) == (0, 0, 0, 0)
    assert _amount(conn, pid, STONE) == 5
    row = _row(conn, pid)
    assert row is None or row["pending"] == ""


def test_constellation0_opens_at_quality41(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 5)
    res = _roll(reg, handlers, session, method=1)
    assert _props(res) == (2, 2, 20, 1)


def test_method1_takes_one_stone_2000(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 3)
    _roll(reg, handlers, session, method=1)
    assert _amount(conn, pid, STONE) == 2
    assert _money(conn, pid) == (100000, 1000)
    assert _notifies(session, notify.IDENT_ITEM)


def test_method2_takes_stone_and_10000_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 3)
    _roll(reg, handlers, session, method=2)
    assert _amount(conn, pid, STONE) == 2
    assert _money(conn, pid) == (90000, 1000)
    assert _notifies(session, notify.IDENT_PLAYER)


def test_method3_takes_300_diamonds(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _roll(reg, handlers, session, method=3)
    assert _props(res) == (2, 2, 20, 1)
    assert _money(conn, pid) == (100000, 700)


def test_method4_takes_one_special_stone_2200(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, SPECIAL, 2)
    _roll(reg, handlers, session, method=4)
    assert _amount(conn, pid, SPECIAL) == 1
    assert _money(conn, pid) == (100000, 1000)


def test_ten_rolls_cost_ten_times(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 12)
    res = _roll(reg, handlers, session, method=2, times=2)
    assert _amount(conn, pid, STONE) == 2
    assert _money(conn, pid) == (0, 1000)
    # Ten steps of 0.002 x limit, all below frac 0.1.
    assert _props(res) == (20, 20, 200, 10)


def test_hundred_rolls_cost_hundred_times(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET diamond = 30000 WHERE id = ?", (pid,))
    conn.commit()
    _roll(reg, handlers, session, method=3, times=3)
    assert _money(conn, pid) == (100000, 0)


def test_shortfall_takes_nothing_and_answers_current(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 9)
    res = _roll(reg, handlers, session, method=1, times=2)
    assert _props(res) == (0, 0, 0, 0)
    assert _amount(conn, pid, STONE) == 9
    # Stone enough, gold short: nothing taken either.
    conn.execute("UPDATE players SET gold = 9999 WHERE id = ?", (pid,))
    conn.commit()
    _roll(reg, handlers, session, method=2)
    assert _amount(conn, pid, STONE) == 9
    assert _money(conn, pid) == (9999, 1000)
    assert session.outbox == []


def test_roll_is_a_preview_until_insure(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 3)
    _roll(reg, handlers, session, method=1)
    row = _row(conn, pid)
    assert (row["p0"], row["p1"], row["p2"], row["p3"]) == (0, 0, 0, 0)
    assert json.loads(row["pending"]) == [2, 2, 20, 1]
    assert _props(_query(reg, handlers, session).propertySP[0]) == (0, 0, 0, 0)

    session.outbox.clear()
    res = _ensure(reg, handlers, session, 1)
    assert _props(res) == (2, 2, 20, 1)
    row = _row(conn, pid)
    assert (row["p0"], row["p1"], row["p2"], row["p3"]) == (2, 2, 20, 1)
    assert row["pending"] == ""
    heroes = _notifies(session, notify.IDENT_HERO)
    assert heroes and heroes[0].refer == KNIGHT
    assert _props(_query(reg, handlers, session).propertySP[0]) == (2, 2, 20, 1)

    # A second confirm with nothing pending changes nothing.
    assert _props(_ensure(reg, handlers, session, 1)) == (2, 2, 20, 1)


def test_new_roll_starts_from_stored_values_not_the_old_preview(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 3)
    _roll(reg, handlers, session, method=1)
    res = _roll(reg, handlers, session, method=1)
    assert _props(res) == (2, 2, 20, 1)


def test_cancel_discards_pending_and_keeps_cost(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, STONE, 3)
    _roll(reg, handlers, session, method=1)
    res = _ensure(reg, handlers, session, 0)
    assert _props(res) == (0, 0, 0, 0)
    row = _row(conn, pid)
    assert row["pending"] == ""
    assert (row["p0"], row["p1"], row["p2"], row["p3"]) == (0, 0, 0, 0)
    assert _amount(conn, pid, STONE) == 2


def test_values_capped_at_limit(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute(
        "INSERT INTO hero_develop (player_id, hero, constellation, p0, p1, p2, p3)"
        " VALUES (?, ?, 0, 999, 1000, 9999, 0)", (pid, KNIGHT),
    )
    conn.commit()
    grant_item(conn, pid, STONE, 3)
    res = _roll(reg, handlers, session, method=1)
    # 999/1000 sits in the 0.9 bracket: +1.6, capped at 1000; 9999 + 16 -> 10000.
    assert _props(res) == (1000, 1000, 10000, 1)


def test_full_constellation_takes_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute(
        "INSERT INTO hero_develop (player_id, hero, constellation, p0, p1, p2, p3)"
        " VALUES (?, ?, 0, 1000, 1000, 10000, 500)", (pid, KNIGHT),
    )
    conn.commit()
    grant_item(conn, pid, STONE, 3)
    res = _roll(reg, handlers, session, method=1)
    assert _props(res) == (1000, 1000, 10000, 500)
    assert _amount(conn, pid, STONE) == 3


def test_bonus_maps_property_ids(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    # idx 0: 3/5/1/16; idx 1: 9 (all attack)/3/1/14.
    conn.executemany(
        "INSERT INTO hero_develop (player_id, hero, constellation, p0, p1, p2, p3, pending)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(pid, KNIGHT, 0, 2, 4, 20, 1, "[9, 9, 9, 9]"),
         (pid, KNIGHT, 1, 5, 3, 30, 7, "")],
    )
    conn.commit()
    got = herodevelop.bonus(conn, cfg, heroes_of(conn, pid)[0])
    assert got == {
        "defence": 2 + 3, "magic_defence": 4, "max_hp": 20 + 30,
        "tenacity_base": 1, "power": 5, "magic": 5, "block_base": 7,
    }
