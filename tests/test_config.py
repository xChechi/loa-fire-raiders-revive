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
