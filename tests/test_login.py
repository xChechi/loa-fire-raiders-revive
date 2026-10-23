"""The login module over real sockets: srvinfo, protocol, state, login, create, beat.

Every server here binds 127.0.0.1 explicitly through bind_host (settings.host stays
the client-side address) and takes port 0, so assertions use the live server.port.
"""

import asyncio
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, find_player
from server.modules import login
from server.net.registry import Registry
from server.net.server import Server, Session
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


def _login_body(reg: Registry, name: str, username: str = "stefan") -> bytes:
    return reg.message_class(name)(
        username=username, token="local", datetime=1,
        device="", IMEI="LOA-HOME-0001", args=["1"],
    ).SerializeToString()


def test_srvinfo_answers_host_and_port(reg, settings, cfg) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(194, 2001, bytes.fromhex("0a0131"))
        frame = await c.recv()
        res = reg.message_class("QuerySrvInfoRes")()
        res.ParseFromString(frame.body)
        assert res.district == 1
        assert res.addr == f"127.0.0.1:{port}"  # the live port, not settings.port
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_protocol_res_carries_a_colon(reg, settings, cfg) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        frame = await c.recv()
        res = reg.message_class("ProtocolRes")()
        res.ParseFromString(frame.body)
        assert res.issue_required == "1.0.0.5:0"
        assert len(res.issue_required.split(":")) == 2
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_first_login_creates_the_player_and_answers_ok(reg, settings, cfg) -> None:
    """The client never acts on 327682, so the server creates the character.

    Verified on the emulator on 21-10-2026: the server answered
    LoginRes{status = 327682}, the client's own dump printed
    `"status" = 327682`, and `LoginSocketData:loginReceiveHdr` still took its
    `rs.status == 0` branch and sent 5_2005 instead of 3_2003. The body status
    does not reach that gate (docs/protocol.md, open question 1), so a first
    login that only says "no role" leaves the account with no character for
    ever.
    """
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)

        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2002)
        res = reg.message_class("LoginRes")()
        res.ParseFromString(frame.body)
        assert res.status == login.STATUS_OK
        assert res.session > 0
        row = find_player(conn, "stefan")
        assert row is not None and row["nickname"] == "stefan"

        # a second login reuses that character, it does not create another
        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        res2 = reg.message_class("LoginRes")()
        res2.ParseFromString(frame.body)
        assert res2.status == login.STATUS_OK
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 1

        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_login_uses_the_settings_account_not_the_name_the_client_sent(
    reg, settings, cfg
) -> None:
    """One player, one account. Seen live on 21-10-2026: a client reconnecting
    after the server restarted sent LoginReq with an empty username, and the
    server created a second, nameless character for it."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)

        await c.send(3, 2001, _login_body(reg, "LoginReq", username=""))
        assert (await c.recv()).cmd == 2002
        await c.send(3, 2001, _login_body(reg, "LoginReq", username="someone-else"))
        assert (await c.recv()).cmd == 2002

        rows = conn.execute("SELECT username FROM players").fetchall()
        assert [r["username"] for r in rows] == ["stefan"]

        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_gameplay_req_is_still_answered_if_a_client_sends_it(
    reg, settings, cfg
) -> None:
    """3_2003 stays supported: it is the stock create-character message."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)

        await c.send(3, 2003, _login_body(reg, "GameplayReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2004)
        res = reg.message_class("GameplayRes")()
        res.ParseFromString(frame.body)
        assert res.status == login.STATUS_OK
        assert res.timestamp > 0
        row = find_player(conn, "stefan")
        assert row is not None and row["nickname"] == "stefan"

        # and sending it again does not create a second character
        await c.send(3, 2003, _login_body(reg, "GameplayReq"))
        assert (await c.recv()).cmd == 2004
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 1

        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_srvinfo_on_first_socket_then_login_on_second(reg, settings, cfg) -> None:
    """Review Focus 3, with the real handlers: the client uses two sockets."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)

        ser = await Client.connect(port)
        await ser.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await ser.recv()).cmd == 2002

        game = await Client.connect(port)
        await game.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        assert (await game.recv()).cmd == 2006
        await game.send(3, 2015)
        assert (await game.recv()).cmd == 2016
        await game.send(3, 2001, _login_body(reg, "LoginReq"))
        assert (await game.recv()).cmd == 2002

        # the first socket is still open and still answering
        await ser.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await ser.recv()).cmd == 2002

        await ser.close()
        await game.close()
        await _stop(task)

    asyncio.run(scenario())


def test_heartbeat_echoes_a_time(reg, settings, cfg) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        body = reg.message_class("HeartbeatReq")(time=1).SerializeToString()
        await c.send(3, 2009, body)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2010)
        res = reg.message_class("HeartbeatRes")()
        res.ParseFromString(frame.body)
        assert res.status == 0
        assert res.time > 1_700_000_000
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_a_fresh_character_gets_the_config_starting_kit(reg, settings) -> None:
    """variables.db, not invented numbers: HERO_GOLD_INIT 1280000,
    HERO_DIAMOND_INIT 18888, PLAYER_ITEMS_INIT 1100|3,1200|2,
    HERO_FIRST_ENTRY 100000 at its lowest hero_quality (10), ENERGY_INIT 60.
    LineFrame:startFight refuses to start a stage with no hero on the field,
    which is why the first hero is granted here and not by the gacha."""
    from server.config import Config
    from server.db import connect, find_player, heroes_of, items_of
    from server.modules import login

    cfg = Config.load(STOCK)
    conn = connect(settings.db_path)
    handlers = login.handlers(reg, settings, conn, cfg)
    body = reg.message_class("LoginReq")(
        username="stefan", token="local", datetime=1, args=["1"]
    )
    handlers[(3, 2001)](Session(writer=None, peer="t", bound_port=0), body)

    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000
    assert int(row["diamond"]) == 18888
    assert int(row["energy"]) == 60
    assert int(row["max_energy"]) == 60
    heroes = heroes_of(conn, int(row["id"]))
    assert [int(h["entry"]) for h in heroes] == [100000]
    assert int(heroes[0]["quality"]) == 10
    assert int(heroes[0]["star"]) == 1
    assert int(heroes[0]["level"]) == 1
    assert {int(i["entry"]): int(i["amount"]) for i in items_of(conn, int(row["id"]))} == {
        1100: 3, 1200: 2
    }
    cfg.close()


def test_logging_in_again_does_not_grant_the_kit_twice(reg, settings) -> None:
    from server.config import Config
    from server.db import connect, find_player, heroes_of, items_of
    from server.modules import login

    cfg = Config.load(STOCK)
    conn = connect(settings.db_path)
    handlers = login.handlers(reg, settings, conn, cfg)
    body = reg.message_class("LoginReq")(
        username="stefan", token="local", datetime=1, args=["1"]
    )
    session = Session(writer=None, peer="t", bound_port=0)
    handlers[(3, 2001)](session, body)
    handlers[(3, 2001)](session, body)

    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000
    assert len(heroes_of(conn, int(row["id"]))) == 1
    assert len(items_of(conn, int(row["id"]))) == 2
    cfg.close()


def test_a_starting_kit_variable_the_config_lacks_fails_loudly(reg, settings) -> None:
    """A missing key must name itself, not grant nothing in silence: a
    character created with no gold and no hero looks like a working login and
    then cannot start a stage."""
    class WithoutGold(Config):
        def variable(self, key: str):
            return None if key == "HERO_GOLD_INIT" else super().variable(key)

    cfg = WithoutGold.load(STOCK)
    with pytest.raises(KeyError, match="HERO_GOLD_INIT"):
        login.starting_kit(cfg)
    cfg.close()
