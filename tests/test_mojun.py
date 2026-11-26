"""Demon onslaught: 5_2727 MagicArmyQuery, 5_2729 MagicArmyBattleStart, 5_2731
MagicArmyBattleEnd.

T0 is Wednesday 25-11-2026 10:00 local. The client's day (MojunDataHelp.lua:
24-39: getDay(), 0 = Sunday read as 7, hours 0-4 belong to the day before) is
3, so today's monster is chapter_info type 12 with idx 3: 8030000 远古树精.
Its difficulties are the stage_info rows of that chapter by idx: 8030100 (1,
level 47), 8030200 (2, level 47), 8030300 (3, level 55).
"""

import logging
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import mojun
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
WEDNESDAY = 8030000
D1, D2, D3 = 8030100, 8030200, 8030300
THURSDAY_D1 = 8010100      # chapter 8010000 has idx 4


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


def _world(settings, cfg, reg, level=47):
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (level, pid))
    conn.commit()
    clock = {"now": T0}
    handlers = mojun.handlers(
        reg, settings, conn, cfg, clock=lambda: clock["now"], rng=random.Random(7)
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


@pytest.fixture
def world(settings, cfg, reg):
    return _world(settings, cfg, reg)


def _query(reg, handlers, session, entry=WEDNESDAY):
    res = handlers[(5, 2727)](session, reg.message_class("MagicArmyQueryReq")(entry=entry))
    res.SerializeToString()
    return res


def _start(reg, handlers, session, level):
    res = handlers[(5, 2729)](
        session, reg.message_class("MagicArmyBattleStartReq")(level=level)
    )
    res.SerializeToString()
    return res


def _end(reg, handlers, session, level, result=1):
    req = reg.message_class("MagicArmyBattleEndReq")(
        level=level, group=1, angel=0, result=result
    )
    req.heroes.extend([0] * 6)
    res = handlers[(5, 2731)](session, req)
    res.SerializeToString()
    return res


def _fight(reg, handlers, session, level, result=1):
    assert _start(reg, handlers, session, level).flag == mojun.FLAG_OK
    return _end(reg, handlers, session, level, result)


def _items(conn, pid):
    return {
        int(r["entry"]): int(r["amount"])
        for r in conn.execute("SELECT * FROM items WHERE player_id = ?", (pid,))
    }


def _pet_money(conn, pid):
    return int(conn.execute("SELECT pet_money FROM players WHERE id = ?", (pid,)).fetchone()[0])


def test_query_below_47_refused(reg, settings, cfg, caplog):
    _conn, _pid, handlers, session, _clock = _world(settings, cfg, reg, level=46)
    with caplog.at_level(logging.WARNING, logger="loa.mojun"):
        res = _query(reg, handlers, session)
    # MagicArmyQueryRes has no status: the refusal is logged and the current
    # state answered.
    assert "327957" in caplog.text
    assert (res.state, res.battle_times) == (0, 0)


def test_today_chapter_by_weekday(cfg):
    assert mojun.today_chapter(cfg, T0) == WEDNESDAY
    # 04:59 on Thursday still belongs to Wednesday's monster.
    assert mojun.today_chapter(cfg, datetime(2026, 11, 26, 4, 59).timestamp()) == WEDNESDAY
    assert mojun.today_chapter(cfg, datetime(2026, 11, 26, 5, 0).timestamp()) == 8010000
    # Sunday is idx 7 (MojunDataHelp.lua:26-28).
    assert mojun.today_chapter(cfg, datetime(2026, 11, 29, 10, 0).timestamp()) == 8060000


def test_query_fresh_player_state0_times0(reg, world):
    _conn, _pid, handlers, session, _clock = world
    res = _query(reg, handlers, session)
    assert (res.state, res.battle_times) == (0, 0)


def test_start_flag0_then_win_pays_drops_incl_pet_money(reg, world):
    conn, pid, handlers, session, _clock = world
    # flag 1 is the refusal: MojunLine.lua:62-65 floats x13001 and returns;
    # any other flag enters the fight.
    assert _start(reg, handlers, session, D1).flag == 0
    res = _end(reg, handlers, session, D1, result=1)
    assert res.result == 1
    categories = {p.category for p in res.drop}
    assert 86 in categories and 20 in categories
    paid = sum(p.amount for p in res.drop if p.category == 86)
    assert _pet_money(conn, pid) == paid > 0
    owned = _items(conn, pid)
    for prize in res.drop:
        if prize.category == 20:
            assert owned.get(prize.refer, 0) >= prize.amount
    # First clear of a difficulty uses no run (f00465 首次通关不消耗次数).
    assert (res.state, res.battle_times) == (1, 0)
    notes = [(s, c, m) for (s, c, m) in session.outbox if (s, c) == (5, 2008)]
    assert any(m.ident == 4 for (_s, _c, m) in notes)
    assert any(m.ident == 1 for (_s, _c, m) in notes)
    q = _query(reg, handlers, session)
    assert (q.state, q.battle_times) == (1, 0)


def test_repeat_clear_uses_one_run(reg, world):
    _conn, _pid, handlers, session, _clock = world
    _fight(reg, handlers, session, D1)
    res = _fight(reg, handlers, session, D1)
    assert res.result == 1
    assert (res.state, res.battle_times) == (1, 1)


def test_third_fight_refused_flag1(reg, world, caplog):
    conn, pid, handlers, session, _clock = world
    _fight(reg, handlers, session, D1)          # first clear, free
    _fight(reg, handlers, session, D1)          # run 1
    assert _fight(reg, handlers, session, D1).battle_times == 2   # run 2
    before = (_items(conn, pid), _pet_money(conn, pid))
    with caplog.at_level(logging.WARNING, logger="loa.mojun"):
        start = _start(reg, handlers, session, D1)
    assert start.flag == 1
    assert "328195" in caplog.text
    res = _end(reg, handlers, session, D1)
    assert res.result == 0
    assert len(res.drop) == 0
    assert res.battle_times == 2
    assert (_items(conn, pid), _pet_money(conn, pid)) == before


def test_first_clear_allowed_with_no_runs_left(reg, world):
    # MojunDetailInfoUI.lua:165,302: the challenge is refused only when the
    # runs are spent AND the difficulty was passed before.
    _conn, _pid, handlers, session, _clock = world
    for _ in range(3):
        _fight(reg, handlers, session, D1)
    res = _fight(reg, handlers, session, D2)
    assert res.result == 1
    assert (res.state, res.battle_times) == (2, 2)


def test_loss_uses_no_time(reg, world):
    conn, pid, handlers, session, _clock = world
    _fight(reg, handlers, session, D1)
    before = (_items(conn, pid), _pet_money(conn, pid))
    res = _fight(reg, handlers, session, D1, result=0)
    assert res.result == 0
    assert len(res.drop) == 0
    assert (res.state, res.battle_times) == (1, 0)
    assert (_items(conn, pid), _pet_money(conn, pid)) == before
    # A lost first attempt does not raise the state either.
    assert _fight(reg, handlers, session, D2, result=0).state == 1


def test_times_reset_at_5am(reg, world):
    _conn, _pid, handlers, session, clock = world
    _fight(reg, handlers, session, D1)
    _fight(reg, handlers, session, D1)
    clock["now"] = datetime(2026, 11, 26, 4, 59).timestamp()
    assert _query(reg, handlers, session).battle_times == 1
    clock["now"] = datetime(2026, 11, 26, 5, 0).timestamp()
    assert _query(reg, handlers, session, entry=8010000).battle_times == 0


def test_other_days_stage_refused_flag1(reg, world, caplog):
    _conn, _pid, handlers, session, _clock = world
    with caplog.at_level(logging.WARNING, logger="loa.mojun"):
        assert _start(reg, handlers, session, THURSDAY_D1).flag == 1
    assert "328193" in caplog.text
    assert _end(reg, handlers, session, THURSDAY_D1).result == 0


def test_difficulty_needs_previous_one_passed(reg, world, caplog):
    _conn, _pid, handlers, session, _clock = world
    with caplog.at_level(logging.WARNING, logger="loa.mojun"):
        assert _start(reg, handlers, session, D2).flag == 1
    assert "328193" in caplog.text


def test_difficulty_needs_its_unlock_level(reg, world, caplog):
    _conn, _pid, handlers, session, _clock = world
    _fight(reg, handlers, session, D1)
    _fight(reg, handlers, session, D2)
    # 8030300 opens at 55 (stage_info.unlock_level, SelectRender.lua:98-112).
    with caplog.at_level(logging.WARNING, logger="loa.mojun"):
        assert _start(reg, handlers, session, D3).flag == 1
    assert "327957" in caplog.text


def test_end_without_start_pays_nothing(reg, world):
    conn, pid, handlers, session, _clock = world
    before = (_items(conn, pid), _pet_money(conn, pid))
    res = _end(reg, handlers, session, D1)
    assert res.result == 0
    assert res.state == 0
    assert (_items(conn, pid), _pet_money(conn, pid)) == before


def test_mojun_responses_serialise(reg, world):
    _conn, _pid, handlers, session, _clock = world
    for res in (
        _query(reg, handlers, session),
        _query(reg, handlers, session, entry=999999),
        _start(reg, handlers, session, D1),
        _end(reg, handlers, session, D1),
        _start(reg, handlers, session, 999999),
        _end(reg, handlers, session, 999999),
    ):
        assert res.IsInitialized()
        type(res).FromString(res.SerializeToString())
