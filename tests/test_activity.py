"""Server-run activities answer "closed", and the LoginRes function blacklist."""

import logging
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import activity
from server.net import msgmap
from server.net.registry import Registry
from server.net.server import Session, fill_required
from server.settings import Settings

STOCK = Path(".stock")


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    handlers = activity.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _has_status(msg) -> bool:
    return any(fd.name == "status" for fd in msg.DESCRIPTOR.fields)


def _answer(reg, handlers, session, key):
    return handlers[key](session, reg.class_for(*key)())


def test_every_closed_id_answers_327974_or_has_no_status(reg, world, caplog) -> None:
    _, _, handlers, session = world
    assert set(handlers) == set(activity.CLOSED_IDS)
    # Table G of the plan plus 5_2037, 5_2643 and 5_2649.
    assert {(5, 2319), (5, 2581), (5, 2583), (5, 2037), (5, 2643), (5, 2649)} <= set(handlers)
    with_status = set()
    with caplog.at_level(logging.INFO, logger="loa.activity"):
        for key in activity.CLOSED_IDS:
            assert reg.name_for(*key) is not None, key
            res_key = msgmap.res_key(reg.ids, *key)
            res = _answer(reg, handlers, session, key)
            assert type(res) is reg.class_for(*res_key)
            if _has_status(res):
                assert res.status == 327974  # language.db 活动尚未开启或已结束
                with_status.add(key)
            else:
                empty = reg.class_for(*res_key)()
                fill_required(empty)
                assert res == empty
            # Asked twice, logged once.
            _answer(reg, handlers, session, key)
    assert with_status == {(5, 2319), (5, 2321), (5, 2037)}
    logged = [r for r in caplog.records if r.name == "loa.activity"]
    assert len(logged) == len(activity.CLOSED_IDS)
    assert session.outbox == []


def test_closed_responses_serialise(reg, world) -> None:
    _, _, handlers, session = world
    for key in activity.CLOSED_IDS:
        res = _answer(reg, handlers, session, key)
        raw = res.SerializeToString()
        assert type(res).FromString(raw) == res


def test_blacklist_entries_exist_in_functions_table(reg, cfg) -> None:
    entries = activity.blacklist_entries(cfg)
    assert [e for e, _ in entries] == [
        10100, 10101, 10102, 10103, 10220, 60010, 70010, 70020, 90010, 90050,
        90060, 90090, 90200, 90230, 90250, 90270, 90290, 90310, 90320, 90330,
        90340, 90360, 90370, 90380, 90390, 90400,
    ]
    assert all(disabled == 1 for _, disabled in entries)
    known = {
        int(row["entry"])
        for row in cfg.conn("functions").execute("SELECT entry FROM [function]")
    }
    assert {e for e, _ in entries} <= known
    # The pair fits LoginRes.blacklist (ClientFunctionBlackList{entry, disabled}).
    res = reg.message_class("LoginRes")()
    for entry, disabled in entries:
        res.blacklist.add(entry=entry, disabled=disabled)
    assert len(res.blacklist) == len(entries)


def test_blacklist_keeps_7day_login_and_signin_visible(cfg) -> None:
    ids = {e for e, _ in activity.blacklist_entries(cfg)}
    # 10410 7日登陆礼包, 10600 至尊签到, 10610 开服7日活动 (functions.db).
    assert ids.isdisjoint({10410, 10600, 10610})
