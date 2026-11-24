"""Achievements (event_info catalog 0): 5_2241 EventAwardReq, 5_2243 AllEventAwardReq.

At level 1 the active catalog-0 roots are 10270 / 21000 (kind 1, own 5 heroes),
10920 (kind 2, clear stage 10022), 10430 / 41000 (kind 3, level 10 / 30) and
10600 / 42000 / 43000 (kinds 5 / 103 / 106, not counted in Wave 1). 10270's
child is 10280 (own 6 heroes); 10270 pays drop 150260 = 3x item 1110.
"""

import random
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
