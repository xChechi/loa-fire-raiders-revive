"""Gold trial: 5_2213 GoldTrailsInfo, 5_2215 GoldTrailsResult, 5_2217
GoldTrailsPrize.

Numbers from the stock tables: function(10070).unlock_level 25,
GOLD_TRAILS_TIMES 2, GOLD_TRAILS_FIGHT_TICK 1800, GOLD_TRAILS_STAR_GOLD_RATE
0.01. gold_trails_exchange_info bands 80000/270, 160000/165, 300000/105, ...
(gold per 100 damage, BattleFactoryCoinTry.lua:136-160). gold_trails_gold_limit
level 1 = 93600, level 25 = 994200. gold_trails_prize_info sorted by damage
starts 20000/30000, 50000/42000, 120000/54000.
"""

from datetime import date
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_angel, grant_hero
from server.modules import goldtrial, player
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
DAY1 = date(2026, 11, 25)
DAY2 = date(2026, 11, 26)
KNIGHT = 100000
GODDESS = 500000
STAGE = 1000000
GOLD0 = 1000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=GOLD0, diamond=0)
    conn.execute("UPDATE players SET level = 25 WHERE id = ?", (pid,))
    conn.commit()
    clock = {"today": DAY1}
    handlers = goldtrial.handlers(reg, settings, conn, cfg, clock=lambda: clock["today"])
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


def _info(reg, handlers, session, level=STAGE):
    res = handlers[(5, 2213)](session, reg.message_class("GoldTrailsInfoReq")(level=level))
    res.SerializeToString()
    return res


def _result(reg, handlers, session, damage, heroes=(0, 0, 0, 0, 0, 0), angel=0):
    req = reg.message_class("GoldTrailsResultReq")(
        level=STAGE, angel=angel, star=1, damage=damage,
    )
    req.heroes.extend(heroes)
    res = handlers[(5, 2215)](session, req)
    res.SerializeToString()
    return res


def _prize(reg, handlers, session, index=0, get_all=False):
    res = handlers[(5, 2217)](session, reg.message_class("GoldTrailsPrizeReq")(
        index=index, get_all=get_all,
    ))
    res.SerializeToString()
    return res


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()["gold"])


def _row(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def test_client_coin_formula_walks_the_bands() -> None:
    bands = [(80000, 270), (160000, 165), (300000, 105), (500000, 60), (9999999, 30)]
    assert goldtrial.coin_by_damage(bands, 50000) == 135000
    # 216000 + 132000 + 42000
    assert goldtrial.coin_by_damage(bands, 200000) == 390000
    assert goldtrial.coin_by_damage(bands, 0) == 0


def test_info_answers_level_urandom_and_fight_tick(reg, world) -> None:
    _, _, handlers, session, _ = world
    res = _info(reg, handlers, session)
    assert res.status == 0
    assert res.level == STAGE
    assert len(res.urandom) == 64
    assert list(res.drop) == []
    assert res.fight_tick == 1800


def test_info_below_level25_refused_327957(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 24 WHERE id = ?", (pid,))
    conn.commit()
    assert _info(reg, handlers, session).status == 327957   # 未满足此玩法的等级


def test_info_refused_after_two_runs_331014(reg, world) -> None:
    _, _, handlers, session, _ = world
    for _ in range(2):
        assert _info(reg, handlers, session).status == 0
        assert _result(reg, handlers, session, 1000).status == 0
    assert _info(reg, handlers, session).status == 331014   # 挑战次数不够


def test_result_past_the_daily_runs_pays_nothing(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _result(reg, handlers, session, 1000)
    _result(reg, handlers, session, 1000)
    gold = _gold(conn, pid)
    assert _result(reg, handlers, session, 50000).status == 331014
    assert _gold(conn, pid) == gold
    assert int(_row(conn, pid)["gold_trails_times"]) == 2


def test_result_gold_matches_client_formula_at_50000_damage(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    res = _result(reg, handlers, session, 50000)
    assert res.status == 0
    assert res.gold == 135000                 # floor(50000 * 0.01 * 270)
    assert res.addition_gold == 0             # no heroes on the line
    assert res.damage == 50000
    assert res.all_damage == 50000
    assert res.times == 1
    assert res.cooldown == 0
    assert _gold(conn, pid) == GOLD0 + 135000
    notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]
    assert notes, "the new gold balance is pushed"


def test_gold_capped_by_player_level_limit(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 1 WHERE id = ?", (pid,))
    conn.commit()
    # The level gate is on 5_2213 only; the cap is gold_trails_gold_limit(1).
    res = _result(reg, handlers, session, 50000)
    assert res.gold == 93600
    assert _gold(conn, pid) == GOLD0 + 93600


def test_addition_gold_counts_hero_and_angel_stars(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, KNIGHT, 1, star=3)
    grant_angel(conn, pid, GODDESS, level=1, star=2)
    res = _result(reg, handlers, session, 50000, heroes=(KNIGHT, 0, 0, 0, 0, 0), angel=GODDESS)
    # LineRight:rightLineStar = hero stars + angel star = 5, x 0.01 (CoinLine.lua:37-41)
    assert res.gold == 135000
    assert res.addition_gold == 6750
    assert _gold(conn, pid) == GOLD0 + 135000 + 6750


def test_damage_adds_up_to_todays_total(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _result(reg, handlers, session, 30000)
    res = _result(reg, handlers, session, 25000)
    assert res.damage == 25000
    assert res.all_damage == 55000
    row = _row(conn, pid)
    assert int(row["gold_trails_best"]) == 55000
    assert row["gold_trails_day"] == DAY1.isoformat()


def test_prize_ladder_pays_each_row_once(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _result(reg, handlers, session, 30000)
    _result(reg, handlers, session, 25000)     # today's total 55000: rows 0 and 1
    gold = _gold(conn, pid)
    res = _prize(reg, handlers, session, index=1)
    assert res.index == 1
    assert res.prize == 0b10
    assert [(p.category, p.amount) for p in res.prizeEntries] == [(1, 42000)]
    assert _gold(conn, pid) == gold + 42000
    # The same row again pays nothing and keeps the flags.
    again = _prize(reg, handlers, session, index=1)
    assert again.prize == 0b10
    assert list(again.prizeEntries) == []
    assert _gold(conn, pid) == gold + 42000
    # Row 2 (120000) is not reached.
    assert _prize(reg, handlers, session, index=2).prize == 0b10
    assert _gold(conn, pid) == gold + 42000


def test_prize_get_all_pays_every_reached_unclaimed_row(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _result(reg, handlers, session, 55000)
    _prize(reg, handlers, session, index=0)
    gold = _gold(conn, pid)
    res = _prize(reg, handlers, session, get_all=True)
    assert res.prize == 0b11
    assert [(p.category, p.amount) for p in res.prizeEntries] == [(1, 42000)]
    assert _gold(conn, pid) == gold + 42000
    assert int(_row(conn, pid)["gold_trails_prize"]) == 0b11


def test_counters_reset_next_day(reg, world) -> None:
    conn, pid, handlers, session, clock = world
    _result(reg, handlers, session, 55000)
    _result(reg, handlers, session, 1000)
    _prize(reg, handlers, session, get_all=True)
    assert _info(reg, handlers, session).status == 331014
    clock["today"] = DAY2
    assert _info(reg, handlers, session).status == 0
    res = _result(reg, handlers, session, 25000)
    assert res.times == 1
    assert res.all_damage == 25000
    # Yesterday's claimed rows are claimable again on the new day's total.
    assert _prize(reg, handlers, session, index=0).prize == 0b1
    row = _row(conn, pid)
    assert int(row["gold_trails_times"]) == 1
    assert int(row["gold_trails_best"]) == 25000
    assert row["gold_trails_day"] == DAY2.isoformat()


def test_query_myself_reports_todays_total_and_flags(reg, cfg, world) -> None:
    conn, pid, handlers, session, _ = world
    _result(reg, handlers, session, 30000)
    _result(reg, handlers, session, 25000)
    _prize(reg, handlers, session, get_all=True)
    res = player.build_query_myself_res(reg, cfg, conn, _row(conn, pid), today=DAY1.isoformat())
    assert res.gold_trails.damage == 55000
    assert res.gold_trails.prize == 0b11
    assert res.stats.gold_trails_times == 2
