"""localise/: masking, Lua parsing, placeholder validation, line parsing.

No network: the API layer is not exercised here.
"""

import pytest

from localise.extract import Template, build_templates, Entry, mask, parse_lua_strings, unmask
from localise.translate import (
    check_line,
    format_batch,
    parse_numbered,
    placeholders,
    select_sample,
    validate_batch,
)


# --- masking -----------------------------------------------------------------


def test_mask_replaces_each_digit_run_with_hash():
    assert mask("消耗20点体力，第3关") == ("消耗#点体力，第#关", ["20", "3"])


def test_mask_turns_real_newlines_and_tabs_into_escapes():
    assert mask("第一行\n第二行\r\n\t第三")[0] == "第一行\\n第二行\\n\\t第三"


def test_mask_keeps_existing_escaped_newline():
    assert mask("巨石陨落:\\n眩晕1-2个单位")[0] == "巨石陨落:\\n眩晕#-#个单位"


def test_unmask_round_trips_digits():
    text = "提升10%命中率，持续2回合"
    tpl, digits = mask(text)
    assert unmask(tpl, digits) == text
    assert unmask("Accuracy +#% for # turns", digits) == "Accuracy +10% for 2 turns"


def test_unmask_rejects_slot_count_mismatch():
    with pytest.raises(ValueError):
        unmask("only # here", ["1", "2"])


def test_same_template_for_different_numbers():
    entries = [
        Entry("config", "a", "t.c", "等级1"),
        Entry("config", "b", "t.c", "等级25"),
    ]
    ts = build_templates(entries)
    assert list(ts) == ["等级#"]
    assert ts["等级#"].locations == ["a", "b"]


# --- Lua parsing ---------------------------------------------------------------


def test_parse_lua_strings_quoted_long_and_comments():
    src = (
        "--[[ header ]]\n"
        "local Language = nil;\n"
        "Language = {\n"
        '    a1 ="生命",\n'
        "    -- b2 = \"注释\",\n"
        '    c3 = "试炼 -- 请先完成\\n第二行",\n'
        "    d4 = [[规则:\n1.第一条\n]],\n"
        "    e5 = '单引号',\n"
        "};\n"
    )
    assert parse_lua_strings(src) == [
        ("a1", "生命"),
        ("c3", "试炼 -- 请先完成\n第二行"),
        ("d4", "规则:\n1.第一条\n"),
        ("e5", "单引号"),
    ]


# --- placeholder validation ------------------------------------------------------


def test_placeholders_counts_each_kind():
    c = placeholders("消耗#点%s，{0}次\\n$|$")
    assert c == {"#": 1, "%s": 1, "{0}": 1, "\\n": 1, "$": 2, "|": 1}


@pytest.mark.parametrize(
    "en",
    ["Deals #%-damage boost", "+#%defense for # turns", "Gain #%damage and #%speed"],
)
def test_percent_followed_by_english_word_is_not_a_slot(en):
    assert placeholders(en) == {"#": en.count("#")}
    assert check_line("造成#%伤害" + "#" * (en.count("#") - 1), en) is None


def test_percent_slot_before_chinese_or_unit_still_counts():
    assert placeholders("需要更新%sm资源") == {"%s": 1}
    assert placeholders("%d%%") == {"%d": 1}


def test_check_line_accepts_good_translation():
    assert check_line("消耗#点体力\\n确定?", "Costs # Stamina\\nConfirm?") is None


@pytest.mark.parametrize(
    "src,en,why",
    [
        ("消耗#点体力", "Costs some Stamina", "placeholders"),
        ("消耗#点体力", "Costs # # Stamina", "placeholders"),
        ("第一\\n第二", "First Second", "placeholders"),
        ("获得%s", "Obtained %d", "placeholders"),
        ("+$怒气", "+Rage", "placeholders"),
        ('<content><text value="加入" color="#"/></content>', '<text value="Joined" color="#"/>', "tags"),
        ("确定", "确定", "Chinese"),
        ("确定", "  ", "empty"),
    ],
)
def test_check_line_rejects(src, en, why):
    assert why in check_line(src, en)


def test_check_line_allows_translated_tag_value():
    src = '<content> <text value="|加入了公会" color ="#" tag="#"/> </content>'
    en = '<content> <text value="| joined the guild" color ="#" tag="#"/> </content>'
    assert check_line(src, en) is None


# --- line parsing ------------------------------------------------------------------


def test_format_batch_numbers_from_one():
    assert format_batch(["确定", "取消"]) == "1. 确定\n2. 取消"


def test_parse_numbered_ok_with_blank_lines():
    assert parse_numbered("1. OK\n\n2. Cancel\n", 2) == ["OK", "Cancel"]


def test_parse_numbered_keeps_text_starting_with_number_slot():
    assert parse_numbered("1. #. Reach level #", 1) == ["#. Reach level #"]


@pytest.mark.parametrize(
    "reply",
    [
        "1. OK",  # missing line
        "1. OK\n2. Cancel\n3. More",  # extra line
        "1. OK\n1. Again",  # duplicate
        "1. OK\nCancel",  # unnumbered continuation
        "Here you go:\n1. OK\n2. Cancel",  # preamble
    ],
)
def test_parse_numbered_rejects(reply):
    with pytest.raises(ValueError):
        parse_numbered(reply, 2)


def test_validate_batch_reports_bad_line():
    lines, problems = validate_batch(["消耗#点", "确定"], "1. Costs\n2. OK")
    assert lines == ["Costs", "OK"]
    assert problems and problems[0].startswith("line 1:")


def test_validate_batch_parse_error():
    lines, problems = validate_batch(["确定"], "nothing numbered")
    assert lines == [] and "unnumbered" in problems[0]


# --- sample selection ----------------------------------------------------------------


def test_select_sample_is_deterministic_and_disjoint():
    ts = {}
    for i in range(30):
        ts[f"英雄{chr(0x4E00 + i)}"] = Template(f"英雄{chr(0x4E00 + i)}", {"config"}, {"hero_info.name"})
        ts[f"界面{chr(0x4E00 + i)}"] = Template(f"界面{chr(0x4E00 + i)}", {"ui"}, {"Language_cn.lua"})
    a = select_sample(ts, 200)
    b = select_sample(ts, 200)
    assert a == b
    names, others = a
    assert {it.kind for it in names} == {"hero"}
    assert {it.kind for it in others} == {"UI string"}
    assert not {it.template for it in names} & {it.template for it in others}


# --- full run helpers ------------------------------------------------------------------

from localise.translate import Item, batches, full_plan, glossary_mismatches, reject_records


def test_batches_cap_count_and_chars():
    items = [Item("字" * 10, "k") for _ in range(100)]
    sizes = [len(b) for b in batches(items, max_n=40, max_chars=10_000)]
    assert sizes == [40, 40, 20]
    sizes = [len(b) for b in batches(items, max_n=40, max_chars=95)]
    assert sizes == [9] * 11 + [1]


def test_batches_oversized_item_goes_alone():
    items = [Item("短", "k"), Item("长" * 50, "k"), Item("短", "k")]
    assert [len(b) for b in batches(items, max_n=40, max_chars=20)] == [1, 1, 1]


def test_reject_records_name_the_offending_line():
    recs = reject_records(
        ["确定", "消耗#点"], ["OK", "Costs"], ["line 2: placeholders differ"], "raw"
    )
    assert recs == ["placeholders differ\t消耗#点\tCosts"]


def test_reject_records_whole_reply_when_unparseable():
    recs = reject_records(["确定"], [], ["unnumbered line: 'x'"], "x\ny")
    assert recs == ["unnumbered line: 'x'\t(whole batch)\tx\\ny"]


def test_full_plan_orders_heroes_first_and_texts_last():
    ts = {
        "玫瑰骑士": Template("玫瑰骑士", {"config"}, {"hero_info.name"}),
        "圣剑": Template("圣剑", {"config"}, {"item_info.name"}),
        "确定": Template("确定", {"ui"}, {"Language_cn.lua"}),
    }
    first, names, texts = full_plan(ts)
    assert [it.template for it in first] == ["玫瑰骑士"]
    assert [it.template for it in names] == ["圣剑"]
    assert [(it.template, it.kind) for it in texts] == [("确定", "UI string")]


def test_glossary_mismatches_finds_other_rendering():
    gl = {"玫瑰骑士": "Rose Knight", "天马骑士": "Pegasus Knight", "火": "Fire"}
    tx = {
        "玫瑰骑士的普通攻击": "Rose Knight's basic attack",
        "玫瑰骑士的技能": "Skill of the Knight of Roses",
        "天马骑士的普通攻击": "pegasus knight's basic attack",
        "火焰": "Flame",
    }
    assert glossary_mismatches(gl, tx) == [
        ("玫瑰骑士", "Rose Knight", 1, 2, "玫瑰骑士的技能", "Skill of the Knight of Roses")
    ]
