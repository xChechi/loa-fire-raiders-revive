"""The login module over real sockets: srvinfo, protocol, state, login, create, beat.

Every server here binds 127.0.0.1 explicitly through bind_host (settings.host stays
the client-side address) and takes port 0, so assertions use the live server.port.
"""

import asyncio
from pathlib import Path

import pytest

from server.db import connect, find_player
from server.modules import login
from server.net.registry import Registry
from server.net.server import Server
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)


def _login_body(reg: Registry, name: str, username: str = "stefan") -> bytes:
    return reg.message_class(name)(
        username=username, token="local", datetime=1,
        device="", IMEI="LOA-HOME-0001", args=["1"],
    ).SerializeToString()


def test_srvinfo_answers_host_and_port(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn), bind_host=BIND
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


def test_protocol_res_carries_a_colon(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn), bind_host=BIND
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


def test_first_login_says_no_role_then_gameplay_creates_the_player(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)

        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2002)
        res = reg.message_class("LoginRes")()
        res.ParseFromString(frame.body)
        assert res.status == login.STATUS_NO_ROLE
        assert find_player(conn, "stefan") is None

        await c.send(3, 2003, _login_body(reg, "GameplayReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2004)
        res2 = reg.message_class("GameplayRes")()
        res2.ParseFromString(frame.body)
        assert res2.status == login.STATUS_OK
        assert res2.timestamp > 0
        row = find_player(conn, "stefan")
        assert row is not None and row["nickname"] == "stefan"

        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        res3 = reg.message_class("LoginRes")()
        res3.ParseFromString(frame.body)
        assert res3.status == login.STATUS_OK
        assert res3.session > 0

        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_srvinfo_on_first_socket_then_login_on_second(reg, settings) -> None:
    """Review Focus 3, with the real handlers: the client uses two sockets."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn), bind_host=BIND
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


def test_heartbeat_echoes_a_time(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, login.handlers(reg, settings, conn), bind_host=BIND
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
