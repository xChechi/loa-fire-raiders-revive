"""Replay the client login burst against a running server.

py -3.14 tools/fake_client.py            # uses settings.toml
py -3.14 tools/fake_client.py --port 8112
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    # Run as a path (py -3.14 tools/fake_client.py), sys.path[0] is tools/.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.net import framing  # noqa: E402
from server.net.registry import Registry  # noqa: E402
from server.settings import load as load_settings  # noqa: E402

GAME_VERSION = "1.0.0.5"


class Conn:
    def __init__(self, reader, writer) -> None:
        self.reader = reader
        self.writer = writer
        self.buf = b""
        # Header offset 4. The real client sends 0 until 194_2002 tells it a
        # district, then every frame carries that value (docs/protocol.md).
        self.district = 0

    @classmethod
    async def open(cls, host: str, port: int, district: int = 0) -> "Conn":
        reader, writer = await asyncio.open_connection(host, port)
        conn = cls(reader, writer)
        conn.district = district
        return conn

    async def call(self, service: int, cmd: int, body: bytes = b"") -> framing.Frame:
        self.writer.write(framing.encode(service, cmd, 0, body, self.district))
        await self.writer.drain()
        while True:
            decoded = framing.decode(self.buf)
            if decoded is not None:
                frame, self.buf = decoded
                return frame
            chunk = await asyncio.wait_for(self.reader.read(65536), 10)
            if not chunk:
                raise RuntimeError(f"server closed after {service}_{cmd}")
            self.buf += chunk

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


def _login_body(reg: Registry, name: str, username: str) -> bytes:
    return reg.message_class(name)(
        username=username,
        token="local",
        datetime=int(time.time()),
        device="",
        IMEI="LOA-HOME-0001",
        args=["1"],
    ).SerializeToString()


async def replay(
    host: str, port: int, username: str, reg: Registry
) -> list[tuple[int, int]]:
    answered: list[tuple[int, int]] = []

    ser = await Conn.open(host, port)
    req = reg.message_class("QuerySrvInfoReq")(server_id="1")
    frame = await ser.call(194, 2001, req.SerializeToString())
    answered.append((frame.service, frame.cmd))
    srv = reg.message_class("QuerySrvInfoRes")()
    srv.ParseFromString(frame.body)
    # The client keeps this socket open and never writes to it again
    # (connIndex 999, SERVER_SER); closing it here is the harsher variant and
    # proves the server does not tie player state to it.
    await ser.close()

    # addr's host half is the client-side alias (10.0.2.2 for the emulator),
    # which only resolves inside the AVD, so take the port and keep our host.
    _client_host, _, game_port = srv.addr.rpartition(":")
    game = await Conn.open(host, int(game_port), district=srv.district)

    body = reg.message_class("ProtocolReq")(issue=GAME_VERSION).SerializeToString()
    frame = await game.call(3, 2005, body)
    answered.append((frame.service, frame.cmd))

    frame = await game.call(3, 2015)
    answered.append((frame.service, frame.cmd))

    frame = await game.call(3, 2001, _login_body(reg, "LoginReq", username))
    answered.append((frame.service, frame.cmd))
    res = reg.message_class("LoginRes")()
    res.ParseFromString(frame.body)
    # LoginSocketData:loginReceiveHdr has the same branch. Against this server
    # it is not taken: 3_2001 creates the character and answers status 0.
    if res.status == 327682:
        frame = await game.call(3, 2003, _login_body(reg, "GameplayReq", username))
        answered.append((frame.service, frame.cmd))
        created = reg.message_class("GameplayRes")()
        created.ParseFromString(frame.body)
        assert created.status == 0, created.status

    frame = await game.call(5, 2005)
    answered.append((frame.service, frame.cmd))
    me = reg.message_class("QueryMyselfRes")()
    me.ParseFromString(frame.body)
    assert me.status == 0, me.status
    assert me.player.username == username, me.player.username
    assert me.player.nickname == username, me.player.nickname
    assert me.player.HasField("nobility_level")
    assert me.HasField("gold_trails")
    print(f"player {me.player.nickname!r} level {me.player.level}")

    for service, cmd in ((5, 2317), (151, 2041), (5, 2801), (153, 2001), (5, 2943)):
        frame = await game.call(service, cmd)
        answered.append((frame.service, frame.cmd))

    hb = reg.message_class("HeartbeatReq")(time=int(time.time())).SerializeToString()
    frame = await game.call(3, 2009, hb)
    answered.append((frame.service, frame.cmd))

    await game.close()
    return answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    s = load_settings(args.settings)
    reg = Registry.load(s.stock_dir)
    answered = asyncio.run(replay(args.host, args.port or s.port, s.username, reg))
    for service, cmd in answered:
        print(f"answered {service}_{cmd} {reg.name_for(service, cmd)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
