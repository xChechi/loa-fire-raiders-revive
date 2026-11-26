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


def test_config_train_tables(cfg: Config) -> None:
    slots = cfg.train_slots()
    assert [int(r["entry"]) for r in slots] == list(range(1, 13))
    assert [int(r["entry"]) for r in slots if int(r["is_free"])] == [1, 2, 3, 11, 12]
    row = cfg.train_quality(4, 1)
    assert (int(row["diamond"]), int(row["exp_up"]), int(row["effect"])) == (880, 75, 1)
    assert int(cfg.train_quality(1, 2)["diamond"]) == 1880
    assert cfg.train_quality(1, 6) is None
    assert float(cfg.train_level_xp(8, 1)["rate"]) == pytest.approx(0.07)
    assert float(cfg.train_level_xp(8, 1)["base"]) == 0


# --- Wave 2 A6: lookups for the Phase B systems (values read 25-11-2026) ----

def test_config_gold_trails_limit_level1_is_93600(cfg: Config) -> None:
    assert int(cfg.gold_trails_limit(1)["gold"]) == 93600
    assert cfg.gold_trails_limit(0) is None
    exchange = cfg.gold_trails_exchange()
    assert [(int(r["damage"]), int(r["gold"])) for r in exchange][:2] == [
        (80000, 270), (160000, 165)
    ]
    assert len(exchange) == 5
    prizes = cfg.gold_trails_prizes()
    assert len(prizes) == 19
    assert (int(prizes[0]["damage"]), int(prizes[0]["gold"])) == (20000, 30000)
    assert [int(r["damage"]) for r in prizes] == sorted(int(r["damage"]) for r in prizes)


def test_config_herotrials_grade_1000_cd_300(cfg: Config) -> None:
    grade = cfg.herotrials_grade(1000)
    assert (int(grade["cd"]), int(grade["level"])) == (300, 30)
    assert cfg.herotrials_grade(1) is None
    stage = cfg.herotrials_stage(1010)
    assert (int(stage["vocation"]), int(stage["weekday"])) == (1, 4)
    assert int(stage["three_star_drops"]) == 802000


def test_config_angeltrials_level1_event_2(cfg: Config) -> None:
    assert int(cfg.angeltrials_level(1)["event"]) == 2
    assert int(cfg.angeltrials_level(2)["event"]) == 3
    assert cfg.angeltrials_level(0) is None
    buffs = cfg.angeltrials_buffs()
    assert len(buffs) == 21 and int(buffs[0]["cost_star"]) == 6
    assert [cfg.angeltrials_treasure_cost(n) for n in (1, 2, 4)] == [100, 200, 400]
    assert cfg.angeltrials_treasure_cost(101) is None
    drops = cfg.angeltrials_treasure_drops()
    assert len(drops) == 2068 and int(drops[0]["drop_entry"]) == 10000
    # Ranks are bands: the row is the smallest `rank` at or above the asked one.
    assert cfg.angeltrials_rank_award(1) == 510000
    assert cfg.angeltrials_rank_award(21) == 512000
    assert cfg.angeltrials_rank_award(50) == 512000
    assert cfg.angeltrials_rank_award(10_000_000) is None


def test_config_hero_runes_100000(cfg: Config) -> None:
    assert cfg.hero_runes(100000) == [1000000, 1001000, 1002000, 1003000, 1004000]
    assert cfg.hero_runes(1) is None
    rune = cfg.rune(1000000)
    assert (int(rune["rune"]), int(rune["unlock_level"])) == (10000, 30)
    # rune_level_up is keyed by rune_info.rune, not rune_info.entry.
    row = cfg.rune_level(10000, 1)
    assert (int(row["gold"]), int(row["max_hp"])) == (2000, 60)
    assert cfg.rune_level(1000000, 1) is None


# --- Wave 3 A5 lookups (read out of .stock on 26-11-2026) --------------------


def test_config_hero_breakthrough_level0_has_stone8_and_max_score180(cfg: Config) -> None:
    row = cfg.hero_breakthrough(0)
    assert row is not None
    # Every hero_breakthrough_info row stores id = NULL: a lookup on id would
    # find nothing, so finding the row proves the key is a data column.
    assert row["id"] is None
    assert int(row["breakthrough_stone"]) == 8
    assert (int(row["breakthrough_min"]), int(row["breakthrough_max"])) == (4, 8)
    assert int(row["max_score"]) == 180
    assert row["rate"] == "0:0|90:0.02|117:0.08|144:0.2|180:1"
    assert cfg.hero_breakthrough(20) is not None
    assert cfg.hero_breakthrough(21) is None


def test_config_hero_rune_develop_full_scan_is_51_rows(cfg: Config) -> None:
    # The count(*) trap (docs/protocol-coverage-2026-11-25.md): the table's
    # broken autoindex makes count(*) say 0; a full scan finds the 51 rows.
    conn = cfg.conn("hero_rune_develop_info")
    assert conn.execute("SELECT count(*) FROM hero_rune_develop_info").fetchone()[0] == 0
    rows = conn.execute("SELECT * FROM hero_rune_develop_info NOT INDEXED").fetchall()
    assert len(rows) == 51
    assert sorted(int(r["rune_develop_level"]) for r in rows) == list(range(51))


def test_parse_rate_ladder() -> None:
    from server.config import parse_rate_ladder

    assert parse_rate_ladder("0:0|90:0.02|117:0.08|144:0.2|180:1") == [
        (0, 0.0), (90, 0.02), (117, 0.08), (144, 0.2), (180, 1.0),
    ]
    assert parse_rate_ladder("0:0|225:0.02|292:0.08|360:0.2|450:1")[-1] == (450, 1.0)
    assert parse_rate_ladder("") == []


def test_config_angel_advance_level0_max_score450(cfg: Config) -> None:
    row = cfg.angel_advance(0)
    assert int(row["max_score"]) == 450
    assert (int(row["gold"]), int(row["advance_stone"])) == (10000, 2)
    assert row["rate"] == "0:0|225:0.02|292:0.08|360:0.2|450:1"
    assert cfg.angel_advance(999) is None


def test_config_hero_transmigrate_level1_needs_55_costs_300000(cfg: Config) -> None:
    row = cfg.hero_transmigrate(1)
    assert int(row["need_level"]) == 55
    assert int(row["gold_cost"]) == 300000
    assert float(row["growth_add"]) == 0.1
    assert cfg.hero_transmigrate(0) is None


def test_config_wave3_lookups_key_on_data_columns(cfg: Config) -> None:
    constellations = cfg.hero_constellations()
    assert [int(r["idx"]) for r in constellations] == list(range(8))
    assert [int(constellations[0][f"property_id{k}"]) for k in range(4)] == [3, 5, 1, 16]
    medals = cfg.bless_medals()
    assert len(medals) == 10
    assert (int(medals[0]["entry"]), int(medals[0]["bless_open_level"])) == (10000, 45)
    crystal = cfg.bless_crystal(10000, 0)
    assert (int(crystal["gold"]), int(crystal["item0"]), int(crystal["amount0"])) == (10000, 1600, 20)
    rank0, top = cfg.bless_rank(10000, 0), cfg.bless_rank(10000, 15)
    assert (int(rank0["entry"]), int(rank0["score"])) == (10000, 3000)
    assert (int(top["entry"]), int(top["score"])) == (10150, 0)
    assert cfg.bless_rank(10000, 16) is None
    assert int(cfg.angel_glory(0, 0)["cost"]) == 1
    signet = cfg.signet(10101011)
    assert (int(signet["star"]), int(signet["part"])) == (1, 1)
    upgrade = cfg.signet_upgrade(1, 0)
    assert (int(upgrade["cost_essence"]), int(upgrade["cost_gold"])) == (15, 150)
    assert len(cfg.signet_attributes()) == 66
    assert len(cfg.signet_changes()) == 150
    assert int(cfg.artifact(1500100)["position"]) == 7
    assert int(cfg.artifact_level(1)["upgrade_exp1"]) == 56
    assert int(cfg.magic_army_recommend(8010100)["hero_icon0"]) == 313000


def test_config_chest_by_entry_and_missing_raises(cfg: Config) -> None:
    """chest_info (A5b for B8): entries 1-42, all type 1, image 4007."""
    first, last = cfg.chest(1), cfg.chest(42)
    assert (int(first["type"]), int(first["drops"]), int(first["image"])) == (1, 1400000, 4007)
    assert int(last["drops"]) == 1413200
    with pytest.raises(KeyError):
        cfg.chest(43)


def test_config_signet_set_by_set_entry_and_quality(cfg: Config) -> None:
    """signet_set_info (A5b for B5), keyed (set_entry, quality) as the client
    reads it (StampRenderInfoPanel.lua:105,240): sets 1-10, qualities 1-5."""
    row = cfg.signet_set(1, 1)
    assert (int(row["entry"]), int(row["set_number"])) == (10101, 4)
    assert (int(row["set_attribute_type"]), float(row["attribute_multi"])) == (89, 0.04)
    assert int(cfg.signet_set(5, 5)["attribute_multi"]) == 1500
    assert int(cfg.signet_set(6, 5)["set_buff"]) == 15060500
    with pytest.raises(KeyError):
        cfg.signet_set(11, 1)
    with pytest.raises(KeyError):
        cfg.signet_set(1, 6)
