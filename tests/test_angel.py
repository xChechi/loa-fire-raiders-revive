"""5_2303 SummonAngelReq and 5_2305 UpgradeAngelStarReq. Goddess 500000 costs
item 500000 x10 at star 1 and x20 for star 2 (angel_info), gold
ANGEL_STAR_UP_COST_1 = 0 and ANGEL_STAR_UP_COST_2 = 100000 (variables)."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import angels_of, connect, create_player, grant_angel, grant_item, items_of
from server.modules import angel
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
    handlers = angel.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _items(conn, pid) -> dict[int, int]:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0])


def _summon(reg, handlers, session, entry=500000):
    return handlers[(5, 2303)](session, reg.message_class("SummonAngelReq")(angel_entry=entry))


def _star_up(reg, handlers, session, entry=500000):
    return handlers[(5, 2305)](
        session, reg.message_class("UpgradeAngelStarReq")(angel_entry=entry)
    )


def test_summon_500000_takes_ten_stones_and_returns_client_angel(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 500000, 10)
    res = _summon(reg, handlers, session)
    assert res.status == 0
    assert res.angel.angel_entry == 500000
    assert res.angel.star == 1 and res.angel.level == 1 and res.angel.exp == 0
    rows = angels_of(conn, pid)
    assert [(int(r["angel_entry"]), int(r["star"]), int(r["level"])) for r in rows] == [
        (500000, 1, 1)
    ]
    assert _items(conn, pid).get(500000, 0) == 0
    item_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 4]
    assert [list(m.data) for m in item_notes] == [[500000.0, 0.0]]
    player_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]
    assert len(player_notes) == 1


def test_summon_refused_327942_without_stones_writes_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 500000, 9)
    res = _summon(reg, handlers, session)
    assert res.status == 327942
    assert not res.HasField("angel")
    assert angels_of(conn, pid) == []
    assert _items(conn, pid)[500000] == 9
    assert _gold(conn, pid) == 1280000
    assert session.outbox == []


def test_summon_twice_refused_328449(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 500000, 20)
    assert _summon(reg, handlers, session).status == 0
    res = _summon(reg, handlers, session)
    assert res.status == 328449
    assert _items(conn, pid)[500000] == 10
    assert len(angels_of(conn, pid)) == 1


def test_summon_unknown_angel_refused_328459(reg, world) -> None:
    conn, pid, handlers, session = world
    assert _summon(reg, handlers, session, entry=123).status == 328459


def test_client_angel_has_two_spells_and_six_auras(reg, cfg, world) -> None:
    conn, pid, _h, _s = world
    grant_angel(conn, pid, 500000, level=1, star=1)
    msg = angel.build_client_angel(reg, cfg, angels_of(conn, pid)[0])
    assert list(msg.spells) == [5000000, 5010000]
    assert list(msg.auras) == [5020000, 0, 0, 0, 0, 0]
    assert msg.ability == 0 and msg.advance_level == 0
    msg.SerializeToString()


def test_star_up_costs_next_star_row_and_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=1, star=1)
    grant_item(conn, pid, 500000, 25)
    res = _star_up(reg, handlers, session)
    assert res.status == 0
    assert res.angel.star == 2
    assert list(res.angel.spells) == [5001000, 5011000]
    assert list(res.angel.auras) == [5020000, 5021000, 0, 0, 0, 0]
    assert int(angels_of(conn, pid)[0]["star"]) == 2
    assert _items(conn, pid)[500000] == 5
    assert _gold(conn, pid) == 1280000 - 100000
    angel_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 3]
    assert len(angel_notes) == 1
    assert angel_notes[0].refer == 500000
    assert list(angel_notes[0].data) == [2.0]


def test_star_up_refused_327942_and_327937_write_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=1, star=1)
    grant_item(conn, pid, 500000, 19)
    assert _star_up(reg, handlers, session).status == 327942
    grant_item(conn, pid, 500000, 1)
    conn.execute("UPDATE players SET gold = 99999 WHERE id = ?", (pid,))
    conn.commit()
    assert _star_up(reg, handlers, session).status == 327937
    assert int(angels_of(conn, pid)[0]["star"]) == 1
    assert _items(conn, pid)[500000] == 20
    assert session.outbox == []


def test_star_up_not_owned_refused_328457(reg, world) -> None:
    _conn, _pid, handlers, session = world
    assert _star_up(reg, handlers, session).status == 328457


def test_star_up_at_max_star_refused_328450(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=1, star=6)
    grant_item(conn, pid, 500000, 999)
    assert _star_up(reg, handlers, session).status == 328450
    assert int(angels_of(conn, pid)[0]["star"]) == 6


def test_angel_responses_serialise(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 500000, 30)
    _summon(reg, handlers, session).SerializeToString()
    _summon(reg, handlers, session).SerializeToString()
    _star_up(reg, handlers, session).SerializeToString()
    _star_up(reg, handlers, session, entry=777).SerializeToString()
    for _s, _c, m in session.outbox:
        m.SerializeToString()
