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


# Every IMPL/ANS Req of the Wave 1 inventory (plan 2026-11-24, tables A-I),
# except the achievements of table H, which E1 adds.
WAVE1_IDS = [
    (5, 2303), (5, 2305),
    (5, 2105), (5, 2163), (5, 2109), (5, 2111), (5, 2725), (5, 2107), (5, 2127),
    (5, 2139),
    (5, 2137), (5, 2131), (5, 2933), (5, 2037),
    (5, 2013), (5, 2145), (5, 2141), (5, 2147), (5, 2143), (5, 2129), (5, 2135),
    (5, 2643), (5, 2649),
    (5, 2015), (5, 2009), (5, 2023), (5, 2025), (5, 2585), (5, 2043),
    (5, 2223), (5, 2225), (5, 2227),
    (5, 2205), (5, 2207), (11, 2005), (11, 2009),
]


def test_build_handlers_covers_wave1_ids(reg, settings) -> None:
    from server.__main__ import build_handlers
    from server.modules import activity

    handlers = build_handlers(reg, settings)
    missing = [k for k in [*WAVE1_IDS, *activity.CLOSED_IDS] if k not in handlers]
    assert missing == []


def _login_once(reg, settings, cfg, cmd: int = 2001, name: str = "LoginReq"):
    conn = connect(settings.db_path)
    handlers = login.handlers(reg, settings, conn, cfg)
    body = reg.message_class(name)(
        username="stefan", token="local", datetime=1, args=["1"]
    )
    res = handlers[(3, cmd)](Session(writer=None, peer="t", bound_port=0), body)
    return conn, res


def test_login_records_login_day(reg, settings, cfg) -> None:
    from datetime import date

    conn, _ = _login_once(reg, settings, cfg)
    row = find_player(conn, "stefan")
    assert row["last_login_day"] == date.today().isoformat()
    assert int(row["login_days"]) == 1
    assert int(row["login_award"]) & 1 == 1  # day 1 claimable
    assert row["daily_day"] == date.today().isoformat()

    # a second login the same day counts nothing more
    login.handlers(reg, settings, conn, cfg)[(3, 2001)](
        Session(writer=None, peer="t", bound_port=0),
        reg.message_class("LoginReq")(username="stefan", token="local"),
    )
    assert int(find_player(conn, "stefan")["login_days"]) == 1


def test_gameplay_records_login_day(reg, settings, cfg) -> None:
    from datetime import date

    conn, _ = _login_once(reg, settings, cfg, 2003, "GameplayReq")
    assert find_player(conn, "stefan")["last_login_day"] == date.today().isoformat()


def test_login_res_carries_blacklist(reg, settings, cfg) -> None:
    from server.modules import activity

    expected = activity.blacklist_entries(cfg)
    for cmd, name in ((2001, "LoginReq"), (2003, "GameplayReq")):
        _, res = _login_once(reg, settings, cfg, cmd, name)
        assert [(b.entry, b.disabled) for b in res.blacklist] == expected
        assert 10410 not in {b.entry for b in res.blacklist}  # 7-day login visible
        res.SerializeToString()


def test_login_rolls_yesterdays_stage_counts(reg, settings, cfg) -> None:
    """QueryMyselfRes.levels must carry today's counts, so a levels row whose
    deadline has passed is reset at login, before the client asks 5_2005."""
    import time

    conn, _ = _login_once(reg, settings, cfg)
    pid = int(find_player(conn, "stefan")["id"])
    conn.execute(
        "INSERT INTO levels (player_id, level, star, count, reset_count, deadline)"
        " VALUES (?, 10000, 3, 5, 1, 1)", (pid,),
    )
    conn.commit()
    login.handlers(reg, settings, conn, cfg)[(3, 2001)](
        Session(writer=None, peer="t", bound_port=0),
        reg.message_class("LoginReq")(username="stefan", token="local"),
    )
    row = conn.execute(
        "SELECT count, reset_count, deadline FROM levels WHERE player_id = ?", (pid,)
    ).fetchone()
    assert (int(row["count"]), int(row["reset_count"])) == (0, 0)
    assert int(row["deadline"]) > int(time.time())


# Every IMPL/ANS Req of the Wave 2 inventory (plan 2026-11-25, tables A-F);
# the 5_2020/5_2022 pushes have no Req and are not handler keys.
WAVE2_IDS = [
    (5, 2121), (5, 2123), (5, 2103), (5, 2139), (5, 2119), (5, 2117), (5, 2125),
    (5, 2165),
    (5, 2323), (5, 2309),
    (5, 2201), (5, 2203), (5, 2337),
    (5, 2129),
    (5, 2213), (5, 2215), (5, 2217),
    (5, 2331), (5, 2333), (5, 2335),
    *[(8, cmd) for cmd in range(2501, 2528, 2)],
    (5, 2161), (5, 2565),
    (5, 2241), (5, 2243),
]


def test_build_handlers_covers_wave2_ids(reg, settings) -> None:
    from server.__main__ import build_handlers

    assert len([k for k in WAVE2_IDS if k[0] == 8]) == 14
    handlers = build_handlers(reg, settings)
    assert [k for k in WAVE2_IDS if k not in handlers] == []


def _merchant_world(reg, settings, cfg, mystery_energy: int):
    """A level-16 player one stage entry (6 energy) short of
    max_appeared_cost 600, so the merchant must appear (O-W2-11)."""
    from server.db import create_player
    from server.modules import level

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    conn.execute(
        "UPDATE players SET level = 16, mystery_energy = ? WHERE id = ?",
        (mystery_energy, pid),
    )
    conn.commit()
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, level.handlers(reg, settings, conn, cfg), session


def _merchant_pushes(session) -> list:
    return [m for s, c, m in session.outbox if (s, c) == (5, 2020)]


def test_stage_entry_feeds_the_merchant_roll(reg, settings, cfg) -> None:
    conn, pid, handlers, session = _merchant_world(reg, settings, cfg, 594)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0
    pushes = _merchant_pushes(session)
    assert len(pushes) == 1 and pushes[0].store.store == 2 and pushes[0].onEnergyCost
    row = find_player(conn, "stefan")
    assert int(row["energy_use"]) == 6
    assert int(row["mystery_energy"]) == 0
    assert int(row["mystery_shown"]) == 1


def test_stage_sweep_feeds_the_merchant_roll(reg, settings, cfg) -> None:
    from server.db import upsert_level

    conn, pid, handlers, session = _merchant_world(reg, settings, cfg, 594)
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    res = handlers[(5, 2205)](
        session, reg.message_class("LevelCleanReq")(level=10000, times=1)
    )
    assert res.flag == 0
    assert len(_merchant_pushes(session)) == 1
    assert int(find_player(conn, "stefan")["energy_use"]) == 6


def test_query_myself_tells_an_expired_merchant_to_leave(reg, settings, cfg) -> None:
    import time

    from server.modules import player

    conn, pid, _h, session = _merchant_world(reg, settings, cfg, 0)
    handlers = player.handlers(reg, settings, conn, cfg)
    req = reg.message_class("QueryMyselfReq")()
    handlers[(5, 2005)](session, req)
    assert [(s, c) for s, c, _m in session.outbox if (s, c) == (5, 2022)] == []

    conn.execute(
        "UPDATE players SET mystery_appear = ?, mystery_stay = 3600 WHERE id = ?",
        (int(time.time()) - 3601, pid),
    )
    conn.commit()
    handlers[(5, 2005)](session, req)
    gone = [m for s, c, m in session.outbox if (s, c) == (5, 2022)]
    assert len(gone) == 1 and gone[0].store == 2


def test_login_hero_payload_carries_the_rune_stats(reg, settings, cfg) -> None:
    """QueryMyselfRes.heroes is what the client fights and shows with until a
    notify says otherwise, so a levelled rune's stats must be in it."""
    from server.db import create_player, grant_hero, heroes_of
    from server.modules import hero, player

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_hero(conn, pid, 100000, 10, star=1, level=30)
    row = find_player(conn, "stefan")
    plain = player.build_query_myself_res(reg, cfg, conn, row).heroes[0]
    conn.execute(
        "INSERT INTO runes (player_id, hero, idx, level, rune_val) VALUES (?, ?, 1, 2, 7)",
        (pid, 100000),
    )
    conn.commit()
    sent = player.build_query_myself_res(reg, cfg, conn, row).heroes[0]
    hero_row = heroes_of(conn, pid)[0]
    expected = hero.build_client_hero_with_runes(
        reg, cfg, hero_row, hero.runes_of(conn, hero_row)
    )
    assert [(r.idx, r.level, r.rune_val) for r in sent.runes][1] == (1, 2, 7)
    assert sent.unit == expected.unit
    assert sent.unit != plain.unit
    assert sent.base_unit == plain.base_unit


# Every IMPL/ANS Req of the Wave 3 Phase B inventory (plan 2026-11-26,
# "Req inventory"); 5_2201/5_2203 on type-13 stages ride level.py's keys.
WAVE3_IDS = [
    (5, 2571), (5, 2573), (5, 2575), (5, 2577), (5, 2597), (5, 2671),
    (5, 2701), (5, 2703), (5, 2705),
    (5, 2727), (5, 2729), (5, 2731),
    (5, 2909), (5, 2911), (5, 2913),
    (5, 2621), (5, 2733), (5, 2735), (5, 2737), (5, 2739), (5, 2805),
    (5, 2811), (5, 2813), (5, 2815),
    (5, 2695),
    *[(5, cmd) for cmd in (2517, 2519, 2521, 2523, 2525, 2527, 2529, 2531, 2543,
                           2547, 2551, 2563)],
    *[(5, cmd) for cmd in (2533, 2535, 2537, 2539, 2541, 2545, 2549, 2553, 2555)],
    (5, 2779), (5, 2781), (5, 2783), (5, 2785), (5, 2803),
]


def test_build_handlers_covers_wave3_ids(reg, settings) -> None:
    from server.__main__ import build_handlers

    assert len(WAVE3_IDS) == len(set(WAVE3_IDS)) == 51
    handlers = build_handlers(reg, settings)
    assert [k for k in WAVE3_IDS if k not in handlers] == []
