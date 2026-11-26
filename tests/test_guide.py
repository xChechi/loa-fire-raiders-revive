"""5_2041 SaveGuideIdReq: the guide id the client saves must survive a restart.

NewGuideManager sends this at four sites (NewGuideManager.lua:234, 331, 404, 725)
and it is the only request the new-player guide makes. RPGGame:init (RPGGame.lua:78)
opens the main scene directly when player.guide_id is not 0, so persisting this
value is exactly what stops the tutorial replaying.
"""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, set_guide_id
from server.modules import guide, player
from server.net.registry import Registry
from server.net.server import Server, Session
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"

# No new_player_guide_info row has this id (asserted in the test below, not
# assumed), so NewGuideManager could never resume from it.
UNKNOWN_GUIDE = 999999999

# The players table exactly as Plan A created it (server/db.py at d946f3c).
# A real character of Stefan's lives in a database of this shape.
PLAN_A_PLAYERS = """
CREATE TABLE players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    nickname   TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    gold       INTEGER NOT NULL DEFAULT 0,
    diamond    INTEGER NOT NULL DEFAULT 0,
    vip        INTEGER NOT NULL DEFAULT 0,
    energy     INTEGER NOT NULL DEFAULT 60,
    max_energy INTEGER NOT NULL DEFAULT 60,
    avatar     INTEGER NOT NULL DEFAULT 0,
    guide_id   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
"""


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
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind=BIND, port=0, username="stefan", guide_id=0,
    )


def test_save_guide_id_persists_and_answers_status_zero(reg, settings, cfg) -> None:
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)

    async def scenario() -> None:
        handlers = {}
        handlers.update(guide.handlers(reg, settings, conn, cfg))
        handlers.update(player.handlers(reg, settings, conn, cfg))
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        body = reg.message_class("SaveGuideIdReq")(guide_id=10041).SerializeToString()
        await client.send(5, 2041, body)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2042)
        res = reg.message_class("SaveGuideIdRes")()
        res.ParseFromString(frame.body)
        assert res.status == 0
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
    assert int(find_player(conn, "stefan")["guide_id"]) == 10041


def test_an_unknown_guide_id_is_refused_and_not_saved(reg, settings, cfg, caplog) -> None:
    """The guide_id is CLIENT input, and NewGuideManager:check resumes from it
    by looking the row up. An id with no new_player_guide_info row cannot be
    resumed, so storing it would strand the tutorial: refuse with status 1,
    warn, write nothing. No monotonicity check - the guide legitimately jumps
    backwards (jump_id)."""
    assert cfg.guide(10041) is not None          # the id the tests above save
    assert cfg.guide(UNKNOWN_GUIDE) is None
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 10041)
    handlers = guide.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid

    req = reg.message_class("SaveGuideIdReq")(guide_id=UNKNOWN_GUIDE)
    with caplog.at_level("WARNING"):
        res = handlers[(5, 2041)](session, req)

    assert res.status == 1
    assert str(UNKNOWN_GUIDE) in caplog.text
    assert int(find_player(conn, "stefan")["guide_id"]) == 10041


def test_a_later_guide_id_overwrites_an_earlier_one(reg, settings) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 10041)
    set_guide_id(conn, pid, 10160)
    assert int(find_player(conn, "stefan")["guide_id"]) == 10160


def test_query_myself_reports_the_saved_guide_id(reg, cfg, settings) -> None:
    """The client seeds NewGuideManager from QueryMyselfRes.player.guide_id."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 10160)
    res = player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert res.player.guide_id == 10160


def test_a_plan_a_players_row_survives_and_keeps_its_data(settings) -> None:
    """Opening a Plan A database must not rebuild or touch the existing row."""
    raw = sqlite3.connect(settings.db_path)
    raw.executescript(PLAN_A_PLAYERS)
    raw.execute(
        "INSERT INTO players (username, nickname, level, xp, gold, diamond, vip,"
        " energy, max_energy, avatar, guide_id, created_at)"
        " VALUES ('stefan', 'Stefan', 7, 310, 1234, 55, 1, 48, 72, 3, 0,"
        " '2026-10-21T12:31:00+00:00')"
    )
    raw.commit()
    raw.close()

    conn = connect(settings.db_path)
    row = find_player(conn, "stefan")
    assert (row["nickname"], row["level"], row["xp"], row["gold"]) == (
        "Stefan", 7, 310, 1234
    )
    assert (row["diamond"], row["vip"], row["energy"], row["max_energy"]) == (
        55, 1, 48, 72
    )
    assert row["avatar"] == 3
    assert row["created_at"] == "2026-10-21T12:31:00+00:00"

    set_guide_id(conn, int(row["id"]), 10160)
    after = find_player(conn, "stefan")
    assert int(after["guide_id"]) == 10160
    assert (after["nickname"], after["level"], after["gold"]) == ("Stefan", 7, 1234)


# BattleEndLayer.lua:1041-1048 calls NewGuideManager:check(id, nil, true) for
# these eight ids after EVERY fight (lost or won, campaign, elite, angel trial).
BATTLE_END_BURST = (10160, 10159, 10290, 10330, 10380, 10500, 10540, 10580)


def _save(reg, settings, conn, cfg, pid, gid):
    handlers = guide.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    req = reg.message_class("SaveGuideIdReq")(guide_id=gid)
    return handlers[(5, 2041)](session, req)


def test_a_post_fight_burst_does_not_overwrite_an_unrelated_guide_step(
    reg, settings, cfg
) -> None:
    """Runs 8, 10 and 11: after each fight the client sent the eight ids of
    BattleEndLayer.lua:1041-1048 and guide_id fell 11208 -> 10380 (and
    10390 -> 10380). NewGuideManager:check (NewGuideManager.lua:238-331)
    sends `id` to the server only after the "引导接不上" test at :290-298
    (data.nextid must equal id), but when no guide is playing
    (self.guideData == nil, set at :430 when the step's node is missing) it
    takes the isFirst branch (:276-288), skips that test, and sends every id
    of the burst while it actually replays saveGuideId's own next step.
    So a burst id is the guide's progress only when it is the saved step's
    nextid (or the saved step itself)."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    for start in (11208, 10390):
        set_guide_id(conn, pid, start)
        for gid in BATTLE_END_BURST:
            _save(reg, settings, conn, cfg, pid, gid)
        assert int(find_player(conn, "stefan")["guide_id"]) == start


def test_a_burst_id_that_is_the_saved_steps_next_is_saved(reg, settings, cfg) -> None:
    """The tutorial path the burst exists for: 10150 -> 10160 (run 2), 10280 ->
    10290 (run 6) and 10313 -> 10380 (run 7) are each row's nextid."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    for before, after in ((10150, 10160), (10280, 10290), (10313, 10380)):
        assert int(cfg.guide(before)["nextid"]) == after
        set_guide_id(conn, pid, before)
        for gid in BATTLE_END_BURST:
            _save(reg, settings, conn, cfg, pid, gid)
        assert int(find_player(conn, "stefan")["guide_id"]) == after


def test_a_lower_guide_id_outside_the_burst_is_still_saved(reg, settings, cfg) -> None:
    """Guide ids are not ordered in play: run 10 went 11208 -> 10400 -> 10410
    legitimately (the achievement guide after the train guide), so the
    server keeps no numeric monotonicity."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 11208)
    res = _save(reg, settings, conn, cfg, pid, 10400)
    assert res.status == 0
    assert int(find_player(conn, "stefan")["guide_id"]) == 10400


# Board f-216389: until Wave 4 the arena and guild do not exist, so the saved
# 11700 (level 15) and 14202 (level 40) would replay at every login: check(0)
# follows jump_id (NewGuideManager.lua:255-259) to 11701/14201, whose nextid is
# the guide again. The chains' own last steps 11750 and 14204 have nextid
# 99999, which has no row, so playGuide(nil) just clears (:362-366), the same
# end as 11820 or 11640.
@pytest.mark.parametrize("stored, reported", [(11700, 11750), (14202, 14204)])
def test_an_unreachable_guide_is_reported_as_its_chains_finished_step(
    reg, cfg, settings, stored, reported
) -> None:
    assert int(cfg.guide(reported)["nextid"]) == 99999
    assert int(cfg.guide(reported)["jump_id"]) == 0
    assert cfg.guide(99999) is None
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, stored)
    res = player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert res.player.guide_id == reported
    assert int(find_player(conn, "stefan")["guide_id"]) == stored


def test_other_guides_are_reported_unchanged_and_the_stored_value_is_kept(
    reg, cfg, settings
) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_guide_id(conn, pid, 11820)
    res = player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert res.player.guide_id == 11820
    set_guide_id(conn, pid, 11700)
    player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert int(find_player(conn, "stefan")["guide_id"]) == 11700
