"""ClientStock and prize granting (categories from ClientPlayer.lua:146-186)."""

import json
from pathlib import Path

import pytest

from server.config import Config
from server.db import (
    angels_of, connect, create_player, grant_item, heroes_of, items_of,
)
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
    B3 adds the ids of the overflow mails, the player xp change and the
    angels granted; W1 the indices of the heroes that became soul stones."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [])
    assert set(out) == {
        "gold", "diamond", "energy", "items", "heroes", "mails", "xp", "angels",
        "converted", "coins",
    }
    assert out["xp"] is None and out["angels"] == [] and out["converted"] == []
    assert out["coins"] == {}


def test_categories_51_and_52_add_arena_and_goddess_trial_coins(reg, cfg, conn) -> None:
    """ClientPlayer.lua:150-151,652-655: 51 is arena_point, 52 angel_money.
    `coins` carries the new absolute value of each one touched."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [(51, 0, 1000), (52, 0, 300), (52, 0, 700)])
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert (int(row["arena_point"]), int(row["angel_money"])) == (1000, 1000)
    assert out["coins"] == {"arena_point": 1000, "angel_money": 1000}
    again = grant_prizes(conn, cfg, pid, [(51, 0, 5)])
    assert again["coins"] == {"arena_point": 1005}


def test_category_11_adds_player_xp(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    need = int(cfg.xp_for_level(1)["player_xp_for_next_level"])
    out = grant_prizes(conn, cfg, pid, [(11, 0, need + 1)])
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert (int(row["level"]), int(row["xp"])) == (2, 1)
    assert out["xp"]["levelled"] is True
    assert out["xp"]["before"][0] == 1 and out["xp"]["after"][0] == 2
    small = grant_prizes(conn, cfg, pid, [(11, 0, 1)])
    assert small["xp"]["levelled"] is False


def test_category_40_grants_or_converts_angel(reg, cfg, conn) -> None:
    """A new angel is granted at star 1; an owned one arrives as
    ANGEL_DISCOUNT_STAR_{star} of activation_item, star and item read off the
    angel's first angel_info row (MMAwardDropItem.lua:105-129)."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [(40, 500000, 1)])
    assert out["angels"] == [500000]
    rows = angels_of(conn, pid)
    assert [(int(r["angel_entry"]), int(r["star"])) for r in rows] == [(500000, 1)]
    info = cfg.angel_by_star(500000, 1)
    assert int(rows[0]["level"]) == int(info["min_level"])

    again = grant_prizes(conn, cfg, pid, [(40, 500000, 1)])
    assert again["angels"] == []
    assert len(angels_of(conn, pid)) == 1
    stones = cfg.variable_int("ANGEL_DISCOUNT_STAR_1", 0)
    assert stones == 8
    assert again["items"] == [(int(info["activation_item"]), stones)]


def test_an_angel_without_a_star1_row_raises(reg, cfg, conn) -> None:
    """5000000 is in angel_info but starts at star 3, so it cannot be granted
    at star 1; 999999 is not there at all. Both are refused before any write
    (ValueError, which test_gacha's poison case (40, 1, 1) also expects)."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100)
    for refer in (5000000, 999999):
        with pytest.raises(ValueError, match=str(refer)):
            grant_prizes(conn, cfg, pid, [(1, 0, 500), (40, refer, 1)])
    assert angels_of(conn, pid) == []
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 100


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


def test_granted_hero_starts_at_hero_info_star_and_init_level(reg, cfg, conn) -> None:
    """A prize hero arrives the way the soul-stone summon (5_2105) grants one:
    hero_info.star and hero_info.init_level. 304000 (7-day gift day 2,
    LOGIN_AWARD drop 700010) is a 3-star hero starting at level 5; 100000 is
    1-star at level 1, so the two together pin both columns."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_prizes(conn, cfg, pid, [(30, 304000, 1), (30, 100000, 1)])
    by_entry = {int(h["entry"]): h for h in heroes_of(conn, pid)}
    info = cfg.hero(304000)
    assert (int(info["star"]), int(info["init_level"])) == (3, 5)
    assert int(by_entry[304000]["star"]) == 3
    assert int(by_entry[304000]["level"]) == 5
    assert int(by_entry[100000]["star"]) == 1
    assert int(by_entry[100000]["level"]) == 1


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
    with pytest.raises(ValueError, match="category 12"):
        grant_prizes(conn, cfg, pid, [(12, 0, 1)])


def test_an_unknown_category_leaves_the_earlier_prizes_unapplied(reg, cfg, conn) -> None:
    """One call is one transaction: the whole list is checked before anything is
    written, so a raise cannot leave half a reward behind."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100)
    with pytest.raises(ValueError):
        grant_prizes(conn, cfg, pid, [(1, 0, 500), (20, 10000, 1), (12, 0, 1)])
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


# --- W1: the client side of grant_prizes' result ------------------------------


def _session():
    from server.net.server import Session

    return Session(writer=None, peer="t", bound_port=0)


def test_grant_prizes_reports_which_hero_prizes_became_soul_stones(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    out = grant_prizes(conn, cfg, pid, [(1, 0, 5), (30, 101000, 1), (30, 100000, 1)])
    assert out["converted"] == [2]


def test_mark_converted_sets_extra_type_1_on_those_entries_only(reg, cfg, conn) -> None:
    """MMAwardDropItem.lua:74 shows the soul-stone conversion of a hero prize
    only when extra.type == 1; TavernUtil.lua:22,365 and TavernCoin.lua:115,200
    read the same flag."""
    from server.modules import item

    cls = reg.message_class("ClientPrizeEntry")
    entries = [cls(category=1, refer=0, amount=5), cls(category=30, refer=100000, amount=1)]
    item.mark_converted(entries, {"converted": [1]})
    assert not entries[0].HasField("extra")
    assert entries[1].extra.type == 1


def test_announce_queues_the_mail_notify_for_an_overflow_mail(reg, cfg, conn) -> None:
    from server.modules import item

    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 10000, int(cfg.item(10000)["stackable"]))
    out = grant_prizes(conn, cfg, pid, [(20, 10000, 3)])
    session = _session()
    item.announce(reg, session, out)
    assert [(c, m.ident) for (_s, c, m) in session.outbox] == [(2008, 7)]


def test_announce_queues_player_xp_and_the_level_up(reg, cfg, conn) -> None:
    from server.modules import item, notify

    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    need = int(cfg.xp_for_level(1)["player_xp_for_next_level"])
    out = grant_prizes(conn, cfg, pid, [(11, 0, need + 1)])
    session = _session()
    item.announce(reg, session, out)
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008), (5, 2036)]
    player_msg, level_up = session.outbox[0][2], session.outbox[1][2]
    assert player_msg.ident == 1
    fields = [n for n in notify.PLAYER_FIELDS if n in ("level", "xp", "energy", "max_energy")]
    assert player_msg.flags == notify.flags_for(fields)
    assert dict(zip(fields, map(int, player_msg.data)))["level"] == 2
    assert (level_up.oldLevel, level_up.newLevel) == (1, 2)


def test_announce_xp_without_a_level_up_sends_no_level_up(reg, cfg, conn) -> None:
    from server.modules import item

    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    session = _session()
    item.announce(reg, session, grant_prizes(conn, cfg, pid, [(11, 0, 1)]))
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008)]


def test_announce_pushes_the_coins_as_one_player_notify(reg, cfg, conn) -> None:
    from server.modules import item, notify

    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    session = _session()
    item.announce(reg, session, grant_prizes(conn, cfg, pid, [(51, 0, 7), (52, 0, 9)]))
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008)]
    msg = session.outbox[0][2]
    assert msg.flags == notify.flags_for(["angel_money", "arena_point"])
    # data follows PLAYER_FIELDS order: angel_money (16) before arena_point (17).
    assert list(msg.data) == [9.0, 7.0]


def test_announce_is_silent_for_plain_prizes_and_angels(reg, cfg, conn) -> None:
    """A new angel has no push the client listens to: AngelNotify 5_2932 has
    no Lua listener and ident 3 skips an angel without serverInfo
    (ClientAngel.lua:131-133). It shows up with the next QueryMyselfRes."""
    from server.modules import item

    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    session = _session()
    item.announce(reg, session, grant_prizes(conn, cfg, pid, [(1, 0, 5), (40, 500000, 1)]))
    assert session.outbox == []
