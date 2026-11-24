"""ClientStock and prize granting (categories from ClientPlayer.lua:146-186)."""

import json
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
    """Tasks 11, 14 and 15 read these five keys by name off the return value;
    B3 adds the ids of the overflow mails."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [])
    assert set(out) == {"gold", "diamond", "energy", "items", "heroes", "mails"}


def test_grant_prizes_adds_energy_through_the_db_helper(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0, energy=10)
    out = grant_prizes(conn, cfg, pid, [(2, 0, 5)])
    assert out["energy"] == 15
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["energy"]) == 15


def test_duplicate_hero_converts_to_soul_stones(reg, cfg, conn) -> None:
    """MMAwardDropItem.lua:70-97: an owned hero arrives as
    HERO_DISCOUNT_STAR_{hero_info.star} of hero_info.item (category 20)."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    out = grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    info = cfg.hero(100000)
    stones = cfg.variable_int(f"HERO_DISCOUNT_STAR_{int(info['star'])}", 0)
    assert stones == 8
    assert len(heroes_of(conn, pid)) == 1
    assert out["heroes"] == []
    assert out["items"] == [(int(info["item"]), stones)]
    assert [(int(r["entry"]), int(r["amount"])) for r in items_of(conn, pid)] == [
        (int(info["item"]), stones)
    ]


def test_two_of_one_new_hero_in_one_call_is_a_hero_and_stones(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [(30, 101000, 2)])
    assert len(out["heroes"]) == 1
    assert out["items"] == [(101000, 8)]


def test_overflow_beyond_stackable_goes_to_mail_99999(reg, cfg, conn) -> None:
    """item_info.stackable caps a stock; the rest is mailed under template
    99999 物品超限提醒, one mail per call, named in the result."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    cap = int(cfg.item(10000)["stackable"])
    assert cap == 9999
    grant_item(conn, pid, 10000, cap - 9)
    out = grant_prizes(conn, cfg, pid, [(20, 10000, 20), (20, 1100, 1)])
    assert out["items"] == [(10000, cap), (1100, 1)]
    assert len(out["mails"]) == 1
    row = conn.execute("SELECT * FROM mails WHERE id = ?", (out["mails"][0],)).fetchone()
    assert int(row["player_id"]) == pid
    assert int(row["entry"]) == 99999
    assert json.loads(row["attachments"]) == [[20, 10000, 11]]
    assert row["body"] == cfg.item(10000)["name"]


def test_no_overflow_means_no_mail(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [(20, 10000, 5)])
    assert out["mails"] == []
    assert conn.execute("SELECT COUNT(*) FROM mails").fetchone()[0] == 0


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
