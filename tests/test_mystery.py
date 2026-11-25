"""The mystery merchant: store 2 appears on energy spent (O-W2-11).

store_info(2): merchandise_amount 12, min/max_appeared_cost 120/600,
appeared_rate 0.05, stay_time 3600, vip_buy_level 14. MAX_SHOW_STORE_TIMES is
1 and function(10350).unlock_level is 16. The push is 5_2020 ShowStoreNotify
{store, onEnergyCost} (RPGGame.lua:846-885)."""

from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import mystery
from server.net.registry import Registry
from server.net.server import Session

STOCK = Path(".stock")
T0 = datetime(2026, 11, 25, 10, 0).timestamp()


class FixedRng:
    """random() always answers `value`; randrange is the generator's pick."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value

    def randrange(self, n: int) -> int:
        return 0


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def world(tmp_path):
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=1000)
    conn.execute("UPDATE players SET level = 16 WHERE id = ?", (pid,))
    conn.commit()
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, session


def _spend(conn, cfg, reg, session, pid, amount, rng, now=T0) -> bool:
    return mystery.on_energy_spent(conn, cfg, reg, session, pid, amount, rng=rng, now=now)


def _row(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def test_no_appearance_below_120_energy_spent(reg, cfg, world) -> None:
    conn, pid, session = world
    # A roll of 0.0 would always hit 0.05, so only the 120 floor stops it.
    for amount in (6, 12, 100):
        assert _spend(conn, cfg, reg, session, pid, amount, FixedRng(0.0)) is False
    assert session.outbox == []
    row = _row(conn, pid)
    assert int(row["mystery_energy"]) == 118
    assert int(row["energy_use"]) == 118
    assert row["mystery_day"] == "2026-11-25"
    assert int(row["mystery_shown"]) == 0
    # From 120 on, every spend rolls appeared_rate.
    assert _spend(conn, cfg, reg, session, pid, 2, FixedRng(0.0)) is True


def test_roll_above_the_rate_does_not_appear(reg, cfg, world) -> None:
    conn, pid, session = world
    assert _spend(conn, cfg, reg, session, pid, 300, FixedRng(0.05)) is False
    assert session.outbox == []


def test_forced_appearance_at_600(reg, cfg, world) -> None:
    conn, pid, session = world
    never = FixedRng(0.99)
    for _ in range(4):
        assert _spend(conn, cfg, reg, session, pid, 120, never) is False
    assert _spend(conn, cfg, reg, session, pid, 120, never) is True
    row = _row(conn, pid)
    assert int(row["mystery_energy"]) == 0
    assert int(row["mystery_appear"]) == int(T0)
    assert int(row["mystery_stay"]) == 3600
    assert int(row["mystery_shown"]) == 1
    assert int(row["energy_use"]) == 600


def test_at_most_one_appearance_per_day(reg, cfg, world) -> None:
    conn, pid, session = world
    assert _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.99)) is True
    assert _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.0), now=T0 + 7200) is False
    assert len(session.outbox) == 1
    # The next day the counters start again at midnight.
    tomorrow = T0 + 86400
    assert _spend(conn, cfg, reg, session, pid, 120, FixedRng(0.0), now=tomorrow) is True
    row = _row(conn, pid)
    assert row["mystery_day"] == "2026-11-26"
    assert int(row["mystery_shown"]) == 1
    assert int(row["energy_use"]) == 120


def test_no_appearance_below_level_16(reg, cfg, world) -> None:
    conn, pid, session = world
    conn.execute("UPDATE players SET level = 15 WHERE id = ?", (pid,))
    conn.commit()
    assert _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.0)) is False
    assert session.outbox == []
    assert int(_row(conn, pid)["energy_use"]) == 600


def test_appearance_queues_5_2020_with_12_slots_and_onEnergyCost(reg, cfg, world) -> None:
    conn, pid, session = world
    assert _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.99)) is True
    assert len(session.outbox) == 1
    service, cmd, msg = session.outbox[0]
    assert (service, cmd) == (5, 2020)
    assert msg.onEnergyCost is True
    assert msg.store.store == 2
    assert msg.store.lastappear == int(T0)
    assert msg.store.stay_time == 3600
    slots = list(msg.store.merchandise)
    assert len(slots) == 12
    assert [s.index for s in slots] == list(range(12))
    assert len({s.merchandise for s in slots}) == 12
    rows = {int(r["entry"]): r for r in cfg.merchandise(2)}
    for s in slots:
        assert int(rows[s.merchandise]["min_level"]) <= 16 <= int(rows[s.merchandise]["max_level"])
        assert s.buy == 0
    msg.SerializeToString()
    saved = conn.execute(
        "SELECT * FROM stores WHERE player_id = ? AND store = 2", (pid,)
    ).fetchone()
    assert saved is not None
    assert int(saved["lastupdate"]) == int(T0)


def test_vip14_appearance_has_no_stay(reg, cfg, world) -> None:
    conn, pid, session = world
    conn.execute("UPDATE players SET vip = 14 WHERE id = ?", (pid,))
    conn.commit()
    assert _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.99)) is True
    assert session.outbox[0][2].store.stay_time == 0
    assert int(_row(conn, pid)["mystery_stay"]) == 0


def test_expire_queues_5_2022_after_the_stay(reg, cfg, world) -> None:
    conn, pid, session = world
    _spend(conn, cfg, reg, session, pid, 600, FixedRng(0.99))
    session.outbox.clear()
    assert mystery.expire(reg, session, _row(conn, pid), now=T0 + 3599) is False
    assert session.outbox == []
    assert mystery.expire(reg, session, _row(conn, pid), now=T0 + 3600) is True
    (service, cmd, msg), = session.outbox
    assert (service, cmd) == (5, 2022)
    assert msg.store == 2
    msg.SerializeToString()


# --- store 7, the celestial merchant (plan B2 Wave 3 A3, O-W3-3) -------------
# store_info(7): merchandise_amount 6, min/max_appeared_cost 200/400,
# appeared_rate 0.005, stay_time 3600; function(10370).unlock_level is 19.


def _level(conn, pid, level) -> None:
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (level, pid))
    conn.commit()


def _pushed(session, store) -> list:
    return [m for (s, c, m) in session.outbox if (s, c) == (5, 2020) and m.store.store == store]


def test_store7_needs_200_energy_before_rolling(reg, cfg, world) -> None:
    conn, pid, session = world
    _level(conn, pid, 19)
    # A roll of 0.0 always hits 0.005, so only the 200 floor stops it.
    _spend(conn, cfg, reg, session, pid, 199, FixedRng(0.0))
    assert _pushed(session, 7) == []
    assert int(_row(conn, pid)["legends_energy"]) == 199
    _spend(conn, cfg, reg, session, pid, 1, FixedRng(0.0))
    assert len(_pushed(session, 7)) == 1


def test_store7_forced_at_400(reg, cfg, world) -> None:
    conn, pid, session = world
    _level(conn, pid, 19)
    never = FixedRng(0.99)
    _spend(conn, cfg, reg, session, pid, 399, never)
    assert _pushed(session, 7) == []
    assert _spend(conn, cfg, reg, session, pid, 1, never) is True
    (msg,) = _pushed(session, 7)
    assert msg.onEnergyCost is True
    assert msg.store.lastappear == int(T0)
    assert msg.store.stay_time == 3600
    row = _row(conn, pid)
    assert int(row["legends_energy"]) == 0
    assert int(row["legends_appear"]) == int(T0)
    assert int(row["legends_stay"]) == 3600
    assert int(row["legends_shown"]) == 1
    assert row["legends_day"] == "2026-11-25"
    msg.SerializeToString()


def test_store7_and_store2_counters_are_independent(reg, cfg, world) -> None:
    conn, pid, session = world
    _level(conn, pid, 19)
    never = FixedRng(0.99)
    _spend(conn, cfg, reg, session, pid, 400, never)
    assert len(_pushed(session, 7)) == 1
    assert _pushed(session, 2) == []
    row = _row(conn, pid)
    assert (int(row["legends_energy"]), int(row["mystery_energy"])) == (0, 400)
    _spend(conn, cfg, reg, session, pid, 200, never)
    assert len(_pushed(session, 2)) == 1
    row = _row(conn, pid)
    assert (int(row["legends_energy"]), int(row["mystery_energy"])) == (200, 0)
    assert int(row["energy_use"]) == 600


def test_store7_once_per_day(reg, cfg, world) -> None:
    conn, pid, session = world
    _level(conn, pid, 19)
    never = FixedRng(0.99)
    _spend(conn, cfg, reg, session, pid, 400, never)
    _spend(conn, cfg, reg, session, pid, 400, never, now=T0 + 7200)
    assert len(_pushed(session, 7)) == 1
    _spend(conn, cfg, reg, session, pid, 400, never, now=T0 + 86400)
    assert len(_pushed(session, 7)) == 2
    row = _row(conn, pid)
    assert row["legends_day"] == "2026-11-26"
    assert int(row["legends_shown"]) == 1


def test_store7_below_level19_never_appears(reg, cfg, world) -> None:
    conn, pid, session = world
    _level(conn, pid, 18)
    _spend(conn, cfg, reg, session, pid, 400, FixedRng(0.0))
    assert _pushed(session, 7) == []
    assert int(_row(conn, pid)["legends_appear"]) == 0


def test_store7_expired_at_login_queues_5_2022(reg, cfg, world) -> None:
    # player.py's QueryMyself calls mystery.expire after the Res.
    conn, pid, session = world
    _level(conn, pid, 19)
    _spend(conn, cfg, reg, session, pid, 400, FixedRng(0.99))
    session.outbox.clear()
    assert mystery.expire(reg, session, _row(conn, pid), now=T0 + 3599) is False
    assert session.outbox == []
    assert mystery.expire(reg, session, _row(conn, pid), now=T0 + 3600) is True
    (service, cmd, msg), = session.outbox
    assert (service, cmd) == (5, 2022)
    assert msg.store == 7
