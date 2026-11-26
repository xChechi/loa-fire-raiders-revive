"""Divine ruins (神之遗迹): 5_2517 state, 5_2551 enter, 5_2531 result, 5_2563
cooldown reset, 5_2547 chest.

The tower's first chapter is chapter_info 5000000 (type 8, idx 1). Its floors
are stage_info 5000000 (idx 1), 5000100 (idx 2), 5000200 (idx 3, flags 1 =
chest_info 1), ... 5000900 (idx 10). Every floor has two teams (group0,
group1), costs 6 energy, invisible_drops 1500000, visible_drops 1500010.
chest_info 1 drops 1400000 = one item 1500002.
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player
from server.modules import godtower
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
FLOOR1, FLOOR2, FLOOR3, FLOOR4 = 5000000, 5000100, 5000200, 5000300
CHAPTER1 = 5000000


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


def _world(settings, cfg, reg, level=57, diamond=0, vip=0):
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000,
                        diamond=diamond, energy=100, max_energy=100)
    conn.execute("UPDATE players SET level = ?, vip = ?, energy_at = ? WHERE id = ?",
                 (level, vip, int(T0), pid))
    conn.commit()
    clock = {"now": T0}
    handlers = godtower.handlers(
        reg, settings, conn, cfg, clock=lambda: clock["now"], rng=random.Random(7)
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


@pytest.fixture
def world(settings, cfg, reg):
    return _world(settings, cfg, reg)


def _call(reg, handlers, session, cmd, name, **fields):
    res = handlers[(5, cmd)](session, reg.message_class(name)(**fields))
    res.SerializeToString()
    return res


def _state(reg, handlers, session):
    return _call(reg, handlers, session, 2517, "GodChallengeReq")


def _enter(reg, handlers, session, floor, group):
    return _call(reg, handlers, session, 2551, "GodFightIntoReq", chapter=floor, group=group)


def _result(reg, handlers, session, floor, group, heroes=(), angel=0, result=1):
    req = reg.message_class("GodFightReq")(
        chapter=floor, group=group, angel=angel, result=result
    )
    req.heroes.extend(list(heroes) + [0] * (6 - len(heroes)))
    res = handlers[(5, 2531)](session, req)
    res.SerializeToString()
    return res


def _fight(reg, handlers, session, floor, group, heroes=(), angel=0, result=1):
    assert _enter(reg, handlers, session, floor, group).flag == godtower.FLAG_OK
    return _result(reg, handlers, session, floor, group, heroes, angel, result)


def _player(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _items(conn, pid):
    return {
        int(r["entry"]): int(r["amount"])
        for r in conn.execute("SELECT * FROM items WHERE player_id = ?", (pid,))
    }


def test_state_at_level57(reg, world):
    _conn, _pid, handlers, session, _clock = world
    res = _state(reg, handlers, session)
    assert (res.cd, res.cd_time, res.fight_status) == (0, 0, 0)
    # last_god_level 0 is the first floor; `chapter` is its chapter entry.
    assert res.chapter == CHAPTER1
    assert list(res.heros) == [] and list(res.angel) == []


def test_state_below_57_logs_327957(reg, settings, cfg, caplog):
    _conn, _pid, handlers, session, _clock = _world(settings, cfg, reg, level=56)
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        _state(reg, handlers, session)
        flag = _enter(reg, handlers, session, FLOOR1, 0).flag
    assert "327957" in caplog.text
    assert flag == godtower.FLAG_REFUSED


def test_enter_and_win_floor1_pays_drops_sets_cd_300(reg, world):
    conn, pid, handlers, session, clock = world
    # Team 0: beaten, its units rest, no prize yet, 300 s of cooldown.
    res = _fight(reg, handlers, session, FLOOR1, 0, heroes=[300000], angel=4)
    assert res.result == 1 and len(res.drop) == 0 and res.is_draw == 0
    state = _state(reg, handlers, session)
    assert (state.fight_status, state.cd_time, state.cd) == (0b01, 300, 0)
    assert list(state.heros) == [300000] and list(state.angel) == [4]

    # Team 1, 300 s later: the floor is cleared and pays its invisible_drops.
    clock["now"] += 300
    before = _player(conn, pid)
    res = _fight(reg, handlers, session, FLOOR1, 1, heroes=[301000])
    assert res.result == 1 and len(res.drop) >= 1
    assert res.is_draw == godtower.ALL_CARDS
    paid = _items(conn, pid)
    for prize in res.drop:
        assert prize.category == 20 and paid[prize.refer] >= prize.amount
    row = _player(conn, pid)
    assert int(row["energy"]) == int(before["energy"]) - 6
    assert int(row["xp"]) > int(before["xp"]) or int(row["level"]) > int(before["level"])
    # On to floor 2 with every team alive and nobody resting.
    state = _state(reg, handlers, session)
    assert int(row["last_god_level"]) == FLOOR2
    assert (state.fight_status, state.cd_time) == (0, 300)
    assert list(state.heros) == [] and list(state.angel) == []
    assert int(conn.execute(
        "SELECT star FROM levels WHERE player_id = ? AND level = ?", (pid, FLOOR1)
    ).fetchone()[0]) == 1


def test_loss_pays_nothing_adds_cd(reg, world):
    conn, pid, handlers, session, _clock = world
    res = _fight(reg, handlers, session, FLOOR1, 0, heroes=[300000], result=0)
    assert res.result == 0 and len(res.drop) == 0
    state = _state(reg, handlers, session)
    assert (state.fight_status, state.cd_time) == (0, 300)
    assert list(state.heros) == []


def test_result_without_enter_pays_nothing(reg, world, caplog):
    conn, pid, handlers, session, _clock = world
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _result(reg, handlers, session, FLOOR1, 0)
    assert "328196" in caplog.text and res.result == 0
    assert int(_player(conn, pid)["god_fight_status"]) == 0


def test_rested_hero_refused_336009(reg, world, caplog):
    conn, pid, handlers, session, _clock = world
    _fight(reg, handlers, session, FLOOR1, 0, heroes=[300000])
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _fight(reg, handlers, session, FLOOR1, 1, heroes=[300000])
    assert "336009" in caplog.text and res.result == 0
    assert int(_player(conn, pid)["god_fight_status"]) == 0b01


def test_fight_in_cd_refused_336012(reg, world, caplog):
    conn, pid, handlers, session, clock = world
    # Four fights pile up 1200 s: locked while the time left is >= 1200.
    conn.execute("UPDATE players SET god_cd_until = ? WHERE id = ?",
                 (int(T0) + 1200, pid))
    conn.commit()
    assert _state(reg, handlers, session).cd == 1
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        assert _enter(reg, handlers, session, FLOOR1, 0).flag == godtower.FLAG_REFUSED
    assert "336012" in caplog.text
    # The refused entry leaves nothing to pay.
    assert _result(reg, handlers, session, FLOOR1, 0).result == 0
    clock["now"] += 1
    assert _state(reg, handlers, session).cd == 0
    assert _enter(reg, handlers, session, FLOOR1, 0).flag == godtower.FLAG_OK


def test_enter_wrong_floor_or_beaten_team_refused(reg, world, caplog):
    _conn, _pid, handlers, session, _clock = world
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        assert _enter(reg, handlers, session, FLOOR2, 0).flag == godtower.FLAG_REFUSED
        assert _enter(reg, handlers, session, FLOOR1, 2).flag == godtower.FLAG_REFUSED
        _fight(reg, handlers, session, FLOOR1, 0)
        assert _enter(reg, handlers, session, FLOOR1, 0).flag == godtower.FLAG_REFUSED
    assert "336001" in caplog.text and "336013" in caplog.text


def test_cd_reset_costs_100(reg, settings, cfg):
    conn, pid, handlers, session, _clock = _world(settings, cfg, reg, diamond=150)
    conn.execute("UPDATE players SET god_cd_until = ? WHERE id = ?", (int(T0) + 1300, pid))
    conn.commit()
    _call(reg, handlers, session, 2563, "GodCdResetReq", level=FLOOR1)
    assert int(_player(conn, pid)["diamond"]) == 50
    state = _state(reg, handlers, session)
    assert (state.cd, state.cd_time) == (0, 0)
    # Short of diamonds: nothing changes.
    conn.execute("UPDATE players SET god_cd_until = ? WHERE id = ?", (int(T0) + 1300, pid))
    conn.commit()
    _call(reg, handlers, session, 2563, "GodCdResetReq", level=FLOOR1)
    assert int(_player(conn, pid)["diamond"]) == 50
    assert _state(reg, handlers, session).cd_time == 1300


def test_chest_once(reg, world, caplog):
    conn, pid, handlers, session, _clock = world
    conn.execute(
        "UPDATE players SET last_god_level = ?, god_fight_status = 1,"
        " god_rest_heroes = ? WHERE id = ?", (FLOOR3, json.dumps([300000]), pid),
    )
    conn.commit()
    _fight(reg, handlers, session, FLOOR3, 1, heroes=[301000])
    row = _player(conn, pid)
    # Floor 3's stage_info.flags is chest_info 1.
    assert int(row["last_god_chest"]) == 1 and int(row["last_god_level"]) == FLOOR4
    before = _items(conn, pid).get(1500002, 0)
    res = _call(reg, handlers, session, 2547, "GodGetChestReq")
    assert [(d.category, d.refer, d.amount) for d in res.drops] == [(20, 1500002, 1)]
    assert _items(conn, pid)[1500002] == before + 1
    assert int(_player(conn, pid)["last_god_chest"]) == 0
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        again = _call(reg, handlers, session, 2547, "GodGetChestReq")
    assert len(again.drops) == 0 and "336008" in caplog.text
    assert _items(conn, pid)[1500002] == before + 1


def test_floor_without_chest_leaves_none(reg, world):
    conn, pid, handlers, session, _clock = world
    _fight(reg, handlers, session, FLOOR1, 0)
    _fight(reg, handlers, session, FLOOR1, 1)
    assert int(_player(conn, pid)["last_god_chest"]) == 0


# --- resets and sweeps ------------------------------------------------------
# vip_info at VIP 8: 20120 free resets 4, 20150 reset buys 999, 20130 free
# sweeps 2, 20140 sweep buys 0. At VIP 7 the reset buys are 0; at VIP 18 the
# sweep buys are 10. GOD_LEVEL_RESET_COST = 100|2,200|3,..., GOD_CHAPTER_CLEAN_
# COST = 1000|2,2000|2,...
LAST_OF_CHAPTER1 = 5000900
CHAPTER2 = 5010000


def test_reset_tiers_and_limit(reg, settings, cfg, caplog):
    conn, pid, handlers, session, _clock = _world(settings, cfg, reg, diamond=1000, vip=8)
    state = _state(reg, handlers, session)
    assert (state.balance, state.max) == (4, 4)
    conn.execute("UPDATE players SET god_reset_used = 4, god_fight_status = 1 WHERE id = ?",
                 (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        _call(reg, handlers, session, 2519, "GodLevelResetReq")
    assert "336002" in caplog.text
    assert int(_player(conn, pid)["god_fight_status"]) == 1

    q = _call(reg, handlers, session, 2521, "GodQueryBuyLevelResetReq")
    assert (q.max, q.used, q.diamond) == (999, 0, 100)
    prices = []
    for _ in range(3):
        before = int(_player(conn, pid)["diamond"])
        res = _call(reg, handlers, session, 2523, "GodBuyLevelResetReq")
        prices.append(before - int(_player(conn, pid)["diamond"]))
    # Two at 100, then the 200 tier; the Res names the next price.
    assert prices == [100, 100, 200] and (res.used, res.diamond) == (3, 200)
    state = _state(reg, handlers, session)
    assert (state.balance, state.max) == (3, 7)

    conn.execute("UPDATE players SET god_rest_heroes = '[300000]', god_cd_until = ?"
                 " WHERE id = ?", (int(T0) + 900, pid))
    conn.commit()
    _call(reg, handlers, session, 2519, "GodLevelResetReq")
    state = _state(reg, handlers, session)
    assert (state.fight_status, state.cd_time, state.balance) == (0, 0, 2)
    assert list(state.heros) == []
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        _call(reg, handlers, session, 2519, "GodLevelResetReq")
    assert "336011" in caplog.text and _state(reg, handlers, session).balance == 2


def test_reset_buy_limit_at_vip7_refused_336003(reg, settings, cfg, caplog):
    conn, pid, handlers, session, _clock = _world(settings, cfg, reg, diamond=1000, vip=7)
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _call(reg, handlers, session, 2523, "GodBuyLevelResetReq")
    assert "336003" in caplog.text and (res.max, res.used) == (0, 0)
    assert int(_player(conn, pid)["diamond"]) == 1000


def _clear_chapter1(conn, pid):
    conn.execute("INSERT INTO levels (player_id, level, star) VALUES (?, ?, 1)",
                 (pid, LAST_OF_CHAPTER1))
    conn.commit()


def test_sweep_with_gold_card_costs_1000(reg, settings, cfg, caplog):
    conn, pid, handlers, session, _clock = _world(settings, cfg, reg, diamond=20000, vip=8)
    q = _call(reg, handlers, session, 2527, "GodQueryBuyChapterCleanReq")
    assert (q.clean_num, q.clean_max, q.max, q.used, q.diamond) == (0, 2, 0, 0, 1000)
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _call(reg, handlers, session, 2525, "GodChapterCleanReq",
                    chapter=CHAPTER1, times=1, gold_card=True)
    assert "336007" in caplog.text and len(res.drops) == 0 and res.times == 2

    _clear_chapter1(conn, pid)
    before = _player(conn, pid)
    res = _call(reg, handlers, session, 2525, "GodChapterCleanReq",
                chapter=CHAPTER1, times=1, gold_card=True)
    row = _player(conn, pid)
    # The gold card is 1000 diamonds per floor, ten floors.
    assert int(before["diamond"]) - int(row["diamond"]) == 10 * 1000
    assert int(before["energy"]) - int(row["energy"]) == 10 * 6
    assert len(res.drops) == 10 and len(res.gold_drops) == 10 and len(res.silver_drops) == 0
    assert all(len(e.drop) == 2 for e in res.drops)      # invisible + visible
    assert all(len(e.drop) == 1 for e in res.gold_drops)
    assert res.times == 1
    paid = _items(conn, pid)
    for entry in list(res.drops) + list(res.gold_drops):
        for prize in entry.drop:
            assert paid[prize.refer] >= prize.amount

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _call(reg, handlers, session, 2525, "GodChapterCleanReq",
                    chapter=CHAPTER1, times=2)
    assert "336006" in caplog.text and res.times == 1
    _call(reg, handlers, session, 2525, "GodChapterCleanReq", chapter=CHAPTER1, times=1)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        res = _call(reg, handlers, session, 2525, "GodChapterCleanReq",
                    chapter=CHAPTER1, times=1)
    assert "336004" in caplog.text and res.times == 0
    # A sweep of a chapter not yet climbed is refused even with sweeps left.
    assert not godtower.chapter_cleared(conn, cfg, pid, CHAPTER2)


def test_sweep_buys(reg, settings, cfg, caplog):
    conn, pid, handlers, session, _clock = _world(settings, cfg, reg, diamond=5000, vip=18)
    res = _call(reg, handlers, session, 2529, "GodBuyChapterCleanReq")
    assert (res.max, res.used, res.diamond) == (10, 1, 1000)
    res = _call(reg, handlers, session, 2529, "GodBuyChapterCleanReq")
    assert (res.used, res.diamond) == (2, 2000)
    assert int(_player(conn, pid)["diamond"]) == 3000
    q = _call(reg, handlers, session, 2527, "GodQueryBuyChapterCleanReq")
    assert (q.clean_num, q.clean_max) == (0, 4)
    conn.execute("UPDATE players SET vip = 8 WHERE id = ?", (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.godtower"):
        _call(reg, handlers, session, 2529, "GodBuyChapterCleanReq")
    assert "336005" in caplog.text and int(_player(conn, pid)["diamond"]) == 3000


def test_day_reset_at_5am(reg, settings, cfg):
    conn, pid, handlers, session, clock = _world(settings, cfg, reg, vip=8)
    _state(reg, handlers, session)          # stamps today's god_day
    conn.execute(
        "UPDATE players SET god_reset_used = 4, god_reset_bought = 1, god_clean_used = 2,"
        " god_clean_bought = 1, god_fight_status = 1 WHERE id = ?", (pid,),
    )
    conn.commit()
    clock["now"] = datetime(2026, 11, 26, 4, 59).timestamp()
    state = _state(reg, handlers, session)
    assert (state.balance, state.max) == (1, 5)
    clock["now"] = datetime(2026, 11, 26, 5, 0).timestamp()
    state = _state(reg, handlers, session)
    assert (state.balance, state.max) == (4, 4)
    q = _call(reg, handlers, session, 2527, "GodQueryBuyChapterCleanReq")
    assert (q.clean_num, q.clean_max, q.used) == (0, 2, 0)
    # The day boundary rolls counters only; the climb itself stays.
    assert state.fight_status == 1
