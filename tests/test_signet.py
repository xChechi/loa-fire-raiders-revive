"""Signets and the master dungeon (plan B2 Wave 3, task B5; O-W3-7).

Master-dungeon stages are chapter_info type 13: chapter 9001000 holds 9000000
and 9000100, energy 0, no maxcount, visible drops 40101000 (one signet,
category 21) and invisible 40001000 (one more)."""

import json
import random
import time
from pathlib import Path

import pytest

from server.config import Config
from server.db import add_signet, connect, create_player, find_player
from server.modules import level, notify, signet
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
FIRST = 9000000
SECOND = 9000100


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=5000)
    conn.execute("UPDATE players SET level = 52 WHERE id = ?", (pid,))
    conn.commit()
    handlers = level.handlers(reg, settings, conn, cfg, rng=random.Random(3))
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _into(handlers, session, reg, lvl):
    return handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=lvl))


def _fight(handlers, session, reg, lvl, star=3):
    _into(handlers, session, reg, lvl)
    req = reg.message_class("LevelOutReq")(level=lvl, star=star, angel=0)
    return handlers[(5, 2203)](session, req)


def _signets(conn, pid):
    return conn.execute(
        "SELECT * FROM signets WHERE player_id = ? ORDER BY id", (pid,)
    ).fetchall()


def _queued(session, service, cmd):
    return [m for (s, c, m) in session.outbox if (s, c) == (service, cmd)]


def _player_values(session, name):
    """The values `name` took in the ident-1 notifies, in order."""
    out = []
    for m in _queued(session, 5, 2008):
        if m.ident != notify.IDENT_PLAYER or not m.flags & notify.flags_for([name]):
            continue
        ordered = [n for n in notify.PLAYER_FIELDS if m.flags & notify.flags_for([n])]
        out.append(m.data[ordered.index(name)])
    return out


# --- commit A: the master dungeon ---------------------------------------------
def test_master_dungeon_first_stage_is_9000000_at_level52(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    assert level.frontier(cfg, find_player(conn, "stefan"), 13) == FIRST
    conn.execute("UPDATE players SET level = 51 WHERE id = ?", (pid,))
    conn.commit()
    assert _into(handlers, session, reg, FIRST).flag == level.FLAG_STAGE_CHANGED
    assert int(find_player(conn, "stefan")["signet_cnt_used"]) == 0
    conn.execute("UPDATE players SET level = 52 WHERE id = ?", (pid,))
    conn.commit()
    res = _into(handlers, session, reg, FIRST)
    assert res.flag == level.FLAG_OK
    assert len(res.urandom) == level.URANDOM_SIZE
    # The next stage is locked until the first is cleared.
    assert _into(handlers, session, reg, SECOND).flag == level.FLAG_STAGE_CHANGED


def test_signet_stage_win_sets_last_signet_and_drops_a_signet_with_5_2742(
    reg, cfg, world
) -> None:
    conn, pid, handlers, session = world
    res = _fight(handlers, session, reg, FIRST)
    assert res.status == 0
    row = find_player(conn, "stefan")
    assert int(row["last_signet"]) == FIRST
    assert int(row["last_level"]) == 0 and int(row["last_elite"]) == 0
    assert level.frontier(cfg, row, 13) == SECOND
    owned = _signets(conn, pid)
    assert len(owned) == 2                      # one visible, one invisible drop
    signet_drops = [d for d in res.drop if d.category == 21]
    assert [d.extra.signet_id for d in signet_drops] == [r["id"] for r in owned]
    [obtain] = _queued(session, 5, 2742)
    assert [s.id for s in obtain.signets] == [r["id"] for r in owned]
    for sent, stored in zip(obtain.signets, owned):
        assert len(sent.main_attrs) == 1 and not sent.equip
        assert json.loads(stored["main_attrs"])[0]["attr_type"] == sent.main_attrs[0].attr_type
        info = cfg.signet(stored["entry"])
        assert len(sent.sub_attrs) == int(info["quality"]) - 1
    obtain.SerializeToString()
    res.SerializeToString()
    assert _into(handlers, session, reg, SECOND).flag == level.FLAG_OK


def test_signet_fight_spends_a_count_and_recovers_after_1800s(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    before = int(time.time())
    assert _into(handlers, session, reg, FIRST).flag == level.FLAG_OK
    row = find_player(conn, "stefan")
    assert int(row["signet_cnt_used"]) == 1
    assert _player_values(session, "signet_fight_cnt") == [19]
    at = int(row["signet_cnt_at"])
    assert at >= before
    assert signet.settle_fights(conn, cfg, pid, now=at + 1799) == 19
    assert signet.settle_fights(conn, cfg, pid, now=at + 1800) == 20
    # Out of fights: flag 2 (z00225), nothing spent, 338111 in the log.
    conn.execute(
        "UPDATE players SET signet_cnt_used = 20, signet_cnt_at = ? WHERE id = ?",
        (int(time.time()), pid),
    )
    conn.commit()
    assert _into(handlers, session, reg, FIRST).flag == level.FLAG_MAX_TIMES
    assert int(find_player(conn, "stefan")["signet_cnt_used"]) == 20


def test_master_dungeon_sweep_spends_signet_fights(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, FIRST, star=3)
    session.outbox.clear()
    req = reg.message_class("LevelCleanReq")(level=FIRST, times=3)
    res = handlers[(5, 2205)](session, req)
    assert res.flag == level.FLAG_OK
    assert int(find_player(conn, "stefan")["signet_cnt_used"]) == 4
    assert len(_signets(conn, pid)) == 2 + 3 * 2
    [obtain] = _queued(session, 5, 2742)
    assert len(obtain.signets) == 6
    assert _player_values(session, "signet_fight_cnt") == [16]
    # More than the fights left: refused, nothing spent.
    res = handlers[(5, 2205)](session, reg.message_class("LevelCleanReq")(level=FIRST, times=17))
    assert res.flag == level.FLAG_STAGE_CHANGED
    assert int(find_player(conn, "stefan")["signet_cnt_used"]) == 4


def test_bag_full_at_300_refuses_and_notifies_5_2744(reg, cfg, world) -> None:
    """The bag takes no signet past SIGNET_MAX_NUMBER; the fight's signets go
    to mail 101200 and 5_2744 floats fu00073 (RPGGame.lua:1090-1096)."""
    conn, pid, handlers, session = world
    for _ in range(cfg.variable_int("SIGNET_MAX_NUMBER", 0)):
        add_signet(conn, pid, 10101011)
    res = _fight(handlers, session, reg, FIRST)
    assert res.status == 0 and res.if_mail
    assert len(_signets(conn, pid)) == 300
    assert len(_queued(session, 5, 2744)) == 1
    assert _queued(session, 5, 2742) == []
    [mail_row] = conn.execute("SELECT * FROM mails WHERE player_id = ?", (pid,)).fetchall()
    assert int(mail_row["entry"]) == signet.BAG_FULL_MAIL
    assert [c for c, _r, _a in json.loads(mail_row["attachments"])] == [21, 21]
    assert int(find_player(conn, "stefan")["last_signet"]) == FIRST
    res.SerializeToString()


def test_elite_and_campaign_frontiers_unchanged(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, FIRST)
    row = find_player(conn, "stefan")
    assert level.frontier(cfg, row) == 10000
    assert level.frontier(cfg, row, 2) == 110000
    assert _into(handlers, session, reg, 10000).flag == level.FLAG_OK
    assert int(find_player(conn, "stefan")["signet_cnt_used"]) == 1
