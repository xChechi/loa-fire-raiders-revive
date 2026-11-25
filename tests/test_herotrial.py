"""Hero trials: 5_2331 HerotrialsInfo, 5_2333 HerotrialsBattle, 5_2335
HerotrialsBattleResult.

T0 is Wednesday 25-11-2026 10:00 local, so the client's weekday
(getDay(-5*3600), 0 = Sunday, ServerTimeManager.lua:102-108) is 3. Wednesday's
stages are the vocation-3 (ss) rows with weekday 3: 1200 (icon 1000, level 40)
up to 7200. Stage 1200's grade row is herotrials_grade_info 1000 (cd 300);
stage 5200's icon 5000 has no grade row, so HERO_TRIALS_COOLDOWN (0) applies.
"""

import logging
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import herotrial
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
SS_WEDNESDAY = 1200        # vocation 3, weekday 3, level 40, icon 1000
SS_WEDNESDAY_V = 5200      # vocation 3, weekday 3, level 75, icon 5000 (no grade row)
ZS_MONDAY = 1000           # vocation 1, weekday 1


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


def _world(settings, cfg, reg, level=40):
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    conn.execute("UPDATE players SET level = ? WHERE id = ?", (level, pid))
    conn.commit()
    clock = {"now": T0}
    handlers = herotrial.handlers(
        reg, settings, conn, cfg, clock=lambda: clock["now"], rng=random.Random(7)
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


@pytest.fixture
def world(settings, cfg, reg):
    return _world(settings, cfg, reg)


def _info(reg, handlers, session):
    res = handlers[(5, 2331)](session, reg.message_class("HerotrialsInfoReq")())
    res.SerializeToString()
    return res


def _battle(reg, handlers, session, entry):
    res = handlers[(5, 2333)](
        session, reg.message_class("HerotrialsBattleReq")(trialEntry=entry)
    )
    res.SerializeToString()
    return res


def _result(reg, handlers, session, entry, star=3):
    req = reg.message_class("HerotrialsBattleResultReq")(
        trialEntry=entry, angel=0, star=star
    )
    req.heroes.extend([0] * 6)
    res = handlers[(5, 2335)](session, req)
    res.SerializeToString()
    return res


def _items(conn, pid):
    return {
        int(r["entry"]): int(r["amount"])
        for r in conn.execute("SELECT * FROM items WHERE player_id = ?", (pid,))
    }


def test_t0_is_wednesday_for_the_client():
    assert herotrial.weekday(T0) == 3


def test_info_three_free_runs_per_vocation(reg, world):
    _conn, _pid, handlers, session, _clock = world
    res = _info(reg, handlers, session)
    assert res.maxTrialTimes == 3
    assert (res.zs_trialTimes, res.fs_trialTimes, res.ss_trialTimes) == (0, 0, 0)
    assert (res.zs_cd, res.fs_cd, res.ss_cd) == (0, 0, 0)


def test_battle_echoes_entry_with_64_randoms(reg, world):
    _conn, _pid, handlers, session, _clock = world
    res = _battle(reg, handlers, session, SS_WEDNESDAY)
    assert res.trialEntry == SS_WEDNESDAY
    assert len(res.Urandom) == 64


def test_win_pays_star_drops_and_sets_cd_300(reg, world):
    conn, pid, handlers, session, _clock = world
    _battle(reg, handlers, session, SS_WEDNESDAY)
    res = _result(reg, handlers, session, SS_WEDNESDAY, star=3)
    assert res.success is True
    assert res.trialEntry == SS_WEDNESDAY
    assert (res.zs_trialTimes, res.fs_trialTimes, res.ss_trialTimes) == (0, 0, 1)
    assert res.ss_cd == int(T0) + 300
    assert (res.zs_cd, res.fs_cd) == (0, 0)
    assert len(res.prizes) > 0
    owned = _items(conn, pid)
    for prize in res.prizes:
        assert prize.category == 20
        assert owned.get(prize.refer, 0) >= prize.amount
    item_notes = [m for (s, c, m) in session.outbox if (s, c) == (5, 2008)]
    assert any(m.ident == 4 for m in item_notes)

    info = _info(reg, handlers, session)
    assert info.ss_trialTimes == 1
    assert info.ss_cd == int(T0) + 300


def test_stage_without_grade_row_uses_hero_trials_cooldown(reg, settings, cfg):
    _conn, _pid, handlers, session, _clock = _world(settings, cfg, reg, level=75)
    _battle(reg, handlers, session, SS_WEDNESDAY_V)
    res = _result(reg, handlers, session, SS_WEDNESDAY_V, star=1)
    assert res.success is True
    # HERO_TRIALS_COOLDOWN is 0: the cooldown ends the moment the run does.
    assert res.ss_cd == int(T0)


def test_loss_counts_nothing_and_pays_nothing(reg, world):
    conn, pid, handlers, session, _clock = world
    before = _items(conn, pid)
    _battle(reg, handlers, session, SS_WEDNESDAY)
    res = _result(reg, handlers, session, SS_WEDNESDAY, star=0)
    assert res.success is False
    assert len(res.prizes) == 0
    assert (res.ss_trialTimes, res.ss_cd) == (0, 0)
    assert _items(conn, pid) == before


def test_cooldown_refused_logged_333314(reg, world, caplog):
    _conn, _pid, handlers, session, clock = world
    _battle(reg, handlers, session, SS_WEDNESDAY)
    _result(reg, handlers, session, SS_WEDNESDAY, star=3)
    clock["now"] = T0 + 299
    with caplog.at_level(logging.WARNING, logger="loa.herotrial"):
        res = _battle(reg, handlers, session, SS_WEDNESDAY)
    assert res.trialEntry == SS_WEDNESDAY
    assert "333314" in caplog.text
    after = _result(reg, handlers, session, SS_WEDNESDAY, star=3)
    assert after.success is False
    assert after.ss_trialTimes == 1


def test_fourth_run_refused_logged_333313(reg, world, caplog):
    conn, pid, handlers, session, clock = world
    for run in range(3):
        clock["now"] = T0 + run * 301
        _battle(reg, handlers, session, SS_WEDNESDAY)
        assert _result(reg, handlers, session, SS_WEDNESDAY).success is True
    before = _items(conn, pid)
    clock["now"] = T0 + 3 * 301
    with caplog.at_level(logging.WARNING, logger="loa.herotrial"):
        res = _battle(reg, handlers, session, SS_WEDNESDAY)
    # No status on HerotrialsBattleRes: the client starts the fight anyway
    # (HeroTryLine.lua:67-112), so the refusal lives in the log and in the
    # result that follows.
    assert len(res.Urandom) == 64
    assert "333313" in caplog.text
    after = _result(reg, handlers, session, SS_WEDNESDAY)
    assert after.success is False
    assert after.ss_trialTimes == 3
    assert len(after.prizes) == 0
    assert _items(conn, pid) == before


def test_stage_level_gates_not_grade_level(reg, settings, cfg, caplog):
    # Grade 1000 says level 30, but the stage row says 40 and the client greys
    # the stage out below it (HeroTryTypeLevelItem.lua:159).
    _conn, _pid, handlers, session, _clock = _world(settings, cfg, reg, level=39)
    with caplog.at_level(logging.WARNING, logger="loa.herotrial"):
        _battle(reg, handlers, session, SS_WEDNESDAY)
    assert "327957" in caplog.text
    assert _result(reg, handlers, session, SS_WEDNESDAY).success is False


def test_below_function_unlock_refused_327957(reg, settings, cfg, caplog):
    # function 10091 英雄试炼 opens at 36.
    _conn, _pid, handlers, session, _clock = _world(settings, cfg, reg, level=35)
    with caplog.at_level(logging.WARNING, logger="loa.herotrial"):
        _battle(reg, handlers, session, SS_WEDNESDAY)
    assert "327957" in caplog.text


def test_other_weekdays_stage_refused(reg, world, caplog):
    _conn, _pid, handlers, session, _clock = world
    with caplog.at_level(logging.WARNING, logger="loa.herotrial"):
        _battle(reg, handlers, session, ZS_MONDAY)
    assert "weekday" in caplog.text
    assert _result(reg, handlers, session, ZS_MONDAY).success is False


def test_unknown_stage_refused(reg, world):
    _conn, _pid, handlers, session, _clock = world
    res = _battle(reg, handlers, session, 999999)
    assert res.trialEntry == 999999
    assert _result(reg, handlers, session, 999999).success is False


def test_result_without_battle_pays_nothing(reg, world):
    conn, pid, handlers, session, _clock = world
    before = _items(conn, pid)
    res = _result(reg, handlers, session, SS_WEDNESDAY)
    assert res.success is False
    assert _items(conn, pid) == before


def test_runs_reset_at_5am(reg, world):
    _conn, _pid, handlers, session, clock = world
    _battle(reg, handlers, session, SS_WEDNESDAY)
    _result(reg, handlers, session, SS_WEDNESDAY)
    clock["now"] = datetime(2026, 11, 26, 4, 59).timestamp()
    assert _info(reg, handlers, session).ss_trialTimes == 1
    clock["now"] = datetime(2026, 11, 26, 5, 0).timestamp()
    assert _info(reg, handlers, session).ss_trialTimes == 0


def test_trial_responses_serialise(reg, world):
    _conn, _pid, handlers, session, _clock = world
    for res in (
        _info(reg, handlers, session),
        _battle(reg, handlers, session, SS_WEDNESDAY),
        _result(reg, handlers, session, SS_WEDNESDAY),
        _battle(reg, handlers, session, 999999),
        _result(reg, handlers, session, 999999),
    ):
        assert res.IsInitialized()
        type(res).FromString(res.SerializeToString())
