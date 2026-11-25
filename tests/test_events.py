"""Achievements (event_info catalog 0): 5_2241 EventAwardReq, 5_2243 AllEventAwardReq.

At level 1 the active catalog-0 roots are 10270 / 21000 (kind 1, own 5 heroes),
10920 (kind 2, clear stage 10022), 10430 / 41000 (kind 3, level 10 / 30) and
10600 / 42000 / 43000 (kinds 5 / 103 / 106, not counted in Wave 1). 10270's
child is 10280 (own 6 heroes); 10270 pays drop 150260 = 3x item 1110.
"""

import logging
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, items_of, upsert_level
from server.modules import events
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
HEROES = (100000, 101000, 102000, 103000, 104000, 105000)


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    handlers = events.handlers(reg, settings, conn, cfg, rng=random.Random(1))
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _heroes(conn, pid, n) -> None:
    """Own exactly the first n of HEROES."""
    owned = {int(r[0]) for r in conn.execute(
        "SELECT entry FROM heroes WHERE player_id = ?", (pid,))}
    for entry in HEROES[:n]:
        if entry not in owned:
            grant_hero(conn, pid, entry, 10)


def _row(conn, pid, entry):
    return conn.execute(
        "SELECT * FROM events WHERE player_id = ? AND entry = ?", (pid, entry)
    ).fetchone()


def _state(conn, pid, entry):
    row = _row(conn, pid, entry)
    return None if row is None else (int(row["progress"]), int(row["done"]), int(row["claimed"]))


def _task_notifies(session):
    return [m for (s, c, m) in session.outbox if (s, c) == (5, 2008) and m.ident == 6]


def _award(reg, handlers, session, entry):
    return handlers[(5, 2241)](session, reg.message_class("EventAwardReq")(entry=entry))


def test_kind1_hero_count_progress(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    _heroes(conn, pid, 2)
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 10270) == (2, 0, 0)
    _heroes(conn, pid, 5)
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 10270) == (5, 1, 0)
    assert _state(conn, pid, 21000) == (5, 1, 0)


def test_kind1_quality_rows_are_not_a_hero_count(reg, cfg, world) -> None:
    """12378 is kind 1 with arg1 1 / arg2 20, "进阶1名英雄到绿色品质"
    (advance one hero to green). Counting every owned hero would complete it
    with the starter hero, so it stays at 0 in Wave 1."""
    conn, pid, _, _ = world
    conn.execute("UPDATE players SET level = 3 WHERE id = ?", (pid,))
    conn.commit()
    _heroes(conn, pid, 2)
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 12378) == (0, 0, 0)


def test_kind2_stage_10022_done_after_clear(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 10920) == (0, 0, 0)
    upsert_level(conn, pid, 10022, star=1)
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 10920) == (1, 1, 0)


def test_kind3_player_level(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    conn.execute("UPDATE players SET level = 10 WHERE id = ?", (pid,))
    conn.commit()
    events.refresh(conn, cfg, reg, None, pid)
    assert _state(conn, pid, 10430) == (10, 1, 0)
    assert _state(conn, pid, 41000) == (10, 0, 0)


def test_other_kinds_are_active_at_progress_0(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    events.refresh(conn, cfg, reg, None, pid)
    for entry in (10600, 42000, 43000):
        assert _state(conn, pid, entry) == (0, 0, 0)


def test_children_and_locked_entries_are_not_active(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    events.refresh(conn, cfg, reg, None, pid)
    assert _row(conn, pid, 10280) is None            # parent 10270 not claimed
    assert _row(conn, pid, 11640) is None            # unlock_level 9


def test_award_pays_drops_and_activates_child(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _heroes(conn, pid, 5)
    events.refresh(conn, cfg, reg, None, pid)
    res = _award(reg, handlers, session, 10270)
    assert (res.status, res.entry) == (0, 10270)
    res.SerializeToString()
    assert _state(conn, pid, 10270)[2] == 1
    assert {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)} == {1110: 3}
    assert _state(conn, pid, 10280) == (5, 0, 0)
    assert 10280 in [m.refer for m in _task_notifies(session)]
    assert 4 in [m.ident for (_s, c, m) in session.outbox if c == 2008]
    # a claimed event is never paid twice
    assert _award(reg, handlers, session, 10270).status == events.STATUS_UNKNOWN


def test_award_not_done_refused_330754(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _heroes(conn, pid, 2)
    res = _award(reg, handlers, session, 10270)
    assert res.status == 330754
    assert _state(conn, pid, 10270) == (2, 0, 0)
    assert items_of(conn, pid) == []


def test_award_unknown_or_inactive_refused_330753(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _heroes(conn, pid, 6)
    for entry in (999, 10280):                        # 10280: parent not claimed
        assert _award(reg, handlers, session, entry).status == 330753
    assert items_of(conn, pid) == []


def test_all_award_returns_entrys(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _heroes(conn, pid, 5)
    upsert_level(conn, pid, 10022, star=1)
    res = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=0))
    res.SerializeToString()
    assert sorted(res.entrys) == [10270, 10920, 21000]
    assert (res.eventNum, res.type) == (3, 0)
    assert sorted((d.category, d.refer, d.amount) for d in res.drops) == [
        (1, 0, 300000), (20, 1110, 3), (20, 1230, 6), (20, 1240, 6), (20, 202000, 30),
    ]
    for entry in (10270, 10920, 21000):
        assert _state(conn, pid, entry)[2] == 1
    assert _row(conn, pid, 10280) is not None and _row(conn, pid, 10930) is not None
    # nothing left to claim: an empty answer
    again = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=0))
    assert (again.eventNum, list(again.entrys), list(again.drops)) == (0, [], [])


def test_all_award_daily_catalog_claims_nothing(reg, cfg, world) -> None:
    """Daily tasks (catalog 1) are W2; the achievements stay untouched."""
    conn, pid, handlers, session = world
    _heroes(conn, pid, 5)
    res = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=1))
    assert (res.eventNum, res.type, list(res.entrys)) == (0, 1, [])
    assert _state(conn, pid, 10270)[2] == 0


def test_refresh_pushes_task_notify_only_on_change(reg, cfg, world) -> None:
    conn, pid, _, session = world
    _heroes(conn, pid, 1)
    events.refresh(conn, cfg, reg, session, pid)
    first = {m.refer for m in _task_notifies(session)}
    assert first == {10270, 10430, 10600, 10920, 21000, 41000, 42000, 43000}
    session.outbox.clear()
    events.refresh(conn, cfg, reg, session, pid)
    assert session.outbox == []
    _heroes(conn, pid, 2)
    events.refresh(conn, cfg, reg, session, pid)
    pushed = _task_notifies(session)
    assert sorted(m.refer for m in pushed) == [10270, 21000]
    assert all(m.flags == 0b10 and list(m.data) == [2.0] for m in pushed)


def test_refresh_without_a_session_pushes_nothing(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    events.refresh(conn, cfg, reg, None, pid)
    assert _row(conn, pid, 10270) is not None


def test_a_done_event_pushes_the_done_flag(reg, cfg, world) -> None:
    conn, pid, _, session = world
    _heroes(conn, pid, 5)
    events.refresh(conn, cfg, reg, session, pid)
    done = [m for m in _task_notifies(session) if m.refer == 10270]
    assert [m.flags for m in done] == [0b100]


# --- daily tasks (catalog 1, Wave 2 E2) ------------------------------------------
# Function 10430 opens the daily tab at level 10. Active then: 10022 potion,
# 10060 gacha x3, 10070 any stage x10, 10080 elite x5, 10100 hero level,
# 10101 hero skill, 10580 / 10590 lunch / dinner (kind 4), 53010 chat (unmapped).

DAILY_AT_10 = {10022, 10060, 10070, 10080, 10100, 10101, 10580, 10590, 53010}


def _at(day: int, hour: int, minute: int = 0) -> float:
    """A local timestamp in November 2026."""
    return datetime(2026, 11, day, hour, minute).timestamp()


def _set_level(conn, pid, lvl) -> None:
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (lvl, pid))
    conn.commit()


def _daily_rows(conn, pid) -> dict:
    return {
        int(r["entry"]): r for r in conn.execute(
            "SELECT * FROM events WHERE player_id = ? AND day != ''", (pid,)
        )
    }


def _clocked(reg, settings, conn, cfg, clock):
    return events.handlers(reg, settings, conn, cfg, rng=random.Random(1),
                           clock=lambda: clock[0])


def test_daily_rows_appear_at_their_unlock_level(reg, cfg, world) -> None:
    conn, pid, _, _ = world
    now = _at(25, 10)
    _set_level(conn, pid, 9)                          # 10100 unlocks at 9, the tab at 10
    events.refresh(conn, cfg, reg, None, pid, now)
    assert _daily_rows(conn, pid) == {}
    _set_level(conn, pid, 10)
    events.refresh(conn, cfg, reg, None, pid, now)
    rows = _daily_rows(conn, pid)
    assert set(rows) == DAILY_AT_10                   # 10030 / 10040 wait for level 18
    assert {r["day"] for r in rows.values()} == {"2026-11-25"}
    assert all(_state(conn, pid, e) == (0, 0, 0) for e in DAILY_AT_10)


def test_bump_stage_win_counts_normal_and_elite(reg, cfg, settings, world) -> None:
    from server.modules import level

    conn, pid, _, session = world
    _set_level(conn, pid, 10)
    handlers = level.handlers(reg, settings, conn, cfg, rng=random.Random(1))

    def fight(lvl, star):
        handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=lvl))
        handlers[(5, 2203)](
            session, reg.message_class("LevelOutReq")(level=lvl, star=star, angel=0)
        )

    fight(10000, 0)                                   # a lost stage counts nothing
    assert _row(conn, pid, 10070) is None or _state(conn, pid, 10070) == (0, 0, 0)
    fight(10000, 3)                                   # normal: 10070 only
    assert (_state(conn, pid, 10070), _state(conn, pid, 10080)) == ((1, 0, 0), (0, 0, 0))
    session.outbox.clear()
    fight(110000, 3)                                  # elite: 10070 and 10080
    assert (_state(conn, pid, 10070), _state(conn, pid, 10080)) == ((2, 0, 0), (1, 0, 0))
    assert {10070, 10080} <= {m.refer for m in _task_notifies(session)}
    # direct bumps: the gold and hero trials (arg1 3 / 4) are other rows
    events.bump(conn, cfg, reg, session, pid, events.KIND_FIGHT, events.FIGHT_GOLD_TRIAL)
    assert _state(conn, pid, 10070) == (2, 0, 0)
    # a bump stops at arg0 and marks it done
    events.bump(conn, cfg, reg, session, pid, events.KIND_FIGHT, events.FIGHT_ELITE, n=9)
    assert (_state(conn, pid, 10070), _state(conn, pid, 10080)) == ((10, 1, 0), (5, 1, 0))


def test_daily_resets_at_5am(reg, cfg, settings, world) -> None:
    conn, pid, _, session = world
    _set_level(conn, pid, 10)
    clock = [_at(25, 4, 59)]                          # still the day of 24-11-2026
    handlers = _clocked(reg, settings, conn, cfg, clock)
    for _ in range(3):
        events.bump(conn, cfg, reg, session, pid, events.KIND_GACHA, now=clock[0])
    assert _state(conn, pid, 10060) == (3, 1, 0)
    assert _row(conn, pid, 10060)["day"] == "2026-11-24"
    assert _award(reg, handlers, session, 10060).status == 0
    assert _state(conn, pid, 10060) == (3, 1, 1)
    assert _award(reg, handlers, session, 10060).status == events.STATUS_UNKNOWN
    session.outbox.clear()
    clock[0] = _at(25, 5, 0)
    events.refresh(conn, cfg, reg, session, pid, clock[0])
    assert _state(conn, pid, 10060) == (0, 0, 0)
    assert _row(conn, pid, 10060)["day"] == "2026-11-25"
    assert 10060 in [m.refer for m in _task_notifies(session)]
    # an achievement is not a daily row: its state survives the boundary
    assert _row(conn, pid, 10270)["day"] == ""


def test_lunch_energy_claimable_only_after_12(reg, cfg, settings, world) -> None:
    from server.db import find_player

    conn, pid, _, session = world
    _set_level(conn, pid, 10)
    clock = [_at(25, 11, 59)]
    handlers = _clocked(reg, settings, conn, cfg, clock)
    conn.execute("UPDATE players SET energy = 0 WHERE id = ?", (pid,))
    conn.commit()
    assert _award(reg, handlers, session, 10580).status == events.STATUS_NOT_DONE
    clock[0] = _at(25, 12, 0)
    assert _award(reg, handlers, session, 10580).status == 0
    # drop 150430 is 80 energy, paid in full even past the level's max_energy
    assert int(find_player(conn, "stefan")["energy"]) == 80
    assert _award(reg, handlers, session, 10590).status == events.STATUS_NOT_DONE
    clock[0] = _at(26, 4, 59)                         # dinner is open until 05:00
    assert _award(reg, handlers, session, 10590).status == 0
    clock[0] = _at(26, 5, 0)                          # a new day: lunch is not open yet
    events.refresh(conn, cfg, reg, None, pid, clock[0])
    assert _state(conn, pid, 10580) == (0, 0, 0)


def test_lunch_and_dinner_energy_pass_the_cap(reg, cfg, settings, world) -> None:
    """Owner's decision (run 11 finding 2): the lunch / dinner prize is paid in
    full at full energy, on the single claim and on claim-all. Regeneration
    then adds nothing until the player is back under the cap."""
    from server.db import find_player, refresh_energy

    conn, pid, _, session = world
    _set_level(conn, pid, 10)
    cap = int(cfg.xp_for_level(10)["max_energy"])
    clock = [_at(25, 12, 0)]
    handlers = _clocked(reg, settings, conn, cfg, clock)
    conn.execute("UPDATE players SET energy = ?, energy_at = 0 WHERE id = ?", (cap, pid))
    conn.commit()
    assert _award(reg, handlers, session, 10580).status == 0
    assert int(find_player(conn, "stefan")["energy"]) == cap + 80
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=clock[0] + 3600)
    assert int(row["energy"]) == cap + 80
    clock[0] = _at(25, 18, 0)                         # dinner, by claim-all
    res = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=1))
    assert 10590 in res.entrys
    assert int(find_player(conn, "stefan")["energy"]) == cap + 160


def test_an_energy_achievement_still_stops_at_the_cap(reg, cfg, world) -> None:
    """Only the kind-4 daily prize passes the cap; 41000 (level 30, drop
    152000 = 100 energy) is clipped as before."""
    from server.db import find_player

    conn, pid, handlers, session = world
    _set_level(conn, pid, 30)
    cap = int(cfg.xp_for_level(30)["max_energy"])
    conn.execute("UPDATE players SET energy = ? WHERE id = ?", (cap - 10, pid))
    conn.commit()
    assert _award(reg, handlers, session, 41000).status == 0
    assert int(find_player(conn, "stefan")["energy"]) == cap


def test_award_all_type1_claims_only_daily(reg, cfg, settings, world) -> None:
    conn, pid, _, session = world
    _set_level(conn, pid, 10)
    _heroes(conn, pid, 5)                             # achievement 10270 is done too
    clock = [_at(25, 10)]
    handlers = _clocked(reg, settings, conn, cfg, clock)
    events.bump(conn, cfg, reg, session, pid, events.KIND_GACHA, n=3, now=clock[0])
    res = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=1))
    res.SerializeToString()
    assert (res.eventNum, res.type, list(res.entrys)) == (1, 1, [10060])
    assert len(res.drops) > 0
    assert _state(conn, pid, 10060)[2] == 1
    assert _state(conn, pid, 10270) == (5, 1, 0)
    again = handlers[(5, 2243)](session, reg.message_class("AllEventAwardReq")(type=0))
    assert 10060 not in again.entrys and 10270 in again.entrys


def test_unmapped_kinds_stay_zero_logged_once(reg, cfg, world, monkeypatch, caplog) -> None:
    conn, pid, _, session = world
    _set_level(conn, pid, 22)        # 10090 arena, 14030-14070 guild, 20000+ nobility
    monkeypatch.setattr(events, "_logged_kinds", set())
    caplog.set_level(logging.INFO, logger="loa.events")
    now = _at(25, 10)
    events.refresh(conn, cfg, reg, session, pid, now)
    events.bump(conn, cfg, reg, session, pid, 3604487, now=now)
    events.refresh(conn, cfg, reg, session, pid, now)
    for entry in (10090, 14030, 14060, 53010, 20000):  # 20000 has arg0 0: still not done
        assert _state(conn, pid, entry) == (0, 0, 0)
    logged = [r for r in caplog.records if "daily task kind 3604487" in r.getMessage()]
    assert len(logged) == 1


# --- call sites ---------------------------------------------------------------


def test_query_myself_carries_the_active_events(reg, cfg, settings, world) -> None:
    from server.modules import player

    conn, pid, _, session = world
    _heroes(conn, pid, 5)
    res = player.handlers(reg, settings, conn, cfg)[(5, 2005)](
        session, reg.message_class("QueryMyselfReq")()
    )
    sent = {e.entry: (e.cur_progress, e.done) for e in res.events}
    assert sent[10270] == (5, 1)
    assert 10280 not in sent
    assert _task_notifies(session) == []             # it rides in the Res


def test_a_won_stage_refreshes_the_achievements(reg, cfg, settings, world) -> None:
    from server.modules import level

    conn, pid, _, session = world
    grant_hero(conn, pid, 100000, 10, star=1, level=1)
    handlers = level.handlers(reg, settings, conn, cfg, rng=random.Random(1))
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    req = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)
    req.heroes.append(100000)
    handlers[(5, 2203)](session, req)
    assert 10270 in [m.refer for m in _task_notifies(session)]


def test_a_gacha_draw_refreshes_the_achievements(reg, cfg, settings, world) -> None:
    from server.modules import gacha

    conn, pid, _, session = world
    conn.execute("UPDATE players SET gold = 10000000 WHERE id = ?", (pid,))
    conn.commit()
    handlers = gacha.handlers(reg, settings, conn, cfg, rng=random.Random(1))
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert 10270 in [m.refer for m in _task_notifies(session)]


def test_a_hero_call_refreshes_the_achievements(reg, cfg, settings, world) -> None:
    from server.db import grant_item
    from server.modules import hero

    conn, pid, _, session = world
    info = cfg.hero(101000)
    grant_item(conn, pid, int(info["item"]), 999)
    conn.execute("UPDATE players SET gold = 10000000 WHERE id = ?", (pid,))
    conn.commit()
    res = hero.handlers(reg, settings, conn, cfg)[(5, 2127)](
        session, reg.message_class("HeroCallReq")(hero=101000)
    )
    assert res.status == 0
    assert 10270 in [m.refer for m in _task_notifies(session)]


def test_build_handlers_registers_the_achievements(reg, settings) -> None:
    from server.__main__ import build_handlers

    handlers = build_handlers(reg, settings)
    assert (5, 2241) in handlers and (5, 2243) in handlers
