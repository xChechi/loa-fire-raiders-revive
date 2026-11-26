"""Hero gear: 5_2105 HeroEquip, 5_2163 HeroEquipAll, 5_2111 ItemComposite,
5_2725 ItemCompositeAll, 5_2109 HeroQualityUp.

Hero 100000 at quality 10 wears 10000, 11010, 11120, 11040, 11020, 11170
(hero_quality, next 20, prototype 100000 -> 100010); every one of them needs
hero level 2. 11120 crafts from 11000 + 11030 for 600 gold, 30000 from five
31000 for 1500 gold (item_composite)."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import (
    connect,
    create_player,
    grant_hero,
    grant_item,
    heroes_of,
    items_of,
    set_hero_items,
)
from server.modules import hero, notify
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
Q10_SLOTS = [10000, 11010, 11120, 11040, 11020, 11170]


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
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = hero.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _items(conn, pid) -> dict[int, int]:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0])


def _hero_row(conn, pid):
    return heroes_of(conn, pid)[0]


def _decode(msg, order) -> dict:
    """The inverse of notify._fields_changed for FLAGS_BYTE_ORDER little."""
    out, values = {}, iter(msg.data)
    for i, name in enumerate(order):
        if msg.flags & (1 << i):
            out[name] = next(values)
    return out


def _notes(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


def _req(reg, name, **kw):
    return reg.message_class(name)(**kw)


def test_equip_10000_on_100000_slot0_consumes_one_and_notifies_item0(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=2)
    grant_item(conn, pid, 10000, 2)
    res = handlers[(5, 2105)](session, _req(reg, "HeroEquipReq", hero=100000, index=0))
    assert res.status == 0
    assert int(_hero_row(conn, pid)["item0"]) == 10000
    assert _items(conn, pid)[10000] == 1
    assert [list(m.data) for m in _notes(session, 4)] == [[10000.0, 1.0]]
    hero_notes = _notes(session, 2)
    assert len(hero_notes) == 1 and hero_notes[0].refer == 100000
    fields = _decode(hero_notes[0], notify.HERO_FIELDS)
    assert fields["item0"] == 10000
    assert "item1" not in fields
    # 10000 adds max_hp 10 over the gear-free level-2 stats.
    built = hero.build_client_hero(reg, cfg, _hero_row(conn, pid), conn=conn)
    assert fields["max_hp"] == built.base_unit.max_hp + 10
    assert "ability" in fields and "quality" not in fields


def test_equip_refused_327944_when_hero_level_1(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=1)
    grant_item(conn, pid, 10000, 1)
    res = handlers[(5, 2105)](session, _req(reg, "HeroEquipReq", hero=100000, index=0))
    assert res.status == 327944
    assert int(_hero_row(conn, pid)["item0"]) == 0
    assert _items(conn, pid)[10000] == 1
    assert session.outbox == []


def test_equip_refused_328961_on_full_slot(reg, world) -> None:
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 10, level=2)
    set_hero_items(conn, hid, [10000, 0, 0, 0, 0, 0])
    grant_item(conn, pid, 10000, 1)
    res = handlers[(5, 2105)](session, _req(reg, "HeroEquipReq", hero=100000, index=0))
    assert res.status == 328961
    assert _items(conn, pid)[10000] == 1


def test_equip_refusals_for_unknown_hero_bad_index_and_missing_item(reg, world) -> None:
    conn, pid, handlers, session = world
    equip = handlers[(5, 2105)]
    assert equip(session, _req(reg, "HeroEquipReq", hero=100000, index=0)).status == 327941
    grant_hero(conn, pid, 100000, 10, level=2)
    assert equip(session, _req(reg, "HeroEquipReq", hero=100000, index=6)).status == 327681
    assert equip(session, _req(reg, "HeroEquipReq", hero=100000, index=1)).status == 327942


def test_equip_res_echoes_index(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=2)
    grant_item(conn, pid, 11040, 1)
    res = handlers[(5, 2105)](session, _req(reg, "HeroEquipReq", hero=100000, index=3))
    assert (res.status, res.index) == (0, 3)
    assert int(_hero_row(conn, pid)["item3"]) == 11040
    res.SerializeToString()


def test_equip_all_fills_every_owned_slot_in_one_notify(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=2)
    for entry in Q10_SLOTS:
        grant_item(conn, pid, entry, 1)
    res = handlers[(5, 2163)](session, _req(reg, "HeroEquipAllReq", hero=100000))
    res.SerializeToString()
    assert [int(_hero_row(conn, pid)[f"item{i}"]) for i in range(6)] == Q10_SLOTS
    assert all(_items(conn, pid).get(e, 0) == 0 for e in Q10_SLOTS)
    hero_notes = _notes(session, 2)
    assert len(hero_notes) == 1
    fields = _decode(hero_notes[0], notify.HERO_FIELDS)
    assert [fields[f"item{i}"] for i in range(6)] == Q10_SLOTS
    assert len(_notes(session, 4)) == 1
    assert _gold(conn, pid) == 1280000


def test_equip_all_crafts_directly_composable_for_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=2)
    grant_item(conn, pid, 11000, 1)
    grant_item(conn, pid, 11030, 1)
    handlers[(5, 2163)](session, _req(reg, "HeroEquipAllReq", hero=100000))
    row = _hero_row(conn, pid)
    assert int(row["item2"]) == 11120
    assert _items(conn, pid).get(11000, 0) == 0 and _items(conn, pid).get(11030, 0) == 0
    assert _gold(conn, pid) == 1280000 - 600
    player_notes = _notes(session, 1)
    assert len(player_notes) == 1
    assert _decode(player_notes[0], notify.PLAYER_FIELDS) == {"gold": 1280000 - 600}


def test_equip_all_with_nothing_to_do_writes_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=2)
    grant_item(conn, pid, 10000, 1)
    # Level 1: every q10 item needs level 2, so nothing applies.
    conn.execute("UPDATE heroes SET level = 1")
    conn.commit()
    handlers[(5, 2163)](session, _req(reg, "HeroEquipAllReq", hero=100000))
    assert [int(_hero_row(conn, pid)[f"item{i}"]) for i in range(6)] == [0] * 6
    assert _items(conn, pid)[10000] == 1
    assert session.outbox == []


def test_composite_30000_from_five_31000(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 31000, 6)
    res = handlers[(5, 2111)](session, _req(reg, "ItemCompositeReq", item=30000))
    assert res.status == 0
    assert _items(conn, pid)[30000] == 1 and _items(conn, pid)[31000] == 1
    assert _gold(conn, pid) == 1280000 - 1500
    assert sorted(list(m.data) for m in _notes(session, 4)) == [[31000.0, 1.0, 30000.0, 1.0]]
    assert len(_notes(session, 1)) == 1


def test_composite_refusals_328968_327942_327937(reg, world) -> None:
    conn, pid, handlers, session = world
    composite = handlers[(5, 2111)]
    assert composite(session, _req(reg, "ItemCompositeReq", item=10000)).status == 328968
    grant_item(conn, pid, 31000, 4)
    assert composite(session, _req(reg, "ItemCompositeReq", item=30000)).status == 327942
    grant_item(conn, pid, 31000, 1)
    conn.execute("UPDATE players SET gold = 1499 WHERE id = ?", (pid,))
    conn.commit()
    assert composite(session, _req(reg, "ItemCompositeReq", item=30000)).status == 327937
    assert _items(conn, pid)[31000] == 5
    assert session.outbox == []


def test_composite_refused_327970_at_stack_cap(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 30000, 9999)
    grant_item(conn, pid, 31000, 5)
    res = handlers[(5, 2111)](session, _req(reg, "ItemCompositeReq", item=30000))
    assert res.status == 327970
    assert _items(conn, pid)[31000] == 5


def test_composite_all_makes_as_many_as_materials_allow(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 31000, 12)
    res = handlers[(5, 2725)](session, _req(reg, "ItemCompositeAllReq", entry=30000))
    res.SerializeToString()
    assert _items(conn, pid)[30000] == 2 and _items(conn, pid)[31000] == 2
    assert _gold(conn, pid) == 1280000 - 3000


def test_composite_all_is_limited_by_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 31000, 15)
    conn.execute("UPDATE players SET gold = 3100 WHERE id = ?", (pid,))
    conn.commit()
    handlers[(5, 2725)](session, _req(reg, "ItemCompositeAllReq", entry=30000))
    assert _items(conn, pid)[30000] == 2 and _items(conn, pid)[31000] == 5
    assert _gold(conn, pid) == 100


def test_quality_up_needs_six_slots_328967(reg, world) -> None:
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 10, level=2)
    set_hero_items(conn, hid, Q10_SLOTS[:5] + [0])
    res = handlers[(5, 2109)](session, _req(reg, "HeroQualityUpReq", hero=100000))
    assert res.status == 328967
    assert int(_hero_row(conn, pid)["quality"]) == 10
    assert session.outbox == []


def test_quality_up_at_top_refused_328966(reg, world) -> None:
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 53, level=2)
    set_hero_items(conn, hid, [1, 1, 1, 1, 1, 1])
    conn.execute("UPDATE heroes SET item0 = 50330, item1 = 50140, item2 = 50300,"
                 " item3 = 50080, item4 = 50170, item5 = 40350")
    conn.commit()
    res = handlers[(5, 2109)](session, _req(reg, "HeroQualityUpReq", hero=100000))
    assert res.status == 328966


def test_quality_up_sets_next_clears_slots_one_hero_notify_after_res(reg, world) -> None:
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 10, level=2)
    set_hero_items(conn, hid, Q10_SLOTS)
    res = handlers[(5, 2109)](session, _req(reg, "HeroQualityUpReq", hero=100000))
    assert res.status == 0
    res.SerializeToString()
    row = _hero_row(conn, pid)
    assert int(row["quality"]) == 20
    assert [int(row[f"item{i}"]) for i in range(6)] == [0] * 6
    # Settled point 11: exactly one ident-2 notify for the hero, so the success
    # panel counts Res + one INFO_CHANGE_NTF_HERO; the dispatcher writes the
    # outbox after the Res.
    hero_notes = _notes(session, 2)
    assert len(hero_notes) == 1
    fields = _decode(hero_notes[0], notify.HERO_FIELDS)
    assert fields["quality"] == 20 and fields["prototype"] == 100010
    assert [fields[f"item{i}"] for i in range(6)] == [0] * 6
    # Prototype 100010 unlocks its second skill (npc_info.skill1 = 1001000).
    assert (fields["spell0"], fields["spell1"]) == (1000000, 1001000)
    base_notes = _notes(session, 9)
    assert len(base_notes) == 1 and base_notes[0].refer == 100000
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008), (5, 2008)]
