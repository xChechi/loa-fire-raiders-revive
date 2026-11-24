"""11_2005 QueryTalkDataReq and 11_2009 QueryHistoryTalkReq: valid empty answers."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import chat
from server.net.registry import Registry
from server.net.server import Session
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
    handlers = chat.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def test_query_talk_data_has_exactly_one_world_entry(reg, world) -> None:
    """ChatRoom:dealWithQueryTalkDataRes reads msg.data[1].talkTimes with no
    nil check (ChatRoom.lua:1161-1166); data[2] would be the guild channel."""
    _, _, handlers, session = world
    res = handlers[(11, 2005)](session, reg.message_class("QueryTalkDataReq")())
    assert res.status == 0
    assert len(res.data) == 1
    world_entry = res.data[0]
    assert (world_entry.channel, world_entry.talkTimes, world_entry.timeLimit) == (0, 0, 0)
    assert res.ignoreLevel == 0
    assert session.outbox == []


def test_query_history_talk_echoes_channel_and_is_empty(reg, world) -> None:
    """ChatRoom:refreshTalkTimes asks channel 0 and channel 1 (ChatRoom.lua:1180-1181)."""
    _, _, handlers, session = world
    for channel in (0, 1):
        req = reg.message_class("QueryHistoryTalkReq")(channel=channel)
        res = handlers[(11, 2009)](session, req)
        assert res.status == 0
        assert res.channel == channel
        assert list(res.speaks) == []


def test_chat_responses_serialise(reg, world) -> None:
    _, _, handlers, session = world
    talk = handlers[(11, 2005)](session, reg.message_class("QueryTalkDataReq")())
    history = handlers[(11, 2009)](
        session, reg.message_class("QueryHistoryTalkReq")(channel=1)
    )
    for res in (talk, history):
        raw = res.SerializeToString()
        again = type(res).FromString(raw)
        assert again == res
    assert reg.class_for(11, 2006) is type(talk)
    assert reg.class_for(11, 2010) is type(history)
