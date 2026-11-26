"""Hero rebirth: 5_2695 HeroTransmigrateReq (plan B2 Wave 3, task B7)."""

import logging
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero
from server.modules import rebirth
from server.modules.notify import IDENT_HERO, IDENT_PLAYER, HERO_FIELDS, PLAYER_FIELDS
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
HERO = 100000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1_000_000, diamond=0)
    conn.execute("UPDATE players SET level = 60 WHERE id = ?", (pid,))
    conn.commit()
    hero_id = grant_hero(conn, pid, HERO, 10, star=1, level=60)
    conn.execute("UPDATE heroes SET xp = 500 WHERE id = ?", (hero_id,))
    conn.commit()
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, hero_id, session


def _req(reg, entry=HERO):
    return reg.message_class("HeroTransmigrateReq")(entry=entry)


def _run(reg, settings, conn, cfg, session, entry=HERO):
    handlers = rebirth.handlers(reg, settings, conn, cfg)
    return handlers[(5, 2695)](session, _req(reg, entry))


def _hero(conn, hero_id):
    return conn.execute("SELECT * FROM heroes WHERE id = ?", (hero_id,)).fetchone()


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()["gold"])


def _notes(reg, session, ident):
    cls = reg.message_class("ClientNotification")
    out = []
    for service, cmd, msg in session.outbox:
        if (service, cmd) != (5, 2008):
            continue
        if not isinstance(msg, cls):
            msg = cls.FromString(msg)
        if msg.ident == ident:
            out.append(msg)
    return out


def _decode(msg, order) -> dict:
    names = [n for i, n in enumerate(order) if msg.flags >> i & 1]
    return dict(zip(names, msg.data))


def test_rebirth_below_55_changes_nothing(reg, settings, cfg, world, caplog) -> None:
    conn, pid, hero_id, session = world
    # The player below function 90000's level 55: 327957.
    conn.execute("UPDATE players SET level = 54 WHERE id = ?", (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.rebirth"):
        res = _run(reg, settings, conn, cfg, session)
    assert "327957" in caplog.text
    assert res.SerializeToString() == b""
    # The hero below need_level 55 of row 1: 327944.
    conn.execute("UPDATE players SET level = 60 WHERE id = ?", (pid,))
    conn.execute("UPDATE heroes SET level = 54 WHERE id = ?", (hero_id,))
    conn.commit()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.rebirth"):
        _run(reg, settings, conn, cfg, session)
    assert "327944" in caplog.text
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 0 and int(row["level"]) == 54
    assert _gold(conn, pid) == 1_000_000
    assert session.outbox == []


def test_rebirth_short_gold_changes_nothing(reg, settings, cfg, world, caplog) -> None:
    conn, pid, hero_id, session = world
    conn.execute("UPDATE players SET gold = 299999 WHERE id = ?", (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.rebirth"):
        _run(reg, settings, conn, cfg, session)
    assert "327937" in caplog.text
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 0 and int(row["level"]) == 60
    assert _gold(conn, pid) == 299999
    assert session.outbox == []


def test_rebirth_unknown_hero_or_top_changes_nothing(
    reg, settings, cfg, world, caplog
) -> None:
    conn, pid, hero_id, session = world
    with caplog.at_level(logging.WARNING, logger="loa.rebirth"):
        _run(reg, settings, conn, cfg, session, entry=999999)
    assert "327941" in caplog.text
    conn.execute("UPDATE heroes SET transmigrate_level = 15, level = 100 WHERE id = ?",
                 (hero_id,))
    conn.execute("UPDATE players SET level = 100 WHERE id = ?", (pid,))
    conn.commit()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.rebirth"):
        _run(reg, settings, conn, cfg, session)
    assert "top" in caplog.text
    assert int(_hero(conn, hero_id)["transmigrate_level"]) == 15
    assert _gold(conn, pid) == 1_000_000


def test_rebirth_costs_300000_and_raises_transmigrate_level(
    reg, settings, cfg, world
) -> None:
    conn, pid, hero_id, session = world
    res = _run(reg, settings, conn, cfg, session)
    res.SerializeToString()
    assert _gold(conn, pid) == 700_000
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 1
    # RoleData:getHeroInfoAfterRebirth: the xp of levels 55..59 plus 500,
    # re-levelled from 1, is level 49 with 26230 xp.
    assert (int(row["level"]), int(row["xp"])) == (49, 26230)


def test_rebirth_reset_follows_need_level_of_the_next_row(
    reg, settings, cfg, world
) -> None:
    conn, pid, hero_id, session = world
    conn.execute(
        "UPDATE heroes SET transmigrate_level = 1, level = 80, xp = 1234 WHERE id = ?",
        (hero_id,),
    )
    conn.execute("UPDATE players SET level = 80 WHERE id = ?", (pid,))
    conn.commit()
    _run(reg, settings, conn, cfg, session)
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 2
    assert (int(row["level"]), int(row["xp"])) == (75, 157464)
    assert _gold(conn, pid) == 400_000


def test_rebirth_stores_the_old_level_as_max_level(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    _run(reg, settings, conn, cfg, session)
    assert int(_hero(conn, hero_id)["max_level"]) == 60
    # A second rebirth from below the stored high keeps the high.
    conn.execute("UPDATE heroes SET level = 80, max_level = 90 WHERE id = ?", (hero_id,))
    conn.execute("UPDATE players SET level = 80 WHERE id = ?", (pid,))
    conn.commit()
    _run(reg, settings, conn, cfg, session)
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 2 and int(row["max_level"]) == 90


def test_rebirth_at_need_level_resets_to_1(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    conn.execute("UPDATE heroes SET level = 55, xp = 7 WHERE id = ?", (hero_id,))
    conn.commit()
    _run(reg, settings, conn, cfg, session)
    row = _hero(conn, hero_id)
    assert (int(row["level"]), int(row["xp"])) == (1, 7)


def test_rebirth_pushes_hero_notify(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    _run(reg, settings, conn, cfg, session)
    heroes = _notes(reg, session, IDENT_HERO)
    assert len(heroes) == 1 and heroes[0].refer == HERO
    fields = _decode(heroes[0], HERO_FIELDS)
    assert fields["transmigrate_level"] == 1
    assert fields["level"] == 49 and fields["xp"] == 26230
    # ClientHero.max_level "历史最高等级" keeps the level before the rebirth.
    assert fields["max_level"] == 60
    assert "ability" in fields and "max_hp" in fields
    players = _notes(reg, session, IDENT_PLAYER)
    assert len(players) == 1
    assert _decode(players[0], PLAYER_FIELDS) == {"gold": 700_000}


def test_rebirth_settles_the_training_slot_first(reg, settings, cfg, world) -> None:
    """The panel opens from the training screen (TrainCtr.lua:118-125), whose
    cell ticks xp locally; the hero's slot is settled before the level check."""
    conn, pid, hero_id, session = world
    conn.execute("UPDATE heroes SET level = 54, xp = 85499 WHERE id = ?", (hero_id,))
    conn.execute(
        "INSERT INTO trains (player_id, train, quality, refer_type, refer_id, cal_time)"
        " VALUES (?, 1, 1, 1, ?, 0)", (pid, HERO),
    )
    conn.commit()
    handlers = rebirth.handlers(reg, settings, conn, cfg, clock=lambda: 3600.0)
    handlers[(5, 2695)](session, _req(reg))
    row = _hero(conn, hero_id)
    assert int(row["transmigrate_level"]) == 1
    assert int(row["level"]) < 55


def test_bonus_growth_add_10pct(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    assert rebirth.bonus(conn, cfg, _hero(conn, hero_id)) == {}
    conn.execute("UPDATE heroes SET transmigrate_level = 1 WHERE id = ?", (hero_id,))
    conn.commit()
    growth = cfg.hero_growth(HERO, 1)
    out = rebirth.bonus(conn, cfg, _hero(conn, hero_id))
    # level 60 = 59 growth steps, growth_add 0.1 at transmigrate level 1
    assert out["max_hp"] == pytest.approx(59 * float(growth["max_hp"]) * 0.1)
    assert out["power"] == pytest.approx(59 * float(growth["power"]) * 0.1)
    assert all(v != 0 for v in out.values())
