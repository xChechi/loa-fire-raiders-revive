"""5_2103 HeroSkillUpReq: one skill level, or every level up to a target.

Hero 100000 (the rose knight) at quality 10 has only skill0 = 1000000
(npc_info 100000); quality 20 (prototype 100010) adds skill1 = 1001000.
spell_info 1000000 -> 1000001 -> 1000002 cost the NEXT row's upgrade_cost,
1000 and 1500 (RoleSkillRender.lua:164,284). spell_level_up caps skill0 at
level 2 for hero levels 3-4 and at 3 for level 5 (RoleSkillRender.lua:236-263).
The skill tab opens at function(10050).unlock_level = 5 (RoleUI.lua:353).
"""

from collections import defaultdict
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, heroes_of, set_hero_items
from server.modules import hero, notify, team
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
Q10_SLOTS = [10000, 11010, 11120, 11040, 11020, 11170]


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=0)
    conn.execute("UPDATE players SET level = 5 WHERE id = ?", (pid,))
    conn.commit()
    handlers = hero.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0])


def _row(conn, pid):
    return heroes_of(conn, pid)[0]


def _decode(msg, order) -> dict:
    out, values = {}, iter(msg.data)
    for i, name in enumerate(order):
        if msg.flags & (1 << i):
            out[name] = next(values)
    return out


def _skill_up(reg, handlers, session, hero_entry=100000, index=0, spell_entry=None):
    req = reg.message_class("HeroSkillUpReq")(hero=hero_entry, index=index)
    if spell_entry is not None:
        req.spell_entry = spell_entry
    res = handlers[(5, 2103)](session, req)
    res.SerializeToString()
    return res


def test_knight_skill0_to_level2_at_hero_level3_costs_1000_gold(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=3)
    res = _skill_up(reg, handlers, session)
    assert res.status == 0
    assert _gold(conn, pid) == 100000 - 1000
    assert int(_row(conn, pid)["spell0_lv"]) == 2
    assert list(hero.build_client_hero(reg, cfg, _row(conn, pid)).spells) == [1000001]


def test_skill_up_past_hero_level_cap_refused_328962_writes_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 10, level=3)
    conn.execute("UPDATE heroes SET spell0_lv = 2 WHERE id = ?", (hid,))
    conn.commit()
    res = _skill_up(reg, handlers, session)
    assert res.status == 328962                     # 已经是当前最高等级
    assert res.index == 0
    assert _gold(conn, pid) == 100000
    assert int(_row(conn, pid)["spell0_lv"]) == 2
    assert session.outbox == []


def test_skill_up_below_player_level5_refused_327957(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET level = 4 WHERE id = ?", (pid,))
    conn.commit()
    grant_hero(conn, pid, 100000, 10, level=3)
    res = _skill_up(reg, handlers, session)
    assert res.status == 327957                     # 未满足此玩法的等级
    assert _gold(conn, pid) == 100000
    assert int(_row(conn, pid)["spell0_lv"]) == 1


def test_locked_skill_slot_refused_328963(reg, world) -> None:
    """Quality 10's prototype has no skill1 (RoleSkillRender.lua:312-321);
    index 4 is the awaken skill (W3)."""
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=5)
    assert _skill_up(reg, handlers, session, index=1).status == 328963   # 此技能未激活
    assert _skill_up(reg, handlers, session, index=4).status == 328963
    assert _gold(conn, pid) == 100000


def test_skill_up_unknown_hero_refused_327941(reg, world) -> None:
    conn, pid, handlers, session = world
    assert _skill_up(reg, handlers, session).status == 327941           # 英雄不存在


def test_skill_up_all_to_target_charges_the_sum_and_echoes_spell_entry(
    reg, world
) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=5)
    res = _skill_up(reg, handlers, session, spell_entry=1000002)
    assert res.status == 0
    assert (res.index, res.spell_entry) == (0, 1000002)
    assert _gold(conn, pid) == 100000 - 1000 - 1500
    assert int(_row(conn, pid)["spell0_lv"]) == 3


def test_skill_up_target_off_the_chain_refused_327681(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=5)
    res = _skill_up(reg, handlers, session, spell_entry=1001001)
    assert res.status == 327681                     # 系统内部错误
    assert _gold(conn, pid) == 100000
    assert int(_row(conn, pid)["spell0_lv"]) == 1


def test_skill_up_without_gold_refused_327937(reg, world) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET gold = 999 WHERE id = ?", (pid,))
    conn.commit()
    grant_hero(conn, pid, 100000, 10, level=3)
    res = _skill_up(reg, handlers, session)
    assert res.status == 327937                     # 金币不足
    assert _gold(conn, pid) == 999
    assert int(_row(conn, pid)["spell0_lv"]) == 1


def test_single_skill_up_res_has_spell_entry_0_and_one_hero_notify_spell0(
    reg, world
) -> None:
    """With spell_entry 0 the client keeps the old id and waits for the
    ident-2 spell0 (RoleUICtr.lua:427-442, ClientHero.lua:335-350)."""
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=3)
    res = _skill_up(reg, handlers, session)
    assert (res.status, res.index, res.spell_entry) == (0, 0, 0)
    notes = [m for (_s, c, m) in session.outbox if c == 2008]
    assert [m.ident for m in notes] == [1, 2]
    assert _decode(notes[0], notify.PLAYER_FIELDS) == {"gold": 100000 - 1000}
    assert notes[1].refer == 100000
    assert _decode(notes[1], notify.HERO_FIELDS) == {"spell0": 1000001}


def test_levelled_skill0_survives_quality_up(reg, cfg, world) -> None:
    """O-W2-6: levels are stored, the id is resolved from the new prototype."""
    conn, pid, handlers, session = world
    hid = grant_hero(conn, pid, 100000, 10, level=2)
    conn.execute("UPDATE heroes SET spell0_lv = 2 WHERE id = ?", (hid,))
    conn.commit()
    set_hero_items(conn, hid, Q10_SLOTS)
    res = handlers[(5, 2109)](
        session, reg.message_class("HeroQualityUpReq")(hero=100000)
    )
    assert res.status == 0
    built = hero.build_client_hero(reg, cfg, _row(conn, pid), conn=conn)
    assert built.quality == 20
    assert list(built.spells) == [1000001, 1001000]
    fields = _decode(
        [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 2][0],
        notify.HERO_FIELDS,
    )
    assert (fields["spell0"], fields["spell1"]) == (1000001, 1001000)


def test_fight_unit_carries_the_levelled_spell(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_hero(conn, pid, 100000, 10, level=5)
    _skill_up(reg, handlers, session, spell_entry=1000002)
    unit = team.build_fight_unit(reg, cfg, _row(conn, pid), 1)
    assert list(unit.spells) == [1000002]


def test_every_hero_keeps_its_skill_bases_across_qualities(cfg) -> None:
    """O-W2-6's premise: per hero and slot, every quality's prototype names
    the same level-1 base (or 0 while the slot is locked)."""
    heroes = {
        int(r["hero"]) for r in cfg.conn("hero_quality").execute(
            "SELECT hero FROM hero_quality"
        )
    }
    assert heroes
    for entry in heroes:
        bases: dict[int, set[int]] = defaultdict(set)
        for quality in cfg.hero_qualities(entry):
            npc_row = cfg.npc(int(quality["prototype"]))
            for i in range(4):
                spell = int(npc_row[f"skill{i}"] or 0)
                if spell:
                    bases[i].add(spell)
                    assert int(cfg.spell(spell)["level"]) == 1, (entry, i, spell)
        assert all(len(s) == 1 for s in bases.values()), (entry, dict(bases))


def test_spell_at_level_walks_next_and_raises_past_the_end(cfg) -> None:
    assert hero.spell_at_level(cfg, 1000000, 1) == 1000000
    assert hero.spell_at_level(cfg, 1000000, 3) == 1000002
    with pytest.raises(KeyError):
        hero.spell_at_level(cfg, 1000000, 10_000)
