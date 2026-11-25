"""5_2323 UpgradeAngelSpellReq and 5_2309 UpgradeAngelAuraReq (plan B1).

Goddess 500000 at star 1 has spells 5000000/5010000 and aura 5020000; star 2
has 5001000/5011000 and auras 5020000/5021000 (angel_info 500000/500010,
max_level 40). spell_info: 5000000 L1 costs 50, 5000001 L2 100, 5000002 L3
200; 5021000 L1 50. A step costs the CURRENT row's upgrade_cost
(AngelSkillCell.lua:168-209) and the spell level stays below the angel level
(AngelSkillCell.lua:441-442)."""

import logging
from pathlib import Path

import pytest

from server.config import Config
from server.db import angels_of, connect, create_player, grant_angel, grant_item
from server.modules import angel
from server.modules.notify import ANGEL_FIELDS
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
GOLD = 1280000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=GOLD, diamond=18888)
    handlers = angel.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def _gold(conn, pid) -> int:
    return int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0])


def _row(conn, pid):
    return angels_of(conn, pid)[0]


def _set(conn, pid, **cols) -> None:
    for col, value in cols.items():
        conn.execute(f"UPDATE angels SET {col} = ? WHERE player_id = ?", (value, pid))
    conn.commit()


def _decode(msg, order) -> dict:
    out, values = {}, iter(msg.data)
    for i, name in enumerate(order):
        if msg.flags & (1 << i):
            out[name] = next(values)
    return out


def _spell_up(reg, handlers, session, spell, upgrade_spell=None, entry=500000):
    req = reg.message_class("UpgradeAngelSpellReq")(angel_entry=entry, spell=spell)
    if upgrade_spell is not None:
        req.upgrade_spell = upgrade_spell
    return handlers[(5, 2323)](session, req)


def _aura_up(reg, handlers, session, aura, upgrade_aura=None, entry=500000):
    req = reg.message_class("UpgradeAngelAuraReq")(angel_entry=entry, aura=aura)
    if upgrade_aura is not None:
        req.upgrade_aura = upgrade_aura
    return handlers[(5, 2309)](session, req)


def test_angel_spell_level1_to_2_costs_the_current_rows_50_gold(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=5, star=1)
    res = _spell_up(reg, handlers, session, 5000000)
    # AngelSkill:onUpskill looks the angel up by msg.angel.angel_entry
    # (AngelSkill.lua:96-97): a zero stub there is the run-10 LUA ERROR.
    assert res.angel.angel_entry == 500000
    assert res.angel.level == 5 and res.angel.star == 1
    assert list(res.angel.spells) == [5000001, 5010000]
    assert list(res.angel.auras) == [5020000, 0, 0, 0, 0, 0]
    assert res.upgrade_spell == 0
    assert _gold(conn, pid) == GOLD - 50
    assert int(_row(conn, pid)["spell0_lv"]) == 2
    assert int(_row(conn, pid)["spell1_lv"]) == 1
    player_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]
    assert len(player_notes) == 1
    angel_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 3]
    assert len(angel_notes) == 1
    assert angel_notes[0].refer == 500000
    assert _decode(angel_notes[0], ANGEL_FIELDS) == {"spell0": 5000001.0}


def test_angel_spell_capped_at_angel_level_answers_unchanged_angel(
    reg, world, caplog
) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=1, star=1)
    with caplog.at_level(logging.WARNING, logger="loa.angel"):
        res = _spell_up(reg, handlers, session, 5000000)
    assert res.angel.angel_entry == 500000
    assert list(res.angel.spells) == [5000000, 5010000]
    assert _gold(conn, pid) == GOLD
    assert int(_row(conn, pid)["spell0_lv"]) == 1
    assert session.outbox == []
    assert "328461" in caplog.text
    res.SerializeToString()

    # At angel_info.max_level (40) the cap is 328460, whatever the angel level.
    _set(conn, pid, level=60, spell1_lv=40)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="loa.angel"):
        res = _spell_up(reg, handlers, session, 5010039)
    assert list(res.angel.spells) == [5000000, 5010039]
    assert "328460" in caplog.text
    assert _gold(conn, pid) == GOLD and session.outbox == []


def test_angel_spell_short_gold_or_unknown_spell_answers_unchanged_angel(
    reg, world, caplog
) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=5, star=1)
    conn.execute("UPDATE players SET gold = 49 WHERE id = ?", (pid,))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="loa.angel"):
        res = _spell_up(reg, handlers, session, 5000000)
        assert list(res.angel.spells) == [5000000, 5010000]
        assert "327937" in caplog.text
        res = _spell_up(reg, handlers, session, 5000001)  # not the slot's id
        assert list(res.angel.spells) == [5000000, 5010000]
    assert _gold(conn, pid) == 49
    assert int(_row(conn, pid)["spell0_lv"]) == 1
    assert session.outbox == []


def test_angel_spell_for_an_unowned_angel_sends_nothing(reg, world, caplog) -> None:
    _conn, _pid, handlers, session = world
    with caplog.at_level(logging.WARNING, logger="loa.angel"):
        assert _spell_up(reg, handlers, session, 5000000) is None
    assert "328457" in caplog.text
    assert session.outbox == []


def test_angel_spell_batch_to_upgrade_spell(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=4, star=1)
    # AngelSkillCell:culSkillGold pays L1, L2, L3 and names the L4 row.
    res = _spell_up(reg, handlers, session, 5000000, upgrade_spell=5000003)
    assert list(res.angel.spells) == [5000003, 5010000]
    assert res.upgrade_spell == 5000003
    assert _gold(conn, pid) == GOLD - (50 + 100 + 200)
    assert int(_row(conn, pid)["spell0_lv"]) == 4
    angel_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 3]
    assert [_decode(m, ANGEL_FIELDS) for m in angel_notes] == [{"spell0": 5000003.0}]

    # A target past the angel level is refused whole: nothing is paid.
    session.outbox.clear()
    res = _spell_up(reg, handlers, session, 5010000, upgrade_spell=5010004)
    assert list(res.angel.spells) == [5000003, 5010000]
    assert _gold(conn, pid) == GOLD - 350
    assert session.outbox == []


def test_aura_upgrade_returns_index_and_new_id(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=3, star=2)
    res = _aura_up(reg, handlers, session, 5021000)
    assert res.status == 0
    assert res.angel_entry == 500000
    assert res.angel_ability == 0
    assert res.aura == 5021001
    assert res.aura_index == 1
    assert res.upgrade_aura == 0
    assert _gold(conn, pid) == GOLD - 50
    assert int(_row(conn, pid)["aura1_lv"]) == 2
    assert int(_row(conn, pid)["aura0_lv"]) == 1
    player_notes = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]
    assert len(player_notes) == 1

    res = _aura_up(reg, handlers, session, 5021001, upgrade_aura=5021002)
    assert res.status == 0 and res.aura == 5021002 and res.upgrade_aura == 5021002
    assert _gold(conn, pid) == GOLD - 50 - 100


def test_aura_at_angel_level_refused_328454(reg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=1, star=1)
    res = _aura_up(reg, handlers, session, 5020000)
    assert res.status == 328454
    assert not res.HasField("aura")
    assert _gold(conn, pid) == GOLD
    assert int(_row(conn, pid)["aura0_lv"]) == 1
    assert session.outbox == []


def test_aura_refusals_write_nothing(reg, world) -> None:
    conn, pid, handlers, session = world
    assert _aura_up(reg, handlers, session, 5020000).status == 328457
    grant_angel(conn, pid, 500000, level=60, star=1)
    # Star 1 has aura0 only: 5021000 is not one of its auras.
    assert _aura_up(reg, handlers, session, 5021000).status == 328462
    assert _aura_up(reg, handlers, session, 0).status == 328462
    _set(conn, pid, aura0_lv=40)
    assert _aura_up(reg, handlers, session, 5020039).status == 328453
    _set(conn, pid, aura0_lv=1)
    conn.execute("UPDATE players SET gold = 49 WHERE id = ?", (pid,))
    conn.commit()
    assert _aura_up(reg, handlers, session, 5020000).status == 327937
    assert int(_row(conn, pid)["aura0_lv"]) == 1
    assert _gold(conn, pid) == 49
    assert session.outbox == []


def test_spell_levels_survive_star_up(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    grant_angel(conn, pid, 500000, level=10, star=1)
    _set(conn, pid, spell0_lv=3, aura0_lv=2)
    msg = angel.build_client_angel(reg, cfg, _row(conn, pid))
    assert list(msg.spells) == [5000002, 5010000]
    assert list(msg.auras) == [5020001, 0, 0, 0, 0, 0]
    grant_item(conn, pid, 500000, 20)
    res = handlers[(5, 2305)](
        session, reg.message_class("UpgradeAngelStarReq")(angel_entry=500000)
    )
    assert res.status == 0
    assert list(res.angel.spells) == [5001002, 5011000]
    assert list(res.angel.auras) == [5020001, 5021000, 0, 0, 0, 0]


def test_angel_skill_responses_serialise(reg, world) -> None:
    conn, pid, handlers, session = world
    _aura_up(reg, handlers, session, 5020000).SerializeToString()
    grant_angel(conn, pid, 500000, level=5, star=2)
    _spell_up(reg, handlers, session, 5001000).SerializeToString()
    _spell_up(reg, handlers, session, 5011000, upgrade_spell=5011003).SerializeToString()
    _spell_up(reg, handlers, session, 5000000).SerializeToString()
    _aura_up(reg, handlers, session, 5020000).SerializeToString()
    _aura_up(reg, handlers, session, 5021000, upgrade_aura=5021003).SerializeToString()
    _aura_up(reg, handlers, session, 5099999).SerializeToString()
    for _s, _c, m in session.outbox:
        m.SerializeToString()
