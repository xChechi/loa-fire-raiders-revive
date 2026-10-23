"""5_2008 ClientNotification and friends.

RoleData:onPlayerInfoChange walks ClientPlayer.PLAYER_FIELD_DIC and, for each
set bit, consumes the next value out of data. flags is a fixed64 in the proto
but Lua reads it with string.byte, so the mask is byte-indexed: bit
2^((i-1) mod 8) of byte floor((i-1)/8)+1 for the 1-based field index.
Whether those 8 bytes reach Lua little-endian is open question A in the plan;
these tests pin the little-endian reading, which is what protobuf writes.
"""

import asyncio
from pathlib import Path

import pytest

from server.modules import notify
from server.net.registry import Registry
from server.net.server import Server, Session
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind=BIND, port=0, username="stefan", guide_id=0,
    )


def test_player_field_dic_matches_the_client_list(reg) -> None:
    assert notify.PLAYER_FIELDS[:9] == (
        "vip", "vip_expires", "paycount", "xp", "level", "energy", "max_energy",
        "gold", "diamond",
    )
    assert notify.PLAYER_FIELDS[12] == "last_level"
    assert len(notify.PLAYER_FIELDS) == 48


def test_the_fields_the_tutorial_touches_keep_their_one_based_index() -> None:
    """The index is what RoleData tests, so these four are pinned by number:
    energy 6, gold 8, diamond 9, last_level 13 in ClientPlayer.PLAYER_FIELD_DIC."""
    for name, one_based in [("energy", 6), ("gold", 8), ("diamond", 9),
                            ("last_level", 13)]:
        assert notify.PLAYER_FIELDS.index(name) + 1 == one_based, name


def test_flags_for_sets_one_bit_per_field() -> None:
    assert notify.flags_for(["vip"]) == 1 << 0
    assert notify.flags_for(["energy"]) == 1 << 5
    assert notify.flags_for(["gold"]) == 1 << 7
    assert notify.flags_for(["last_level"]) == 1 << 12
    assert notify.flags_for(["energy", "gold"]) == (1 << 5) | (1 << 7)


def test_the_flag_byte_order_is_the_little_endian_default() -> None:
    """Open question A of the plan: the emulator check that settles it has not
    run yet, so the pin is the protobuf-native order. Flipping
    notify.FLAGS_BYTE_ORDER to "big" byte-swaps the whole mask, which is what
    the reversed reading would need."""
    assert notify.FLAGS_BYTE_ORDER == "little"
    assert notify.flags_for(["last_level"]).to_bytes(8, "little")[1] == 1 << 4


def test_player_changed_orders_data_by_field_index(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.player_changed(reg, session, {"gold": 1616, "energy": 54, "xp": 6})
    (service, cmd, msg) = session.outbox[0]
    assert (service, cmd) == (5, 2008)
    assert msg.ident == 1
    assert msg.flags == (1 << 3) | (1 << 5) | (1 << 7)
    assert list(msg.data) == [6.0, 54.0, 1616.0]      # xp, energy, gold
    msg.SerializeToString()


def test_player_changed_drops_a_name_the_client_does_not_know(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.player_changed(reg, session, {"energy": 54, "chocolate": 1})
    (_, _, msg) = session.outbox[0]
    assert msg.flags == 1 << 5
    assert list(msg.data) == [54.0]


def test_items_changed_is_flat_entry_amount_pairs(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.items_changed(reg, session, [(10000, 2), (1100, 5)])
    (_, _, msg) = session.outbox[0]
    assert msg.ident == 4
    assert list(msg.data) == [10000.0, 2.0, 1100.0, 5.0]
    msg.SerializeToString()


def test_items_changed_queues_nothing_for_an_empty_list(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.items_changed(reg, session, [])
    assert session.outbox == []


def test_level_up_notify_carries_all_six_values(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.level_up(reg, session, (1, 54, 60), (2, 66, 62))
    (service, cmd, msg) = session.outbox[0]
    assert (service, cmd) == (5, 2036)
    assert (msg.oldLevel, msg.newLevel) == (1, 2)
    assert (msg.oldEnergy, msg.newEnergy) == (54, 66)
    assert (msg.oldMaxEnergy, msg.newMaxEnergy) == (60, 62)
    msg.SerializeToString()


def test_hero_added_carries_the_client_hero_and_serializes(reg) -> None:
    hero = reg.message_class("ClientHero")(id=7, entry=1001)
    session = Session(writer=None, peer="t", bound_port=0)
    notify.hero_added(reg, session, hero)
    (service, cmd, msg) = session.outbox[0]
    assert (service, cmd) == (5, 2012)
    assert (msg.hero.id, msg.hero.entry) == (7, 1001)
    msg.SerializeToString()


def test_the_dispatcher_flushes_the_outbox_after_the_reply(reg, settings) -> None:
    def handler(session: Session, req):
        notify.player_changed(reg, session, {"energy": 54})
        return reg.message_class("SaveGuideIdRes")(status=0)

    async def scenario() -> None:
        server = Server(reg, settings, {(5, 2041): handler}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        body = reg.message_class("SaveGuideIdReq")(guide_id=1).SerializeToString()
        await client.send(5, 2041, body)
        first = await client.recv()
        second = await client.recv()
        assert (first.service, first.cmd) == (5, 2042)
        assert (second.service, second.cmd) == (5, 2008)
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_the_outbox_is_cleared_even_when_a_send_raises(reg, settings) -> None:
    """A dead writer must not leave the frames queued for the next request."""
    server = Server(reg, settings, {}, bind_host=BIND)
    session = Session(writer=None, peer="t", bound_port=0)
    notify.player_changed(reg, session, {"energy": 54})
    notify.level_up(reg, session, (1, 54, 60), (2, 66, 62))
    with pytest.raises(AttributeError):
        asyncio.run(server._flush(session))
    assert session.outbox == []
