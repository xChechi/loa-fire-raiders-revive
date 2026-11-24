"""Monthly sign-in (5_2015, 5_2009, 5_2023, 5_2025, 5_2585) and the 7-day
login gift (5_2043)."""

from datetime import date
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, items_of
from server.modules import checkin
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
TODAY = date(2026, 11, 24)
RECHARGE_ITEM = 30000154   # every 202311 row pays this item, refer_type 20


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
def clock():
    """A mutable 'today' the handlers read through checkin.handlers(clock=)."""
    box = {"today": TODAY}
    return box


@pytest.fixture
def world(settings, cfg, reg, clock):
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    handlers = checkin.handlers(reg, settings, conn, cfg, clock=lambda: clock["today"])
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _req(reg, name, **kw):
    return reg.message_class(name)(**kw)


def _have(conn, pid, entry) -> int:
    return {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)}.get(entry, 0)


def _row(conn, pid):
    return conn.execute("SELECT * FROM checkins WHERE player_id = ?", (pid,)).fetchone()


# --- month mapping (O3) -------------------------------------------------------

def test_month_mapping_nov_2026_uses_202311(cfg) -> None:
    month, total_days = checkin.table_month(cfg, date(2026, 11, 24))
    assert month == 202311
    assert total_days == 30


def test_month_mapping_truncates_to_rows_present(cfg) -> None:
    # February 2028 has 29 days; the newest February in the table, 202302, has 28 rows.
    month, total_days = checkin.table_month(cfg, date(2028, 2, 10))
    assert month == 202302
    assert total_days == 28


# --- 5_2015 query ---------------------------------------------------------------

def test_query_awards_count_equals_days_present(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2015)](session, _req(reg, "CheckInQueryReq"))
    assert res.status == 0
    assert len(res.awards) == 30
    first = res.awards[0]
    assert (first.award.category, first.award.refer, first.award.amount) == (20, RECHARGE_ITEM, 1)
    assert (first.vip, first.times) == (12, 2)
    assert res.day == 24 and res.total_days == 30
    assert res.normal_flags == 0 and res.vip_flags == 0
    assert res.total_checkin_times == 0
    # check_award chain head 10001: 5 sign-ins for 600 diamonds, 100000 gold, 50x item 1100.
    assert res.total_checkin_awards.next_times == 5
    assert [(p.category, p.refer, p.amount) for p in res.total_checkin_awards.next_awards] == [
        (9, 0, 600), (1, 0, 100000), (20, 1100, 50)
    ]
    assert list(res.statusexterme) == [0] * 30
    assert res.flag == 24
    res.SerializeToString()


# --- 5_2009 check in ------------------------------------------------------------

def test_check_in_sets_today_bit_and_pays(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    assert res.status == 0
    assert res.normal_flags == 1 << 23          # calendar day 24
    assert res.vip_flags == 0                   # VIP 0 is below row 1's vip 12
    assert res.total_checkin_times == 1
    assert res.day == 24 and res.total_days == 30
    assert [(p.category, p.refer, p.amount) for p in res.awards] == [(20, RECHARGE_ITEM, 1)]
    assert _have(conn, pid, RECHARGE_ITEM) == 1
    assert int(_row(conn, pid)["total_times"]) == 1
    assert any(cmd == 2008 for _, cmd, _ in session.outbox)
    res.SerializeToString()


def test_check_in_vip_doubles_and_sets_position_bit(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET vip = 12 WHERE id = ?", (pid,))
    conn.commit()
    res = handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    assert res.status == 0
    assert res.vip_flags == 1                   # position 1, SignData:isVIPCheckedAtPos
    assert [(p.category, p.refer, p.amount) for p in res.awards] == [(20, RECHARGE_ITEM, 2)]
    assert _have(conn, pid, RECHARGE_ITEM) == 2


def test_check_in_twice_refused_330241(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    res = handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    assert res.status == 330241
    assert _have(conn, pid, RECHARGE_ITEM) == 1
    assert int(_row(conn, pid)["total_times"]) == 1


def test_second_day_pays_the_second_position(reg, cfg, world, clock) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    clock["today"] = date(2026, 11, 26)
    res = handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    assert res.status == 0
    assert res.normal_flags == (1 << 23) | (1 << 25)
    assert res.total_checkin_times == 2


def test_new_month_clears_the_flags_but_not_the_total(reg, cfg, world, clock) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    clock["today"] = date(2026, 12, 1)
    q = handlers[(5, 2015)](session, _req(reg, "CheckInQueryReq"))
    assert q.normal_flags == 0 and q.vip_flags == 0
    assert q.total_days == 31 and len(q.awards) == 31
    assert q.total_checkin_times == 1


# --- 5_2023 VIP top-up of today's position -------------------------------------

def test_vip_append_pays_the_vip_extra_of_todays_position(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2009)](session, _req(reg, "CheckInReq"))      # at VIP 0: x1
    conn.execute("UPDATE players SET vip = 12 WHERE id = ?", (pid,))
    conn.commit()
    res = handlers[(5, 2023)](session, _req(reg, "VipCheckInAppendReq"))
    assert res.status == 0
    assert res.vip_flags == 1
    assert res.normal_flags == 1 << 23
    assert [(p.category, p.refer, p.amount) for p in res.awards] == [(20, RECHARGE_ITEM, 1)]
    assert _have(conn, pid, RECHARGE_ITEM) == 2
    again = handlers[(5, 2023)](session, _req(reg, "VipCheckInAppendReq"))
    assert again.status == 330241
    assert _have(conn, pid, RECHARGE_ITEM) == 2
    res.SerializeToString()


def test_vip_append_before_check_in_refused_330242(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2023)](session, _req(reg, "VipCheckInAppendReq"))
    assert res.status == 330242
    assert _row(conn, pid) is None or int(_row(conn, pid)["vip_flags"]) == 0


def test_vip_append_vip_too_low_refused_330245(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2009)](session, _req(reg, "CheckInReq"))
    res = handlers[(5, 2023)](session, _req(reg, "VipCheckInAppendReq"))
    assert res.status == 330245
    assert _have(conn, pid, RECHARGE_ITEM) == 1


# --- 5_2025 cumulative award ----------------------------------------------------

def test_total_award_needs_times(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2025)](session, _req(reg, "CheckInTotalAwardReq"))
    assert res.status == 330245
    conn.execute(
        "UPDATE checkins SET total_times = 5 WHERE player_id = ?",
        (pid,),
    )
    conn.commit()
    res = handlers[(5, 2025)](session, _req(reg, "CheckInTotalAwardReq"))
    assert res.status == 0
    assert [(p.category, p.refer, p.amount) for p in res.awards] == [
        (9, 0, 600), (1, 0, 100000), (20, 1100, 50)
    ]
    assert res.total_checkin_awards.next_times == 10        # 10002
    player = conn.execute("SELECT gold, diamond FROM players WHERE id = ?", (pid,)).fetchone()
    assert (int(player["gold"]), int(player["diamond"])) == (101000, 600)
    assert _have(conn, pid, 1100) == 50
    assert int(_row(conn, pid)["total_award"]) == 10002
    again = handlers[(5, 2025)](session, _req(reg, "CheckInTotalAwardReq"))
    assert again.status == 330245
    res.SerializeToString()


# --- 5_2585 ---------------------------------------------------------------------

def test_extreme_reward_answers_torf_1(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2585)](session, _req(reg, "CheckinExtremeRewardReq", today=1))
    assert res.torf == 1
    res.SerializeToString()


# --- 7-day login gift -----------------------------------------------------------

def test_record_login_sets_bit_once_per_day_up_to_7(cfg, world) -> None:
    conn, pid, _, _ = world

    def state():
        r = conn.execute(
            "SELECT login_award, login_days, last_login_day, daily_day FROM players"
            " WHERE id = ?", (pid,),
        ).fetchone()
        return int(r["login_award"]), int(r["login_days"]), r["last_login_day"], r["daily_day"]

    checkin.record_login(conn, cfg, pid, "2026-11-24")
    assert state() == (0b1, 1, "2026-11-24", "2026-11-24")
    checkin.record_login(conn, cfg, pid, "2026-11-24")
    assert state() == (0b1, 1, "2026-11-24", "2026-11-24")
    for n in range(25, 35):
        checkin.record_login(conn, cfg, pid, f"2026-11-{n:02d}" if n <= 30 else f"2026-12-{n - 30:02d}")
    award, days, last, _ = state()
    assert days == 7
    assert award == 0b111_1111
    assert last == "2026-12-04"


def test_login_award_day1_pays_and_marks_claimed(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    checkin.record_login(conn, cfg, pid, "2026-11-24")
    res = handlers[(5, 2043)](session, _req(reg, "LoginAwardReq", award_index=1))
    assert res.status == 0
    assert res.login_award == 0b1 | (1 << 8)
    # drop 700000: 1000 diamonds, 40000 gold, 10x item 100000, 3x item 100.
    assert sorted((p.category, p.refer, p.amount) for p in res.awards) == [
        (1, 0, 40000), (9, 0, 1000), (20, 100, 3), (20, 100000, 10)
    ]
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(player["login_award"]) == 0b1 | (1 << 8)
    assert (int(player["gold"]), int(player["diamond"])) == (41000, 1000)
    assert _have(conn, pid, 100000) == 10 and _have(conn, pid, 100) == 3
    again = handlers[(5, 2043)](session, _req(reg, "LoginAwardReq", award_index=1))
    assert again.status == 330245
    res.SerializeToString()


def test_login_award_unclaimable_refused_330245(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    checkin.record_login(conn, cfg, pid, "2026-11-24")
    for idx in (2, 0, 8):
        res = handlers[(5, 2043)](session, _req(reg, "LoginAwardReq", award_index=idx))
        assert res.status == 330245
    assert int(conn.execute(
        "SELECT login_award FROM players WHERE id = ?", (pid,)).fetchone()[0]) == 0b1


def test_login_award_every_day_pays_or_raises_explicitly(reg, cfg, world) -> None:
    """Plan risk 5: roll the real drop ids. Days 3 and 5 carry categories 52
    and 51, which no task of this plan implements, so grant_prizes raises
    before any write and the day stays unclaimed."""
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET login_award = ? WHERE id = ?", (0b111_1111, pid))
    conn.commit()
    for idx in range(1, 8):
        if idx in (3, 5):
            with pytest.raises(ValueError, match=r"\b5[12]\b"):
                handlers[(5, 2043)](session, _req(reg, "LoginAwardReq", award_index=idx))
            bits = int(conn.execute(
                "SELECT login_award FROM players WHERE id = ?", (pid,)).fetchone()[0])
            assert not bits & (1 << (8 + idx - 1))
        else:
            res = handlers[(5, 2043)](session, _req(reg, "LoginAwardReq", award_index=idx))
            assert res.status == 0, idx
            assert res.login_award & (1 << (8 + idx - 1))
