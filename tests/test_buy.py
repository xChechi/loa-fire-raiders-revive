"""5_2013 SyncEnergy, 5_2145/5_2141 energy purchase, 5_2147/5_2143 gold purchase.

Stock values used below: ENERGY_BUY_GAIN 150, ENERGY_BUY_COST
"250|2,500|4,..." (price|count tiers, MMTools:getCost), vip_info 10000 (energy
buys) vip0 0 / vip1 3, vip_info 10010 (gold buys) vip0 0 / vip1 5,
buy_gold_cost(1) 50, GOLD_BUY_BASE 50000, GOLD_BUY_LEVEL_BASE 320,
GOLD_BUY_TIMES_RATIO 0.2, PLAYER_ENERGY_RECOVER_CYCLE 360.
"""

import math
import time
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import buy
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
def world(settings, cfg, reg, monkeypatch):
    monkeypatch.setattr(buy, "_today", lambda: "2026-11-24")
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=18888)
    handlers = buy.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _player(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _set(conn, pid, **cols):
    for k, v in cols.items():
        conn.execute(f"UPDATE players SET {k} = ? WHERE id = ?", (v, pid))
    conn.commit()


def _call(reg, handlers, session, cmd, **kw):
    name = reg.name_for(5, cmd)
    return handlers[(5, cmd)](session, reg.message_class(name)(**kw))


def _player_notes(session):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]


def test_sync_energy_returns_energy_at_and_notifies_regen(reg, world) -> None:
    conn, pid, handlers, session = world
    # Two whole cycles and a bit ago, 10 below the level-1 cap of 60.
    start = int(time.time()) - 2 * 360 - 100
    _set(conn, pid, energy=50, energy_at=start)
    res = _call(reg, handlers, session, 2013)
    row = _player(conn, pid)
    assert int(row["energy"]) == 52
    assert int(row["energy_at"]) == start + 720
    assert res.last_recover_time == start + 720
    notes = _player_notes(session)
    assert len(notes) == 1 and list(notes[0].data) == [52.0]
    res.SerializeToString()


def test_sync_energy_without_regen_sends_no_notify(reg, world) -> None:
    conn, pid, handlers, session = world
    now = int(time.time())
    _set(conn, pid, energy=50, energy_at=now)
    res = _call(reg, handlers, session, 2013)
    assert res.last_recover_time == now
    assert session.outbox == []


def test_query_buy_energy_vip0_max_0(reg, world) -> None:
    _conn, _pid, handlers, session = world
    res = _call(reg, handlers, session, 2145)
    assert res.status == 0
    assert (res.used, res.max, res.energy, res.diamond) == (0, 0, 150, 250)
    res.SerializeToString()


def test_buy_energy_vip0_refused_327952(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _call(reg, handlers, session, 2141)
    assert res.status == 327952
    row = _player(conn, pid)
    assert (int(row["energy"]), int(row["diamond"]), int(row["buy_energy_used"])) == (
        60, 18888, 0
    )
    assert session.outbox == []


def test_buy_energy_vip1_first_costs_tier1_price_and_adds_150(reg, world) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1)
    res = _call(reg, handlers, session, 2141)
    assert res.status == 0
    row = _player(conn, pid)
    # Uncapped: 60 + 150, past the level-1 max of 60 (the client guards 2400).
    assert int(row["energy"]) == 210
    assert int(row["diamond"]) == 18888 - 250
    assert int(row["buy_energy_used"]) == 1
    # StrengthUI.lua:184-223: energy is this purchase's gain, nextEnergy and
    # diamond describe the next purchase (tier 1 holds two buys at 250).
    assert (res.energy, res.nextEnergy, res.diamond, res.used, res.max) == (
        150, 150, 250, 1, 3
    )
    notes = _player_notes(session)
    assert len(notes) == 1 and list(notes[0].data) == [210.0, 18888.0 - 250]
    res.SerializeToString()


def test_buy_energy_third_purchase_costs_tier2(reg, world) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1, buy_energy_used=2, daily_day="2026-11-24")
    assert _call(reg, handlers, session, 2145).diamond == 500
    res = _call(reg, handlers, session, 2141)
    assert res.status == 0 and res.used == 3
    assert int(_player(conn, pid)["diamond"]) == 18888 - 500
    # used == max now: the next buy is refused.
    assert _call(reg, handlers, session, 2141).status == 327952


def test_buy_energy_refused_327938_when_diamonds_short(reg, world) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1, diamond=249)
    assert _call(reg, handlers, session, 2141).status == 327938
    row = _player(conn, pid)
    assert (int(row["energy"]), int(row["diamond"]), int(row["buy_energy_used"])) == (
        60, 249, 0
    )
    assert session.outbox == []


def test_query_buy_gold_vip0(reg, world) -> None:
    _conn, _pid, handlers, session = world
    res = _call(reg, handlers, session, 2147)
    assert res.status == 0
    assert (res.used, res.max) == (0, 0)
    # DigUI:getAddGoldNum: (base + level_base * level) * n ^ ratio, n = 1.
    assert res.gold == 50000 + 320
    res.SerializeToString()


def test_buy_gold_vip0_refused_327952(reg, world) -> None:
    conn, pid, handlers, session = world
    res = _call(reg, handlers, session, 2143, use_times=1)
    assert res.status == 327952
    row = _player(conn, pid)
    assert (int(row["gold"]), int(row["diamond"]), int(row["buy_gold_used"])) == (
        1000, 18888, 0
    )
    assert session.outbox == []


def test_buy_gold_vip1_uses_buy_gold_cost_1(reg, world, monkeypatch) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1)
    monkeypatch.setattr(buy, "_roll", lambda: 0.0)  # inside the 1x band
    res = _call(reg, handlers, session, 2143, use_times=1)
    assert res.status == 0
    assert list(res.gold) == [50320] and list(res.crit) == [1]
    assert (res.used, res.max) == (1, 5)
    row = _player(conn, pid)
    assert int(row["diamond"]) == 18888 - 50
    assert int(row["gold"]) == 1000 + 50320
    assert int(row["buy_gold_used"]) == 1
    notes = _player_notes(session)
    assert len(notes) == 1 and list(notes[0].data) == [51320.0, 18888.0 - 50]
    res.SerializeToString()


def test_buy_gold_several_uses_roll_crit_and_grow_per_use(reg, world, monkeypatch) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1)
    # vip1 bands: 1x 0.7, 2x 0.25, 3x 0.05.
    rolls = iter([0.71, 0.96, 0.1])
    monkeypatch.setattr(buy, "_roll", lambda: next(rolls))
    res = _call(reg, handlers, session, 2143, use_times=3)
    assert res.status == 0
    base = 50320
    expected = [math.ceil(base * n ** 0.2) * c for n, c in ((1, 2), (2, 3), (3, 1))]
    assert list(res.gold) == expected and list(res.crit) == [2, 3, 1]
    assert res.used == 3
    row = _player(conn, pid)
    assert int(row["diamond"]) == 18888 - 150
    assert int(row["gold"]) == 1000 + sum(expected)


def test_buy_gold_more_uses_than_left_refused_327952(reg, world) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1, buy_gold_used=4, daily_day="2026-11-24")
    assert _call(reg, handlers, session, 2143, use_times=2).status == 327952
    assert int(_player(conn, pid)["buy_gold_used"]) == 4


def test_buy_gold_refused_327938_when_diamonds_short(reg, world) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1, diamond=99)
    assert _call(reg, handlers, session, 2143, use_times=2).status == 327938
    row = _player(conn, pid)
    assert (int(row["gold"]), int(row["diamond"]), int(row["buy_gold_used"])) == (
        1000, 99, 0
    )
    assert session.outbox == []


def test_counters_reset_next_day(reg, world, monkeypatch) -> None:
    conn, pid, handlers, session = world
    _set(conn, pid, vip=1, buy_energy_used=3, buy_gold_used=5, daily_day="2026-11-24")
    assert _call(reg, handlers, session, 2141).status == 327952
    assert _call(reg, handlers, session, 2143, use_times=1).status == 327952
    monkeypatch.setattr(buy, "_today", lambda: "2026-11-25")
    assert _call(reg, handlers, session, 2145).used == 0
    assert _call(reg, handlers, session, 2147).used == 0
    assert _call(reg, handlers, session, 2141).status == 0
