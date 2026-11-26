"""Hero breakthrough: 5_2811 report query, 5_2813 one attempt, 5_2815 auto
(plan B2 Wave 3, task B6; O-W3-8)."""

import logging
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, grant_item
from server.modules import breakthrough
from server.modules.notify import HERO_FIELDS, IDENT_HERO, flags_for
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
HERO = 100000
STONE = breakthrough.STONE_ITEM


class FixedRng(random.Random):
    """randint always gives `score`; random() always gives `roll`."""

    def __init__(self, score: int, roll: float) -> None:
        super().__init__(0)
        self._score, self._roll = score, roll

    def randint(self, a, b):
        assert a <= self._score <= b or self._score in (a, b)
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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=0)
    conn.execute("UPDATE players SET level = 54 WHERE id = ?", (pid,))
    conn.commit()
    hero_id = grant_hero(conn, pid, HERO, 10, star=1, level=10)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, hero_id, session


def _handlers(reg, settings, conn, cfg, rng):
    return breakthrough.handlers(reg, settings, conn, cfg, rng=rng)


def _stones(conn, pid) -> int:
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, STONE)
    ).fetchone()
    return int(row["amount"]) if row else 0


def _hero(conn, hero_id):
    return conn.execute("SELECT * FROM heroes WHERE id = ?", (hero_id,)).fetchone()


def _hero_notifies(reg, session):
    cls = reg.message_class("ClientNotification")
    out = []
    for service, cmd, msg in session.outbox:
        if (service, cmd) != (5, 2008):
            continue
        if not isinstance(msg, cls):
            msg = cls.FromString(msg)
        if msg.ident == IDENT_HERO:
            out.append(msg)
    return out


def test_attempt_takes_8_stones_and_adds_4_to_8_score(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 20)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.99))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert _stones(conn, pid) == 12
    assert res.state == 0
    assert res.breakthrough_level == 0 and res.breakthrough_score == 6
    row = _hero(conn, hero_id)
    assert int(row["breakthrough_level"]) == 0 and int(row["breakthrough_score"]) == 6
    # a real rng stays inside the row's 4..8
    handlers = _handlers(reg, settings, conn, cfg, random.Random(7))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert 6 + 4 <= res.breakthrough_score <= 6 + 8
    assert _stones(conn, pid) == 4
    notes = _hero_notifies(reg, session)
    assert notes and notes[-1].refer == HERO
    want = flags_for(["ability", "breakthrough_level", "breakthrough_score"], HERO_FIELDS)
    assert notes[-1].flags & want == want      # plus every unit stat (C1)
    res.SerializeToString()


def test_success_resets_score_and_raises_level(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 8)
    # score 90 + 8 = 98 is in the 90:0.02 bracket; roll 0.01 < 0.02 succeeds.
    conn.execute("UPDATE heroes SET breakthrough_score = 90 WHERE id = ?", (hero_id,))
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(8, 0.01))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.state == 1
    assert res.breakthrough_level == 1 and res.breakthrough_score == 0
    row = _hero(conn, hero_id)
    assert int(row["breakthrough_level"]) == 1 and int(row["breakthrough_score"]) == 0
    assert _stones(conn, pid) == 0


def test_failed_roll_in_bracket_keeps_level(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 8)
    conn.execute("UPDATE heroes SET breakthrough_score = 90 WHERE id = ?", (hero_id,))
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(8, 0.02))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.state == 0 and res.breakthrough_level == 0 and res.breakthrough_score == 98


def test_score_at_max_succeeds(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 8)
    conn.execute("UPDATE heroes SET breakthrough_score = 172 WHERE id = ?", (hero_id,))
    conn.commit()
    # 172 + 8 = 180 = max_score: p = 1, even with the worst roll.
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(8, 0.999999))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.state == 1 and res.breakthrough_level == 1 and res.breakthrough_score == 0


def test_score_at_max_below_ladder_top_succeeds(reg, settings, cfg, world) -> None:
    """From level 10 max_score (12800) sits below the ladder's 15000:1."""
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 100)
    conn.execute(
        "UPDATE heroes SET breakthrough_level = 10, breakthrough_score = 12750"
        " WHERE id = ?", (hero_id,),
    )
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(50, 0.999999))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.state == 1 and res.breakthrough_level == 11


def test_short_stones_answer_unchanged_with_warning(
    reg, settings, cfg, world, caplog
) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 7)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.0))
    with caplog.at_level(logging.WARNING, logger="loa.breakthrough"):
        res = handlers[(5, 2813)](
            session, reg.message_class("HeroBreakthroughReq")(entry=HERO)
        )
    assert "327942" in caplog.text
    assert res.state == 0 and res.breakthrough_level == 0 and res.breakthrough_score == 0
    assert _stones(conn, pid) == 7


def test_below_level54_answers_unchanged(reg, settings, cfg, world, caplog) -> None:
    conn, pid, hero_id, session = world
    conn.execute("UPDATE players SET level = 53 WHERE id = ?", (pid,))
    conn.commit()
    grant_item(conn, pid, STONE, 8)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.0))
    with caplog.at_level(logging.WARNING, logger="loa.breakthrough"):
        res = handlers[(5, 2813)](
            session, reg.message_class("HeroBreakthroughReq")(entry=HERO)
        )
    assert "327957" in caplog.text
    assert res.breakthrough_score == 0 and _stones(conn, pid) == 8


def test_unknown_hero_answers_empty(reg, settings, cfg, world, caplog) -> None:
    conn, pid, hero_id, session = world
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.0))
    with caplog.at_level(logging.WARNING, logger="loa.breakthrough"):
        res = handlers[(5, 2815)](
            session, reg.message_class("HeroBreakthroughAutoReq")(entry=999999)
        )
    assert "327941" in caplog.text
    assert res.state == 0
    res.SerializeToString()


def test_auto_stops_on_success_or_shortfall(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    # Rolls always miss below max: 4 per try, 180 / 4 = 45 tries to reach max.
    grant_item(conn, pid, STONE, 8 * 50)
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(4, 0.999999))
    res = handlers[(5, 2815)](
        session, reg.message_class("HeroBreakthroughAutoReq")(entry=HERO)
    )
    assert res.state == 1 and res.breakthrough_level == 1 and res.breakthrough_score == 0
    assert _stones(conn, pid) == 8 * 5          # stopped on the success
    # Level 1 costs 12 a try; 40 stones = 3 tries, then the shortfall stops it.
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.999999))
    res = handlers[(5, 2815)](
        session, reg.message_class("HeroBreakthroughAutoReq")(entry=HERO)
    )
    assert res.state == 0 and res.breakthrough_level == 1
    assert res.breakthrough_score == 18
    assert _stones(conn, pid) == 4
    res.SerializeToString()


def test_max_level_answers_unchanged(reg, settings, cfg, world, caplog) -> None:
    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 500)
    conn.execute("UPDATE heroes SET breakthrough_level = 20 WHERE id = ?", (hero_id,))
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(150, 0.0))
    for key, req in (((5, 2813), "HeroBreakthroughReq"), ((5, 2815), "HeroBreakthroughAutoReq")):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="loa.breakthrough"):
            res = handlers[key](session, reg.message_class(req)(entry=HERO))
        assert "339174" in caplog.text
        assert res.state == 0 and res.breakthrough_level == 20
    assert _stones(conn, pid) == 500


def test_report_query_empty(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(6, 0.0))
    res = handlers[(5, 2811)](
        session, reg.message_class("HeroBreakthroughReportQueryReq")(level=1)
    )
    assert list(res.reports) == []
    res.SerializeToString()


def test_bonus_is_grow_add_of_the_level_growth(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    row = _hero(conn, hero_id)
    assert breakthrough.bonus(conn, cfg, row) == {}
    conn.execute("UPDATE heroes SET breakthrough_level = 3 WHERE id = ?", (hero_id,))
    conn.commit()
    row = _hero(conn, hero_id)
    growth = cfg.hero_growth(HERO, 1)
    out = breakthrough.bonus(conn, cfg, row)
    # level 10 = nine growth steps, grow_add 0.3 at breakthrough level 3
    assert out["max_hp"] == pytest.approx(9 * float(growth["max_hp"]) * 0.3)
    assert all(v != 0 for v in out.values())


# --- the Monday 05:00 score reset (h12024, RoleBreakthroughPanel.lua:635-637) --

# Local time, like db.day_key: Monday 30-11-2026 and the week before it.
MONDAY_0459 = datetime(2026, 11, 30, 4, 59).timestamp()
MONDAY_0500 = datetime(2026, 11, 30, 5, 0).timestamp()
LAST_WEEK = datetime(2026, 11, 26, 12, 0).timestamp()      # Thursday


def _scored_last_week(reg, settings, conn, cfg, pid, hero_id, session):
    """Level 3, score 40, written on Thursday 26-11-2026 (an attempt then
    stamps that week); no stones, so the later attempts only read."""
    clock = {"now": LAST_WEEK}
    handlers = breakthrough.handlers(
        reg, settings, conn, cfg, rng=FixedRng(6, 0.99), clock=lambda: clock["now"]
    )
    handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    conn.execute(
        "UPDATE heroes SET breakthrough_level = 3, breakthrough_score = 40 WHERE id = ?",
        (hero_id,),
    )
    conn.commit()
    return handlers, clock


def test_score_from_last_week_is_zero_after_monday_0500(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    handlers, clock = _scored_last_week(reg, settings, conn, cfg, pid, hero_id, session)
    clock["now"] = MONDAY_0500
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert (res.breakthrough_level, res.breakthrough_score) == (3, 0)
    row = _hero(conn, hero_id)
    assert (int(row["breakthrough_level"]), int(row["breakthrough_score"])) == (3, 0)


def test_score_kept_on_monday_0459(reg, settings, cfg, world) -> None:
    conn, pid, hero_id, session = world
    handlers, clock = _scored_last_week(reg, settings, conn, cfg, pid, hero_id, session)
    clock["now"] = MONDAY_0459
    res = handlers[(5, 2815)](session, reg.message_class("HeroBreakthroughAutoReq")(entry=HERO))
    assert (res.breakthrough_level, res.breakthrough_score) == (3, 40)


def test_reset_clears_every_hero_once_per_week(reg, settings, cfg, world) -> None:
    """RoleData:clearAllHerosBreakScore clears every hero (RoleData.lua:
    2509-2520); a score earned after the reset survives the same week."""
    conn, pid, hero_id, session = world
    other = grant_hero(conn, pid, 101000, 10, star=1, level=10)
    handlers, clock = _scored_last_week(reg, settings, conn, cfg, pid, hero_id, session)
    conn.execute("UPDATE heroes SET breakthrough_score = 25 WHERE id = ?", (other,))
    conn.commit()
    clock["now"] = MONDAY_0500
    handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert int(_hero(conn, other)["breakthrough_score"]) == 0
    conn.execute("UPDATE heroes SET breakthrough_score = 7 WHERE id = ?", (hero_id,))
    conn.commit()
    clock["now"] = MONDAY_0500 + 3 * 86400
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.breakthrough_score == 7


def test_unstamped_world_keeps_its_scores(reg, settings, cfg, world) -> None:
    """A world from before the stamp (breakthrough_week '') is stamped, not
    cleared: its scores are taken as this week's."""
    conn, pid, hero_id, session = world
    conn.execute("UPDATE heroes SET breakthrough_score = 40 WHERE id = ?", (hero_id,))
    conn.commit()
    handlers = breakthrough.handlers(
        reg, settings, conn, cfg, rng=FixedRng(6, 0.99), clock=lambda: MONDAY_0500
    )
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.breakthrough_score == 40


def test_attempt_pushes_the_full_hero_stats(reg, settings, cfg, world) -> None:
    """C1: a new breakthrough level changes the unit (bonus), so the notify
    carries every unit stat next to the level, score and ability."""
    from server.modules import hero

    conn, pid, hero_id, session = world
    grant_item(conn, pid, STONE, 20)
    # score max_score - 8, then 8: p = 1 (test_score_at_max_succeeds).
    top = int(cfg.hero_breakthrough(2)["max_score"])
    conn.execute(
        "UPDATE heroes SET breakthrough_level = 2, breakthrough_score = ? WHERE id = ?",
        (top - 8, hero_id),
    )
    conn.commit()
    handlers = _handlers(reg, settings, conn, cfg, FixedRng(8, 0.999999))
    res = handlers[(5, 2813)](session, reg.message_class("HeroBreakthroughReq")(entry=HERO))
    assert res.state == 1
    [note] = _hero_notifies(reg, session)
    names = [n for i, n in enumerate(HERO_FIELDS) if note.flags >> i & 1]
    fields = dict(zip(names, note.data))
    row = _hero(conn, hero_id)
    built = hero.build_client_hero_with_runes(reg, cfg, row, hero.runes_of(conn, row), conn=conn)
    for name in hero.STAT_NAMES:
        assert fields[name] == pytest.approx(getattr(built.unit, name)), name
    assert fields["breakthrough_level"] == 3 and fields["breakthrough_score"] == 0
    assert fields["ability"] == built.ability
    assert fields["max_hp"] > built.base_unit.max_hp
