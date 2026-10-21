"""Server core: fill_required, the zero-stub policy and dispatch over real sockets.

Every socket here binds and connects to 127.0.0.1 explicitly (the name localhost
resolves ::1 first and costs about 2 s per connect on this machine), and every
server binds through the bind_host parameter so settings.host stays the
client-side address baked into the APK.
"""

import asyncio
import logging
from pathlib import Path

import pytest

from server.net import framing
from server.net.registry import Registry
from server.net.server import Server, Session, fill_required, stub_response
from server.settings import Settings

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        stock_dir=STOCK,
        db_path=tmp_path / "player.db",
        host="127.0.0.1",
        port=0,
        username="stefan",
        guide_id=0,
    )


def test_fill_required_satisfies_proto2(reg: Registry) -> None:
    msg = reg.message_class("TounamentQuerySeasonStateRes")()
    fill_required(msg)
    assert msg.SerializeToString() == bytes.fromhex("08001000")


def test_fill_required_recurses_into_required_submessages(reg: Registry) -> None:
    msg = reg.message_class("ClientHero")()
    fill_required(msg)
    msg.SerializeToString()  # must not raise: unit and base_unit are required


def test_every_stub_res_serializes(reg: Registry) -> None:
    """Review Focus 1: no Res the dispatcher can emit may miss a required field."""
    burst = [(5, 2317), (5, 2801), (5, 2943), (153, 2001), (151, 2041),
             (3, 2005), (3, 2015), (3, 2001), (3, 2003), (3, 2009), (5, 2005)]
    for service, cmd in burst:
        res = stub_response(reg, service, cmd)
        assert res is not None, (service, cmd)
        res.SerializeToString()


def test_every_res_in_the_registry_serializes(reg: Registry) -> None:
    """The same guarantee over every id in msgIDMap, not just the boot burst."""
    for service, cmd in reg.ids:
        res = stub_response(reg, service, cmd)
        if res is not None:
            res.SerializeToString()


def test_stub_response_is_none_without_a_paired_res(reg: Registry) -> None:
    for key in [(5, 2031), (5, 2039), (5, 2343), (148, 2093), (134, 2001), (150, 2059)]:
        assert stub_response(reg, *key) is None
    assert stub_response(reg, 5, 4004) is None
    assert stub_response(reg, 9999, 9999) is None


class Client:
    """A minimal framed client. 127.0.0.1 only, never the name localhost."""

    def __init__(self, reader, writer) -> None:
        self.reader = reader
        self.writer = writer
        self.buf = b""

    @classmethod
    async def connect(cls, port: int) -> "Client":
        reader, writer = await asyncio.open_connection(BIND, port)
        return cls(reader, writer)

    async def send(
        self, service: int, cmd: int, body: bytes = b"", district: int = 0
    ) -> None:
        self.writer.write(framing.encode(service, cmd, 0, body, district))
        await self.writer.drain()

    async def recv(self, timeout: float = 5.0) -> framing.Frame:
        while True:
            decoded = framing.decode(self.buf)
            if decoded is not None:
                frame, self.buf = decoded
                return frame
            chunk = await asyncio.wait_for(self.reader.read(65536), timeout)
            if not chunk:
                raise AssertionError("server closed the connection")
            self.buf += chunk

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


async def _run_server(server: Server) -> tuple[asyncio.Task, int]:
    ready = asyncio.Event()
    task = asyncio.create_task(server.serve(ready))
    await asyncio.wait_for(ready.wait(), 5)
    return task, server.port


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_handler_is_dispatched_by_service_and_cmd(reg, settings) -> None:
    seen: list[tuple[int, str]] = []

    def on_protocol(session: Session, req):
        seen.append((1, req.issue))
        res = reg.message_class("ProtocolRes")(issue_required=req.issue + ":deadbeef")
        return res

    async def scenario() -> None:
        server = Server(reg, settings, {(3, 2005): on_protocol}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (3, 2006)
        res = reg.message_class("ProtocolRes")()
        res.ParseFromString(frame.body)
        assert res.issue_required == "1.0.0.5:deadbeef"
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
    assert seen == [(1, "1.0.0.5")]


def test_unknown_id_gets_a_zero_filled_res(reg, settings) -> None:
    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(151, 2041)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (151, 2042)
        res = reg.message_class("TounamentQuerySeasonStateRes")()
        res.ParseFromString(frame.body)
        assert res.season_state == 0
        assert res.season_state_end_time == 0
        assert (151, 2041) in server.sent_unknown
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_unknown_id_without_res_sends_nothing(reg, settings) -> None:
    """Review Focus 5: a Req with no paired Res, and a Notify."""

    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(134, 2001)  # BugReportReq, no BugReportRes exists
        await client.send(5, 4004)    # BatchNotify
        await client.send(151, 2041)  # a known-answerable id, as a fence
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (151, 2042)
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_two_concurrent_sessions_are_independent(reg, settings) -> None:
    """Review Focus 3: the client opens SERVER_SER, then SERVER_GAME."""
    peers: list[str] = []

    def on_srvinfo(session: Session, req):
        peers.append(session.peer)
        session.data["server_id"] = req.server_id
        return reg.message_class("QuerySrvInfoRes")(
            district=1, addr=f"127.0.0.1:{session.bound_port}"
        )

    def on_protocol(session: Session, req):
        assert "server_id" not in session.data, "sessions must not share state"
        return reg.message_class("ProtocolRes")(issue_required=req.issue + ":x")

    async def scenario() -> None:
        server = Server(
            reg,
            settings,
            {(194, 2001): on_srvinfo, (3, 2005): on_protocol},
            bind_host=BIND,
        )
        task, port = await _run_server(server)
        a = await Client.connect(port)
        b = await Client.connect(port)
        await a.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await a.recv()).cmd == 2002
        await b.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        assert (await b.recv()).cmd == 2006
        # connection a is still alive and still has its own state
        await a.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await a.recv()).cmd == 2002
        await a.close()
        await b.close()
        await _stop(task)

    asyncio.run(scenario())
    assert len(peers) == 2


def test_handler_exception_answers_status_one_and_keeps_the_connection(reg, settings) -> None:
    def boom(session: Session, req):
        raise RuntimeError("deliberate")

    async def scenario() -> None:
        server = Server(reg, settings, {(5, 2005): boom}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(5, 2005)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.status == 1
        # still usable
        await client.send(151, 2041)
        assert (await client.recv()).cmd == 2042
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_malformed_body_answers_a_stub_and_keeps_the_connection(
    reg, settings, caplog
) -> None:
    """spec §6: never drop the connection. A corrupt body is not a reason to.

    b"\\xff\\xff" is not valid wire format for QuerySrvInfoReq, so
    ParseFromString raises DecodeError before any handler sees the request.
    """
    called: list[object] = []

    def on_srvinfo(session: Session, req):
        called.append(req)
        return reg.message_class("QuerySrvInfoRes")(district=1, addr="x")

    async def scenario() -> None:
        server = Server(reg, settings, {(194, 2001): on_srvinfo}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(194, 2001, b"\xff\xff")
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (194, 2002)
        res = reg.message_class("QuerySrvInfoRes")()
        res.ParseFromString(frame.body)
        assert res.addr == ""  # the zero stub, not the handler's answer
        # still usable
        await client.send(151, 2041)
        assert (await client.recv()).cmd == 2042
        await client.close()
        await _stop(task)

    with caplog.at_level(logging.DEBUG, logger="loa.net"):
        asyncio.run(scenario())

    assert called == [], "the handler must not run on an undecodable body"
    hits = [
        r for r in caplog.records
        if r.name == "loa.net" and "ffff" in r.getMessage()
    ]
    assert hits, [r.getMessage() for r in caplog.records]
    assert "194_2001" in hits[0].getMessage()


def test_malformed_body_without_a_paired_res_sends_nothing(reg, settings) -> None:
    """BugReportReq has no BugReportRes, so a corrupt one is logged and dropped."""

    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(134, 2001, b"\xff\xff")
        await client.send(151, 2041)  # a known-answerable id, as a fence
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (151, 2042)
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_two_frames_in_one_write_are_both_handled(reg, settings) -> None:
    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        client.writer.write(
            framing.encode(151, 2041, 0, b"") + framing.encode(153, 2001, 0, b"")
        )
        await client.writer.drain()
        first = await client.recv()
        second = await client.recv()
        assert {first.cmd, second.cmd} == {2042, 2002}
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_sent_frame_carries_the_session_district_at_offset_four(reg, settings) -> None:
    """The client echoes the district the server assigned; the server echoes it back."""

    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(151, 2041, district=7)
        header = await asyncio.wait_for(
            client.reader.readexactly(framing.HEADER_SIZE), 5
        )
        assert int.from_bytes(header[4:6], "little") == 7
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_server_binds_the_bind_host_not_settings_host(reg, settings) -> None:
    """settings.host is the client-side address; the bind address is separate."""

    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        assert server.bind_host == BIND
        assert port != 0
        await _stop(task)

    asyncio.run(scenario())
    assert Server(reg, settings, {}).bind_host == "0.0.0.0"
