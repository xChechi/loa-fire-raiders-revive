"""5_2201 LevelIntoReq. Stage rows are quoted in the plan: chapter 1 is
10000, 10010, 10012, 10020, 10022, each costing 6 energy."""

import random
import sqlite3
import time
from pathlib import Path

import pytest

from server.config import Config
from server.db import (
    chapters_of,
    connect,
    create_player,
    find_player,
    set_last_level,
    upsert_level,
)
from server.modules import drops, level
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")

# A seeded rng makes the two rolls of an entry predictable: the handler draws
# the visible roll first, then the invisible one, then the 64 urandoms, so the
# same seed replayed in the same order gives the lists it used.
SEED = 7


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
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = level.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _expected_rolls(cfg, visible_drops: int, invisible_drops: int):
    """The two lists the handler rolls for a stage, in its own order."""
    rng = random.Random(SEED)
    return (
        drops.roll(cfg, visible_drops, rng=rng),
        drops.roll(cfg, invisible_drops, rng=rng),
    )


def test_the_frontier_of_a_fresh_player_is_stage_one_one(cfg, world) -> None:
    conn, pid, _h, _s = world
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10000


def test_the_frontier_follows_last_level(cfg, world) -> None:
    conn, pid, _h, _s = world
    set_last_level(conn, pid, 10000)
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10010


def test_urandom_is_64_values_under_10000(world, reg) -> None:
    """Review Focus 4: BattleAlthm.NewAlgorithm refuses any other length and
    Random() divides by SCALE 10000."""
    values = level.roll_urandom(random.Random(0))
    assert len(values) == 64
    assert all(0 <= v < 10000 for v in values)
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert len(res.urandom) == 64
    assert all(0 <= v < 10000 for v in res.urandom)


def test_entering_stage_one_one_spends_six_energy_and_pre_rolls_the_drops(
    reg, cfg, settings, world
) -> None:
    conn, pid, _h, session = world
    handlers = level.handlers(reg, settings, conn, cfg, rng=random.Random(SEED))
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    visible, invisible = _expected_rolls(cfg, 10000, 10005)
    assert res.flag == 0
    assert int(find_player(conn, "stefan")["energy"]) == 54
    # visible_drops 10000 is certain: 粗布头巾 x2
    assert (20, 10000, 2) in drops.as_triples(visible)
    # Only the visible roll goes out on entry: msg.drop becomes FightData.drops,
    # the items that visibly fall during the fight (FightData.lua:33). The full
    # list reaches the end screen from LevelOutRes.drop.
    assert [(d.category, d.refer, d.amount) for d in res.drop] == drops.as_triples(
        visible
    )
    assert drops.as_triples(session.data[level.PENDING_KEY][10000]) == drops.as_triples(
        visible + invisible
    )
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008)]
    res.SerializeToString()


def test_the_pending_entry_holds_the_visible_and_the_invisible_roll(
    reg, cfg, settings, world
) -> None:
    """The invisible roll is withheld from LevelIntoRes but still owed to the
    player, so it has to be in the pending entry Task 14's level_out grants."""
    conn, pid, _h, session = world
    handlers = level.handlers(reg, settings, conn, cfg, rng=random.Random(SEED))
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    visible, invisible = _expected_rolls(cfg, 10000, 10005)
    assert invisible, "stage 10000 has an invisible roll to withhold at this seed"
    pending = session.data[level.PENDING_KEY][10000]
    assert len(pending) == len(visible) + len(invisible)
    assert len(res.drop) == len(visible)


def test_a_locked_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10022))
    assert res.flag == 1
    assert int(find_player(conn, "stefan")["energy"]) == 60      # nothing spent
    assert level.PENDING_KEY not in session.data or not session.data[level.PENDING_KEY]


def test_an_unknown_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=999999))
    assert res.flag == 1


def test_a_cleared_stage_can_be_replayed_when_once_is_zero(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    set_last_level(conn, pid, 10000)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0                                   # stage_info.once is 0


def test_a_cleared_once_stage_is_refused_with_flag_one_and_its_star(
    reg, cfg, world
) -> None:
    """stage 10010 has once = 1 (open question C in the plan)."""
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10010, star=2, count_delta=1)
    set_last_level(conn, pid, 10010)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10010))
    assert res.flag == 1
    assert res.star == 2


def test_too_little_energy_is_refused_and_logged_with_the_real_code(
    reg, cfg, world, caplog
) -> None:
    conn, pid, handlers, session = world
    # energy_at in 2038 parks the regeneration clock in the future, so
    # refresh_energy adds nothing and the player really has 2 energy.
    conn.execute("UPDATE players SET energy = 2, energy_at = ? WHERE id = ?",
                 (2 ** 31, pid))
    conn.commit()
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 1
    assert "327939" in caplog.text
    assert int(find_player(conn, "stefan")["energy"]) == 2


def test_a_refusal_writes_nothing_at_all(reg, cfg, world) -> None:
    """Every refusal path leaves the db and the session untouched: no energy
    spent, no pending entry, no notification queued."""
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET energy = 2, energy_at = ? WHERE id = ?",
                 (2 ** 31, pid))
    conn.commit()
    for entry in (10022, 999999, 10000):        # locked, unknown, no energy
        res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=entry))
        assert res.flag == 1
        assert list(res.drop) == []
        assert list(res.urandom) == []
    assert int(find_player(conn, "stefan")["energy"]) == 2
    assert session.data.get(level.PENDING_KEY, {}) == {}
    assert session.outbox == []


def _fight(handlers, session, reg, lvl, star, heroes=(100000,)):
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=lvl))
    req = reg.message_class("LevelOutReq")(level=lvl, star=star, angel=0)
    for entry in heroes:
        req.heroes.append(entry)
    return handlers[(5, 2203)](session, req)


def test_a_cleared_stage_pays_xp_gold_drops_and_unlocks_the_next(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    from server.db import grant_hero, items_of
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    res = _fight(handlers, session, reg, 10000, star=3)
    assert res.status == 0
    assert res.star == 3
    row = find_player(conn, "stefan")
    # stage 10000: player_xp 6, gold 516, energy 6 spent
    assert int(row["gold"]) == 1280000 + 516
    assert int(row["last_level"]) == 10000
    assert int(row["energy"]) == 54
    prog = conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = 10000", (pid,)
    ).fetchone()
    assert (int(prog["star"]), int(prog["count"])) == (3, 1)
    assert {int(i["entry"]) for i in items_of(conn, pid)} >= {10000}
    assert res.owner.level >= 1
    assert [h.refer for h in res.heroes] == [100000]
    res.SerializeToString()


def test_level_out_twice_grants_once(reg, cfg, world) -> None:
    """Review Focus 1: requestServerInfo retries the same 5_2203 after 6 s."""
    conn, pid, handlers, session = world
    from server.db import grant_hero, items_of
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    first = _fight(handlers, session, reg, 10000, star=3)
    after_first = find_player(conn, "stefan")
    gold_after_first = int(after_first["gold"])
    items_after_first = {int(i["entry"]): int(i["amount"]) for i in items_of(conn, pid)}
    xp_after_first = (int(after_first["level"]), int(after_first["xp"]))
    hero_after_first = conn.execute(
        "SELECT level, xp FROM heroes WHERE player_id = ? AND entry = 100000"
        " ORDER BY id", (pid,)
    ).fetchone()
    again = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)
    again.heroes.append(100000)
    second = handlers[(5, 2203)](session, again)
    assert first.status == 0
    assert second.status == 328196                  # language.db 没有进入关卡
    after_second = find_player(conn, "stefan")
    assert int(after_second["gold"]) == gold_after_first
    assert {int(i["entry"]): int(i["amount"]) for i in items_of(conn, pid)} == (
        items_after_first
    )
    assert (int(after_second["level"]), int(after_second["xp"])) == xp_after_first
    hero_after_second = conn.execute(
        "SELECT level, xp FROM heroes WHERE player_id = ? AND entry = 100000"
        " ORDER BY id", (pid,)
    ).fetchone()
    assert (int(hero_after_second["level"]), int(hero_after_second["xp"])) == (
        int(hero_after_first["level"]), int(hero_after_first["xp"])
    )
    assert list(second.drop) == []


def test_a_loss_keeps_the_stage_locked_and_pays_nothing(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = _fight(handlers, session, reg, 10000, star=0)
    assert res.status == 0
    row = find_player(conn, "stefan")
    assert int(row["last_level"]) == 0
    assert int(row["gold"]) == 1280000
    prog = conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = 10000", (pid,)
    ).fetchone()
    assert int(prog["star"]) == 0
    assert int(prog["count"]) == 1


def test_player_xp_levels_up_and_notifies(reg, cfg, world) -> None:
    """xp_for_level lvl 1 needs 12 player xp; stage 10000 pays 6 per clear."""
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, 10000, star=3)
    session.outbox.clear()
    _fight(handlers, session, reg, 10000, star=3)
    row = find_player(conn, "stefan")
    assert int(row["level"]) == 2
    assert int(row["max_energy"]) == 62
    # The level-up hands out xp_for_level(2).levelup_recovery_energy, read here
    # rather than hardcoded. Two 6-energy entries took 60 -> 54 -> 48, and the
    # payout is capped at the new max_energy.
    recovery = int(cfg.xp_for_level(2)["levelup_recovery_energy"])
    assert int(row["energy"]) == min(62, 48 + recovery)
    assert (5, 2036) in [(s, c) for (s, c, _m) in session.outbox]


def test_a_level_out_for_the_wrong_stage_is_refused(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    req = reg.message_class("LevelOutReq")(level=10012, star=3, angel=0)
    assert handlers[(5, 2203)](session, req).status == 328196


def test_a_poisoned_drop_rolls_everything_back_and_keeps_the_pending_entry(
    reg, cfg, world
) -> None:
    """Task 11 ordering lesson: grant_prizes validates the whole prize list
    before it writes, so a bad prize must leave the handler's own writes
    undone and the pending entry re-usable."""
    conn, pid, handlers, session = world
    from server.modules.drops import Drop
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    session.data[level.PENDING_KEY][10000] = [Drop(category=40, refer=1, amount=1)]
    req = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)

    with pytest.raises(ValueError):
        handlers[(5, 2203)](session, req)

    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000          # grant never applied
    assert int(row["level"]) == 1
    assert int(row["xp"]) == 0
    assert int(row["last_level"]) == 0
    assert conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = 10000", (pid,)
    ).fetchone() is None
    assert session.data[level.PENDING_KEY][10000]


def test_a_write_that_fails_after_the_payout_is_logged_with_the_facts_and_reraised(
    reg, cfg, world, caplog, monkeypatch
) -> None:
    """The pending entry is popped before grant_prizes runs, so a DB error in
    the bookkeeping that follows leaves the stage paid and unrecorded, and the
    retry refused with 328196. Restoring the pending entry would re-pay the
    drops and a transaction is Plan B2, so the only honest answer is an ERROR
    naming the facts and the exception going up."""
    conn, pid, handlers, session = world
    from server.db import grant_hero
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr("server.modules.level.db.upsert_level", boom)
    with caplog.at_level("ERROR"):
        with pytest.raises(sqlite3.OperationalError):
            _fight(handlers, session, reg, 10000, star=3)

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors, "the lost write must be logged"
    text = errors[0].getMessage()
    assert "10000" in text and str(pid) in text          # the stage and the player
    assert errors[0].exc_info is not None                # the traceback is kept
    # The payout did happen: stage 10000 pays 516 gold on top of the start.
    assert int(find_player(conn, "stefan")["gold"]) == 1280000 + 516
    # ... and the pending entry is gone, so the client's retry is refused.
    assert 10000 not in session.data.get(level.PENDING_KEY, {})


def test_refighting_an_old_stage_does_not_move_last_level_backwards(
    reg, cfg, world
) -> None:
    conn, pid, handlers, session = world
    for lvl in (10000, 10010, 10012):
        upsert_level(conn, pid, lvl, star=3, count_delta=1)
    set_last_level(conn, pid, 10012)
    conn.execute("UPDATE players SET energy = 60 WHERE id = ?", (pid,))
    conn.commit()

    res = _fight(handlers, session, reg, 10000, star=3)
    assert res.status == 0
    assert int(find_player(conn, "stefan")["last_level"]) == 10012


def test_chapter_stars_add_up_across_the_chapter(reg, cfg, world) -> None:
    conn, pid, _h, _s = world
    upsert_level(conn, pid, 10000, star=3)
    upsert_level(conn, pid, 10010, star=2)
    assert level.chapter_stars(cfg, conn, pid, 10000) == 5


def test_the_chest_threshold_comes_from_chapter_info(cfg) -> None:
    """Risk 7: chapter 1 has 5 stages, so 15 stars are available, and the chest
    asks for chapter_info.star_req0 of them. The handler must read this row,
    never a literal."""
    assert len(cfg.stages_in_chapter(10000)) * 3 == 15
    assert int(cfg.chapter(10000)["star_req0"]) == 9


def test_the_chapter_chest_pays_award0_once(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    for entry in (10000, 10010, 10012):
        upsert_level(conn, pid, entry, star=3)       # 9 stars, star_req0 of chapter 1
    before = int(find_player(conn, "stefan")["diamond"])
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert res.status == 0
    assert res.chapter == 10000
    row = find_player(conn, "stefan")
    assert int(row["diamond"]) == before + 600
    assert int(row["gold"]) == 1280000 + 60000
    assert [(int(c["chapter"]), int(c["award"])) for c in chapters_of(conn, pid)] == [
        (10000, 1)
    ]

    again = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert again.status == 328194                   # language.db 关卡不可重复刷
    assert int(find_player(conn, "stefan")["diamond"]) == before + 600
    assert int(find_player(conn, "stefan")["gold"]) == 1280000 + 60000
    res.SerializeToString()
    again.SerializeToString()


def test_too_few_stars_is_refused(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10000, star=1)
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert res.status == 328197                     # language.db 星级不够
    assert res.chapter == 10000
    row = find_player(conn, "stefan")
    assert (int(row["gold"]), int(row["diamond"])) == (1280000, 18888)
    assert chapters_of(conn, pid) == []
    assert session.outbox == []
    res.SerializeToString()


def test_an_unknown_chapter_is_refused(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=424242, prize=0)
    )
    assert res.status != 0


def test_a_poisoned_chapter_award_claims_nothing(
    reg, cfg, world, monkeypatch
) -> None:
    """Task 11 ordering lesson: grant_prizes vets the whole prize list before it
    writes, so it has to run before the irreversible set_chapter_award. If the
    award cannot be paid, the chest stays unclaimed and can be retried."""
    conn, pid, handlers, session = world
    for entry in (10000, 10010, 10012):
        upsert_level(conn, pid, entry, star=3)
    monkeypatch.setattr(
        drops, "roll", lambda *a, **k: [drops.Drop(category=40, refer=1, amount=1)]
    )
    with pytest.raises(ValueError):
        handlers[(5, 2209)](
            session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
        )
    assert chapters_of(conn, pid) == []
    row = find_player(conn, "stefan")
    assert (int(row["gold"]), int(row["diamond"])) == (1280000, 18888)


def test_sweep_and_reset_refuse_in_the_client_own_language(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    clean = handlers[(5, 2205)](
        session, reg.message_class("LevelCleanReq")(level=10000, times=1)
    )
    assert clean.flag == 1                          # not 3-starred (B7)
    assert len(clean.drops) == 0 and len(clean.reward) == 0
    clean.SerializeToString()
    reset = handlers[(5, 2207)](
        session, reg.message_class("LevelResetReq")(level=10000)
    )
    assert reset.status == 328202                   # language.db 达到关卡重置限制
    assert reset.reset_count == 0
    reset.SerializeToString()
    # Neither refusal writes anything or notifies anyone.
    row = find_player(conn, "stefan")
    assert (int(row["gold"]), int(row["diamond"]), int(row["energy"])) == (
        1280000, 18888, 60
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM levels WHERE player_id = ?", (pid,)
    ).fetchone()[0] == 0
    assert chapters_of(conn, pid) == []
    assert session.outbox == []


def test_a_fight_with_the_support_hero_pays_xp_to_the_owned_heroes_only(
    reg, cfg, world
) -> None:
    """req.heroes may now carry 1103009.

    The newbie fights get the stock support hero in the attacker team
    (variables.NEW_FIGHT_HELP_HERO, Task 19), and BattleEndLayer reports every
    unit that fought. db.add_hero_xp skips an entry the player does not own, so
    the npc costs nothing and raises nothing.
    """
    conn, pid, handlers, session = world
    from server.db import grant_hero
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    res = _fight(handlers, session, reg, 10000, star=3, heroes=(100000, 1103009))

    assert res.status == 0
    assert [h.refer for h in res.heroes] == [100000]
    assert conn.execute(
        "SELECT COUNT(*) FROM heroes WHERE player_id = ? AND entry = 1103009", (pid,)
    ).fetchone()[0] == 0
    res.SerializeToString()


# --- Wave 1 T4b: the stage result updates the client's heroes ----------------
# BattleFactoryLevel:toExpInfo only feeds the end screen, so without an ident-2
# notify ClientHero.level stays 1 until relaunch and item 10000
# (required_level 2) cannot be equipped (plan settled point 2a).
def _hero_notifies(session):
    return [m for (s, c, m) in session.outbox if (s, c) == (5, 2008) and m.ident == 2]


def test_level_out_pushes_hero_notify_for_each_hero_that_gained_xp(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    from server.db import grant_hero
    for entry in (100000, 101000, 102000):
        grant_hero(conn, pid, entry, 10, star=1, level=1)
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    session.outbox.clear()
    req = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)
    # 1103009 is the support hero: not owned, so it gains nothing and gets no notify.
    req.heroes.extend([100000, 101000, 102000, 1103009])
    handlers[(5, 2203)](session, req)
    notes = _hero_notifies(session)
    assert sorted(m.refer for m in notes) == [100000, 101000, 102000]
    for m in notes:
        m.SerializeToString()


def test_level_out_hero_notify_carries_new_level_2(reg, cfg, world) -> None:
    """Stage 10000 pays unit_xp 20 and xp_for_level(1).hero_xp_for_next_level
    is 20, so three level-1 heroes reach level 2 with 0 xp left."""
    from server.modules.notify import HERO_FIELDS

    conn, pid, handlers, session = world
    from server.db import grant_hero
    for entry in (100000, 101000, 102000):
        grant_hero(conn, pid, entry, 10, star=1, level=1)
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    session.outbox.clear()
    req = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)
    req.heroes.extend([100000, 101000, 102000])
    handlers[(5, 2203)](session, req)
    notes = _hero_notifies(session)
    assert len(notes) == 3
    for m in notes:
        assert m.flags & (1 << HERO_FIELDS.index("level"))
        assert m.flags & (1 << HERO_FIELDS.index("xp"))
        assert m.flags & (1 << HERO_FIELDS.index("item0"))
        names = [n for i, n in enumerate(HERO_FIELDS) if m.flags & (1 << i)]
        values = dict(zip(names, m.data))
        assert values["level"] == 2.0
        assert values["xp"] == 0.0
        assert values["max_level"] == 2.0
    # The notifies follow the stage's own player/item pushes, after the Res.
    idents = [m.ident for (s, c, m) in session.outbox if (s, c) == (5, 2008)]
    assert idents[-3:] == [2, 2, 2]


def test_lost_fight_pushes_no_hero_notify(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    from server.db import grant_hero
    grant_hero(conn, pid, 100000, 10, star=1, level=1)
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    session.outbox.clear()
    req = reg.message_class("LevelOutReq")(level=10000, star=0, angel=0)
    req.heroes.append(100000)
    handlers[(5, 2203)](session, req)
    assert _hero_notifies(session) == []


# --- Wave 1 B7: sweep, reset and the daily stage counts ----------------------
# Stage 10000 (chapter 1): energy 6, gold 516, player_xp 6, maxcount 0.
# Stage 110000 (first elite stage): energy 12, maxcount 3.
FUTURE = 2 ** 31            # a deadline that has not passed yet
ELITE = 110000


def _sweep(handlers, session, reg, lvl, times):
    return handlers[(5, 2205)](
        session, reg.message_class("LevelCleanReq")(level=lvl, times=times)
    )


def _set_progress(conn, pid, lvl, star, count=0, reset_count=0, deadline=FUTURE):
    conn.execute(
        "INSERT INTO levels (player_id, level, star, count, reset_count, deadline)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (pid, lvl, star, count, reset_count, deadline),
    )
    conn.commit()


def _progress(conn, pid, lvl):
    return conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = ?", (pid, lvl)
    ).fetchone()


def test_sweep_needs_three_stars(reg, cfg, world) -> None:
    """LevelCleanRes has no status field (B1 settled point 13), so the refusal
    is flag 1, which DesSweepPanel:onReceiveSweepData answers by resyncing the
    count from `times`. Nothing is spent."""
    conn, pid, handlers, session = world
    _set_progress(conn, pid, 10000, star=2, count=1)
    res = _sweep(handlers, session, reg, 10000, 1)
    assert res.flag == 1
    assert res.times == 1
    assert list(res.drops) == []
    row = find_player(conn, "stefan")
    assert (int(row["energy"]), int(row["gold"])) == (60, 1280000)
    assert int(_progress(conn, pid, 10000)["count"]) == 1
    assert session.outbox == []
    res.SerializeToString()


def test_sweep_two_times_spends_energy_and_returns_two_drop_entries(
    reg, cfg, world
) -> None:
    conn, pid, handlers, session = world
    _set_progress(conn, pid, 10000, star=3)
    res = _sweep(handlers, session, reg, 10000, 2)
    assert res.flag == 0
    assert len(res.drops) == 2
    assert list(res.reward) == []
    assert res.times == 2                            # the new count
    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000 + 2 * 516
    # 2 x player_xp 6 = 12 = xp_for_level(1).player_xp_for_next_level
    assert int(row["level"]) == 2
    # 2 x 6 energy spent, then the level-up hands out
    # xp_for_level(2).levelup_recovery_energy, capped at the new max_energy.
    recovery = int(cfg.xp_for_level(2)["levelup_recovery_energy"])
    assert int(row["energy"]) == min(62, 60 - 2 * 6 + recovery)
    assert int(_progress(conn, pid, 10000)["count"]) == 2
    rolled = [(d.category, d.refer, d.amount) for e in res.drops for d in e.drop]
    assert rolled, "visible_drops 10000 is certain"
    sent = [(s, c) for (s, c, _m) in session.outbox]
    assert (5, 2008) in sent and (5, 2036) in sent
    idents = [m.ident for (s, c, m) in session.outbox if (s, c) == (5, 2008)]
    assert 1 in idents and 4 in idents
    res.SerializeToString()


def test_sweep_past_maxcount_flag_1(reg, cfg, world) -> None:
    """The plan says flag 2; the client's sweep listener only knows flag 1
    (DesSweepPanel.lua:713-727: resync count from `times`, float z00225), so
    flag 1 with the server's count is what the client can act on."""
    conn, pid, handlers, session = world
    _set_progress(conn, pid, ELITE, star=3, count=2)
    res = _sweep(handlers, session, reg, ELITE, 2)
    assert res.flag == 1
    assert res.times == 2
    assert int(find_player(conn, "stefan")["energy"]) == 60
    assert int(_progress(conn, pid, ELITE)["count"]) == 2
    assert session.outbox == []


def test_sweep_without_the_energy_is_refused(reg, cfg, world, caplog) -> None:
    conn, pid, handlers, session = world
    _set_progress(conn, pid, 10000, star=3)
    conn.execute("UPDATE players SET energy = 11, energy_at = ? WHERE id = ?",
                 (FUTURE, pid))
    conn.commit()
    res = _sweep(handlers, session, reg, 10000, 2)  # needs 12
    assert res.flag == 1
    assert "327939" in caplog.text
    assert int(find_player(conn, "stefan")["energy"]) == 11
    assert session.outbox == []


def test_reset_vip0_refused_328202(reg, cfg, world) -> None:
    """vip_info 10100 (重置精英关卡次数) is 0 at VIP 0."""
    conn, pid, handlers, session = world
    _set_progress(conn, pid, ELITE, star=3, count=3)
    res = handlers[(5, 2207)](session, reg.message_class("LevelResetReq")(level=ELITE))
    assert res.status == 328202
    assert int(find_player(conn, "stefan")["diamond"]) == 18888
    assert int(_progress(conn, pid, ELITE)["count"]) == 3
    assert session.outbox == []
    res.SerializeToString()


def test_reset_at_vip10_pays_the_first_tier_and_zeroes_the_count(
    reg, cfg, world
) -> None:
    """LEVEL_RESET_COST 200|1,400|1,...: the first reset of the day costs 200
    diamonds (MMTools:getCostNum with times = reset_count 0)."""
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET vip = 10 WHERE id = ?", (pid,))
    conn.commit()
    _set_progress(conn, pid, ELITE, star=3, count=3)
    res = handlers[(5, 2207)](session, reg.message_class("LevelResetReq")(level=ELITE))
    assert res.status == 0
    assert res.reset_count == 1
    assert int(find_player(conn, "stefan")["diamond"]) == 18888 - 200
    prog = _progress(conn, pid, ELITE)
    assert (int(prog["count"]), int(prog["reset_count"])) == (0, 1)
    # vip_info 10100 is 1 at VIP 10, so the second reset is refused.
    again = handlers[(5, 2207)](
        session, reg.message_class("LevelResetReq")(level=ELITE)
    )
    assert again.status == 328202
    assert int(find_player(conn, "stefan")["diamond"]) == 18888 - 200


def test_reset_without_the_diamonds_is_refused_327938(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET vip = 10, diamond = 199 WHERE id = ?", (pid,))
    conn.commit()
    _set_progress(conn, pid, ELITE, star=3, count=3)
    res = handlers[(5, 2207)](session, reg.message_class("LevelResetReq")(level=ELITE))
    assert res.status == 327938                     # language.db 钻石不足
    assert int(_progress(conn, pid, ELITE)["count"]) == 3


def test_counts_reset_after_deadline(reg, cfg, world) -> None:
    """A row whose deadline has passed starts the day at count 0 and
    reset_count 0, with the deadline moved to the end of today."""
    conn, pid, handlers, session = world
    _set_progress(conn, pid, ELITE, star=3, count=3, reset_count=1, deadline=1)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=ELITE))
    assert res.flag == 0                             # maxcount 3 no longer reached
    prog = _progress(conn, pid, ELITE)
    assert (int(prog["count"]), int(prog["reset_count"])) == (0, 0)
    assert int(prog["deadline"]) > int(time.time())


def test_a_fresh_stage_row_carries_today_deadline(reg, cfg, world) -> None:
    """The first play of a stage writes a row whose deadline is the end of
    today, so the next read does not mistake it for an old day's count."""
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, 10000, star=3)
    assert int(_progress(conn, pid, 10000)["deadline"]) > int(time.time())
    _fight(handlers, session, reg, 10000, star=3)
    assert int(_progress(conn, pid, 10000)["count"]) == 2
