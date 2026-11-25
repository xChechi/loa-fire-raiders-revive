"""5_2129 QueryOrRefreshStoreInfoReq and 5_2135 BuyMerchandiseReq.

Store 1 (普通金币商店) shows store_info.merchandise_amount = 8 slots, has
free_refresh = 4 and refresh_cost "100|2,200|2,..." in refresh_cost_type 9
(diamond). The client sends op 1 to open the shop and op 2 to refresh it
(AllShopUI.lua:621,1169; NormalShop.lua:439,715). Merchandise 100020 is item
100000 x1 for 20000 gold (price_type 1)."""

import json
import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, items_of
from server.modules import shop
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
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = shop.handlers(reg, settings, conn, cfg, rng=random.Random(7))
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _query(reg, handlers, session, store=1, op=1):
    return handlers[(5, 2129)](
        session, reg.message_class("QueryOrRefreshStoreInfoReq")(type=store, op=op)
    )


def _buy(reg, handlers, session, store=1, index=0, number=1):
    return handlers[(5, 2135)](
        session,
        reg.message_class("BuyMerchandiseReq")(type=store, index=index, number=number),
    )


def _wallet(conn, pid) -> tuple[int, int]:
    row = conn.execute("SELECT gold, diamond FROM players WHERE id = ?", (pid,)).fetchone()
    return int(row["gold"]), int(row["diamond"])


def _seed_slots(conn, pid, store, entries) -> None:
    conn.execute(
        "UPDATE stores SET slots = ? WHERE player_id = ? AND store = ?",
        (json.dumps([{"merchandise": e, "buy": 0} for e in entries]), pid, store),
    )
    conn.commit()


def test_store1_has_eight_slots_within_level_range(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = _query(reg, handlers, session)
    assert res.status == 0
    assert res.store.store == 1
    assert res.store.lastupdate > 0
    assert res.store.remain_free_refresh == 4
    slots = list(res.store.merchandise)
    assert len(slots) == 8
    assert [s.index for s in slots] == list(range(8))
    entries = [s.merchandise for s in slots]
    assert len(set(entries)) == 8
    rows = {int(r["entry"]): r for r in cfg.merchandise(1)}
    for s in slots:
        row = rows[s.merchandise]
        assert int(row["min_level"]) <= 1 <= int(row["max_level"])
        assert int(row["min_vip"]) <= 0 <= int(row["max_vip"])
        assert s.buy == 0
        # 100 = no discount: the client multiplies the price by discount/100
        # whenever the field is present (AllShopUI.lua:831-833).
        assert s.discount == 100
    # Level 1 never sees the level-50 row 100010.
    assert 100010 not in entries
    res.SerializeToString()


def test_query_twice_returns_same_slots(reg, world) -> None:
    conn, pid, handlers, session = world
    first = _query(reg, handlers, session)
    second = _query(reg, handlers, session, op=1)
    assert [s.merchandise for s in first.store.merchandise] == [
        s.merchandise for s in second.store.merchandise
    ]
    assert first.store.lastupdate == second.store.lastupdate


def test_refresh_free_four_times_then_costs(reg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    gold, diamond = _wallet(conn, pid)
    for left in (3, 2, 1, 0):
        res = _query(reg, handlers, session, op=2)
        assert res.status == 0
        assert res.store.remain_free_refresh == left
        assert len(res.store.merchandise) == 8
    assert _wallet(conn, pid) == (gold, diamond)
    assert session.outbox == []
    # The fifth refresh is the first paid one: tier "100|2" costs 100 diamonds.
    res = _query(reg, handlers, session, op=2)
    assert res.status == 0
    assert _wallet(conn, pid) == (gold, diamond - 100)
    assert len(session.outbox) == 1
    # Paid refreshes 2 and 3 cost 100 and 200 (MMTools:getCostNum).
    _query(reg, handlers, session, op=2)
    _query(reg, handlers, session, op=2)
    assert _wallet(conn, pid) == (gold, diamond - 400)


def test_refresh_short_of_diamonds_refused_327938(reg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    for _ in range(4):
        _query(reg, handlers, session, op=2)
    conn.execute("UPDATE players SET diamond = 99 WHERE id = ?", (pid,))
    conn.commit()
    before = [s.merchandise for s in _query(reg, handlers, session).store.merchandise]
    res = _query(reg, handlers, session, op=2)
    assert res.status == 327938
    assert _wallet(conn, pid)[1] == 99
    assert [s.merchandise for s in _query(reg, handlers, session).store.merchandise] == before


def test_refresh_past_the_last_tier_refused_329985(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    tiers = sum(int(t.split("|")[1]) for t in cfg.store(1)["refresh_cost"].split(","))
    conn.execute(
        "UPDATE stores SET refresh_used = ? WHERE player_id = ? AND store = 1",
        (4 + tiers, pid),
    )
    conn.commit()
    res = _query(reg, handlers, session, op=2)
    assert res.status == 329985


def test_buy_marks_slot_and_charges_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    _seed_slots(conn, pid, 1, [100020, 100030])
    gold, diamond = _wallet(conn, pid)
    res = _buy(reg, handlers, session, index=1)
    assert res.status == 0
    res.SerializeToString()
    assert _wallet(conn, pid) == (gold - 20000, diamond)
    assert {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)} == {101000: 1}
    slots = list(_query(reg, handlers, session).store.merchandise)
    assert [(s.merchandise, s.buy) for s in slots] == [(100020, 0), (100030, 1)]
    # One gold notify and one item notify.
    assert len(session.outbox) == 2


def test_buy_same_slot_refused_329988(reg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    _seed_slots(conn, pid, 1, [100020])
    assert _buy(reg, handlers, session, index=0).status == 0
    gold, _ = _wallet(conn, pid)
    res = _buy(reg, handlers, session, index=0)
    assert res.status == 329988
    assert _wallet(conn, pid)[0] == gold


def test_buy_short_of_gold_refused_327937(reg, world) -> None:
    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    _seed_slots(conn, pid, 1, [100020])
    conn.execute("UPDATE players SET gold = 19999 WHERE id = ?", (pid,))
    conn.commit()
    res = _buy(reg, handlers, session, index=0)
    assert res.status == 327937
    assert items_of(conn, pid) == []


def test_unsupported_currency_refused_and_logged(reg, cfg, world, caplog) -> None:
    conn, pid, handlers, session = world
    arena = next(r for r in cfg.merchandise(3) if int(r["price_type"]) == 51)
    _query(reg, handlers, session, store=3)
    _seed_slots(conn, pid, 3, [int(arena["entry"])])
    before = _wallet(conn, pid)
    with caplog.at_level("WARNING", logger="loa.shop"):
        res = _buy(reg, handlers, session, store=3, index=0)
    assert res.status == 327681
    assert "price_type 51" in caplog.text
    assert _wallet(conn, pid) == before
    assert items_of(conn, pid) == []


def test_buy_past_the_stack_limit_queues_the_mail_notify(reg, cfg, world) -> None:
    """Merchandise 100030 is one hero-soul item 101000; a full stack sends the
    rest to mail 99999, and the client is told a mail arrived."""
    from server.db import grant_item

    conn, pid, handlers, session = world
    _query(reg, handlers, session)
    _seed_slots(conn, pid, 1, [100030])
    grant_item(conn, pid, 101000, int(cfg.item(101000)["stackable"]))
    assert _buy(reg, handlers, session, index=0).status == 0
    assert 7 in [m.ident for (_s, c, m) in session.outbox if c == 2008]


# --- store 2, the mystery merchant (O-W2-11) --------------------------------

T0 = 1_800_000_000


@pytest.fixture
def merchant(settings, cfg, reg):
    """A level-16 player and a shop whose clock is T0."""
    from server.modules import mystery

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=1000)
    conn.execute("UPDATE players SET level = 16 WHERE id = ?", (pid,))
    conn.commit()
    clock = {"now": T0}
    handlers = shop.handlers(
        reg, settings, conn, cfg, rng=random.Random(7), clock=lambda: clock["now"]
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid

    def appear(now=T0):
        always = random.Random(0)
        always.random = lambda: 0.0
        assert mystery.on_energy_spent(
            conn, cfg, reg, session, pid, 600, rng=always, now=now
        )
        session.outbox.clear()

    return conn, pid, handlers, session, clock, appear


def test_store2_opens_during_the_stay_with_lastappear(reg, merchant) -> None:
    conn, pid, handlers, session, clock, appear = merchant
    appear()
    clock["now"] = T0 + 3599
    res = _query(reg, handlers, session, store=2)
    assert res.status == 0
    assert res.store.store == 2
    assert res.store.lastappear == T0
    assert res.store.stay_time == 3600
    assert len(res.store.merchandise) == 12
    res.SerializeToString()


def test_store2_closed_after_stay_refused_329986(reg, merchant) -> None:
    conn, pid, handlers, session, clock, appear = merchant
    appear()
    # GameSceneOtherPanel.lua:75-92 sends op 1 when the stay runs out, so that
    # the server answers with the leave push 5_2022.
    clock["now"] = T0 + 3600
    res = _query(reg, handlers, session, store=2)
    assert res.status == 329986
    assert [(s, c, m.store) for (s, c, m) in session.outbox] == [(5, 2022, 2)]


def test_store2_never_appeared_refused_329986(reg, merchant) -> None:
    conn, pid, handlers, session, clock, appear = merchant
    res = _query(reg, handlers, session, store=2)
    assert res.status == 329986
    assert session.outbox == []


def test_store2_below_level16_refused_327957(reg, merchant) -> None:
    conn, pid, handlers, session, clock, appear = merchant
    appear()
    conn.execute("UPDATE players SET level = 15 WHERE id = ?", (pid,))
    conn.commit()
    res = _query(reg, handlers, session, store=2)
    assert res.status == 327957


def test_vip14_store2_has_no_stay(reg, merchant) -> None:
    conn, pid, handlers, session, clock, appear = merchant
    # VIP >= vip_buy_level 14 skips the level unlock (FunctionType.lua:1184-1193)
    # and keeps the store open (stay_time 0, FunctionType.lua:598-620).
    conn.execute("UPDATE players SET level = 1, vip = 14 WHERE id = ?", (pid,))
    conn.commit()
    clock["now"] = T0 + 10 * 86400
    res = _query(reg, handlers, session, store=2)
    assert res.status == 0
    assert res.store.stay_time == 0
    assert len(res.store.merchandise) == 12
    assert session.outbox == []
