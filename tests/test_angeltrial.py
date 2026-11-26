"""Angel trials (女神试炼): the tower state, its events, fights and shops.

Angel trials open at function(10090).unlock_level 20 (FunctionType.lua:58).
The tower is angeltrials_level_info, 50 floors; each floor's event is 1
treasure, 2 fight or 3 buff shop (AngelTrainSceneUIPanel.lua:189-224). Floor
1 is a fight, 2 a buff shop of buff group 2 (arg0), 4 a treasure whose free
prize is angel_advance_free_drop 4000100 (one item 1900).
"""

import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, heroes_of
from server.modules import angeltrial, team
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
# 25-11-2026 10:00 local: day_key(5) is 2026-11-25.
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
KNIGHT = 100000


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
    conn.execute("UPDATE players SET level = 20 WHERE id = ?", (pid,))
    conn.commit()
    grant_hero(conn, pid, KNIGHT, 10, star=1, level=20)
    clock = {"now": T0}
    handlers = angeltrial.handlers(
        reg, settings, conn, cfg, rng=random.Random(7), clock=lambda: clock["now"]
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


def _call(reg, handlers, session, cmd, name, **fields):
    res = handlers[(8, cmd)](session, reg.message_class(name)(**fields))
    res.SerializeToString()
    return res


def _query(reg, handlers, session):
    return _call(reg, handlers, session, 2501, "QueryAngeltrialsDataReq")


def _start(reg, handlers, session):
    return _call(reg, handlers, session, 2503, "StartAngeltrialsReq")


def _event(reg, handlers, session, level, event):
    return _call(
        reg, handlers, session, 2505, "TriggerAngeltrialsEventReq",
        level=level, event=event,
    )


def _set_level(conn, pid, level):
    conn.execute("UPDATE angeltrials SET level = ? WHERE player_id = ?", (level, pid))
    conn.commit()


def _row(conn, pid):
    return conn.execute("SELECT * FROM angeltrials WHERE player_id = ?", (pid,)).fetchone()


# --- commit 1: the tower ------------------------------------------------------


def test_query_unopened_then_start_opens_level1(world, reg):
    conn, pid, handlers, session, _ = world
    res = _query(reg, handlers, session)
    assert res.status == 0
    # FunctionType.lua:484-497: opened = false makes the client send 8_2503.
    assert res.opened is False
    start = _start(reg, handlers, session)
    assert start.status == 0
    res = _query(reg, handlers, session)
    assert (res.opened, res.level, res.points, res.stars) == (True, 1, 0, 0)
    assert _row(conn, pid)["day"] == "2026-11-25"


def test_start_twice_refused_329730(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    assert _start(reg, handlers, session).status == 329730


def test_query_below_level20_refused_327957(world, reg):
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 19 WHERE id = ?", (pid,))
    conn.commit()
    assert _query(reg, handlers, session).status == 327957
    assert _start(reg, handlers, session).status == 327957


def test_event_before_start_refused_329729(world, reg):
    _, _, handlers, session, _ = world
    # AngelTryCtr.lua:129-133: 329729 is the "trial was reset, re-enter" alert.
    assert _event(reg, handlers, session, 1, 2).status == 329729


def test_event_on_wrong_level_refused_329731(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    res = _event(reg, handlers, session, 2, 3)
    assert res.status == 329731


def test_wrong_event_for_the_level_refused_329732(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 2)
    assert _event(reg, handlers, session, 2, 1).status == 329732


def test_event_past_the_top_refused_329733(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 51)
    assert _event(reg, handlers, session, 51, 2).status == 329733


def test_treasure_floor_pays_the_free_drop_once(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 4)
    res = _event(reg, handlers, session, 4, 1)
    assert res.status == 0 and (res.level, res.event) == (4, 1)
    treasure = res.eventResult.treasureEvent
    assert treasure.buyCount == 0
    assert [(p.category, p.refer, p.amount) for p in treasure.prizes] == [(20, 1900, 1)]
    owned = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = 1900", (pid,)
    ).fetchone()
    assert owned["amount"] == 1
    # The client resends 8_2505 after a reconnect; the prize is not paid twice
    # and an empty prize list takes it straight to the treasure panel
    # (AngelTrainSceneUIPanel.lua:196-204).
    again = _event(reg, handlers, session, 4, 1)
    assert again.status == 0 and list(again.eventResult.treasureEvent.prizes) == []
    owned = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = 1900", (pid,)
    ).fetchone()
    assert owned["amount"] == 1
    # The item arrives on the client as an ident-1 ClientNotification.
    assert any((s, c) == (5, 2008) for s, c, _ in session.outbox)


def test_buff_shop_offers_three_buffs_of_the_floors_group(world, reg, cfg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    _set_level(conn, pid, 2)
    res = _event(reg, handlers, session, 2, 3)
    assert res.status == 0
    offers = list(res.eventResult.buffShopEvent.angeltrialsBuffs)
    assert len(offers) == 3 and len(set(offers)) == 3
    groups = {int(b["id"]): int(b["group"]) for b in cfg.angeltrials_buffs()}
    # angeltrials_level_info(2).arg0 = 2: the cheap tutorial group 9101-9105.
    assert all(groups[b] == 2 for b in offers)
    # The same offer comes back on a resend.
    again = _event(reg, handlers, session, 2, 3)
    assert list(again.eventResult.buffShopEvent.angeltrialsBuffs) == offers


def test_daily_reset_at_5am(world, reg):
    conn, pid, handlers, session, clock = world
    _start(reg, handlers, session)
    conn.execute(
        "UPDATE angeltrials SET level = 9, points = 300, stars = 12,"
        " buffs = '[3]' WHERE player_id = ?", (pid,),
    )
    conn.commit()
    clock["now"] = datetime(2026, 11, 26, 4, 59).timestamp()
    res = _query(reg, handlers, session)
    assert (res.opened, res.level, res.points) == (True, 9, 300)
    clock["now"] = datetime(2026, 11, 26, 5, 0).timestamp()
    res = _query(reg, handlers, session)
    assert (res.opened, res.points, res.stars) == (False, 0, 0)
    # "介于你昨日的表现，今日可以快速碾压" (f00162): yesterday's cleared floors.
    assert res.crashLevel == 8
    row = _row(conn, pid)
    assert row["day"] == "2026-11-26"
    assert json.loads(row["buffs"]) == [] and json.loads(row["units"]) == []


def test_query_buffs_lists_the_owned_buffs(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    conn.execute("UPDATE angeltrials SET buffs = '[3, 9]' WHERE player_id = ?", (pid,))
    conn.commit()
    res = _call(reg, handlers, session, 2507, "QueryAngeltrialsBuffReq")
    assert res.status == 0 and list(res.angeltrialsBuffs) == [3, 9]


def test_rank_lists_only_self(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    conn.execute(
        "UPDATE angeltrials SET level = 6, points = 420 WHERE player_id = ?", (pid,)
    )
    conn.commit()
    res = _call(reg, handlers, session, 2517, "AngeltrialsRankReq")
    assert res.status == 0 and res.selfRank == 1
    assert len(res.leadings) == 1
    me = res.leadings[0]
    assert (me.id, me.name, me.atRank, me.atPoints, me.atLevel, me.level) == (
        pid, "stefan", 1, 420, 6, 20,
    )
    own = _call(reg, handlers, session, 2519, "AngeltrialsSelfRankReq")
    assert own.status == 0 and own.selfRank == 1


# --- commit 2: the fights ------------------------------------------------------

PRIEST = 200000


def _fight_floor(conn, pid, reg, handlers, session, level=1):
    _start(reg, handlers, session)
    _set_level(conn, pid, level)
    return _event(reg, handlers, session, level, 2)


def _fight(reg, handlers, session, difficulty, heros=(KNIGHT,), angel=0):
    return _call(
        reg, handlers, session, 2511, "AngeltrialsFightingReq",
        difficulty=difficulty, heros=list(heros), angel=angel,
    )


def _live(reg, type_, refer, hp, energy, max_hp, max_energy=1000):
    return reg.message_class("ClientFightLiveUnit")(
        type=type_, refer=refer, hp=hp, energy=energy, max_hp=max_hp,
        max_energy=max_energy,
    )


def _end(reg, handlers, session, success, stars, units=(), enemy_units=(), heros=(KNIGHT,)):
    return _call(
        reg, handlers, session, 2513, "AngeltrialsEndFightReq",
        success=success, stars=stars, units=list(units),
        enemyUnits=list(enemy_units), heros=list(heros), angel=0,
    )


def _crash(reg, handlers, session, heroes=(KNIGHT,)):
    return _call(
        reg, handlers, session, 2527, "AngeltrialsCrashLevelReq",
        heroIds=list(heroes), angelIds=[],
    )


def test_fight_floor_offers_three_mirror_teams_scaled_by_difficulty(world, reg):
    conn, pid, handlers, session, _ = world
    res = _fight_floor(conn, pid, reg, handlers, session)
    assert res.status == 0 and (res.level, res.event) == (1, 2)
    fight = res.eventResult.fightEvent
    assert list(fight.fightDifficulty) == [0, 1, 2]
    assert len(fight.enemies) == 3 and list(fight.enemyUnits) == []
    # O-W2-14: the enemy is the player's own line-up.
    assert all([h.entry for h in team.heros] == [KNIGHT] for team in fight.enemies)
    easy, normal, hard = (t.fightAbility for t in fight.enemies)
    # fa_fix_battle_easy/normal/hard of floor 1 are 0.76 / 1 / 1.06.
    assert easy < normal < hard


def test_fighting_req_returns_scaled_enemy_units_and_buff_effects(world, reg, cfg):
    conn, pid, handlers, session, _ = world
    _fight_floor(conn, pid, reg, handlers, session)
    res = _fight(reg, handlers, session, 2)
    assert res.status == 0
    assert len(res.urandom) == 64
    assert len(res.buffEffects) == 6 and set(res.buffEffects) == {0.0}
    # angeltrials_level_info(1).enemy_buff_fix 0.5 (FightData.lua:221-226).
    assert res.enemyBuffRate == pytest.approx(0.5)
    (enemy,) = res.enemyUnits
    assert (enemy.type, enemy.refer, enemy.position) == (1, KNIGHT, 1)
    info = cfg.angeltrials_level(1)
    factor = info["fa_fix_battle_hard"] * (info["floor_fa_fix4"] + info["ceiling_fa_fix4"]) / 2
    own = team.build_fight_unit(reg, cfg, heroes_of(conn, pid)[0], 1, conn=conn)
    assert enemy.unit.max_hp == int(own.unit.max_hp * factor)
    assert enemy.unit.power == pytest.approx(own.unit.power * factor)
    assert enemy.hp == enemy.unit.max_hp


def test_fighting_without_a_fight_event_refused_329736(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    assert _fight(reg, handlers, session, 1).status == 329736


def test_fighting_with_an_unowned_hero_refused_329738(world, reg):
    conn, pid, handlers, session, _ = world
    _fight_floor(conn, pid, reg, handlers, session)
    assert _fight(reg, handlers, session, 1, heros=(PRIEST,)).status == 329738


def test_fight_result_three_stars_scales_points_2_5(world, reg):
    conn, pid, handlers, session, _ = world
    _fight_floor(conn, pid, reg, handlers, session)
    _fight(reg, handlers, session, 1)
    res = _end(reg, handlers, session, True, 3, units=[_live(reg, 1, KNIGHT, 500, 300, 877)])
    assert res.success is True and res.warning is False
    # normal_battle_point 60 x ANGELTRIALS_POINTS_ADDITION_THREE_STAR 2.5 x
    # (1 + player level 20 / 80) (BattleEndLayer.lua:667-700; 80 is the
    # client's own lvTop, AngelTrainBattleSelectRender.lua:125-130).
    assert res.points == 187
    # 3 stars x normal_battle_star 3 (得星倍率, AngelTrainBattleSelectRender.lua:132).
    assert res.stars == 9
    assert res.newLevel == 2
    assert _query(reg, handlers, session).level == 2


def test_end_fight_without_a_fight_changes_nothing(world, reg):
    _, _, handlers, session, _ = world
    _start(reg, handlers, session)
    res = _end(reg, handlers, session, True, 3)
    assert (res.success, res.newLevel, res.points) == (False, 1, 0)


def test_lost_fight_keeps_the_floor_and_the_enemy_hp(world, reg):
    conn, pid, handlers, session, _ = world
    _fight_floor(conn, pid, reg, handlers, session)
    _fight(reg, handlers, session, 0)
    res = _end(
        reg, handlers, session, False, 0,
        units=[_live(reg, 1, KNIGHT, 0, 0, 877)],
        enemy_units=[_live(reg, 1, KNIGHT, 120, 400, 546)],
    )
    assert res.success is False and res.newLevel == 1
    assert _query(reg, handlers, session).points == 0
    again = _event(reg, handlers, session, 1, 2)
    left = again.eventResult.fightEvent.enemyUnits
    assert [(u.refer, u.hp) for u in left] == [(KNIGHT, 120)]
    # The knight died: a dead hero cannot be fielded again.
    assert _fight(reg, handlers, session, 0).status == 329738


def test_enemy_keeps_its_left_hp_on_a_retry_of_the_same_difficulty(world, reg):
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, PRIEST, 10, star=1, level=20)
    _fight_floor(conn, pid, reg, handlers, session)
    _fight(reg, handlers, session, 0)
    _end(
        reg, handlers, session, False, 0,
        units=[_live(reg, 1, KNIGHT, 0, 0, 877)],
        enemy_units=[_live(reg, 1, KNIGHT, 120, 400, 546), _live(reg, 1, PRIEST, 0, 0, 500)],
    )
    _event(reg, handlers, session, 1, 2)
    res = _fight(reg, handlers, session, 0, heros=(PRIEST,))
    assert {(u.refer, u.hp, u.energy) for u in res.enemyUnits} == {
        (KNIGHT, 120, 400), (PRIEST, 0, 0),
    }
    other = _fight(reg, handlers, session, 1, heros=(PRIEST,))
    assert all(u.hp == u.unit.max_hp for u in other.enemyUnits)


def test_live_units_persist_between_fights(world, reg):
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, PRIEST, 10, star=1, level=20)
    _fight_floor(conn, pid, reg, handlers, session)
    _fight(reg, handlers, session, 1, heros=(PRIEST,))
    _end(reg, handlers, session, True, 2,
         units=[_live(reg, 1, PRIEST, 100, 200, 1000)], heros=(PRIEST,))
    _set_level(conn, pid, 3)
    _event(reg, handlers, session, 3, 2)
    _fight(reg, handlers, session, 1)
    res = _end(reg, handlers, session, True, 1, units=[_live(reg, 1, KNIGHT, 400, 50, 877)])
    by_refer = {u.refer: u for u in res.units}
    assert by_refer[KNIGHT].hp == 400
    # The priest sat on the bench: ANGELTRIALS_RECOVER_HP_RATE 0.15 of 1000.
    assert by_refer[PRIEST].hp == 250
    live = _call(reg, handlers, session, 2515, "AngeltrialsFightLiveReq")
    assert live.status == 0
    assert {(u.refer, u.hp, u.energy) for u in live.units} == {
        (KNIGHT, 400, 50), (PRIEST, 250, 200),
    }


def test_trial_fight_team_query_is_answered_by_team_py_unchanged(world, reg, cfg, settings):
    # Risk 6: the fight sends 5_2327 with fight_type 4 (FightType.ANGEL_TRY,
    # FunctionType.lua:1100-1133); team.py answers any fight type with the
    # player's own heroes and keeps the support hero for the campaign.
    conn, pid, _, session, _ = world
    query = team.handlers(reg, settings, conn, cfg)[(5, 2327)]
    res = query(session, reg.message_class("QuerySelfTeamReq")(
        fight_type=4, units=[0, KNIGHT, 0, 0, 0, 0, 0],
    ))
    assert [(u.position, u.refer) for u in res.team_base.units] == [(1, KNIGHT)]


def test_trial_fights_carry_the_heroes_rune_stats(world, reg, cfg):
    """A level-1 rune idx 0 adds its rune_level_up stats (+60 max hp on the
    knight, test_rune.py) to the mirror enemy and to a new live unit."""
    from server.modules import hero

    conn, pid, handlers, session, _ = world
    conn.execute(
        "INSERT INTO runes (player_id, hero, idx, level, rune_val) VALUES (?, ?, 0, 1, 0)",
        (pid, KNIGHT),
    )
    conn.commit()
    row = heroes_of(conn, pid)[0]
    bare = team.build_fight_unit(reg, cfg, row, 1)
    own = team.build_fight_unit(reg, cfg, row, 1, runes=hero.runes_of(conn, row), conn=conn)
    assert own.unit.max_hp > bare.unit.max_hp
    _fight_floor(conn, pid, reg, handlers, session)
    (enemy,) = _fight(reg, handlers, session, 2).enemyUnits
    info = cfg.angeltrials_level(1)
    factor = info["fa_fix_battle_hard"] * (info["floor_fa_fix4"] + info["ceiling_fa_fix4"]) / 2
    assert enemy.unit.max_hp == int(own.unit.max_hp * factor)
    # A crash adds the knight's live unit at full hp: the rune hp counts.
    _set_level(conn, pid, 1)
    conn.execute("UPDATE angeltrials SET crash_level = 3, pending = '{}' WHERE player_id = ?",
                 (pid,))
    conn.commit()
    (knight,) = _crash(reg, handlers, session).units
    assert knight.max_hp == own.unit.max_hp


def test_crash_level_clears_to_crash_level(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    conn.execute("UPDATE angeltrials SET crash_level = 3 WHERE player_id = ?", (pid,))
    conn.commit()
    res = _crash(reg, handlers, session)
    # 3 stars at the hard row (f00167 3星碾压): 80 x 2.5 x 1.25 points, 3 x 5 stars.
    assert (res.newLevel, res.points, res.stars) == (2, 250, 15)
    # ANGELTRIALS_CRASH_RECOVER_ENERGY_RATE 0.3 of the knight's max energy 1000.
    (knight,) = res.units
    assert (knight.refer, knight.energy, knight.hp, knight.max_energy) == (
        KNIGHT, 300, knight.max_hp, 1000,
    )
    _set_level(conn, pid, 3)
    assert _crash(reg, handlers, session).newLevel == 4
    # Floor 5 is above the crash level: the answer is the unchanged tower
    # (floor 3's hard row is 88 points: 250 + 88 x 2.5 x 1.25).
    _set_level(conn, pid, 5)
    res = _crash(reg, handlers, session)
    assert (res.newLevel, res.points, res.stars) == (5, 525, 30)
    # A buff-shop floor is no fight to crash.
    _set_level(conn, pid, 2)
    assert _crash(reg, handlers, session).newLevel == 2


# --- commit 3: the buff and treasure shops --------------------------------------

# Floor 2's group 2: 9101 聚能 energy, 9102 生命 hp 0.3, 9103 强攻 attack 0.03
# (team-wide, effect 2); each costs 1 star.
ENERGY_BUFF, HP_BUFF, ATTACK_BUFF = 9101, 9102, 9103


def _buff_floor(conn, pid, reg, handlers, session, stars):
    _start(reg, handlers, session)
    _set_level(conn, pid, 2)
    _event(reg, handlers, session, 2, 3)
    pending = json.loads(_row(conn, pid)["pending"])
    pending["offers"] = [HP_BUFF, ATTACK_BUFF, ENERGY_BUFF]
    conn.execute(
        "UPDATE angeltrials SET pending = ?, stars = ? WHERE player_id = ?",
        (json.dumps(pending), stars, pid),
    )
    conn.commit()


def _buy_buff(reg, handlers, session, index, unit_entry=None):
    fields = {"index": index}
    if unit_entry is not None:
        fields.update(unitType=1, unitEntry=unit_entry)
    return _call(reg, handlers, session, 2509, "AngeltrialsBuyBuffReq", **fields)


def _set_units(conn, pid, units):
    conn.execute(
        "UPDATE angeltrials SET units = ? WHERE player_id = ?", (json.dumps(units), pid)
    )
    conn.commit()


def test_buff_costs_stars_and_refused_329737(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=0)
    # No status on AngeltrialsBuyBuffRes: a shortfall answers buff 0 and the
    # unchanged stars (AngelTryCtr.lua:200-216 adds nothing for buff 0).
    res = _buy_buff(reg, handlers, session, 1)
    assert (res.angeltrialsBuff, res.newStars) == (0, 0)
    assert json.loads(_row(conn, pid)["buffs"]) == []
    conn.execute("UPDATE angeltrials SET stars = 5 WHERE player_id = ?", (pid,))
    conn.commit()
    res = _buy_buff(reg, handlers, session, 1)
    assert (res.angeltrialsBuff, res.newStars) == (ATTACK_BUFF, 4)
    assert not res.HasField("unit")
    listed = _call(reg, handlers, session, 2507, "QueryAngeltrialsBuffReq")
    assert list(listed.angeltrialsBuffs) == [ATTACK_BUFF]


def test_team_buff_reaches_the_fight_buff_effects(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=5)
    _buy_buff(reg, handlers, session, 1)
    _call(reg, handlers, session, 2521, "AngeltrialsEndBuyBuffReq")
    _set_level(conn, pid, 3)
    _event(reg, handlers, session, 3, 2)
    res = _fight(reg, handlers, session, 1)
    assert list(res.buffEffects) == pytest.approx([0, 0, 0.03, 0, 0, 0])


def test_hp_buff_heals_the_chosen_hero(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=5)
    _set_units(conn, pid, [{"type": 1, "refer": KNIGHT, "hp": 100, "energy": 0,
                            "max_hp": 877, "max_energy": 1000}])
    res = _buy_buff(reg, handlers, session, 0, unit_entry=KNIGHT)
    assert (res.angeltrialsBuff, res.newStars) == (HP_BUFF, 4)
    # effect_value 0.3 of max hp 877.
    assert (res.unit.refer, res.unit.hp) == (KNIGHT, 363)
    assert json.loads(_row(conn, pid)["buffs"]) == []
    live = _call(reg, handlers, session, 2515, "AngeltrialsFightLiveReq")
    assert [(u.refer, u.hp) for u in live.units] == [(KNIGHT, 363)]


def test_hp_buff_on_a_dead_hero_changes_nothing(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=5)
    _set_units(conn, pid, [{"type": 1, "refer": KNIGHT, "hp": 0, "energy": 0,
                            "max_hp": 877, "max_energy": 1000}])
    res = _buy_buff(reg, handlers, session, 0, unit_entry=KNIGHT)
    assert (res.angeltrialsBuff, res.newStars) == (0, 5)


def test_rebuying_a_card_changes_nothing(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=5)
    _buy_buff(reg, handlers, session, 1)
    res = _buy_buff(reg, handlers, session, 1)
    assert (res.angeltrialsBuff, res.newStars) == (0, 4)
    assert json.loads(_row(conn, pid)["buffs"]) == [ATTACK_BUFF]


def test_end_buy_buff_moves_to_the_next_floor(world, reg):
    conn, pid, handlers, session, _ = world
    _buff_floor(conn, pid, reg, handlers, session, stars=0)
    res = _call(reg, handlers, session, 2521, "AngeltrialsEndBuyBuffReq")
    res.SerializeToString()
    assert res.newLevel == 3
    # A second end without a shop on floor 3 keeps the floor.
    assert _call(reg, handlers, session, 2521, "AngeltrialsEndBuyBuffReq").newLevel == 3


def _treasure_floor(conn, pid, reg, handlers, session):
    _start(reg, handlers, session)
    _set_level(conn, pid, 4)
    _event(reg, handlers, session, 4, 1)


def _buy_treasure(reg, handlers, session, count=None):
    fields = {} if count is None else {"count": count}
    return _call(reg, handlers, session, 2523, "AngeltrialsBuyTreasureReq", **fields)


def _diamond(conn, pid):
    return conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()[0]


def test_treasure_cost_steps_up_per_open(world, reg):
    conn, pid, handlers, session, _ = world
    _treasure_floor(conn, pid, reg, handlers, session)
    start = _diamond(conn, pid)
    res = _buy_treasure(reg, handlers, session)
    assert res.buyCount == 1 and len(res.prizes) == 1
    # angeltrials_treasure_cost 1..4 = 100, 200, 200, 400 diamonds.
    assert _diamond(conn, pid) == start - 100
    _buy_treasure(reg, handlers, session)
    assert _diamond(conn, pid) == start - 300
    res = _buy_treasure(reg, handlers, session, count=2)
    assert res.buyCount == 4 and len(res.prizes) == 2
    assert _diamond(conn, pid) == start - 900
    # The free floor prize plus four bought ones.
    assert res.treasure_cum_count == 5


def test_treasure_without_diamonds_changes_nothing(world, reg):
    conn, pid, handlers, session, _ = world
    _treasure_floor(conn, pid, reg, handlers, session)
    conn.execute("UPDATE players SET diamond = 99 WHERE id = ?", (pid,))
    conn.commit()
    res = _buy_treasure(reg, handlers, session)
    assert (res.buyCount, list(res.prizes)) == (0, [])
    assert _diamond(conn, pid) == 99


def test_treasure_pays_its_rows_and_angel_money(world, reg, cfg):
    conn, pid, handlers, session, _ = world
    _treasure_floor(conn, pid, reg, handlers, session)
    res = _buy_treasure(reg, handlers, session, count=10)
    rows = {
        (int(r["drop_type"]), int(r["drop_entry"]))
        for r in cfg.angeltrials_treasure_drops()
        # angeltrials_level_info(4).arg5 = 9; player level 20, VIP 0.
        if int(r["drop_group"]) == 9 and r["min_lvl"] <= 20 <= r["max_lvl"]
        and r["min_vip"] <= 0 <= r["max_vip"]
    }
    assert all((p.category, p.refer) in rows for p in res.prizes)
    money = sum(p.amount for p in res.prizes if p.category == 52)
    owned = conn.execute("SELECT angel_money FROM players WHERE id = ?", (pid,)).fetchone()
    assert owned["angel_money"] == money


def test_treasure_without_the_event_changes_nothing(world, reg):
    conn, pid, handlers, session, _ = world
    _start(reg, handlers, session)
    start = _diamond(conn, pid)
    res = _buy_treasure(reg, handlers, session)
    assert (res.buyCount, list(res.prizes)) == (0, [])
    assert _diamond(conn, pid) == start


def test_end_buy_treasure_moves_to_the_next_floor(world, reg):
    conn, pid, handlers, session, _ = world
    _treasure_floor(conn, pid, reg, handlers, session)
    res = _call(reg, handlers, session, 2525, "AngeltrialsEndBuyTreasureReq")
    res.SerializeToString()
    assert res.newLevel == 5
    assert _query(reg, handlers, session).level == 5
