"""QueryMyselfRes for a fresh player and the five main-city stubs.

Every server here binds 127.0.0.1 explicitly through bind_host (settings.host
stays the client-side address) and takes port 0, so assertions use server.port.
"""

import asyncio
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, grant_hero
from server.modules import player
from server.net.registry import Registry
from server.net.server import Server, fill_required
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg():
    conf = Config.load(STOCK)
    yield conf
    conf.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", "127.0.0.1", bind=BIND,
                    port=0, username="stefan", guide_id=0)


@pytest.fixture
def row(settings: Settings):
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)
    return conn, find_player(conn, "stefan")


def test_query_myself_res_serializes(reg, cfg, row) -> None:
    """Review Focus 1. The fixture is a bare create_player with no starting kit,
    so this character owns nothing yet; the kit is covered by test_login.py."""
    conn, r = row
    res = player.build_query_myself_res(reg, cfg, conn, r)
    raw = res.SerializeToString()
    assert raw  # non-empty
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(raw)
    assert parsed.status == 0
    assert parsed.player.username == "stefan"
    assert parsed.player.nickname == "stefan"
    assert parsed.player.level == 1
    assert parsed.HasField("stats")
    assert parsed.HasField("gold_trails")
    assert len(parsed.heroes) == 0
    assert len(parsed.inventory) == 0
    assert len(parsed.levels) == 0
    assert len(parsed.angels) == 0


def test_query_myself_res_carries_a_granted_hero(reg, cfg, row) -> None:
    """A character that owns a hero sends it inside QueryMyselfRes, and the
    whole message still serializes with its proto2 required fields set."""
    conn, r = row
    grant_hero(conn, int(r["id"]), 100000, 10, star=1, level=1)
    res = player.build_query_myself_res(reg, cfg, conn, r)
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(res.SerializeToString())
    assert len(parsed.heroes) == 1
    assert parsed.heroes[0].entry == 100000
    assert parsed.heroes[0].prototype == 100000
    assert parsed.heroes[0].unit.max_hp == 100


def test_player_sets_every_field_lua_concatenates(reg, row) -> None:
    """Review Focus 2: ClientPlayer:updateData concatenates nobility_level."""
    _, r = row
    p = player.build_client_player(reg, r)
    assert p.HasField("nobility_level")
    assert p.HasField("nobility_exp")
    assert p.HasField("guild_id")


def test_every_required_client_player_field_is_set(reg, row) -> None:
    _, r = row
    p = player.build_client_player(reg, r)
    missing = [
        fd.name for fd in p.DESCRIPTOR.fields if fd.is_required and not p.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in p.DESCRIPTOR.fields if fd.is_required]) == 30


def test_every_required_daily_stats_field_is_set(reg) -> None:
    s = player.build_daily_stats(reg)
    missing = [
        fd.name for fd in s.DESCRIPTOR.fields if fd.is_required and not s.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in s.DESCRIPTOR.fields if fd.is_required]) == 19


def test_guide_id_comes_from_the_stored_row(reg, settings) -> None:
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=14302)
    p = player.build_client_player(reg, find_player(conn, "stefan"))
    assert p.guide_id == 14302


def test_the_five_main_city_stubs_serialize(reg, settings, cfg) -> None:
    """Every explicit main-city Res must survive proto2 required-field encoding."""
    conn = connect(settings.db_path)
    handlers = player.handlers(reg, settings, conn, cfg)
    expected = {
        (5, 2317): "GameReadyRes",
        (5, 2801): "QueryMyPushMessageRes",
        (5, 2943): "QueryBtCardRecordRes",
        (153, 2001): "MagicStateRes",
        (151, 2041): "TounamentQuerySeasonStateRes",
    }
    for key, name in expected.items():
        res = handlers[key](None, None)
        assert res.DESCRIPTOR.name == name
        fill_required(res)
        res.SerializeToString()
    assert handlers[(153, 2001)](None, None).match_state == 99


def test_query_myself_over_a_socket(reg, settings, row, cfg) -> None:
    conn, _ = row

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(5, 2005)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.player.username == "stefan"
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_query_myself_without_any_character_answers_status_one(reg, settings, cfg) -> None:
    """No login and no row: a status 1 stub, never a crash."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(5, 2005)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.status == 1
        assert not res.HasField("player")
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_the_five_main_city_messages_are_answered(reg, settings, row, cfg) -> None:
    conn, _ = row
    expected = {(5, 2317): 2318, (5, 2801): 2802, (5, 2943): 2944,
                (153, 2001): 2002, (151, 2041): 2042}

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        for (service, cmd), res_cmd in expected.items():
            await c.send(service, cmd)
            frame = await c.recv()
            assert (frame.service, frame.cmd) == (service, res_cmd)
        assert server.sent_unknown == set()
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_bt_cards_carries_both_privilege_cards(reg) -> None:
    """Review Focus 5: RoleData:updateRechangeCardsList does for i = 1,#data
    over btCards, and RechangeCardPanel builds its boxes from the same
    variables.db key, so the entries must be 100000 and 100100 in that order."""
    from server.config import Config
    from server.modules.player import build_bt_cards

    cfg = Config.load(STOCK)
    res = build_bt_cards(reg, cfg)
    assert [c.entry for c in res.btCards] == [100000, 100100]
    assert [c.isActivation for c in res.btCards] == [False, False]
    assert [c.isAward for c in res.btCards] == [False, False]
    res.SerializeToString()
    cfg.close()


def test_query_myself_reports_the_regenerated_energy(reg, settings, cfg) -> None:
    """5_2005 answers with the lazily regenerated energy, not the stored one."""
    from server.net.server import Session

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET energy = 10, energy_at = 0 WHERE id = ?", (pid,)
    )
    conn.commit()
    handlers = player.handlers(reg, settings, conn, cfg)
    # Session(writer=None) is safe: query_myself only returns a message.
    res = handlers[(5, 2005)](
        Session(writer=None, peer="t", bound_port=0),
        reg.message_class("QueryMyselfReq")(),
    )
    assert res.player.energy == 60
    assert res.player.max_energy == 60
