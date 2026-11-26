"""Artifacts (plan B2 Wave 3, task B9; O-W3-10).

The start kit ARTIFACT_INIT is the eight green 风灵 artifacts 1502000-1502700
(positions 7, 1, 8, 6, 5, 4, 3, 2), the smelt-only 1500100, two small crystals
1500001 and 50 advance stones 1400, all inventory items (category 20)."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import artifact, notify
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
DAGGER = 1502000        # 风灵匕首, quality 2, position 7
HOOD = 1502100          # 风灵兜帽, position 1
KIT = {1502000: 1, 1502100: 1, 1502200: 1, 1502300: 1, 1502400: 1, 1502500: 1,
       1502600: 1, 1502700: 1, 1500100: 1, 1500001: 2, 1400: 50}


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
    conn.execute("UPDATE players SET level = 57 WHERE id = ?", (pid,))
    conn.commit()
    handlers = artifact.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _items(conn, pid) -> dict[int, int]:
    return {int(r["entry"]): int(r["amount"]) for r in conn.execute(
        "SELECT entry, amount FROM items WHERE player_id = ?", (pid,))}


def _rows(conn, pid):
    return conn.execute(
        "SELECT * FROM artifacts WHERE player_id = ? ORDER BY id", (pid,)
    ).fetchall()


def _queued(session, service, cmd):
    return [m for (s, c, m) in session.outbox if (s, c) == (service, cmd)]


def _main(handlers, session, reg):
    return handlers[(5, 2533)](session, reg.message_class("ArtifactMainReq")())


def _equip(handlers, session, reg, **kw):
    return handlers[(5, 2541)](session, reg.message_class("ArtifactEquipReq")(**kw))


def test_first_main_grants_artifact_init_once(world, reg):
    conn, pid, handlers, session = world
    res = _main(handlers, session, reg)
    assert _items(conn, pid) == KIT
    assert len(res.equiped) == 0 and res.af_info.ability == 0
    assert conn.execute("SELECT artifact_init FROM players WHERE id = ?", (pid,)).fetchone()[0] == 1
    assert _queued(session, 5, 2008)           # the inventory notify
    _main(handlers, session, reg)
    assert _items(conn, pid) == KIT            # not twice


def test_main_below_57_grants_nothing(world, reg):
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET level = 56 WHERE id = ?", (pid,))
    conn.commit()
    _main(handlers, session, reg)
    assert _items(conn, pid) == {}
    assert conn.execute("SELECT artifact_init FROM players WHERE id = ?", (pid,)).fetchone()[0] == 0


def test_equip_by_position(world, reg, cfg):
    conn, pid, handlers, session = world
    _main(handlers, session, reg)
    session.outbox.clear()
    res = _equip(handlers, session, reg, entry=DAGGER)
    (row,) = _rows(conn, pid)
    assert (int(row["entry"]), int(row["level"]), int(row["exp"]), int(row["hero"])) == (DAGGER, 1, 0, 1)
    assert DAGGER not in _items(conn, pid)
    assert [(e.id, e.entry, e.level, e.equiped) for e in res.equiped] == [(row["id"], DAGGER, 1, True)]
    # floor(basic + grow x 1): power 13.39+0.691, magic 8.93+0.461, hit 1.49+0.115, hp 22.32+1.728
    want = {1: 24, 2: 14, 4: 9, 10: 1}
    assert {a.attr_type: a.attr_value for a in res.af_info.base_attrs} == want
    assert res.af_info.ability == int(24 * 0.1 + 14 * 0.5 + 9 * 0.5 + 1)
    (pushed,) = _queued(session, 5, 2558)
    assert {a.attr_type: a.attr_delta for a in pushed.attrs} == want
    assert pushed.ability == res.af_info.ability

    # Another slot: both stay equipped.
    _equip(handlers, session, reg, entry=HOOD)
    assert [int(r["hero"]) for r in _rows(conn, pid)] == [1, 1]

    # A second dagger in position 7 sends the first back to the bag.
    conn.execute("INSERT INTO items (player_id, entry, amount) VALUES (?, ?, 1)", (pid, DAGGER))
    conn.commit()
    res = _equip(handlers, session, reg, entry=DAGGER)
    first, hood, second = _rows(conn, pid)
    assert (int(first["hero"]), int(hood["hero"]), int(second["hero"])) == (0, 1, 1)
    assert sorted(e.id for e in res.equiped) == [hood["id"], second["id"]]

    # Equipping a bag row by id swaps it back; an equipped one is refused.
    res = _equip(handlers, session, reg, id=first["id"])
    assert sorted(e.id for e in res.equiped) == [first["id"], hood["id"]]
    before = [tuple(r) for r in _rows(conn, pid)]
    _equip(handlers, session, reg, id=first["id"])
    assert [tuple(r) for r in _rows(conn, pid)] == before


def test_bag_lists_rows_and_lights_the_nodes(world, reg):
    conn, pid, handlers, session = world
    _main(handlers, session, reg)
    _equip(handlers, session, reg, entry=DAGGER)
    res = handlers[(5, 2549)](session, reg.message_class("ArtifactBagReq")())
    assert [(a.entry, a.equiped) for a in res.artifacts] == [(DAGGER, True)]
    # The eight kit nodes; 1500100 has node 0 and is not in the codex.
    assert list(res.illustrations.entries) == sorted(k for k in KIT if 1502000 <= k <= 1502700)


def test_equip_without_the_item_changes_nothing(world, reg):
    conn, pid, handlers, session = world
    res = _equip(handlers, session, reg, entry=DAGGER)
    assert _rows(conn, pid) == [] and len(res.equiped) == 0


def test_bonus_is_the_equipped_set_on_unit_fields(world, reg, cfg):
    conn, pid, handlers, session = world
    _main(handlers, session, reg)
    _equip(handlers, session, reg, entry=DAGGER)
    hero_row = {"player_id": pid, "entry": 101000}
    assert artifact.bonus(conn, cfg, hero_row) == {
        "max_hp": 24.0, "power": 14.0, "magic": 9.0, "hit_base": 1.0,
    }
    assert set(artifact.bonus(conn, cfg, hero_row)) <= set(notify.BASE_UNIT)
