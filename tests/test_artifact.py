"""Artifacts (plan B2 Wave 3, task B9; O-W3-10).

The start kit ARTIFACT_INIT is the eight green 风灵 artifacts 1502000-1502700
(positions 7, 1, 8, 6, 5, 4, 3, 2), the smelt-only 1500100, two small crystals
1500001 and 50 advance stones 1400, all inventory items (category 20)."""

import sqlite3
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


# --- level-up, advance, smelt, compose (commit 2) -------------------------------
CRYSTAL = 1500001       # 神器晶石(小), exp_score 100
STONE = 1400            # 神器进阶石
DAGGER1 = 1502001       # 风灵匕首+1: smelt_gold_return 15000, smelt_potion_return 50


def _give(conn, pid, entry, amount):
    conn.execute(
        "INSERT INTO items (player_id, entry, amount) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, entry) DO UPDATE SET amount = amount + ?",
        (pid, entry, amount, amount),
    )
    conn.commit()


def _put(conn, pid, entry, level, exp=0, equipped=1) -> int:
    cur = conn.execute(
        "INSERT INTO artifacts (player_id, entry, level, exp, hero) VALUES (?, ?, ?, ?, ?)",
        (pid, entry, level, exp, equipped),
    )
    conn.commit()
    return int(cur.lastrowid)


def _player(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _level_up(handlers, session, reg, artifact_id, stocks=(), afs=()):
    req = reg.message_class("ArtifactLevelUpReq")(id=artifact_id)
    req.food.afs.extend(afs)
    for entry, amount in stocks:
        req.food.stocks.add(entry=entry, amount=amount)
    return handlers[(5, 2537)](session, req)


def _advance(handlers, session, reg, artifact_id):
    return handlers[(5, 2539)](session, reg.message_class("ArtifactAdvanceUpReq")(id=artifact_id))


def _smelt(handlers, session, reg, stocks=(), afs=()):
    req = reg.message_class("ArtifactSmeltReq")()
    req.food.afs.extend(afs)
    for entry, amount in stocks:
        req.food.stocks.add(entry=entry, amount=amount)
    return handlers[(5, 2545)](session, req)


def test_level_up_consumes_exp(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 1)
    _give(conn, pid, CRYSTAL, 3)
    res = _level_up(handlers, session, reg, aid, [(CRYSTAL, 2)])
    # 200 xp, quality 2: 56 (1->2) + 59 (2->3) + 62 (3->4), 23 left at level 4.
    row = _rows(conn, pid)[0]
    assert (int(row["level"]), int(row["exp"])) == (4, 23)
    assert _items(conn, pid) == {CRYSTAL: 1}
    assert int(_player(conn, pid)["gold"]) == 1_000_000 - 200 * 100   # ARTIFACT_EXP_GOLD_SCALE
    assert (res.af_level_up_info.base_info.level, res.af_level_up_info.base_info.exp) == (4, 23)
    assert res.af_next_advance_info.base_info.entry == DAGGER1
    assert [e.id for e in res.equiped] == [aid] and [a.id for a in res.artifacts] == [aid]
    assert _queued(session, 5, 2558)


def test_level_up_overflow_becomes_smelt_essence(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 39, exp=250)       # level 39 needs 256; 40 is quality 2's top
    _give(conn, pid, CRYSTAL, 1)
    _level_up(handlers, session, reg, aid, [(CRYSTAL, 1)])
    row = _rows(conn, pid)[0]
    assert (int(row["level"]), int(row["exp"])) == (40, 0)
    player = _player(conn, pid)
    assert int(player["gold"]) == 1_000_000 - 6 * 100
    assert int(player["artifact_smelt"]) == 14                  # floor(94 x XP_TO_ARTIFACT_SMELT 0.15)
    # At the top: refused, the crystal stays.
    _give(conn, pid, CRYSTAL, 1)
    _level_up(handlers, session, reg, aid, [(CRYSTAL, 1)])
    assert _items(conn, pid) == {CRYSTAL: 1}


def test_level_up_refuses_bad_food(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 1)
    other = _put(conn, pid, HOOD, 1, equipped=0)
    _give(conn, pid, STONE, 5)
    before = [tuple(r) for r in _rows(conn, pid)]
    _level_up(handlers, session, reg, aid, [(STONE, 1)])          # exp_score 0: 337002
    _level_up(handlers, session, reg, aid, afs=[other])           # an id artifact: 337002
    _level_up(handlers, session, reg, aid, [(CRYSTAL, 1)])        # not owned: 327942
    assert [tuple(r) for r in _rows(conn, pid)] == before
    assert _items(conn, pid) == {STONE: 5}
    assert int(_player(conn, pid)["gold"]) == 1_000_000


def test_advance_follows_next_entry(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 4)
    _give(conn, pid, STONE, 200)
    _advance(handlers, session, reg, aid)                         # needlevel 5: 337003
    assert int(_rows(conn, pid)[0]["entry"]) == DAGGER
    conn.execute("UPDATE artifacts SET level = 10, exp = 7 WHERE id = ?", (aid,))
    conn.commit()
    res = _advance(handlers, session, reg, aid)
    row = _rows(conn, pid)[0]
    assert (int(row["entry"]), int(row["level"]), int(row["exp"])) == (DAGGER1, 10, 7)
    assert _items(conn, pid) == {STONE: 150}                      # item_composite 1502001: 50 x 1400
    assert int(_player(conn, pid)["gold"]) == 1_000_000 - 15000
    assert res.af_advance_up_info.base_info.entry == DAGGER1
    assert res.af_next_advance_info.base_info.entry == 1502002
    # +2 also needs a second 1502000 from the inventory.
    _advance(handlers, session, reg, aid)
    assert int(_rows(conn, pid)[0]["entry"]) == DAGGER1
    _give(conn, pid, DAGGER, 1)
    _advance(handlers, session, reg, aid)
    assert int(_rows(conn, pid)[0]["entry"]) == 1502002
    assert _items(conn, pid) == {STONE: 50}
    # Quality 2 stops at +2 (ARTIFACT_MAX_ADVANCE 2|2) although 1502003 exists.
    conn.execute("UPDATE artifacts SET level = 30 WHERE id = ?", (aid,))
    conn.commit()
    _give(conn, pid, STONE, 1000)
    _give(conn, pid, DAGGER, 1)                                   # 1502003's recipe, all present
    _advance(handlers, session, reg, aid)
    assert int(_rows(conn, pid)[0]["entry"]) == 1502002
    assert _items(conn, pid) == {STONE: 1050, DAGGER: 1}


def test_upgrade_unequipped_refused_337005(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 10, equipped=0)
    _give(conn, pid, CRYSTAL, 1)
    _give(conn, pid, STONE, 50)
    _level_up(handlers, session, reg, aid, [(CRYSTAL, 1)])
    _advance(handlers, session, reg, aid)
    row = _rows(conn, pid)[0]
    assert (int(row["entry"]), int(row["level"]), int(row["exp"])) == (DAGGER, 10, 0)
    assert _items(conn, pid) == {CRYSTAL: 1, STONE: 50}
    assert int(_player(conn, pid)["gold"]) == 1_000_000


def test_smelt_returns_scaled(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER1, 3, exp=10, equipped=0)        # total xp 10 + 56 + 59 = 125
    _give(conn, pid, 1500100, 1)                                 # smelt_score 250
    res = _smelt(handlers, session, reg, [(1500100, 1)], [aid])
    want = [
        (61, 0, 250),                         # ceil(250 x POINT_SCALE 1)
        (1, 0, 7500 + 6250),                  # ceil(15000 x 0.5) + ceil(125 x 100 x 0.5)
        (20, STONE, 50),                      # ceil(50 x POTION_SCALE 1)
        (20, CRYSTAL, 1),                     # 125 xp as crystals, largest first
    ]
    assert [(p.category, p.refer, p.amount) for p in res.prizes] == want
    assert _rows(conn, pid) == []
    assert _items(conn, pid) == {STONE: 50, CRYSTAL: 1}
    player = _player(conn, pid)
    assert int(player["artifact_smelt"]) == 250
    assert int(player["gold"]) == 1_000_000 + 13750


def test_smelt_refuses_equipped_and_unsmeltable(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER1, 3)
    _give(conn, pid, DAGGER, 1)                                  # smelt_score 0
    assert len(_smelt(handlers, session, reg, afs=[aid]).prizes) == 0
    assert len(_smelt(handlers, session, reg, [(DAGGER, 1)]).prizes) == 0
    assert len(_rows(conn, pid)) == 1 and _items(conn, pid) == {DAGGER: 1}


def test_smelt_main_lists_rows(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, DAGGER, 2)
    res = handlers[(5, 2555)](session, reg.message_class("ArtifactSmeltMainReq")())
    assert [(a.id, a.equiped) for a in res.artifacts] == [(aid, True)]


def test_compose_takes_fragments_and_gold(world, reg):
    conn, pid, handlers, session = world
    _give(conn, pid, 1713000, 25)                                # 火精灵长弓碎片, recipe 20 + 20000 gold
    req = reg.message_class("ArtifactComposeReq")(item=1513000)
    res = handlers[(5, 2553)](session, req)
    assert (res.prize.category, res.prize.refer, res.prize.amount) == (20, 1513000, 1)
    assert _items(conn, pid) == {1713000: 5, 1513000: 1}
    assert int(_player(conn, pid)["gold"]) == 1_000_000 - 20000
    assert 1513000 in res.illustrations.entries
    # An advance recipe (item0 is an artifact, not a fragment) is not composable.
    handlers[(5, 2553)](session, reg.message_class("ArtifactComposeReq")(item=DAGGER1))
    assert DAGGER1 not in _items(conn, pid)


def test_develop_info_previews_the_next_entry(world, reg):
    conn, pid, handlers, session = world
    aid = _put(conn, pid, 1502004, 30)                           # next_entry 0: previews itself
    res = handlers[(5, 2535)](session, reg.message_class("ArtifactDevelopeInfoReq")(id=aid))
    assert res.af_info.base_info.id == aid and res.af_info.base_info.entry == 1502004
    assert res.af_advance_info.base_info.entry == 1502004 and res.af_advance_info.base_info.id == 0


def test_bonus_basic_plus_grow(world, cfg):
    conn, pid, _handlers, _session = world
    _put(conn, pid, DAGGER1, 10)
    _put(conn, pid, HOOD, 5, equipped=0)                         # in the bag: no bonus
    # floor(basic + grow x 10): power 22.03+8.36, magic 14.69+5.58, hit 2.45+1.39, hp 36.72+20.91
    assert artifact.bonus(conn, cfg, {"player_id": pid, "entry": 101000}) == {
        "power": 30.0, "magic": 20.0, "hit_base": 3.0, "max_hp": 57.0,
    }


def test_crystals_are_every_class_133_item():
    path = (STOCK / "assets/res/data/split/item_info.db").resolve()
    ro = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = ro.execute(
            "SELECT entry FROM item_info WHERE class = '133'"
            " ORDER BY CAST(exp_score AS INTEGER) DESC").fetchall()
    finally:
        ro.close()
    assert tuple(int(r[0]) for r in rows) == artifact.CRYSTALS


def _hero_stats(session) -> dict[int, dict]:
    """{hero entry: {field: value}} merged over the ident-2 notifies."""
    out: dict[int, dict] = {}
    for m in _queued(session, 5, 2008):
        if m.ident != notify.IDENT_HERO:
            continue
        names = [n for i, n in enumerate(notify.HERO_FIELDS) if m.flags >> i & 1]
        out.setdefault(int(m.refer), {}).update(dict(zip(names, m.data)))
    return out


def test_equip_level_up_and_advance_push_every_heros_stats(world, reg, cfg):
    """C1: the equipped set's attributes are in every hero's unit (artifact.
    bonus), so 5_2541, 5_2537 and 5_2539 push all heroes' unit stats."""
    from server.db import grant_hero
    from server.modules import hero

    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, star=1, level=10)
    grant_hero(conn, pid, 101000, 10, star=1, level=10)

    def check():
        stats = _hero_stats(session)
        assert set(stats) == {100000, 101000}
        for row in conn.execute("SELECT * FROM heroes WHERE player_id = ?", (pid,)):
            want = hero.build_client_hero_with_runes(
                reg, cfg, row, hero.runes_of(conn, row), conn=conn
            )
            assert want.unit != want.base_unit
            for name in hero.STAT_NAMES:
                got = stats[int(row["entry"])][name]
                assert got == pytest.approx(getattr(want.unit, name)), name
            assert stats[int(row["entry"])]["ability"] == want.ability
        session.outbox.clear()

    _give(conn, pid, DAGGER, 1)
    _equip(handlers, session, reg, entry=DAGGER)
    check()
    aid = _rows(conn, pid)[0]["id"]
    _give(conn, pid, CRYSTAL, 3)
    _level_up(handlers, session, reg, aid, [(CRYSTAL, 2)])
    check()
    conn.execute("UPDATE artifacts SET level = 10 WHERE id = ?", (aid,))
    conn.commit()
    _give(conn, pid, STONE, 200)
    _advance(handlers, session, reg, aid)
    assert int(_rows(conn, pid)[0]["entry"]) == DAGGER1
    check()
    # A refused equip pushes no hero stats.
    _equip(handlers, session, reg, entry=DAGGER)
    assert _hero_stats(session) == {}
