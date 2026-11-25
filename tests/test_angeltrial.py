"""Angel trials (女神试炼): the tower state, its events, fights and shops.

Angel trials open at function(10090).unlock_level 20 (FunctionType.lua:58).
The tower is angeltrials_level_info, 50 floors; each floor's event is 1
treasure, 2 fight or 3 buff shop (AngelTrainSceneUIPanel.lua:189-224). Floor
1 is a fight, 2 a buff shop of buff group 2 (arg0), 4 a treasure whose free
prize is angel_advance_free_drop 4000100 (one item 1900).
"""

import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero
from server.modules import angeltrial
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
# 25-11-2026 10:00 local: day_key(5) is 2026-11-25.
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
KNIGHT = 100000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=5000)
    conn.execute("UPDATE players SET level = 20 WHERE id = ?", (pid,))
    conn.commit()
    grant_hero(conn, pid, KNIGHT, 10, star=1, level=20)
    clock = {"now": T0}
    handlers = angeltrial.handlers(
        reg, settings, conn, cfg, rng=random.Random(7), clock=lambda: clock["now"]
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


def _call(reg, handlers, session, cmd, name, **fields):
    res = handlers[(8, cmd)](session, reg.message_class(name)(**fields))
    res.SerializeToString()
    return res


def _query(reg, handlers, session):
    return _call(reg, handlers, session, 2501, "QueryAngeltrialsDataReq")


def _start(reg, handlers, session):
    return _call(reg, handlers, session, 2503, "StartAngeltrialsReq")


def _event(reg, handlers, session, level, event):
    return _call(
        reg, handlers, session, 2505, "TriggerAngeltrialsEventReq",
        level=level, event=event,
    )


def _set_level(conn, pid, level):
    conn.execute("UPDATE angeltrials SET level = ? WHERE player_id = ?", (level, pid))
    conn.commit()


def _row(conn, pid):
    return conn.execute("SELECT * FROM angeltrials WHERE player_id = ?", (pid,)).fetchone()


# --- commit 1: the tower ------------------------------------------------------


def test_query_unopened_then_start_opens_level1(world, reg):
    conn, pid, handlers, session, _ = world
    res = _query(reg, handlers, session)
    assert res.status == 0
    # FunctionType.lua:484-497: opened = false makes the client send 8_2503.
    assert res.opened is False
    start = _start(reg, handlers, session)
    assert start.status == 0
    res = _query(reg, handlers, session)
    assert (res.opened, res.level, res.points, res.stars) == (True, 1, 0, 0)
    assert _row(conn, pid)["day"] == "2026-11-25"


def test_start_twice_refused_329730(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    assert _start(reg, handlers, session).status == 329730


def test_query_below_level20_refused_327957(world, reg):
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 19 WHERE id = ?", (pid,))
    conn.commit()
    assert _query(reg, handlers, session).status == 327957
    assert _start(reg, handlers, session).status == 327957


def test_event_before_start_refused_329729(world, reg):
    _, _, handlers, session, _ = world
    # AngelTryCtr.lua:129-133: 329729 is the "trial was reset, re-enter" alert.
    assert _event(reg, handlers, session, 1, 2).status == 329729


def test_event_on_wrong_level_refused_329731(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    res = _event(reg, handlers, session, 2, 3)
    assert res.status == 329731


def test_wrong_event_for_the_level_refused_329732(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 2)
    assert _event(reg, handlers, session, 2, 1).status == 329732


def test_event_past_the_top_refused_329733(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 51)
    assert _event(reg, handlers, session, 51, 2).status == 329733


def test_treasure_floor_pays_the_free_drop_once(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 4)
    res = _event(reg, handlers, session, 4, 1)
    assert res.status == 0 and (res.level, res.event) == (4, 1)
    treasure = res.eventResult.treasureEvent
    assert treasure.buyCount == 0
    assert [(p.category, p.refer, p.amount) for p in treasure.prizes] == [(20, 1900, 1)]
    owned = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = 1900", (pid,)
    ).fetchone()
    assert owned["amount"] == 1
    # The client resends 8_2505 after a reconnect; the prize is not paid twice
    # and an empty prize list takes it straight to the treasure panel
    # (AngelTrainSceneUIPanel.lua:196-204).
    again = _event(reg, handlers, session, 4, 1)
    assert again.status == 0 and list(again.eventResult.treasureEvent.prizes) == []
    owned = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = 1900", (pid,)
    ).fetchone()
    assert owned["amount"] == 1
    # The item arrives on the client as an ident-1 ClientNotification.
    assert any((s, c) == (5, 2008) for s, c, _ in session.outbox)


def test_buff_shop_offers_three_buffs_of_the_floors_group(world, reg, cfg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 2)
    res = _event(reg, handlers, session, 2, 3)
    assert res.status == 0
    offers = list(res.eventResult.buffShopEvent.angeltrialsBuffs)
    assert len(offers) == 3 and len(set(offers)) == 3
    groups = {int(b["id"]): int(b["group"]) for b in cfg.angeltrials_buffs()}
    # angeltrials_level_info(2).arg0 = 2: the cheap tutorial group 9101-9105.
    assert all(groups[b] == 2 for b in offers)
    # The same offer comes back on a resend.
    again = _event(reg, handlers, session, 2, 3)
    assert list(again.eventResult.buffShopEvent.angeltrialsBuffs) == offers


def test_daily_reset_at_5am(world, reg):
    conn, pid, handlers, session, clock = world
    _start(reg, handlers, session)
    conn.execute(
        "UPDATE angeltrials SET level = 9, points = 300, stars = 12,"
        " buffs = '[3]' WHERE player_id = ?", (pid,),
    )
    conn.commit()
    clock["now"] = datetime(2026, 11, 26, 4, 59).timestamp()
    res = _query(reg, handlers, session)
    assert (res.opened, res.level, res.points) == (True, 9, 300)
    clock["now"] = datetime(2026, 11, 26, 5, 0).timestamp()
    res = _query(reg, handlers, session)
    assert (res.opened, res.points, res.stars) == (False, 0, 0)
    # "介于你昨日的表现，今日可以快速碾压" (f00162): yesterday's cleared floors.
    assert res.crashLevel == 8
    row = _row(conn, pid)
    assert row["day"] == "2026-11-26"
    assert json.loads(row["buffs"]) == [] and json.loads(row["units"]) == []


def test_query_buffs_lists_the_owned_buffs(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    conn.execute("UPDATE angeltrials SET buffs = '[3, 9]' WHERE player_id = ?", (pid,))
    conn.commit()
    res = _call(reg, handlers, session, 2507, "QueryAngeltrialsBuffReq")
    assert res.status == 0 and list(res.angeltrialsBuffs) == [3, 9]


def test_rank_lists_only_self(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    conn.execute(
        "UPDATE angeltrials SET level = 6, points = 420 WHERE player_id = ?", (pid,)
    )
    conn.commit()
    res = _call(reg, handlers, session, 2517, "AngeltrialsRankReq")
    assert res.status == 0 and res.selfRank == 1
    assert len(res.leadings) == 1
    me = res.leadings[0]
    assert (me.id, me.name, me.atRank, me.atPoints, me.atLevel, me.level) == (
        pid, "stefan", 1, 420, 6, 20,
    )
    own = _call(reg, handlers, session, 2519, "AngeltrialsSelfRankReq")
    assert own.status == 0 and own.selfRank == 1
