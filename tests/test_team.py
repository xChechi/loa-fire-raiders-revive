"""5_2327 QuerySelfTeamReq / 5_2328 QuerySelfTeamRes.

The emulator run of Task 17 found this one: the client sends 5_2327 between
LevelIntoRes and openFight, and an empty 5_2328 leaves team_base nil, which
kills the Lua VM at LineTeam.lua:34 before any fight can start.

Request slots (FunctionType.lua:1104-1133): param[pos+1] = the hero entry of
the layout unit at pos, the angel goes to param[1], and seven slots are always
sent. So units[0] is the angel slot and units[i] is layout position i.
"""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero
from server.modules import team
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")

# The starting hero: PLAYER_HERO_INIT 100000, hero_quality quality 10,
# prototype npc_info 100000 (ability 1000, max_hp 100, power 15, skill0
# 1000000 and no other skill).
HERO = 100000
QUALITY = 10


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
    """A fresh character with exactly the starting hero, as login grants it."""
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    row_id = grant_hero(conn, pid, HERO, QUALITY, star=1, level=1)
    handlers = team.handlers(reg, settings, conn, cfg, rng=random.Random(7))
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, row_id, handlers, session


def _req(reg, units: list[int], fight_type: int = 1):
    msg = reg.message_class("QuerySelfTeamReq")(fight_type=fight_type, refer=0)
    for entry in units:
        msg.units.append(entry)
    for _ in range(7):
        msg.renter_units.append(0)
    return msg


def test_the_fresh_character_team_carries_its_one_hero(reg, cfg, world) -> None:
    conn, pid, row_id, handlers, session = world
    res = handlers[(5, 2327)](session, _req(reg, [0, HERO, 0, 0, 0, 0, 0]))
    assert res.HasField("team_base")
    assert [u.refer for u in res.team_base.units] == [HERO]
    unit = res.team_base.units[0]
    # ClientFightUnit has no field for our heroes row id: type 1 means refer is
    # the hero entry, the key BattleUnit:initByServerFightHero looks hero_quality
    # up by (BattleUnit.lua:3941-3946). The row is what supplies the rest.
    assert unit.type == 1
    assert unit.position == 1
    assert (unit.star, unit.quality, unit.level) == (1, QUALITY, 1)
    assert unit.ability == 1000
    assert list(unit.spells) == [1000000]
    assert unit.unit.max_hp == 100          # npc_info 100000, never a literal here
    assert unit.unit.power == 15
    assert row_id == 1                      # the row the values came from
    res.SerializeToString()


def test_the_team_base_names_the_player(reg, cfg, world) -> None:
    conn, pid, _row_id, handlers, session = world
    res = handlers[(5, 2327)](session, _req(reg, [0, HERO, 0, 0, 0, 0, 0]))
    base = res.team_base
    assert base.id == pid
    assert base.name == "stefan"
    assert base.level == 1                  # BattleFactoryBase:getTeamLevel
    assert base.fightAbility == 1000        # the one hero's ability
    assert base.origin == ""


def test_the_response_carries_64_randoms(reg, cfg, world) -> None:
    """FightData:initSelfTeam overwrites FightData.randoms with this list and
    traces !!!!!!!!ERR no randoms below 64 (FightData.lua:92-95)."""
    _conn, _pid, _row_id, handlers, session = world
    res = handlers[(5, 2327)](session, _req(reg, [0, HERO, 0, 0, 0, 0, 0]))
    assert len(res.urandom) == 64
    assert all(0 <= v < 10000 for v in res.urandom)


def test_the_slot_follows_the_request_index(reg, cfg, world) -> None:
    """getServerAttackerInfo matches toint(serverInfo.position) against the
    layout place (BattleFactoryBase.lua:171-184), and getLayoutTeam numbers
    heroes from 1 with the angel at 8."""
    _conn, _pid, _row_id, handlers, session = world
    res = handlers[(5, 2327)](session, _req(reg, [0, 0, 0, HERO, 0, 0, 0]))
    assert [u.position for u in res.team_base.units] == [3]


def test_a_player_with_no_heroes_gets_a_team_with_no_units(
    reg, cfg, settings, world
) -> None:
    """LineTeam:initByServerTeamBase indexes team itself (line 34) but reads
    `self.units=team.units or {}` (line 42), and a missing server unit is only
    a trace in getServerAttackerInfo. So an empty unit list is survivable and a
    missing team_base is not."""
    conn, pid, _row_id, handlers, session = world
    conn.execute("DELETE FROM heroes WHERE player_id = ?", (pid,))
    conn.commit()
    res = handlers[(5, 2327)](session, _req(reg, [0, HERO, 0, 0, 0, 0, 0]))
    assert res.HasField("team_base")
    assert len(res.team_base.units) == 0
    assert res.team_base.name == "stefan"
    assert len(res.urandom) == 64
    res.SerializeToString()


def test_query_self_team_answers_an_empty_team_when_no_character_exists(
    reg, cfg, settings, caplog
) -> None:
    """The row-is-None branch (team.py:158-165). QuerySelfTeamRes has no status
    field, so the client cannot be refused: a missing team_base kills the Lua
    VM at LineTeam.lua:34. An empty team plus a WARNING is the only answer."""
    conn = connect(settings.db_path)
    handlers = team.handlers(reg, settings, conn, cfg, rng=random.Random(7))
    session = Session(writer=None, peer="t", bound_port=0)

    with caplog.at_level("WARNING"):
        res = handlers[(5, 2327)](session, _req(reg, [0, HERO, 0, 0, 0, 0, 0]))

    assert session.player_id is None
    assert res.HasField("team_base")
    assert len(res.team_base.units) == 0
    assert len(res.urandom) == 64
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    res.SerializeToString()


def test_an_entry_the_player_does_not_own_is_skipped_and_logged(
    reg, cfg, world, caplog
) -> None:
    _conn, _pid, _row_id, handlers, session = world
    with caplog.at_level("WARNING"):
        res = handlers[(5, 2327)](session, _req(reg, [0, 303000, HERO, 0, 0, 0, 0]))
    assert [u.refer for u in res.team_base.units] == [HERO]
    assert "303000" in caplog.text


def test_the_angel_slot_is_not_read_as_a_hero(reg, cfg, world, caplog) -> None:
    """units[0] is the angel (FunctionType.lua:1117 param[1]), and Plan B1 has
    no angels, so an entry there is refused rather than built as a hero."""
    _conn, _pid, _row_id, handlers, session = world
    with caplog.at_level("WARNING"):
        res = handlers[(5, 2327)](session, _req(reg, [701000, HERO, 0, 0, 0, 0, 0]))
    assert [u.position for u in res.team_base.units] == [1]
    assert "701000" in caplog.text


def test_the_refer_of_the_request_is_echoed(reg, cfg, world) -> None:
    """BattleFactoryCoinTry:199 sends attackerTeamRefer back to the server."""
    _conn, _pid, _row_id, handlers, session = world
    req = _req(reg, [0, HERO, 0, 0, 0, 0, 0])
    req.refer = 4242
    res = handlers[(5, 2327)](session, req)
    assert res.refer == 4242


def test_a_hired_unit_is_refused_and_logged(reg, cfg, world, caplog) -> None:
    _conn, _pid, _row_id, handlers, session = world
    req = _req(reg, [0, HERO, 0, 0, 0, 0, 0])
    req.renter = 99
    req.renter_units[1] = 303000
    with caplog.at_level("WARNING"):
        res = handlers[(5, 2327)](session, req)
    assert [u.refer for u in res.team_base.units] == [HERO]
    assert "renter" in caplog.text.lower() or "hire" in caplog.text.lower()
