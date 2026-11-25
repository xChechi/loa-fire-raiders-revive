"""Training: 5_2139 QueryTrainInfo, 5_2119 TrainUse, 5_2117 TrainQualityUp.

Train opens at function(10040).unlock_level 8 (TrainCache.lua:110). Slots
1-3 are train_info.is_free (O-W2-7); 4 opens for train_quality(4, 1).diamond
880 at vip_need 0. Quality 1 has exp_up 75 per TRAIN_MIN_DURATION 60 s, and
train_level_xp(level 8, quality 1).rate is 0.07, so one tick is 80.25 xp
(O-W2-8; the client's display formula, TrainUI.lua:636-662). At player level
8 a hero's cap is xp_for_level(8).hero_max_level 17 (O-W2-9).
"""

from datetime import datetime
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_angel, grant_hero, heroes_of
from server.modules import notify, train
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
T0 = datetime(2026, 11, 25, 10, 0).timestamp()
KNIGHT = 100000
GODDESS = 500000


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100000, diamond=1000)
    conn.execute("UPDATE players SET level = 8 WHERE id = ?", (pid,))
    conn.commit()
    clock = {"now": T0}
    handlers = train.handlers(reg, settings, conn, cfg, clock=lambda: clock["now"])
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session, clock


def _query(reg, handlers, session, op=1):
    res = handlers[(5, 2139)](session, reg.message_class("QueryTrainInfoReq")(op=op))
    res.SerializeToString()
    return res


def _use(reg, handlers, session, slot, op=1, refer_type=1, refer_id=KNIGHT):
    res = handlers[(5, 2119)](session, reg.message_class("TrainUseReq")(
        train=slot, op=op, refer_type=refer_type, refer_id=refer_id,
    ))
    res.SerializeToString()
    return res


def _quality_up(reg, handlers, session, slot):
    res = handlers[(5, 2117)](session, reg.message_class("TrainQualityUpReq")(train=slot))
    res.SerializeToString()
    return res


def _slot(res, slot):
    return next(t for t in res.trains if t.train == slot)


def _decode(msg, order) -> dict:
    out, values = {}, iter(msg.data)
    for i, name in enumerate(order):
        if msg.flags & (1 << i):
            out[name] = next(values)
    return out


def _notes(session, ident):
    return [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == ident]


def test_query_opens_slots_1_to_3_at_quality_1_and_lists_no_others(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    res = _query(reg, handlers, session)
    assert res.status == 0
    assert [(t.train, t.quality, t.refer_type, t.refer_id) for t in res.trains] == [
        (1, 1, 0, 0), (2, 1, 0, 0), (3, 1, 0, 0)
    ]
    rows = conn.execute("SELECT train FROM trains WHERE player_id = ?", (pid,)).fetchall()
    assert sorted(int(r["train"]) for r in rows) == [1, 2, 3]
    assert list(res.logs) == []
    # A second query opens nothing more.
    assert [t.train for t in _query(reg, handlers, session).trains] == [1, 2, 3]


def test_query_items_are_1100_1110_1120_1130(reg, world) -> None:
    """TrainPanel.lua:32-52: each item becomes a TrainBlock, merchandise 999."""
    _, _, handlers, session, _ = world
    assert list(_query(reg, handlers, session).items) == [1100, 1110, 1120, 1130]


def test_query_below_level8_refused_327957(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 7 WHERE id = ?", (pid,))
    conn.commit()
    res = _query(reg, handlers, session)
    assert res.status == 327957                     # 未满足此玩法的等级
    assert list(res.trains) == []
    assert conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 0


def test_place_hero_in_slot1_query_shows_level_exp_maxexp(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, KNIGHT, 10, level=3, xp=10)
    _query(reg, handlers, session)
    res = _use(reg, handlers, session, 1)
    assert res.status == 0
    t = res.train
    assert (t.train, t.refer_type, t.refer_id) == (1, 1, KNIGHT)
    assert (t.level, t.exp, t.maxexp) == (3, 10, 40)    # hero_xp_for_next_level(3)
    assert t.cal_time == int(T0)
    q = _slot(_query(reg, handlers, session), 1)
    assert (q.refer_id, q.level, q.exp, q.maxexp) == (KNIGHT, 3, 10, 40)


def test_same_hero_on_two_slots_refused_329221(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, KNIGHT, 10)
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 1).status == 0
    res = _use(reg, handlers, session, 2)
    assert res.status == 329221                     # 此英雄已经训练位上
    row = conn.execute(
        "SELECT refer_id FROM trains WHERE player_id = ? AND train = 2", (pid,)
    ).fetchone()
    assert int(row["refer_id"]) == 0


def test_occupied_slot_and_unowned_refused(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, KNIGHT, 10)
    grant_hero(conn, pid, 101000, 10)
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 1).status == 0
    assert _use(reg, handlers, session, 1, refer_id=101000).status == 329219
    assert _use(reg, handlers, session, 2, refer_id=102000).status == 327941
    assert _use(reg, handlers, session, 2, refer_type=2, refer_id=GODDESS).status == 328457


def test_place_in_unopened_slot4_refused_329218(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    grant_hero(conn, pid, KNIGHT, 10)
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 4).status == 329218   # 训练位还未开启


def test_remove_from_empty_slot_refused_329220(reg, world) -> None:
    _, _, handlers, session, _ = world
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 1, op=2).status == 329220   # 训练位上没有英雄


def test_remove_settles_and_clears_the_slot(reg, world) -> None:
    conn, pid, handlers, session, clock = world
    grant_hero(conn, pid, KNIGHT, 10)
    _query(reg, handlers, session)
    _use(reg, handlers, session, 1)
    clock["now"] = T0 + 60
    res = _use(reg, handlers, session, 1, op=2)
    assert res.status == 0
    assert (res.train.refer_type, res.train.refer_id) == (0, 0)
    assert int(heroes_of(conn, pid)[0]["xp"]) == 0 + 80 - 20 - 30   # 80 xp: L1 -> L3
    assert int(heroes_of(conn, pid)[0]["level"]) == 3


def test_ten_minutes_give_ten_ticks_of_exp_up_times_1_plus_rate(reg, cfg, world) -> None:
    """10 x 75 x 1.07 = 802.5, floored to 802: level 1 -> 11 with 142 left
    (20+30+...+120 = 660 for levels 1-10)."""
    conn, pid, handlers, session, clock = world
    grant_hero(conn, pid, KNIGHT, 10)
    _query(reg, handlers, session)
    _use(reg, handlers, session, 1)
    session.outbox.clear()
    clock["now"] = T0 + 600 + 59                    # the 59 s carry over
    res = _query(reg, handlers, session)
    t = _slot(res, 1)
    assert (t.level, t.exp, t.addxp) == (11, 142, 802)
    assert t.maxexp == int(cfg.xp_for_level(11)["hero_xp_for_next_level"])
    assert t.cal_time == int(T0) + 600
    hero_row = heroes_of(conn, pid)[0]
    assert (int(hero_row["level"]), int(hero_row["xp"])) == (11, 142)
    notes = _notes(session, 2)
    assert len(notes) == 1 and notes[0].refer == KNIGHT
    fields = _decode(notes[0], notify.HERO_FIELDS)
    assert (fields["level"], fields["xp"]) == (11, 142)


def test_addxp_reported_then_cleared_by_op2(reg, world) -> None:
    conn, pid, handlers, session, clock = world
    grant_hero(conn, pid, KNIGHT, 10)
    _query(reg, handlers, session)
    _use(reg, handlers, session, 1)
    clock["now"] = T0 + 120
    assert _slot(_query(reg, handlers, session, op=1), 1).addxp == 160
    assert _slot(_query(reg, handlers, session, op=2), 1).addxp == 160
    assert _slot(_query(reg, handlers, session, op=1), 1).addxp == 0


def test_hero_at_cap_holds_exp_at_maxexp_minus_1(reg, world) -> None:
    """TrainCell.lua:145-154: at the cap, exp + 1 == maxexp is "full"."""
    conn, pid, handlers, session, clock = world
    grant_hero(conn, pid, KNIGHT, 10, level=16, xp=0)
    _query(reg, handlers, session)
    _use(reg, handlers, session, 1)
    clock["now"] = T0 + 86400
    t = _slot(_query(reg, handlers, session), 1)
    assert (t.level, t.maxexp) == (17, 900)
    assert t.exp + 1 == t.maxexp
    assert t.addxp == 800 + 899
    hero_row = heroes_of(conn, pid)[0]
    assert (int(hero_row["level"]), int(hero_row["xp"])) == (17, 899)


def test_open_slot4_costs_880_diamonds_and_vip0_suffices(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _query(reg, handlers, session)
    res = _quality_up(reg, handlers, session, 4)
    assert res.status == 0
    assert (res.train.train, res.train.quality, res.train.refer_id) == (4, 1, 0)
    row = conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["diamond"]) == 1000 - 880
    assert _decode(_notes(session, 1)[-1], notify.PLAYER_FIELDS) == {"diamond": 120}
    assert [t.train for t in _query(reg, handlers, session).trains] == [1, 2, 3, 4]


def test_open_slot_refusals_vip_and_diamonds(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _query(reg, handlers, session)
    assert _quality_up(reg, handlers, session, 7).status == 327951      # VIP等级不足
    conn.execute("UPDATE players SET diamond = 879 WHERE id = ?", (pid,))
    conn.commit()
    assert _quality_up(reg, handlers, session, 4).status == 327938      # 钻石不足
    assert conn.execute(
        "SELECT COUNT(*) FROM trains WHERE player_id = ? AND train = 4", (pid,)
    ).fetchone()[0] == 0


def test_upgrade_slot_costs_next_quality_row_and_top_refused_329217(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET diamond = 5000 WHERE id = ?", (pid,))
    conn.commit()
    _query(reg, handlers, session)
    res = _quality_up(reg, handlers, session, 1)
    assert (res.status, res.train.quality) == (0, 2)
    row = conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["diamond"]) == 5000 - 1880        # train_quality(1, 2).diamond
    conn.execute("UPDATE trains SET quality = 5 WHERE player_id = ? AND train = 1", (pid,))
    conn.commit()
    assert _quality_up(reg, handlers, session, 1).status == 329217      # 已经是最高等级
    assert int(conn.execute(
        "SELECT diamond FROM players WHERE id = ?", (pid,)
    ).fetchone()["diamond"]) == 5000 - 1880


def test_angel_in_slot2_gains_angel_xp_and_pushes_ident3(reg, world) -> None:
    """Guide 11206-11208 trains the angel in slot 2 (TrainList.lua:39-43)."""
    conn, pid, handlers, session, clock = world
    grant_angel(conn, pid, GODDESS, level=1, star=1)
    _query(reg, handlers, session)
    res = _use(reg, handlers, session, 2, refer_type=2, refer_id=GODDESS)
    assert res.status == 0
    assert (res.train.level, res.train.exp, res.train.maxexp) == (1, 0, 20)
    assert _use(reg, handlers, session, 3, refer_type=2, refer_id=GODDESS).status == 329222
    session.outbox.clear()
    clock["now"] = T0 + 600
    t = _slot(_query(reg, handlers, session), 2)
    assert (t.refer_type, t.level, t.exp) == (2, 11, 142)
    row = conn.execute(
        "SELECT level, exp FROM angels WHERE player_id = ?", (pid,)
    ).fetchone()
    assert (int(row["level"]), int(row["exp"])) == (11, 142)
    notes = _notes(session, 3)
    assert len(notes) == 1 and notes[0].refer == GODDESS
    assert _decode(notes[0], notify.ANGEL_FIELDS) == {"level": 11, "exp": 142}


# --- Wave 2 A5: xp potions on a slot (5_2125) and buying them (5_2165) -------
# item_info 1100 小经验药水 is class 44 with arg0 60; train_quality(1, 1).effect
# is 1. merchandise_info store 999: 9999000 = 1100 x1 for 300 gold (price_type
# 1), 9999020 = 1120 for 15 diamonds from min_level 30.


def _speed_up(reg, handlers, session, item=1100, slot=1, amount=1):
    res = handlers[(5, 2125)](session, reg.message_class("TrainSpeedUpReq")(
        item=item, train=slot, amount=amount,
    ))
    res.SerializeToString()
    return res


def _buy(reg, handlers, session, merchandise, amount):
    res = handlers[(5, 2165)](session, reg.message_class("BuyXpItemReq")(
        merchandise=merchandise, amount=amount,
    ))
    res.SerializeToString()
    return res


def _owned(conn, pid, entry) -> int:
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
    ).fetchone()
    return int(row["amount"]) if row else 0


def _hero_on_slot1(reg, conn, pid, handlers, session, level=1, xp=0):
    grant_hero(conn, pid, KNIGHT, 10, level=level, xp=xp)
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 1).status == 0
    session.outbox.clear()


def test_guide_11205_one_1100_on_slot1_adds_60_xp(reg, world) -> None:
    """TrainList.lua:47-57 sends {item, train = slot 1, amount = 1}."""
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 3)
    _hero_on_slot1(reg, conn, pid, handlers, session)
    res = _speed_up(reg, handlers, session)
    assert res.status == 0
    assert (res.train.train, res.train.refer_id) == (1, KNIGHT)
    assert (res.train.level, res.train.exp) == (3, 10)      # 60 = 20 + 30 + 10
    assert _owned(conn, pid, 1100) == 2
    hero_row = heroes_of(conn, pid)[0]
    assert (int(hero_row["level"]), int(hero_row["xp"])) == (3, 10)


def test_potions_level_the_hero_and_push_one_hero_notify(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 10)
    _hero_on_slot1(reg, conn, pid, handlers, session)
    res = _speed_up(reg, handlers, session, amount=5)          # 300 xp
    assert res.status == 0
    assert [m.ident for (_s, c, m) in session.outbox if c == 2008] == [4, 2]
    assert [list(m.data) for m in _notes(session, 4)] == [[1100.0, 5.0]]
    fields = _decode(_notes(session, 2)[0], notify.HERO_FIELDS)
    # 20+30+40+50+60+70 = 270 for levels 1-6, 30 left at level 7.
    assert (fields["level"], fields["xp"]) == (7, 30)
    assert "ability" in fields and "max_hp" in fields


def test_potion_amount_clipped_at_the_cap_consumes_only_what_is_needed(reg, world) -> None:
    """Risk 4: a long press sends big amounts. Level 16 -> 17 with 899 of 900
    is 1699 xp, ceil(1699 / 60) = 29 potions."""
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 100)
    _hero_on_slot1(reg, conn, pid, handlers, session, level=16)
    res = _speed_up(reg, handlers, session, amount=100)
    assert res.status == 0
    assert _owned(conn, pid, 1100) == 71
    assert (res.train.level, res.train.exp, res.train.maxexp) == (17, 899, 900)
    hero_row = heroes_of(conn, pid)[0]
    assert (int(hero_row["level"]), int(hero_row["xp"])) == (17, 899)


def test_potion_on_a_full_hero_refused_327945(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 5)
    _hero_on_slot1(reg, conn, pid, handlers, session, level=17, xp=899)
    res = _speed_up(reg, handlers, session)
    assert res.status == 327945                     # 英雄经验值已经满了
    assert _owned(conn, pid, 1100) == 5
    assert session.outbox == []


def test_non_potion_item_refused_327948(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1300, 5)                  # 精英扫荡券, class 60
    _hero_on_slot1(reg, conn, pid, handlers, session)
    assert _speed_up(reg, handlers, session, item=1300).status == 327948
    assert _owned(conn, pid, 1300) == 5


def test_potion_on_an_empty_slot_refused_329220(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 5)
    _query(reg, handlers, session)
    assert _speed_up(reg, handlers, session, slot=2).status == 329220
    assert _speed_up(reg, handlers, session, slot=9).status == 329220
    assert _owned(conn, pid, 1100) == 5


def test_more_potions_than_owned_refused_327942(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 2)
    _hero_on_slot1(reg, conn, pid, handlers, session)
    assert _speed_up(reg, handlers, session, amount=3).status == 327942
    assert _owned(conn, pid, 1100) == 2
    assert int(heroes_of(conn, pid)[0]["xp"]) == 0


def test_potion_on_an_angel_pushes_ident3(reg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session, _ = world
    grant_item(conn, pid, 1100, 1)
    grant_angel(conn, pid, GODDESS, level=1, star=1)
    _query(reg, handlers, session)
    _use(reg, handlers, session, 2, refer_type=2, refer_id=GODDESS)
    session.outbox.clear()
    res = _speed_up(reg, handlers, session, slot=2)
    assert res.status == 0
    assert (res.train.refer_type, res.train.level, res.train.exp) == (2, 3, 10)
    assert _decode(_notes(session, 3)[0], notify.ANGEL_FIELDS) == {"level": 3, "exp": 10}


def test_buy_ten_1100_costs_3000_gold(reg, world) -> None:
    """TrainBuyItemPanel.lua:255-268: amount is groups of merchandise.amount."""
    conn, pid, handlers, session, _ = world
    res = _buy(reg, handlers, session, 9999000, 10)
    assert res.ListFields() == []
    assert _owned(conn, pid, 1100) == 10
    row = conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 100000 - 3000
    assert [list(m.data) for m in _notes(session, 4)] == [[1100.0, 10.0]]
    assert _decode(_notes(session, 1)[0], notify.PLAYER_FIELDS) == {"gold": 97000}


def test_buy_1120_below_level30_changes_nothing(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    _buy(reg, handlers, session, 9999020, 1)
    assert _owned(conn, pid, 1120) == 0
    row = conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["diamond"]) == 1000
    assert session.outbox == []


def test_buy_1120_at_level30_costs_15_diamonds(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET level = 30 WHERE id = ?", (pid,))
    conn.commit()
    _buy(reg, handlers, session, 9999020, 2)
    assert _owned(conn, pid, 1120) == 2
    row = conn.execute("SELECT diamond FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["diamond"]) == 1000 - 30


def test_buy_without_gold_changes_nothing(reg, world) -> None:
    conn, pid, handlers, session, _ = world
    conn.execute("UPDATE players SET gold = 2999 WHERE id = ?", (pid,))
    conn.commit()
    _buy(reg, handlers, session, 9999000, 10)
    assert _owned(conn, pid, 1100) == 0
    row = conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 2999
    assert session.outbox == []


def test_buy_merchandise_outside_store_999_changes_nothing(reg, cfg, world) -> None:
    conn, pid, handlers, session, _ = world
    other = next(
        int(r["entry"]) for r in cfg.conn("merchandise_info").execute(
            "SELECT entry FROM merchandise_info WHERE store = 1 ORDER BY entry"
        )
    )
    _buy(reg, handlers, session, other, 1)
    _buy(reg, handlers, session, 1, 1)
    assert session.outbox == []


def test_angel_in_training_stops_at_the_heroes_cap_for_the_player_level(reg, world) -> None:
    """Run 11 finding 4: Idol Angel trained 19 -> 29 at player level 8-ish
    while the heroes stopped at 17. The client's train screen caps an angel
    at BOTH angel_info.max_level and xp_for_level[player level].hero_max_level
    (train/LevelHelp.lua:38-52, `heroLevel <= maxLevel and heroLevel <=
    maxLevel_exp`), and HeroCell.lua:191-201 shows it "full" at
    exp + 1 == maxexp. At player level 8 that is min(40, 17) = 17."""
    conn, pid, handlers, session, clock = world
    grant_angel(conn, pid, GODDESS, level=16, star=1)
    _query(reg, handlers, session)
    assert _use(reg, handlers, session, 2, refer_type=2, refer_id=GODDESS).status == 0
    clock["now"] = T0 + 86400
    t = _slot(_query(reg, handlers, session), 2)
    assert t.level == 17
    assert t.exp + 1 == t.maxexp
    row = conn.execute(
        "SELECT level, exp FROM angels WHERE player_id = ?", (pid,)
    ).fetchone()
    assert (int(row["level"]), int(row["exp"]) + 1) == (17, t.maxexp)
    from server.db import grant_item

    grant_item(conn, pid, 1100, 1)
    assert _speed_up(reg, handlers, session, slot=2).status == 327945   # 经验值已经满了
    assert _owned(conn, pid, 1100) == 1
