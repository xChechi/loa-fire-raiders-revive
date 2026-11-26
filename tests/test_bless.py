"""Blessing (护佑): 5_2577, 5_2571, 5_2573, 5_2597, 5_2575 and bless.bonus.

Medal 10000 (战之斗魂) opens at 45 for warriors (medal_effect_type 1, arg 1).
Its slots: 0 (angel), 1 and 2 free at level 1; 3 at 45 for 5000 diamonds,
4 at 60 for 10000, 5 at 75 for 20000. Eligible: angels 903000/909000/502000,
heroes 203000/207000/213000/211000/320000/323000/330000/336000. Every hero
prototype has npc_info.ability 1000, so a hero scores floor(1.2 × 1000) =
1200 and an angel 0. Rank rows: level 0 leaves at 3000 (entry 10000), level 1
(entry 10010) has power/magic/agility 40 and hit/crit 20. Crystal 10000
level 0 costs 10000 gold, 20 × 1600 and one each of 2000000/2000010/2000020;
level 1 gives crystal_effect 0.06.
"""

import json
import logging
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_angel, grant_hero, grant_item
from server.modules import bless
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
MEDAL = 10000
WARRIOR_IN_MEDAL = 203000            # vocation 1, eligible for 10000
MAGE_IN_MEDAL = 207000               # vocation 2, eligible for 10000
ARCHER_IN_MEDAL = 213000             # eligible for 10000
WARRIOR_OUTSIDE = 100000             # vocation 1, not in 10000's list
ANGEL_IN_MEDAL = 903000
PUNCH = 1500


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=6000)
    conn.execute("UPDATE players SET level = 45 WHERE id = ?", (pid,))
    conn.commit()
    handlers = bless.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _set_level(conn, pid, level) -> None:
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (level, pid))
    conn.commit()


def _money(conn, pid) -> tuple[int, int]:
    row = conn.execute("SELECT gold, diamond FROM players WHERE id = ?", (pid,)).fetchone()
    return int(row["gold"]), int(row["diamond"])


def _item(conn, pid, entry) -> int:
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
    ).fetchone()
    return int(row["amount"]) if row else 0


def _call(reg, handlers, session, key, name, **fields):
    return handlers[key](session, reg.message_class(name)(**fields))


def _query(reg, handlers, session):
    return _call(reg, handlers, session, (5, 2577), "BlessQueryReq")


def _buy(reg, handlers, session, location, medal=MEDAL):
    return _call(reg, handlers, session, (5, 2571), "BlessBuyLocationReq",
                 id=medal, location=location)


def _add(reg, handlers, session, entry, location, medal=MEDAL):
    return _call(reg, handlers, session, (5, 2573), "BlessHeroAddReq",
                 id=medal, entry=entry, location=location)


def _quick(reg, handlers, session, medal=MEDAL):
    return _call(reg, handlers, session, (5, 2597), "BlessQuickAddUnitReq", id=medal)


def _fuse(reg, handlers, session, medal=MEDAL):
    return _call(reg, handlers, session, (5, 2575), "BlessFusingReq", id=medal)


def _medal_info(infos, medal=MEDAL):
    return next(i for i in infos if i.entry == medal)


def _queued(session, cmd):
    return [m for s, c, m in session.outbox if (s, c) == (5, cmd)]


def test_query_below_level45_refused_327957(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_level(conn, pid, 44)
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _query(reg, handlers, session)
    assert list(res.bless_infos) == []
    assert "327957" in caplog.text


def test_query_lists_medal_10000_at_level45(reg, world) -> None:
    _conn, _pid, handlers, session = world
    res = _query(reg, handlers, session)
    assert [i.entry for i in res.bless_infos] == [10000, 20000, 30000, 40000, 50000, 60000]
    info = _medal_info(res.bless_infos)
    assert info.id == MEDAL
    assert list(info.units) == [1, 1, 1, 0, 0, 0]
    assert list(info.scores) == [0] * 6
    assert (info.medalsore, info.level, info.ranklevel) == (0, 0, 10000)
    assert info.crystalbonus == 0


def test_slot3_costs_5000_diamonds(reg, world) -> None:
    conn, pid, handlers, session = world
    _buy(reg, handlers, session, 3)
    assert _money(conn, pid) == (100000, 1000)
    assert list(_medal_info(_query(reg, handlers, session).bless_infos).units)[3] == 1
    assert _queued(session, 2594) == []


def test_slot3_spends_owned_punches_first(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, PUNCH, 20)
    _buy(reg, handlers, session, 3)
    assert _item(conn, pid, PUNCH) == 0
    assert _money(conn, pid) == (100000, 3000)


def test_slot3_short_of_diamonds_changes_nothing(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET diamond = 4999 WHERE id = ?", (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        _buy(reg, handlers, session, 3)
    assert "327938" in caplog.text
    assert _money(conn, pid) == (100000, 4999)
    (pushed,) = _queued(session, 2594)
    assert list(_medal_info(pushed.bless_infos).units)[3] == 0


def test_slot4_needs_level60_refused_338001(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_level(conn, pid, 59)
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        _buy(reg, handlers, session, 4)
    assert "338001" in caplog.text
    assert _money(conn, pid) == (100000, 6000)
    (pushed,) = _queued(session, 2594)
    assert list(_medal_info(pushed.bless_infos).units)[4] == 0


def test_add_eligible_hero_scores_it(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, WARRIOR_IN_MEDAL, 10, level=45)
    res = _add(reg, handlers, session, WARRIOR_IN_MEDAL, 1)
    assert list(res.bless_info.units) == [1, WARRIOR_IN_MEDAL, 1, 0, 0, 0]
    assert list(res.bless_info.scores) == [0, 1200, 0, 0, 0, 0]
    assert res.bless_info.medalsore == 1200
    assert res.bless_info.infos[0].entry == WARRIOR_IN_MEDAL
    row = conn.execute("SELECT score, units FROM bless WHERE player_id = ?", (pid,)).fetchone()
    assert (row["score"], json.loads(row["units"])) == (1200, [0, WARRIOR_IN_MEDAL, 0, 0, 0, 0])


def test_add_ineligible_hero_refused(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, WARRIOR_OUTSIDE, 10, level=45)
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _add(reg, handlers, session, WARRIOR_OUTSIDE, 1)
    assert "327681" in caplog.text
    assert list(res.bless_info.units) == [1, 1, 1, 0, 0, 0]
    # A hero not owned and a hero in the angel slot are refused the same way.
    res = _add(reg, handlers, session, MAGE_IN_MEDAL, 1)
    assert list(res.bless_info.units) == [1, 1, 1, 0, 0, 0]
    grant_hero(conn, pid, MAGE_IN_MEDAL, 10, level=45)
    res = _add(reg, handlers, session, MAGE_IN_MEDAL, 0)
    assert list(res.bless_info.units) == [1, 1, 1, 0, 0, 0]


def test_add_to_a_locked_slot_refused_338001(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, WARRIOR_IN_MEDAL, 10, level=45)
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _add(reg, handlers, session, WARRIOR_IN_MEDAL, 3)
    assert "338001" in caplog.text
    assert list(res.bless_info.units) == [1, 1, 1, 0, 0, 0]


def test_third_hero_raises_the_rank_and_pushes_5_2588(reg, world) -> None:
    conn, pid, handlers, session = world
    _buy(reg, handlers, session, 3)
    for location, entry in enumerate((WARRIOR_IN_MEDAL, MAGE_IN_MEDAL, ARCHER_IN_MEDAL), 1):
        grant_hero(conn, pid, entry, 10, level=45)
        res = _add(reg, handlers, session, entry, location)
    assert res.bless_info.medalsore == 3600
    assert res.bless_info.ranklevel == 10010
    (pushed,) = _queued(session, 2588)
    assert (pushed.pre_ranklevel_entry, pushed.cur_ranklevel_entry) == (10000, 10010)


def test_quick_add_fills_open_slots(reg, world) -> None:
    conn, pid, handlers, session = world
    for entry in (ARCHER_IN_MEDAL, MAGE_IN_MEDAL, WARRIOR_IN_MEDAL, WARRIOR_OUTSIDE):
        grant_hero(conn, pid, entry, 10, level=45)
    grant_angel(conn, pid, ANGEL_IN_MEDAL, 1, 1)
    res = _quick(reg, handlers, session)
    # Slots 0-2 are open; equal scores fall back to the lower entry.
    assert list(res.bless_info.units) == [ANGEL_IN_MEDAL, WARRIOR_IN_MEDAL, MAGE_IN_MEDAL, 0, 0, 0]
    assert res.bless_info.medalsore == 2400
    assert res.bless_info.info.entry == ANGEL_IN_MEDAL


def test_quick_add_with_nothing_owned_refused_338009(reg, world, caplog) -> None:
    _conn, _pid, handlers, session = world
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _quick(reg, handlers, session)
    assert "338009" in caplog.text
    assert list(res.bless_info.units) == [1, 1, 1, 0, 0, 0]


def test_crystal_level_up_charges_row0(reg, world) -> None:
    conn, pid, handlers, session = world
    for entry, amount in ((1600, 25), (2000000, 1), (2000010, 1), (2000020, 1)):
        grant_item(conn, pid, entry, amount)
    res = _fuse(reg, handlers, session)
    info = _medal_info(res.bless_infos)
    assert (info.level, round(info.crystalbonus, 6)) == (1, 0.06)
    assert len(res.bless_infos) == 6
    assert _money(conn, pid) == (90000, 6000)
    assert [_item(conn, pid, e) for e in (1600, 2000000, 2000010, 2000020)] == [5, 0, 0, 0]


def test_crystal_level_up_short_of_items_changes_nothing(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 1600, 19)
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _fuse(reg, handlers, session)
    assert "327942" in caplog.text
    assert _medal_info(res.bless_infos).level == 0
    assert _money(conn, pid) == (100000, 6000)
    assert _item(conn, pid, 1600) == 19


def test_crystal_at_top_refused_338002(reg, world, caplog) -> None:
    conn, pid, handlers, session = world
    conn.execute(
        "INSERT INTO bless (player_id, medal, crystal_level) VALUES (?, ?, 14)", (pid, MEDAL)
    )
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.bless"):
        res = _fuse(reg, handlers, session)
    assert "338002" in caplog.text
    assert _medal_info(res.bless_infos).level == 14


def test_decompose_is_not_handled_yet(reg, world) -> None:
    """5_2671 pays category 70 (秘藏币), which has no players column: A5b."""
    _conn, _pid, handlers, _session = world
    assert (5, 2671) not in handlers


def test_bonus_adds_medal_percentages(reg, cfg, world) -> None:
    conn, pid, _handlers, _session = world
    for entry in (WARRIOR_IN_MEDAL, MAGE_IN_MEDAL, ARCHER_IN_MEDAL, WARRIOR_OUTSIDE):
        grant_hero(conn, pid, entry, 10, level=45)
    conn.execute(
        "INSERT INTO bless (player_id, medal, slots, units) VALUES (?, ?, '[3]', ?)",
        (pid, MEDAL, json.dumps([0, WARRIOR_IN_MEDAL, MAGE_IN_MEDAL, ARCHER_IN_MEDAL, 0, 0])),
    )
    conn.commit()

    def hero_row(entry):
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ?", (pid, entry)
        ).fetchone()

    # Score 3600 -> rank 1 (10010): 40 + 0.04 × 3600 and 20 + 0.02 × 3600.
    expected = {"power": 184.0, "magic": 184.0, "agility": 184.0,
                "hit_base": 92.0, "crit_base": 92.0}
    assert bless.bonus(conn, cfg, hero_row(WARRIOR_IN_MEDAL)) == expected
    # The medal blesses every warrior, placed or not, and no mage.
    assert bless.bonus(conn, cfg, hero_row(WARRIOR_OUTSIDE)) == expected
    assert bless.bonus(conn, cfg, hero_row(MAGE_IN_MEDAL)) == {}
    # Crystal level 1 (0.06) scales and floors: 184 × 1.06 = 195.04.
    conn.execute("UPDATE bless SET crystal_level = 1 WHERE player_id = ?", (pid,))
    conn.commit()
    assert bless.bonus(conn, cfg, hero_row(WARRIOR_OUTSIDE))["power"] == 195.0


def test_bless_responses_serialise(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, WARRIOR_IN_MEDAL, 10, level=45)
    grant_angel(conn, pid, ANGEL_IN_MEDAL, 1, 1)
    for entry, amount in ((1600, 20), (2000000, 1), (2000010, 1), (2000020, 1)):
        grant_item(conn, pid, entry, amount)
    responses = [
        _query(reg, handlers, session),
        _buy(reg, handlers, session, 3),
        _buy(reg, handlers, session, 4),
        _add(reg, handlers, session, WARRIOR_IN_MEDAL, 1),
        _add(reg, handlers, session, WARRIOR_OUTSIDE, 2),
        _quick(reg, handlers, session),
        _fuse(reg, handlers, session),
        _fuse(reg, handlers, session),
        _add(reg, handlers, session, WARRIOR_IN_MEDAL, 1, medal=999),
    ]
    for res in responses + [m for _s, _c, m in session.outbox]:
        assert res.IsInitialized()
        type(res).FromString(res.SerializeToString())
