"""The scripted client replaying the whole login burst against a live server.

Both sockets bind and connect to 127.0.0.1 explicitly (the name localhost
resolves ::1 first and costs about 2 s per connect on this machine), and the
server binds through bind_host so settings.host stays the client-side address
baked into the APK.
"""

import asyncio
from pathlib import Path

import pytest

from server import db
from server.modules import login, player
from server.net.registry import Registry
from server.net.server import Server
from server.settings import Settings
from tests.test_server_core import _run_server, _stop
from tools.fake_client import replay

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


def _settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", BIND, bind=BIND,
                    port=0, username="stefan", guide_id=0)


def test_full_login_burst_against_a_live_server(reg, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = db.connect(settings.db_path)

    async def scenario() -> list[tuple[int, int]]:
        handlers = {}
        handlers.update(login.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        got = await replay(BIND, port, "stefan", reg)
        assert server.sent_unknown == set()
        await _stop(task)
        return got

    answered = asyncio.run(scenario())

    assert answered == [
        (194, 2002),
        (3, 2006),
        (3, 2016),
        (3, 2002),   # status 0: 3_2001 created the character itself, so the
                     # replay skips 3_2003, exactly as the real client does
        (5, 2006),
        (5, 2318),
        (151, 2042),
        (5, 2802),
        (153, 2002),
        (5, 2944),
        (3, 2010),
    ]
    assert db.find_player(conn, "stefan") is not None


def test_second_run_reuses_the_character(reg, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = db.connect(settings.db_path)

    async def scenario() -> list[tuple[int, int]]:
        handlers = {}
        handlers.update(login.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        await replay(BIND, port, "stefan", reg)
        got = await replay(BIND, port, "stefan", reg)
        await _stop(task)
        return got

    answered = asyncio.run(scenario())
    assert (3, 2004) not in answered
    assert answered[3] == (3, 2002)
    assert answered[4] == (5, 2006)
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 1


def test_replay_echoes_the_district_from_query_srv_info_res(reg, tmp_path: Path) -> None:
    """The real client puts the district it was given at header offset 4."""
    settings = _settings(tmp_path)
    conn = db.connect(settings.db_path)
    seen: list[int] = []

    async def scenario() -> None:
        handlers = {}
        handlers.update(login.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))

        def on_protocol(session, req):
            seen.append(session.district)
            return reg.message_class("ProtocolRes")(issue_required=f"{req.issue}:0")

        handlers[(3, 2005)] = on_protocol
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        await replay(BIND, port, "stefan", reg)
        await _stop(task)

    asyncio.run(scenario())
    # login.srv_info answers district=1, so the game socket must carry 1.
    assert seen == [1]
