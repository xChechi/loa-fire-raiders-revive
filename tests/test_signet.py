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


# --- commit B: the signet bag, equip, level-up, decompose, fight purchases ----
HERO = 100000
PART1 = 10101011            # 猛攻（1）, star 1, part 1, quality 1, pool {102}
PART2_Q3 = 10101032         # 猛攻（2）, star 1, part 2, quality 3 (two subs)
STAR6_SPECIAL = 106010511   # fixed: main 9|176, subs 81|0.035,89|0.03,12|220,13|220


class FixedRng(random.Random):
    """random() always gives `roll`; picks and grid steps stay seeded."""

    def __init__(self, roll: float) -> None:
        super().__init__(5)
        self._roll = roll

    def random(self):
        return self._roll


def _sig_handlers(reg, settings, conn, cfg, rng=None):
    return signet.handlers(reg, settings, conn, cfg, rng=rng or random.Random(1))


def _hero_values(session, entry):
    """{field: value} merged over the ident-2 notifies of one hero."""
    out = {}
    for m in _queued(session, 5, 2008):
        if m.ident != notify.IDENT_HERO or m.refer != entry:
            continue
        ordered = [n for n in notify.HERO_FIELDS if m.flags & notify.flags_for([n], notify.HERO_FIELDS)]
        out.update(dict(zip(ordered, m.data)))
    return out


def _owned_signet(conn, cfg, pid, entry, level_=0, rng=None):
    sid = add_signet(conn, pid, entry)
    conn.execute("UPDATE signets SET level = ? WHERE id = ?", (level_, sid))
    conn.commit()
    row = conn.execute("SELECT * FROM signets WHERE id = ?", (sid,)).fetchone()
    return signet.ensure_rolled(conn, cfg, row, rng or random.Random(2))


def _signet_row(conn, sid):
    return conn.execute("SELECT * FROM signets WHERE id = ?", (sid,)).fetchone()


def test_buy_fights_tier_costs(reg, settings, cfg, world) -> None:
    """SIGNET_BUY_CNT_COST '100|5,200|15,...': buys 1-5 cost 100, 6-20 cost
    200 (MMTools:getCost). The daily cap is vip_info 20260 (0 below VIP 8),
    SIGNET_MAX_BUY_CNT 50 caps the fights held (LevelDes.lua:219-233)."""
    conn, pid, _h, session = world
    h = _sig_handlers(reg, settings, conn, cfg)
    buy = lambda n: h[(5, 2621)](session, reg.message_class("BuyHeroSignetReq")(times=n))
    res = buy(1)                                            # VIP 0: no buys
    assert (res.signet_fight_cnt, res.signet_buy_cnt) == (20, 0)
    assert int(find_player(conn, "stefan")["diamond"]) == 5000
    conn.execute("UPDATE players SET vip = 8 WHERE id = ?", (pid,))
    conn.commit()
    res = buy(6)
    assert (res.signet_fight_cnt, res.signet_buy_cnt) == (26, 6)
    assert int(find_player(conn, "stefan")["diamond"]) == 5000 - (5 * 100 + 200)
    assert _player_values(session, "signet_fight_cnt") == [26]
    res = buy(2)                                            # buys 7, 8: 200 each
    assert (res.signet_fight_cnt, res.signet_buy_cnt) == (28, 8)
    assert int(find_player(conn, "stefan")["diamond"]) == 5000 - 700 - 400
    res = buy(23)                                           # 28 + 23 > 50
    assert (res.signet_fight_cnt, res.signet_buy_cnt) == (28, 8)
    res.SerializeToString()
    # A spent bought fight does not start the recovery clock.
    assert signet.spend_fights(conn, cfg, pid, 1) == 27
    assert signet.settle_fights(conn, cfg, pid, now=time.time() + 10 * 1800) == 27


def test_query_rolls_attrs_once_and_keeps_them(reg, settings, cfg, world) -> None:
    conn, pid, _h, session = world
    first = add_signet(conn, pid, PART2_Q3)
    special = add_signet(conn, pid, STAR6_SPECIAL)
    h = _sig_handlers(reg, settings, conn, cfg)
    res = h[(5, 2805)](session, reg.message_class("SignetQueryReq")())
    a, b = res.signets
    assert a.id == first and len(a.main_attrs) == 1 and len(a.sub_attrs) == 2
    pool = {int(r["attribute_type"]) for r in cfg.signet_attributes()
            if int(r["entry"]) in (101, 102, 103, 104, 105, 106, 110)}
    assert a.main_attrs[0].attr_type in pool
    types = [x.attr_type for x in list(a.main_attrs) + list(a.sub_attrs)]
    assert len(set(types)) == 3
    assert [(x.attr_type, x.attr_value) for x in b.main_attrs] == [(9, 176)]
    assert [(x.attr_type, round(x.attr_value, 6)) for x in b.sub_attrs] == [
        (81, 0.035), (89, 0.03), (12, 220), (13, 220)]
    stored = _signet_row(conn, first)["main_attrs"]
    again = _sig_handlers(reg, settings, conn, cfg, random.Random(99))[(5, 2805)](
        session, reg.message_class("SignetQueryReq")())
    assert _signet_row(conn, first)["main_attrs"] == stored
    assert list(again.signets[0].sub_attrs) == list(a.sub_attrs)
    res.SerializeToString()


def test_equip_unequip_cost_by_star(reg, settings, cfg, world) -> None:
    conn, pid, _h, session = world
    from server.db import grant_hero
    grant_hero(conn, pid, HERO, 10, star=1, level=10)
    h = _sig_handlers(reg, settings, conn, cfg)
    old = _owned_signet(conn, cfg, pid, PART1)["id"]
    new = _owned_signet(conn, cfg, pid, 10101021)["id"]       # also part 1
    star6 = _owned_signet(conn, cfg, pid, STAR6_SPECIAL)["id"]
    equip = lambda sid: h[(5, 2733)](session, reg.message_class("SignetEquipReq")(hero_entry=HERO, signet_id=sid))
    unequip = lambda sid: h[(5, 2735)](session, reg.message_class("SignetUnequipReq")(hero_entry=HERO, signet_id=sid))
    equip(old).SerializeToString()
    assert int(_signet_row(conn, old)["hero"]) == HERO
    assert _hero_values(session, HERO)["signet0"] == old
    # A second part-1 signet replaces the first, which is gone (fu00032).
    equip(new)
    assert _signet_row(conn, old) is None
    assert int(_signet_row(conn, new)["hero"]) == HERO
    session.outbox.clear()
    unequip(new).SerializeToString()                         # star 1: 20 diamonds
    assert int(_signet_row(conn, new)["hero"]) == 0
    assert int(find_player(conn, "stefan")["diamond"]) == 5000 - 20
    assert _hero_values(session, HERO)["signet0"] == 0
    assert _player_values(session, "diamond") == [5000 - 20]
    equip(star6)
    conn.execute("UPDATE players SET diamond = 999 WHERE id = ?", (pid,))
    conn.commit()
    unequip(star6)                                           # star 6: 1000 > 999
    assert int(_signet_row(conn, star6)["hero"]) == HERO
    assert int(find_player(conn, "stefan")["diamond"]) == 999
    # Not the player's hero / not a signet: nothing changes.
    equip(99999999)
    h[(5, 2733)](session, reg.message_class("SignetEquipReq")(hero_entry=1, signet_id=new))
    assert int(_signet_row(conn, new)["hero"]) == 0


def test_level_up_charges_row_and_fails_338109_with_rng(reg, settings, cfg, world, caplog) -> None:
    conn, pid, _h, session = world
    conn.execute("UPDATE players SET signet_essence = 1000 WHERE id = ?", (pid,))
    conn.commit()
    row = _owned_signet(conn, cfg, pid, PART1)
    main0 = json.loads(row["main_attrs"])[0]["attr_value"]
    up = lambda h, **kw: h[(5, 2737)](session, reg.message_class("SignetLevelUpReq")(signet_id=row["id"], **kw))
    # Level 0 star 1: success_rate 1, 15 essence + 150 gold.
    res = up(_sig_handlers(reg, settings, conn, cfg, FixedRng(0.5)))
    assert res.signet.level == 1
    grow = next(float(r["grow_value"]) for r in cfg.signet_attributes() if int(r["entry"]) == 102)
    assert res.signet.main_attrs[0].attr_value == pytest.approx(main0 + grow)
    p = find_player(conn, "stefan")
    assert (int(p["signet_essence"]), int(p["gold"])) == (985, 100000 - 150)
    # Level 1 -> 2 is a multiple of 3 with 0 subs: add_chance 1, one sub appears.
    res = up(_sig_handlers(reg, settings, conn, cfg, FixedRng(0.5)))
    assert res.signet.level == 2 and len(res.signet.sub_attrs) == 1
    # Level 4 (rate 0.9): a roll of 0.95 fails, costs are still paid.
    conn.execute("UPDATE signets SET level = 4 WHERE id = ?", (row["id"],))
    conn.commit()
    res = up(_sig_handlers(reg, settings, conn, cfg, FixedRng(0.95)))
    assert res.signet.level == 4
    assert "338109" in caplog.text
    p = find_player(conn, "stefan")
    assert int(p["signet_essence"]) == 985 - 30 - 75
    # The top (level 15, success_rate 0): 338110, nothing taken.
    conn.execute("UPDATE signets SET level = 15 WHERE id = ?", (row["id"],))
    conn.commit()
    res = up(_sig_handlers(reg, settings, conn, cfg, FixedRng(0.0)))
    assert res.signet.level == 15 and "338110" in caplog.text
    assert int(find_player(conn, "stefan")["signet_essence"]) == 880
    # Short of essence: 338108.
    conn.execute("UPDATE signets SET level = 0 WHERE id = ?", (row["id"],))
    conn.execute("UPDATE players SET signet_essence = 0 WHERE id = ?", (pid,))
    conn.commit()
    res = up(_sig_handlers(reg, settings, conn, cfg, FixedRng(0.0)))
    assert res.signet.level == 0 and "338108" in caplog.text
    res.SerializeToString()


def test_extreme_level_up_pays_diamonds_until_success(reg, settings, cfg, world) -> None:
    """至尊进阶: cost_diamond per try, stops at the first success
    (fu00076), answers the tries and diamonds spent (fu00077)."""
    conn, pid, _h, session = world
    row = _owned_signet(conn, cfg, pid, PART1, level_=4)        # rate 0.9, 30 diamonds

    class Seq(random.Random):
        def __init__(self, rolls):
            super().__init__(5)
            self._rolls = list(rolls)

        def random(self):
            return self._rolls.pop(0) if self._rolls else 0.0

    h = _sig_handlers(reg, settings, conn, cfg, Seq([0.95, 0.95, 0.1]))
    res = h[(5, 2737)](session, reg.message_class("SignetLevelUpReq")(
        signet_id=row["id"], is_extreme=True, extreme_count=10))
    assert res.signet.level == 5
    assert (res.extreme_count, res.extreme_diamond) == (3, 90)
    p = find_player(conn, "stefan")
    assert int(p["diamond"]) == 5000 - 90 and int(p["gold"]) == 100000


def test_decompose_pays_essence(reg, settings, cfg, world) -> None:
    conn, pid, _h, session = world
    a = _owned_signet(conn, cfg, pid, PART1, level_=0)["id"]    # 50 essence, 0 gold
    b = _owned_signet(conn, cfg, pid, PART1, level_=3)["id"]    # 70 essence, 200 gold
    h = _sig_handlers(reg, settings, conn, cfg)
    res = h[(5, 2739)](session, reg.message_class("SignetDecomposeReq")(signet_ids=[a, b]))
    assert sorted((p.category, p.amount) for p in res.prizes) == [(1, 200), (75, 120)]
    assert _signet_row(conn, a) is None and _signet_row(conn, b) is None
    p = find_player(conn, "stefan")
    assert int(p["signet_essence"]) == 120 and int(p["gold"]) == 100000 + 200
    assert _player_values(session, "signet_essence") == [120]
    res.SerializeToString()
    # An equipped signet is not decomposed, and nothing else in the list is.
    c = _owned_signet(conn, cfg, pid, PART1)["id"]
    d = _owned_signet(conn, cfg, pid, PART1)["id"]
    conn.execute("UPDATE signets SET hero = ? WHERE id = ?", (HERO, d))
    conn.commit()
    res = h[(5, 2739)](session, reg.message_class("SignetDecomposeReq")(signet_ids=[c, d]))
    assert list(res.prizes) == []
    assert _signet_row(conn, c) is not None


def test_bonus_sums_equipped_attrs(reg, settings, cfg, world) -> None:
    conn, pid, _h, session = world
    from server.db import grant_hero
    hero_id = grant_hero(conn, pid, HERO, 10, star=1, level=10)
    worn = _owned_signet(conn, cfg, pid, STAR6_SPECIAL)["id"]   # main 9|176, subs 81/89/12/13
    _owned_signet(conn, cfg, pid, STAR6_SPECIAL)                 # in the bag: does not count
    conn.execute("UPDATE signets SET hero = ? WHERE id = ?", (HERO, worn))
    conn.commit()
    hero_row = conn.execute("SELECT * FROM heroes WHERE id = ?", (hero_id,)).fetchone()
    out = signet.bonus(conn, cfg, hero_row)
    base = signet.base_unit(cfg, hero_row)
    assert out["power"] == pytest.approx(176 + 0.03 * base["power"])
    assert out["magic"] == pytest.approx(176 + 0.03 * base["magic"])
    assert out["max_hp"] == pytest.approx(0.035 * base["max_hp"])
    assert out["crit_base"] == pytest.approx(220)
    assert out["crit_damage_base"] == pytest.approx(220)
    assert "defence" not in out


def test_equip_unequip_and_level_up_push_the_full_hero_stats(reg, settings, cfg, world) -> None:
    """C1: a worn signet's attributes are in ClientHero.unit, so equip,
    unequip and a level-up of a worn signet push every unit stat."""
    from server.db import grant_hero
    from server.modules import hero

    conn, pid, _h, session = world
    grant_hero(conn, pid, HERO, 10, star=1, level=10)
    conn.execute("UPDATE players SET signet_essence = 1000 WHERE id = ?", (pid,))
    conn.commit()
    h = _sig_handlers(reg, settings, conn, cfg, FixedRng(0.5))
    sid = _owned_signet(conn, cfg, pid, PART1)["id"]

    def built():
        row = conn.execute("SELECT * FROM heroes WHERE entry = ?", (HERO,)).fetchone()
        return hero.build_client_hero_with_runes(
            reg, cfg, row, hero.runes_of(conn, row), conn=conn
        )

    def check(extra: dict) -> None:
        got, want = _hero_values(session, HERO), built()
        for name in hero.STAT_NAMES:
            assert got[name] == pytest.approx(getattr(want.unit, name)), name
        assert got["ability"] == want.ability
        for k, v in extra.items():
            assert got[k] == v

    h[(5, 2733)](session, reg.message_class("SignetEquipReq")(hero_entry=HERO, signet_id=sid))
    check({"signet0": sid})
    assert built().unit != built().base_unit
    session.outbox.clear()
    h[(5, 2737)](session, reg.message_class("SignetLevelUpReq")(signet_id=sid))
    assert int(_signet_row(conn, sid)["level"]) == 1
    check({})
    session.outbox.clear()
    h[(5, 2735)](session, reg.message_class("SignetUnequipReq")(hero_entry=HERO, signet_id=sid))
    check({"signet0": 0})
    assert built().unit == built().base_unit
