"""5_2137 SellItem, 5_2131 UseItem, 5_2933 ItemBuy, 5_2139 QueryTrainInfo.

Stock rows used below (item_info stores TEXT): 10000 粗布头巾 price 150;
1800 美味吐司 class 99 price 0; 1140 联盟经验合剂 class 45 arg0 100.
item_buy_info: category 20 refer 1210800 rate 500.
"""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_item, items_of
from server.modules import bag
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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=18888)
    handlers = bag.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _player(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _items(conn, pid) -> dict[int, int]:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}


def _call(reg, handlers, session, cmd, **kw):
    name = reg.name_for(5, cmd)
    return handlers[(5, cmd)](session, reg.message_class(name)(**kw))


def _notes(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


def test_sell_10000_pays_price_150_each(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 10000, 3)
    res = _call(reg, handlers, session, 2137, item=10000, amount=2)
    assert (res.status, res.item, res.amount) == (0, 10000, 2)
    assert int(_player(conn, pid)["gold"]) == 1000 + 300
    assert _items(conn, pid) == {10000: 1}
    assert [list(m.data) for m in _notes(session, 4)] == [[10000.0, 1.0]]
    assert [list(m.data) for m in _notes(session, 1)] == [[1300.0]]
    res.SerializeToString()


def test_sell_refused_327942_when_short(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 10000, 1)
    assert _call(reg, handlers, session, 2137, item=10000, amount=2).status == 327942
    assert _items(conn, pid) == {10000: 1}
    assert int(_player(conn, pid)["gold"]) == 1000
    assert session.outbox == []


def test_sell_unpriced_refused_327948(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 1800, 2)
    assert _call(reg, handlers, session, 2137, item=1800, amount=1).status == 327948
    assert _items(conn, pid) == {1800: 2}
    assert int(_player(conn, pid)["gold"]) == 1000
    assert session.outbox == []


def test_use_class45_adds_player_xp(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    from server import db

    grant_item(conn, pid, 1140, 3)
    res = _call(reg, handlers, session, 2131, item=1140, amount=2)
    assert res.status == 0 and res.amount == 2
    assert [(p.category, p.refer, p.amount) for p in res.prizes] == [(11, 0, 200)]
    # The same 200 xp through db.add_player_xp on a twin player.
    twin = create_player(conn, "twin", "twin", guide_id=0)
    db.add_player_xp(conn, cfg, twin, 200)
    me, other = _player(conn, pid), _player(conn, twin)
    assert (int(me["level"]), int(me["xp"])) == (int(other["level"]), int(other["xp"]))
    assert int(me["level"]) > 1
    assert _items(conn, pid) == {1140: 1}
    assert [list(m.data) for m in _notes(session, 4)] == [[1140.0, 1.0]]
    assert len(_notes(session, 1)) == 1
    assert len([m for (_s, c, m) in session.outbox if c == 2036]) == 1
    res.SerializeToString()


def test_use_unknown_class_refused_327948(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_item(conn, pid, 1800, 2)
    res = _call(reg, handlers, session, 2131, item=1800, amount=1)
    assert res.status == 327948
    assert _items(conn, pid) == {1800: 2}
    assert session.outbox == []
    res.SerializeToString()


def test_use_refused_327942_when_short(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _call(reg, handlers, session, 2131, item=1140, amount=1)
    assert res.status == 327942
    assert int(_player(conn, pid)["xp"]) == 0
    assert session.outbox == []


def test_item_buy_charges_rate(reg, world) -> None:
    conn, pid, handlers, session = world
    req = reg.message_class("ItemBuyReq")()
    req.prize.category, req.prize.refer, req.prize.amount = 20, 1210800, 2
    res = handlers[(5, 2933)](session, req)
    assert res.ListFields() == []
    assert int(_player(conn, pid)["diamond"]) == 18888 - 1000
    assert _items(conn, pid) == {1210800: 2}
    assert [list(m.data) for m in _notes(session, 4)] == [[1210800.0, 2.0]]
    assert [list(m.data) for m in _notes(session, 1)] == [[18888.0 - 1000]]
    res.SerializeToString()


def test_item_buy_short_or_unconfigured_changes_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET diamond = 999 WHERE id = ?", (pid,))
    conn.commit()
    for category, refer in ((20, 1210800), (20, 10000), (9, 1210800)):
        req = reg.message_class("ItemBuyReq")()
        req.prize.category, req.prize.refer, req.prize.amount = category, refer, 2
        handlers[(5, 2933)](session, req).SerializeToString()
    assert int(_player(conn, pid)["diamond"]) == 999
    assert _items(conn, pid) == {}
    assert session.outbox == []


def test_train_info_is_valid_and_empty(reg, world) -> None:
    _conn, _pid, handlers, session = world
    res = _call(reg, handlers, session, 2139, op=0)
    assert res.status == 0
    assert list(res.trains) == [] and list(res.items) == [] and list(res.logs) == []
    res.SerializeToString()
