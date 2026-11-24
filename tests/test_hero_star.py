"""5_2107 HeroStarUpReq and 5_2127 HeroCallReq.

hero_growth(100000) star_up_cost by star 1..6: 10, 20, 40, 80, 120, 180.
HERO_STAR_UP_COST_1..6: 0, 100000, 300000, 600000, 1200000, 2400000.
hero_info 100000: star 1, item 100000, break_item 6100000. hero_info 105000:
star 2, item 105000, init_level 5, growth 10 + 20."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, grant_item, heroes_of, items_of
from server.modules import hero, notify
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
GOLD = 5_000_000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=GOLD, diamond=0)
    handlers = hero.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _items(conn, pid) -> dict[int, int]:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0])


def _notes(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


def _decode(msg, order) -> dict:
    out, values = {}, iter(msg.data)
    for i, name in enumerate(order):
        if msg.flags & (1 << i):
            out[name] = next(values)
    return out


def _star_up(reg, handlers, session, entry=100000):
    return handlers[(5, 2107)](session, reg.message_class("HeroStarUpReq")(hero=entry))


def _call(reg, handlers, session, entry):
    return handlers[(5, 2127)](session, reg.message_class("HeroCallReq")(hero=entry))


def test_star_up_100000_1_to_2_costs_20_stones_and_100000_gold(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, star=1, level=3)
    grant_item(conn, pid, 100000, 25)
    res = _star_up(reg, handlers, session)
    assert res.status == 0
    res.SerializeToString()
    row = heroes_of(conn, pid)[0]
    assert int(row["star"]) == 2
    assert _items(conn, pid)[100000] == 5
    assert _gold(conn, pid) == GOLD - 100000
    # Settled point 11: exactly one ident-2 notify, plus base, item and gold.
    hero_notes = _notes(session, 2)
    assert len(hero_notes) == 1 and hero_notes[0].refer == 100000
    fields = _decode(hero_notes[0], notify.HERO_FIELDS)
    assert fields["star"] == 2
    # The unit now grows by the star-2 hero_growth row.
    assert fields["max_hp"] == hero.build_client_hero(reg, cfg, row).unit.max_hp
    assert len(_notes(session, 9)) == 1
    assert [list(m.data) for m in _notes(session, 4)] == [[100000.0, 5.0]]
    assert len(_notes(session, 1)) == 1


def test_star_up_refusals_327941_327942_327937(reg, world) -> None:
    conn, pid, handlers, session = world
    assert _star_up(reg, handlers, session).status == 327941
    grant_hero(conn, pid, 100000, 10, star=1)
    grant_item(conn, pid, 100000, 19)
    assert _star_up(reg, handlers, session).status == 327942
    grant_item(conn, pid, 100000, 1)
    conn.execute("UPDATE players SET gold = 99999 WHERE id = ?", (pid,))
    conn.commit()
    assert _star_up(reg, handlers, session).status == 327937
    assert int(heroes_of(conn, pid)[0]["star"]) == 1
    assert _items(conn, pid)[100000] == 20
    assert session.outbox == []


def test_star_up_at_top_refused_328965(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, star=6)
    grant_item(conn, pid, 6100000, 999)
    assert _star_up(reg, handlers, session).status == 328965
    assert int(heroes_of(conn, pid)[0]["star"]) == 6


def test_star_up_from_5_uses_break_item(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, star=5)
    grant_item(conn, pid, 100000, 999)
    assert _star_up(reg, handlers, session).status == 327942
    grant_item(conn, pid, 6100000, 180)
    assert _star_up(reg, handlers, session).status == 0
    assert int(heroes_of(conn, pid)[0]["star"]) == 6
    assert _items(conn, pid).get(6100000, 0) == 0
    assert _items(conn, pid)[100000] == 999
    assert _gold(conn, pid) == GOLD - 2400000


def test_hero_call_costs_sum_of_growth_up_to_initial_star(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 105000, 31)
    res = _call(reg, handlers, session, 105000)
    assert res.status == 0
    res.SerializeToString()
    rows = heroes_of(conn, pid)
    assert [(int(r["entry"]), int(r["star"]), int(r["level"]), int(r["quality"]))
            for r in rows] == [(105000, 2, 5, 10)]
    assert _items(conn, pid)[105000] == 1
    assert _gold(conn, pid) == GOLD - 100000


def test_hero_call_short_refused_327942_and_327937(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 105000, 29)
    assert _call(reg, handlers, session, 105000).status == 327942
    grant_item(conn, pid, 105000, 1)
    conn.execute("UPDATE players SET gold = 99999 WHERE id = ?", (pid,))
    conn.commit()
    assert _call(reg, handlers, session, 105000).status == 327937
    assert heroes_of(conn, pid) == []
    assert session.outbox == []


def test_hero_call_owned_refused_327940(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10)
    grant_item(conn, pid, 100000, 50)
    assert _call(reg, handlers, session, 100000).status == 327940
    assert len(heroes_of(conn, pid)) == 1


def test_hero_call_pushes_add_hero_notify(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 100000, 10)
    assert _call(reg, handlers, session, 100000).status == 0
    added = [m for (_s, c, m) in session.outbox if c == 2012]
    assert len(added) == 1
    assert (added[0].hero.entry, added[0].hero.star) == (100000, 1)
    assert [list(m.data) for m in _notes(session, 4)] == [[100000.0, 0.0]]
    assert len(_notes(session, 1)) == 1
