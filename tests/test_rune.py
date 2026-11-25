"""5_2161 RuneLevelUpReq and 5_2565 QueryHeroRuneReq.

Hero 100000 (the rose knight) has hero_rune_info rune0..rune4 = 1000000..
1004000. rune_info 1000000 is rune 10000, unlocked at hero level 30
(RuneDataHelp.lua:186,212). rune_level_up(10000, L) rows: level 0..3 need 20
energy, 2000 gold and 200 diamonds for the full step; level 1 gives max_hp 60,
level 2 120. A row's unlock_level is the hero level needed to reach that rune
level, so a level-30 hero caps rune 10000 at level 4 (getRuneMaxLevel,
RuneDataHelp.lua:511-530). The system opens at function(10170) = 35.

Op 1 feeds items: energy = item_info.rune_val x amount; gold = energy x
gold/rune_need of the level it lands in (getRuneCost, RuneDataHelp.lua:297-326,
rounded by toint). Op 2 buys `up_level` levels with diamonds: the rest of the
current level pro rata, rounded up, plus each following row's diamond
(getDiamondCostToLevel, RuneDataHelp.lua:710-742). Op 3 turns stored overflow
into levels (RuneCtr.lua:443-472). RuneLevelUpRes has no status field.
"""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, grant_item, heroes_of
from server.modules import hero, notify, rune
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
KNIGHT = 100000
CRYSTAL_S = 1200                     # 符文晶石(小), class 50, rune_val 10


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=1000)
    conn.execute("UPDATE players SET level = 35 WHERE id = ?", (pid,))
    conn.commit()
    grant_hero(conn, pid, KNIGHT, 10, star=1, level=30)
    handlers = rune.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _money(conn, pid) -> tuple[int, int]:
    row = conn.execute("SELECT gold, diamond FROM players WHERE id = ?", (pid,)).fetchone()
    return int(row["gold"]), int(row["diamond"])


def _rune_row(conn, pid, idx=0):
    return conn.execute(
        "SELECT level, rune_val FROM runes WHERE player_id = ? AND hero = ? AND idx = ?",
        (pid, KNIGHT, idx),
    ).fetchone()


def _level_up(reg, handlers, session, op, idx=0, items=(), up_level=None):
    req = reg.message_class("RuneLevelUpReq")(hero=KNIGHT, idx=idx, op=op)
    for refer, amount in items:
        req.items.add(refer=refer, amount=amount)
    if up_level is not None:
        req.up_level = up_level
    res = handlers[(5, 2161)](session, req)
    res.SerializeToString()
    return res


def _notifies(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


def test_feed_items_adds_rune_val(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, CRYSTAL_S, 3)
    res = _level_up(reg, handlers, session, 1, items=[(CRYSTAL_S, 1)])
    assert (res.hero, res.idx) == (KNIGHT, 0)
    assert (res.rune.idx, res.rune.level, res.rune.rune_val) == (0, 0, 10)
    assert tuple(_rune_row(conn, pid)) == (0, 10)
    # 10 energy at 2000 gold / 20 energy = 1000 gold, no diamonds.
    assert _money(conn, pid) == (99000, 1000)
    assert conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, CRYSTAL_S)
    ).fetchone()["amount"] == 2
    assert _notifies(session, notify.IDENT_ITEM)
    assert _notifies(session, notify.IDENT_PLAYER)


def test_gold_charge_levels_rune_and_adds_unit_stats(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    before = hero.build_client_hero_with_runes(
        reg, cfg, heroes_of(conn, pid)[0], hero.runes_of(conn, heroes_of(conn, pid)[0])
    )
    grant_item(conn, pid, CRYSTAL_S, 2)
    res = _level_up(reg, handlers, session, 1, items=[(CRYSTAL_S, 2)])
    # 20 energy fills level 0's rune_need 20 exactly: level 1, nothing left.
    assert (res.rune.level, res.rune.rune_val) == (1, 0)
    assert _money(conn, pid)[0] == 100000 - 2000
    row = heroes_of(conn, pid)[0]
    after = hero.build_client_hero_with_runes(reg, cfg, row, hero.runes_of(conn, row))
    assert after.unit.max_hp == before.unit.max_hp + 60
    assert after.base_unit.max_hp == before.base_unit.max_hp
    hero_notes = _notifies(session, notify.IDENT_HERO)
    assert len(hero_notes) == 1 and hero_notes[0].refer == KNIGHT


def test_feed_past_the_hero_level_cap_keeps_the_overflow_for_op3(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 1220, 1)               # 符文晶石(大), rune_val 200
    conn.execute("UPDATE players SET gold = 10000000 WHERE id = ?", (pid,))
    conn.commit()
    res = _level_up(reg, handlers, session, 1, items=[(1220, 1)])
    # Levels 0..3 need 20 each (80), level 4 needs 40 and is the cap at hero
    # level 30 (level 5 needs hero level 35): 120 energy stays at level 4.
    assert (res.rune.level, res.rune.rune_val) == (4, 120)
    conn.execute("UPDATE heroes SET level = 35 WHERE player_id = ?", (pid,))
    conn.commit()
    gold = _money(conn, pid)[0]
    res = _level_up(reg, handlers, session, 3)
    # 120 at level 4 (need 40), 5 (40), 6 (40): level 7 with 0 left, free.
    assert (res.rune.level, res.rune.rune_val) == (7, 0)
    assert _money(conn, pid)[0] == gold


def test_diamond_up_level_charges_rows(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, CRYSTAL_S, 1)
    _level_up(reg, handlers, session, 1, items=[(CRYSTAL_S, 1)])   # level 0, 10
    res = _level_up(reg, handlers, session, 2, up_level=2)
    # ceil((20 - 10) x 200 / 20) = 100 for the rest of level 0, + 200 for level 1.
    assert (res.rune.level, res.rune.rune_val) == (2, 0)
    assert _money(conn, pid)[1] == 1000 - 300
    assert tuple(_rune_row(conn, pid)) == (2, 0)


def test_diamond_up_level_past_the_cap_answers_unchanged(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _level_up(reg, handlers, session, 2, up_level=5)      # cap 4 at hero 30
    assert (res.rune.level, res.rune.rune_val) == (0, 0)
    assert _money(conn, pid) == (100000, 1000)
    assert _rune_row(conn, pid) is None
    assert session.outbox == []


def test_feed_without_gold_answers_unchanged(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, CRYSTAL_S, 1)
    conn.execute("UPDATE players SET gold = 999 WHERE id = ?", (pid,))
    conn.commit()
    res = _level_up(reg, handlers, session, 1, items=[(CRYSTAL_S, 1)])
    assert (res.rune.level, res.rune.rune_val) == (0, 0)
    assert _money(conn, pid) == (999, 1000)
    assert session.outbox == []


def test_locked_rune_answers_unchanged(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, CRYSTAL_S, 5)
    # rune2 (1002000) unlocks at hero level 50; the hero is 30.
    res = _level_up(reg, handlers, session, 1, idx=2, items=[(CRYSTAL_S, 1)])
    assert (res.idx, res.rune.idx, res.rune.level, res.rune.rune_val) == (2, 2, 0, 0)
    # Below function(10170) = 35 every rune is locked.
    conn.execute("UPDATE players SET level = 34 WHERE id = ?", (pid,))
    conn.commit()
    res = _level_up(reg, handlers, session, 1, idx=0, items=[(CRYSTAL_S, 1)])
    assert (res.rune.level, res.rune.rune_val) == (0, 0)
    assert _money(conn, pid) == (100000, 1000)
    assert session.outbox == []


def test_query_hero_rune_lists_five_runes_and_ability(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, CRYSTAL_S, 1)
    _level_up(reg, handlers, session, 1, items=[(CRYSTAL_S, 1)])
    req = reg.message_class("QueryHeroRuneReq")(owner=pid, entry=KNIGHT)
    res = handlers[(5, 2565)](session, req)
    res.SerializeToString()
    assert [(r.idx, r.level, r.rune_val) for r in res.runes] == [
        (0, 0, 10), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0),
    ]
    row = heroes_of(conn, pid)[0]
    assert res.ability == hero.build_client_hero(reg, cfg, row).ability
