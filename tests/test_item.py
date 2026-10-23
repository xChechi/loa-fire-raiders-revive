"""ClientStock and prize granting (categories from ClientPlayer.lua:146-186)."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_item, heroes_of, items_of
from server.modules.item import build_client_stock, build_inventory, grant_prizes
from server.net.registry import Registry

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
def conn(tmp_path):
    return connect(tmp_path / "player.db")


def test_build_client_stock_fields(reg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 10000, 2)
    row = items_of(conn, pid)[0]
    stock = build_client_stock(reg, row, index=0)
    assert stock.id == int(row["id"])
    assert stock.entry == 10000
    assert stock.amount == 2
    assert stock.state == 0
    assert stock.index == 0
    stock.SerializeToString()


def test_build_inventory_is_one_stock_per_entry(reg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 1100, 3)
    grant_item(conn, pid, 1100, 2)
    grant_item(conn, pid, 1200, 1)
    stocks = build_inventory(reg, conn, pid)
    assert [(s.entry, s.amount) for s in stocks] == [(1100, 5), (1200, 1)]
    assert [s.index for s in stocks] == [0, 1]


def test_grant_prizes_applies_every_category_this_plan_sends(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100, diamond=10)
    out = grant_prizes(conn, cfg, pid, [
        (1, 0, 516),          # gold
        (9, 0, 600),          # diamond
        (20, 10000, 2),       # item
        (30, 101000, 1),      # hero
    ])
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 616
    assert int(row["diamond"]) == 610
    assert out["gold"] == 616
    assert out["diamond"] == 610
    assert out["items"] == [(10000, 2)]
    assert len(out["heroes"]) == 1
    hero = [h for h in heroes_of(conn, pid) if int(h["entry"]) == 101000][0]
    assert int(hero["quality"]) == int(cfg.hero_qualities(101000)[0]["quality"])


def test_grant_prizes_returns_exactly_the_keys_callers_read(reg, cfg, conn) -> None:
    """Tasks 11, 14 and 15 read these five keys by name off the return value."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [])
    assert set(out) == {"gold", "diamond", "energy", "items", "heroes"}


def test_grant_prizes_adds_energy_through_the_db_helper(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0, energy=10)
    out = grant_prizes(conn, cfg, pid, [(2, 0, 5)])
    assert out["energy"] == 15
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["energy"]) == 15


def test_granting_a_hero_twice_keeps_two_rows(reg, cfg, conn) -> None:
    """The client keeps a list of heroes and RoleData:getHero inserts each one,
    so a duplicate summon is a second row, not an error."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    assert len(heroes_of(conn, pid)) == 2


def test_an_unknown_category_raises(reg, cfg, conn) -> None:
    """Fail loud: a category this server cannot apply is a bug in the caller or
    a drop table this plan has not read, never a silently shrunk reward."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    with pytest.raises(ValueError, match="category 40"):
        grant_prizes(conn, cfg, pid, [(40, 5000000, 1)])


def test_an_unknown_category_leaves_the_earlier_prizes_unapplied(reg, cfg, conn) -> None:
    """One call is one transaction: the whole list is checked before anything is
    written, so a raise cannot leave half a reward behind."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100)
    with pytest.raises(ValueError):
        grant_prizes(conn, cfg, pid, [(1, 0, 500), (20, 10000, 1), (40, 5000000, 1)])
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 100
    assert items_of(conn, pid) == []


def test_an_item_config_does_not_know_raises_with_the_entry(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    with pytest.raises(KeyError, match="999999"):
        grant_prizes(conn, cfg, pid, [(20, 999999, 1)])
    assert items_of(conn, pid) == []


def test_a_hero_config_does_not_know_raises_with_the_entry(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    with pytest.raises(KeyError, match="999999"):
        grant_prizes(conn, cfg, pid, [(30, 999999, 1)])
    assert heroes_of(conn, pid) == []
