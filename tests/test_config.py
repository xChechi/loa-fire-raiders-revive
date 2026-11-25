"""Config lookups against known rows of the stock tables (spec 3.1).

Every value asserted here was read out of .stock on 23-10-2026 and is quoted in
the plan. If one of these fails, the stock tree is not the one the plan read.
"""

from pathlib import Path

import pytest

from server.config import Config

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


def test_stage_one_one(cfg: Config) -> None:
    row = cfg.stage(10000)
    assert row["name"] == "飞鹰岗哨"
    assert int(row["chapter"]) == 10000
    assert int(row["energy"]) == 6
    assert int(row["gold"]) == 516
    assert int(row["player_xp"]) == 6
    assert int(row["unit_xp"]) == 20
    assert int(row["angel_xp"]) == 20
    assert int(row["visible_drops"]) == 10000
    assert int(row["invisible_drops"]) == 10005
    assert int(row["once"]) == 0
    assert int(row["maxcount"]) == 0
    assert int(row["catalog"]) == 2


def test_unknown_stage_is_none(cfg: Config) -> None:
    assert cfg.stage(999999) is None


def test_chapter_one_has_five_stages_in_idx_order(cfg: Config) -> None:
    assert [int(r["entry"]) for r in cfg.stages_in_chapter(10000)] == [
        10000, 10010, 10012, 10020, 10022
    ]


def test_next_stage_walks_the_chapter_then_the_next_chapter(cfg: Config) -> None:
    assert cfg.next_stage(10000) == 10010
    assert cfg.next_stage(10022) == int(cfg.stages_in_chapter(11000)[0]["entry"])
    assert cfg.first_stage() == 10000


def test_chapter_one(cfg: Config) -> None:
    row = cfg.chapter(10000)
    assert row["name"] == "第一章-妖精之乡"
    assert int(row["type"]) == 1
    assert int(row["idx"]) == 1
    assert int(row["star_req0"]) == 9
    assert int(row["award0"]) == 600100


def test_hero_100000_is_the_rose_knight(cfg: Config) -> None:
    assert cfg.hero(100000)["name"] == "玫瑰骑士"
    assert int(cfg.hero(100000)["star"]) == 1


def test_lowest_hero_quality_is_ten_not_the_hero_info_zero(cfg: Config) -> None:
    rows = cfg.hero_qualities(100000)
    assert int(rows[0]["quality"]) == 10
    assert int(rows[0]["prototype"]) == 100000
    assert int(cfg.hero(100000)["quality"]) == 0


def test_hero_growth_and_npc_rows(cfg: Config) -> None:
    growth = cfg.hero_growth(100000, 1)
    assert float(growth["max_hp"]) == 40.92
    assert float(growth["power"]) == 5.346
    npc = cfg.npc(100000)
    assert int(npc["max_hp"]) == 100
    assert float(npc["power"]) == 15
    assert int(npc["ability"]) == 1000
    assert int(npc["attack_type"]) == 1
    assert int(npc["normal_attack_skill"]) == 100000
    assert int(npc["skill0"]) == 1000000
    assert int(npc["skill1"]) == 0


def test_item_info_is_keyed_by_a_text_entry(cfg: Config) -> None:
    assert cfg.item(10000)["name"] == "粗布头巾"
    assert int(cfg.item(10000)["quality"]) == 1
    assert cfg.item(1100)["name"] == "小经验药水"


def test_xp_for_level(cfg: Config) -> None:
    one = cfg.xp_for_level(1)
    assert int(one["player_xp_for_next_level"]) == 12
    assert int(one["hero_xp_for_next_level"]) == 20
    assert int(one["levelup_recovery_energy"]) == 12
    assert int(one["max_energy"]) == 60
    assert int(one["hero_max_level"]) == 10
    assert int(cfg.xp_for_level(2)["max_energy"]) == 62


def test_variables(cfg: Config) -> None:
    assert cfg.variable("HERO_FIRST_ENTRY") == "100000"
    assert cfg.variable_int("HERO_GOLD_INIT", 0) == 1280000
    assert cfg.variable_int("HERO_DIAMOND_INIT", 0) == 18888
    assert cfg.variable("PLAYER_ITEMS_INIT") == "1100|3,1200|2"
    assert cfg.variable_int("PLAYER_ENERGY_RECOVER_CYCLE", 0) == 360
    assert cfg.variable_int("PLAYER_ENERGY_RECOVER", 0) == 1
    assert cfg.variable("BT_CARD_AWARD") == "100000|950816,100100|950811"
    assert cfg.variable("NO_SUCH_KEY") is None
    assert cfg.variable_int("NO_SUCH_KEY", 7) == 7


def test_gacha_rows(cfg: Config) -> None:
    row = cfg.gacha(1200000)
    assert int(row["drop_id"]) == 190000
    assert int(row["cost_type"]) == 1
    assert int(row["cost"]) == 20000
    assert int(cfg.gacha(2400000)["cost_type"]) == 9
    assert int(cfg.gacha(2400000)["cost"]) == 2000
    assert len(cfg.gachas()) == 5


def test_guide_rows(cfg: Config) -> None:
    assert int(cfg.guide(10160)["is_save"]) == 1
    assert int(cfg.guide(10160)["is_over"]) == 1
    assert int(cfg.guide(10010)["play_type"]) == 2


def test_language_texts_for_the_codes_this_plan_sends(cfg: Config) -> None:
    assert cfg.language(0) == "成功"
    assert cfg.language(327937) == "金币不足"
    assert cfg.language(327938) == "钻石不足"
    assert cfg.language(327939) == "体力不足"
    assert cfg.language(328193) == "关卡未开启"
    assert cfg.language(328196) == "没有进入关卡"
    assert cfg.language(328197) == "星级不够"
    assert cfg.language(328202) == "达到关卡重置限制"


def test_drop_chain_for_stage_one_one(cfg: Config) -> None:
    groups = cfg.drop_groups(10000)
    assert [(int(g["drop_group_id"]), float(g["probability"])) for g in groups] == [
        (10001, 1.0)
    ]
    assert cfg.drop_rows(10001) == [
        {"drop_type": 20, "item_id": 10000, "amount": 2, "weight": 1}
    ]


def test_drop_chain_reads_drop_base_2_above_the_split(cfg: Config) -> None:
    assert cfg.drop_rows(10000000) == [
        {"drop_type": 9, "item_id": 0, "amount": 1128, "weight": 1}
    ]
    assert cfg.drop_rows(10000010) == [
        {"drop_type": 1, "item_id": 0, "amount": 600000, "weight": 1}
    ]


def test_gacha_drop_group_is_weighted(cfg: Config) -> None:
    rows = cfg.drop_rows(190000)
    assert len(rows) == 125
    assert rows[0] == {"drop_type": 20, "item_id": 1000, "amount": 1, "weight": 81}
    assert any(r["drop_type"] == 30 and r["item_id"] == 100000 for r in rows)


def test_chapter_one_chest_is_deterministic(cfg: Config) -> None:
    groups = cfg.drop_groups(600100)
    assert [int(g["drop_group_id"]) for g in groups] == [600110, 600120, 600130, 600140]
    assert all(float(g["probability"]) == 1.0 for g in groups)
    assert cfg.drop_rows(600110) == [
        {"drop_type": 9, "item_id": 0, "amount": 600, "weight": 1}
    ]


def test_the_stock_tree_cannot_be_written_to(cfg: Config) -> None:
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        cfg.conn("variables").execute("UPDATE variables SET value = 1")


# --- Wave 1 lookups (read out of .stock on 24-11-2026) -----------------------
def test_angel_500000_star1_costs_ten_stones(cfg: Config) -> None:
    row = cfg.angel_by_star(500000, 1)
    assert int(row["activation_item"]) == 500000
    assert int(row["activation_item_num"]) == 10
    assert int(row["min_level"]) == 1
    assert int(row["spell0"]) == 5000000
    assert int(row["aura0"]) == 5020000
    star1 = cfg.angel_star1_rows()
    assert 500000 in {int(r["angel_entry"]) for r in star1}
    assert all(int(r["star"]) == 1 and int(r["activation_item_num"]) != 0 for r in star1)


def test_angel_500000_star2_costs_twenty(cfg: Config) -> None:
    assert int(cfg.angel_by_star(500000, 2)["activation_item_num"]) == 20
    assert cfg.angel_by_star(500000, 99) is None


def test_item_composite_30000_needs_five_31000_and_1500_gold(cfg: Config) -> None:
    row = cfg.item_composite(30000)
    assert (int(row["item0"]), int(row["amount0"])) == (31000, 5)
    assert int(row["item1"]) == 0
    assert int(row["cost"]) == 1500
    assert cfg.item_composite(999999999) is None


def test_hero_quality_100000_q10_slots(cfg: Config) -> None:
    row = cfg.hero_quality_row(100000, 10)
    assert [int(row[f"item{i}"]) for i in range(6)] == [
        10000, 11010, 11120, 11040, 11020, 11170
    ]
    assert int(row["next"]) == 20
    assert cfg.hero_quality_row(100000, 0) is None


def test_event_10270_is_kind1_arg5_drop150260(cfg: Config) -> None:
    row = cfg.event(10270)
    assert (int(row["catalog"]), int(row["kind"]), int(row["arg0"])) == (0, 1, 5)
    assert int(row["drops"]) == 150260
    assert 10270 in {int(r["entry"]) for r in cfg.events_catalog(0)}
    assert all(int(r["parent"]) == 10270 for r in cfg.event_children(10270))


def test_checkin_months_end_at_202312(cfg: Config) -> None:
    months = cfg.checkin_months()
    assert months[0] == 201406
    assert months[-1] == 202312
    assert months == sorted(months)
    rows = cfg.checkin_rows(202311)
    assert [int(r["idx"]) for r in rows] == sorted(int(r["idx"]) for r in rows)
    assert (int(rows[0]["refer_type"]), int(rows[0]["refer_id"])) == (20, 30000154)
    assert int(cfg.checkin_extreme(1)["drops"]) == 1700000


def test_check_award_10001_times5(cfg: Config) -> None:
    row = cfg.check_award(10001)
    assert int(row["times"]) == 5
    assert int(row["next"]) == 10002


def test_vip_value_energy_buys_vip0_is_0_vip1_is_3(cfg: Config) -> None:
    assert cfg.vip_value(10000, 0) == "0"
    assert cfg.vip_value(10000, 1) == "3"


def test_buy_gold_cost_first_is_50(cfg: Config) -> None:
    assert cfg.buy_gold_cost(1) == 50
    assert cfg.buy_gold_cost(301) is None


def test_store_1_free_refresh_4_amount_8(cfg: Config) -> None:
    row = cfg.store(1)
    assert (int(row["free_refresh"]), int(row["merchandise_amount"])) == (4, 8)
    goods = cfg.merchandise(1)
    assert len(goods) == 244
    assert all(int(r["store"]) == 1 for r in goods)


def test_mail_template_and_item_buy(cfg: Config) -> None:
    assert int(cfg.mail_template(99999)["entry"]) == 99999
    row = cfg.item_buy(1210800)
    assert (int(row["category"]), int(row["rate"])) == (20, 500)


def test_config_function_unlock_10050_is_5_and_10040_is_8(cfg: Config) -> None:
    """functions.db, table `function`: 英雄技能 5, 训练 8."""
    assert cfg.function_unlock(10050) == 5
    assert cfg.function_unlock(10040) == 8
    with pytest.raises(KeyError):
        cfg.function_unlock(1)


def test_config_spell_and_spell_level_up(cfg: Config) -> None:
    assert int(cfg.spell(1000000)["next"]) == 1000001
    assert int(cfg.spell(1000001)["upgrade_cost"]) == 1000
    assert cfg.spell(1) is None
    assert int(cfg.spell_level_up(3)["spell0"]) == 2
    assert int(cfg.spell_level_up(5)["spell1"]) == 2
