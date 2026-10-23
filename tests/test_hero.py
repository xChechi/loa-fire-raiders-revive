"""ClientHero built from hero_quality + npc_info + hero_growth, never invented."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, heroes_of
from server.modules.hero import build_client_hero, prototype_for
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
def hero_row(tmp_path, cfg):
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_hero(conn, pid, 100000, 10, star=1, level=1)
    return heroes_of(conn, pid)[0]


def _granted(tmp_path, entry, quality, star=1, level=1):
    conn = connect(tmp_path / "p.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_hero(conn, pid, entry, quality, star=star, level=level)
    return heroes_of(conn, pid)[0]


def test_prototype_comes_from_hero_quality(cfg) -> None:
    assert prototype_for(cfg, 100000, 10) == 100000
    assert prototype_for(cfg, 100000, 20) == 100010


def test_client_hero_quality_exists_in_hero_quality(reg, cfg, hero_row, tmp_path) -> None:
    """Review Focus 2: ClientHero:getNpcProperty indexes npcList[1][key] with no
    nil check, so a quality with no hero_quality row kills the Lua VM."""
    keys = {int(r["quality"]) for r in cfg.hero_qualities(100000)}
    hero = build_client_hero(reg, cfg, hero_row)
    assert hero.quality in keys
    assert cfg.npc(hero.prototype) is not None
    # hero_info.quality for 100000 is 0 and hero_quality has no row for 0, so a
    # row stamped from hero_info must still leave the client a usable key.
    assert int(cfg.hero(100000)["quality"]) not in keys
    off = build_client_hero(reg, cfg, _granted(tmp_path, 100000, 0))
    assert off.quality in keys
    assert cfg.npc(off.prototype) is not None


def test_client_hero_level_one_is_the_prototype_row(reg, cfg, hero_row) -> None:
    hero = build_client_hero(reg, cfg, hero_row)
    assert hero.entry == 100000
    assert hero.prototype == 100000
    assert hero.quality == 10
    assert hero.star == 1
    assert hero.level == 1
    assert hero.xp == 0
    assert hero.ability == 1000
    assert hero.unit.max_hp == 100
    assert hero.unit.power == 15.0
    assert hero.unit.defence == 5.0
    assert hero.unit.hit_rate == 0.95
    assert hero.unit.initial_energy == 500.0
    assert hero.unit.max_energy == 1000.0
    assert hero.base_unit.max_hp == 100
    assert list(hero.spells) == [1000000]
    assert hero.SerializeToString()


def test_client_hero_level_three_adds_growth_twice(reg, cfg, tmp_path) -> None:
    row = _granted(tmp_path, 100000, 10, star=1, level=3)
    hero = build_client_hero(reg, cfg, row)
    # npc 100 + 2 x hero_growth(100000, 1).max_hp 40.92 = 181.84, int for uint32
    assert hero.unit.max_hp == 181
    assert round(hero.unit.power, 3) == round(15 + 2 * 5.346, 3)


def test_every_required_field_is_set(reg, cfg, hero_row) -> None:
    """Review Focus 1 of Plan A: proto2 required fields raise at send time."""
    hero = build_client_hero(reg, cfg, hero_row)
    hero.SerializeToString()
    assert not hero.FindInitializationErrors()


def test_a_hero_with_no_config_rows_fails_loud(reg, cfg, tmp_path) -> None:
    """Task 6 rule: a missing config row raises instead of inventing a stat."""
    row = _granted(tmp_path, 999999999, 10)
    with pytest.raises(KeyError, match="999999999"):
        build_client_hero(reg, cfg, row)
