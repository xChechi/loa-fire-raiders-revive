"""Angel advance (女神进阶, function 90030, level 60): 5_2779 query, 5_2781 one
attempt, 5_2783 auto, 5_2785 report query, 5_2803 inheritance (plan B2 Wave 3,
task B10; O-W3-8). angel_advance_info level 0: 10000 gold, 2 stones (item
1900), score 2..4, max_score 450; level 21 is the top (22 rows)."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_angel, grant_item
from server.modules import angeladvance
from server.modules.notify import ANGEL_FIELDS, IDENT_ANGEL, flags_for
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
ANGEL = 500000
OTHER = 500001
STONE = angeladvance.STONE_ITEM


class FixedRng(random.Random):
    """randint always gives `score`; random() always gives `roll`."""

    def __init__(self, score: int, roll: float) -> None:
        super().__init__(0)
        self._score, self._roll = score, roll

    def randint(self, a, b):
        assert a <= self._score <= b
        return self._score

    def random(self):
        return self._roll


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
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1_000_000, diamond=5000
    )
    conn.execute("UPDATE players SET level = 60 WHERE id = ?", (pid,))
    conn.commit()
    grant_angel(conn, pid, ANGEL, level=60, star=1)
    grant_angel(conn, pid, OTHER, level=60, star=1)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, session


def _handlers(reg, settings, conn, cfg, rng):
    return angeladvance.handlers(reg, settings, conn, cfg, rng=rng)


def _stones(conn, pid) -> int:
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, STONE)
    ).fetchone()
    return int(row["amount"]) if row else 0


def _player(conn, pid):
    return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _advance(conn, pid, entry) -> tuple[int, int]:
    row = conn.execute(
        "SELECT advance_level, advance_score FROM angels"
        " WHERE player_id = ? AND angel_entry = ?", (pid, entry),
    ).fetchone()
    return int(row["advance_level"]), int(row["advance_score"])


def _set_advance(conn, pid, entry, level, score=0):
    conn.execute(
        "UPDATE angels SET advance_level = ?, advance_score = ?"
        " WHERE player_id = ? AND angel_entry = ?", (level, score, pid, entry),
    )
    conn.commit()


def _angel_notifies(reg, session):
    cls = reg.message_class("ClientNotification")
    out = []
    for service, cmd, msg in session.outbox:
        if (service, cmd) != (5, 2008):
            continue
        if not isinstance(msg, cls):
            msg = cls.FromString(msg)
        if msg.ident == IDENT_ANGEL:
            out.append(msg)
    return out


def _one(reg, handlers, session, entry=ANGEL):
    return handlers[(5, 2781)](session, reg.message_class("AngelAdvanceReq")(entry=entry))


def _auto(reg, handlers, session, entry=ANGEL):
    return handlers[(5, 2783)](
        session, reg.message_class("AngelAdvanceAutoReq")(entry=entry)
    )


def test_query_level0(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    res = handlers[(5, 2779)](
        session, reg.message_class("AngelAdvanceQueryReq")(entry=ANGEL)
    )
    assert (res.advance_level, res.advance_score, res.advance_fight) == (0, 0, 0)
    _set_advance(conn, pid, ANGEL, 3, 120)
    res = handlers[(5, 2779)](
        session, reg.message_class("AngelAdvanceQueryReq")(entry=ANGEL)
    )
    assert (res.advance_level, res.advance_score) == (3, 120)
    res.SerializeToString()


def test_attempt_costs_10000_gold_2_stones(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 5)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(3, 0.99))
    res = _one(reg, handlers, session)
    assert res.state == 0
    assert (res.advance_level, res.advance_score) == (0, 3)
    assert _advance(conn, pid, ANGEL) == (0, 3)
    assert _stones(conn, pid) == 3
    assert int(_player(conn, pid)["gold"]) == 1_000_000 - 10_000
    # a real rng stays inside the row's 2..4
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    res = _one(reg, handlers, session)
    assert 3 + 2 <= res.advance_score <= 3 + 4
    assert _stones(conn, pid) == 1
    res.SerializeToString()


def test_short_gold_logs_327937_and_takes_nothing(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 5)
    conn.execute("UPDATE players SET gold = 9999 WHERE id = ?", (pid,))
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(3, 0.0))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        res = _one(reg, handlers, session)
    assert "327937" in caplog.text
    assert (res.advance_level, res.advance_score, res.state) == (0, 0, 0)
    assert _stones(conn, pid) == 5 and int(_player(conn, pid)["gold"]) == 9999


def test_short_stones_logs_327942(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 1)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(3, 0.0))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        res = _one(reg, handlers, session)
    assert "327942" in caplog.text
    assert res.state == 0 and _advance(conn, pid, ANGEL) == (0, 0)
    assert _stones(conn, pid) == 1


def test_locked_below_level_60_logs_327957(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 5)
    conn.execute("UPDATE players SET level = 59 WHERE id = ?", (pid,))
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(3, 0.0))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        _one(reg, handlers, session)
    assert "327957" in caplog.text
    assert _stones(conn, pid) == 5


def test_unowned_angel_logs_328457(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(3, 0.0))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        res = _one(reg, handlers, session, entry=999999)
    assert "328457" in caplog.text
    res.SerializeToString()


def test_success_at_max_score_450(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 2)
    _set_advance(conn, pid, ANGEL, 0, 448)
    # 448 + 2 = 450 = max_score: p = 1, so even roll 0.999 succeeds.
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(2, 0.999))
    res = _one(reg, handlers, session)
    assert res.state == 1
    assert (res.advance_level, res.advance_score) == (1, 0)
    assert _advance(conn, pid, ANGEL) == (1, 0)
    notes = _angel_notifies(reg, session)
    assert notes and notes[-1].refer == ANGEL
    assert notes[-1].flags == flags_for(["advance_level"], ANGEL_FIELDS)


def test_ladder_bracket_roll(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 4)
    _set_advance(conn, pid, ANGEL, 0, 223)
    # 223 + 2 = 225 sits in the 225:0.02 bracket: 0.03 fails, 0.01 succeeds.
    res = _one(reg, _handlers(reg, settings, conn, cfg, FixedRng(2, 0.03)), session)
    assert res.state == 0 and _advance(conn, pid, ANGEL) == (0, 225)
    res = _one(reg, _handlers(reg, settings, conn, cfg, FixedRng(2, 0.01)), session)
    assert res.state == 1 and _advance(conn, pid, ANGEL) == (1, 0)


def test_auto_until_success(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 20)
    _set_advance(conn, pid, ANGEL, 0, 440)
    # 440 -> 444 -> 448 (roll 0.5 > 0.2) -> 452 >= 450 succeeds: 3 tries.
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(4, 0.5))
    res = _auto(reg, handlers, session)
    assert res.state == 1
    assert (res.advance_level, res.advance_score) == (1, 0)
    assert _stones(conn, pid) == 20 - 3 * 2
    assert int(_player(conn, pid)["gold"]) == 1_000_000 - 3 * 10_000
    res.SerializeToString()


def test_auto_stops_on_shortfall(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 5)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(4, 0.99))
    res = _auto(reg, handlers, session)
    assert res.state == 0
    assert (res.advance_level, res.advance_score) == (0, 8)
    assert _stones(conn, pid) == 1


def test_max_refused_339175(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    grant_item(conn, pid, STONE, 500)
    _set_advance(conn, pid, ANGEL, 21, 0)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(30, 0.0))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        res = _one(reg, handlers, session)
        auto = _auto(reg, handlers, session)
    assert "339175" in caplog.text
    assert (res.advance_level, res.state) == (21, 0)
    assert (auto.advance_level, auto.state) == (21, 0)
    assert _stones(conn, pid) == 500
    assert int(_player(conn, pid)["gold"]) == 1_000_000


def test_report_query_is_empty(reg, settings, cfg, world) -> None:
    conn, pid, session = world
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    res = handlers[(5, 2785)](
        session, reg.message_class("AngelAdvanceReportQueryReq")(advance_level=1)
    )
    assert res.SerializeToString() == b""


def _inherit(reg, handlers, session, to_entry, from_entry):
    return handlers[(5, 2803)](
        session,
        reg.message_class("AngelInheritanceReq")(entry_1=to_entry, entry_2=from_entry),
    )


def test_inherit_high_to_low_only(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    _set_advance(conn, pid, ANGEL, 1, 30)
    _set_advance(conn, pid, OTHER, 3, 200)
    # low -> high is refused and changes nothing
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        _inherit(reg, handlers, session, to_entry=OTHER, from_entry=ANGEL)
    assert "338164" in caplog.text
    assert _advance(conn, pid, ANGEL) == (1, 30)
    assert _advance(conn, pid, OTHER) == (3, 200)
    assert int(_player(conn, pid)["diamond"]) == 5000
    # equal levels are refused too
    _set_advance(conn, pid, ANGEL, 3, 0)
    caplog.clear()
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        _inherit(reg, handlers, session, to_entry=ANGEL, from_entry=OTHER)
    assert "338164" in caplog.text
    assert int(_player(conn, pid)["diamond"]) == 5000
    # high -> low moves the advance and costs ANGEL_INHERITANCE_DIAMOND 1000
    _set_advance(conn, pid, ANGEL, 1, 30)
    res = _inherit(reg, handlers, session, to_entry=ANGEL, from_entry=OTHER)
    assert res.ability == 0
    res.SerializeToString()
    assert _advance(conn, pid, ANGEL) == (3, 200)
    assert _advance(conn, pid, OTHER) == (0, 0)
    assert int(_player(conn, pid)["diamond"]) == 4000
    notes = {n.refer: n for n in _angel_notifies(reg, session)}
    assert set(notes) == {ANGEL, OTHER}


def test_inherit_short_diamonds_logs_327938(reg, settings, cfg, world, caplog) -> None:
    conn, pid, session = world
    conn.execute("UPDATE players SET diamond = 999 WHERE id = ?", (pid,))
    conn.commit()
    _set_advance(conn, pid, OTHER, 3, 0)
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    with caplog.at_level("WARNING", logger="loa.angeladvance"):
        _inherit(reg, handlers, session, to_entry=ANGEL, from_entry=OTHER)
    assert "327938" in caplog.text
    assert _advance(conn, pid, ANGEL) == (0, 0)
    assert _advance(conn, pid, OTHER) == (3, 0)
    assert int(_player(conn, pid)["diamond"]) == 999
