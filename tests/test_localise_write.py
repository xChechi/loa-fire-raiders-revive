"""localise/write.py: digit re-insertion, Lua and .db writers, round trips.

The last tests compare the real output in data/en against .stock; they skip
when `py -3.14 -m localise.write` has not been run.
"""

import shutil
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from localise.extract import CJK, DIGITS, LUA_FILES, lua_string_spans, mask
from localise.translate import PLACEHOLDER
from localise.write import (
    EN_DIR,
    LANG,
    SPLIT,
    Renderer,
    align_digits,
    cap_status,
    lua_name,
    lua_quote,
    write_db,
    write_lua,
)

STOCK = Path(".stock")


# --- number slots ------------------------------------------------------------------


def test_align_moves_percent_and_turns_to_the_english_order():
    tpl, digits = mask("前2回合提升10%命中率")
    assert align_digits(tpl, "Hit Rate +#% for the first # turns", digits) == ["10", "2"]


def test_align_keeps_order_when_english_keeps_it():
    tpl, digits = mask("造成150%伤害并眩晕2回合")
    assert align_digits(tpl, "Deals #% damage and Stuns for # turns", digits) == ["150", "2"]


def test_align_moves_decimal_slot_as_one():
    tpl, digits = mask("每回合有12.5%概率眩晕3回合")
    en = "Stuns for # turns with a #.#% chance each turn"
    assert align_digits(tpl, en, digits) == ["3", "12", "5"]


def test_align_leaves_counts_and_levels_in_order():
    tpl, digits = mask("拥有5个40级英雄符文")
    assert align_digits(tpl, "Own # Lv.# Hero Runes", digits) == ["5", "40"]
    tpl, digits = mask("可获取10~20级宝石")
    assert align_digits(tpl, "Obtain Lv.#~# Gems", digits) == ["10", "20"]


def test_align_gives_up_on_slot_count_mismatch():
    tpl, digits = mask("第1关")
    assert align_digits(tpl, "Stage # # ", digits) == ["1"]


# --- rendering ------------------------------------------------------------------------


def test_renderer_reinserts_digits_and_counts_missing():
    r = Renderer({"消耗#点体力": "Costs # Stamina"}, set())
    assert r("消耗20点体力") == "Costs 20 Stamina"
    assert r("没有翻译") is None
    assert r.missing == {"没有翻译": 1}


def test_renderer_restores_real_newlines_only_where_the_source_had_them():
    r = Renderer({"第一\\n第二": "First\\nSecond"}, set())
    assert r("第一\n第二") == "First\nSecond"
    assert r("第一\\n第二") == "First\\nSecond"


def test_renderer_capitalises_status_only_in_skill_text():
    tr = {"眩晕#回合": "stun for # turns"}
    assert Renderer(tr, {"眩晕#回合"})("眩晕2回合") == "Stun for 2 turns"
    assert Renderer(tr, set())("眩晕2回合") == "stun for 2 turns"


def test_cap_status_leaves_ing_forms_and_other_words():
    assert cap_status("stuns them, stunning and burning") == "Stuns them, stunning and burning"
    assert cap_status("a silence fell; bleed") == "a Silence fell; Bleed"


def test_lua_quote_escapes_and_keeps_existing_escapes():
    assert lua_quote('Say "hi"\\nnow') == '"Say \\"hi\\"\\nnow"'
    assert lua_quote("two\nlines\\") == '"two\\nlines\\\\"'


# --- writers on miniature inputs -----------------------------------------------------------


def test_write_lua_replaces_only_chinese_literals(tmp_path: Path):
    src = tmp_path / "Language_cn.lua"
    src.write_bytes(
        "Language = {\r\n    a1 =\"生命#\",\r\n    -- c = \"注释\",\r\n"
        "    b2 = \"MAX\",\r\n    c3 = [[规则:\r\n1.第一条]],\r\n};\r\nreturn Language\r\n"
        .replace("生命#", "生命5").encode("utf-8")
    )
    r = Renderer({"生命#": "HP #", "规则:\\n#.第一条": "Rules:\\n#. First"}, set())
    dst = tmp_path / "Language_en.lua"
    assert write_lua(src, dst, r) == (2, 0)
    out = dst.read_bytes().decode("utf-8")
    assert out == (
        "Language = {\r\n    a1 =\"HP 5\",\r\n    -- c = \"注释\",\r\n"
        "    b2 = \"MAX\",\r\n    c3 = \"Rules:\\n1. First\",\r\n};\r\nreturn Language\r\n"
    )


def test_write_db_keeps_rows_and_other_columns(tmp_path: Path):
    src = tmp_path / "t.db"
    db = sqlite3.connect(src)
    db.execute("CREATE TABLE item_info (entry INTEGER PRIMARY KEY, name TEXT, price INTEGER, code TEXT)")
    db.executemany(
        "INSERT INTO item_info VALUES (?,?,?,?)",
        [(1, "圣剑", 10, "A1"), (2, "金币#", 5, "B"), (3, "MAX", 7, "汉")],
    )
    db.commit()
    db.close()
    r = Renderer({"圣剑": "Holy Sword", "汉": "Han"}, set())
    dst = tmp_path / "en" / "t.db"
    assert write_db(src, dst, r) == (2, 1)
    rows = sqlite3.connect(dst).execute("SELECT * FROM item_info ORDER BY entry").fetchall()
    assert rows == [(1, "Holy Sword", 10, "A1"), (2, "金币#", 5, "B"), (3, "MAX", 7, "Han")]
    assert sqlite3.connect(src).execute("SELECT name FROM item_info WHERE entry=1").fetchone() == ("圣剑",)


# --- round trip over the real output ----------------------------------------------------------

needs_output = pytest.mark.skipif(
    not (EN_DIR / SPLIT).is_dir(), reason="run `py -3.14 -m localise.write` first"
)


def _non_digit_placeholders(text: str) -> Counter:
    return Counter(p for p in PLACEHOLDER.findall(mask(text)[0]) if p != "#")


@needs_output
@pytest.mark.parametrize("name", LUA_FILES)
def test_english_lua_has_the_same_keys_in_the_same_order(name):
    cn = lua_string_spans((STOCK / LANG / name).read_bytes().decode("utf-8"))
    en = lua_string_spans((EN_DIR / LANG / lua_name(name)).read_bytes().decode("utf-8"))
    assert [k for k, *_ in cn] == [k for k, *_ in en]
    for (k, _, _, zh), (_, _, _, e) in zip(cn, en):
        if CJK.search(zh):
            assert not CJK.search(e), k
            assert _non_digit_placeholders(zh) == _non_digit_placeholders(e), k
            for d in DIGITS.findall(zh):
                assert d in e, (k, d)


@needs_output
@pytest.mark.skipif(shutil.which("luajit") is None, reason="luajit not installed")
@pytest.mark.parametrize("name", LUA_FILES)
def test_luajit_loads_the_english_lua_with_every_key(name):
    # Sorted "path type" lines of every leaf, nested tables included.
    script = (
        "local out = {};"
        " local function walk(t, p) for k, v in pairs(t) do"
        "  local q = p .. '/' .. tostring(k);"
        "  if type(v) == 'table' then walk(v, q) else out[#out + 1] = q .. ' ' .. type(v) end"
        " end end;"
        " walk(dofile(PATH), ''); table.sort(out); io.write(table.concat(out, '\\n'))"
    )

    def leaves(path):
        lua = script.replace("PATH", "'" + Path(path).as_posix() + "'")
        return subprocess.run(["luajit", "-e", lua], capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout

    en = leaves(EN_DIR / LANG / lua_name(name))
    assert en and en == leaves(STOCK / LANG / name)


@needs_output
def test_every_english_db_matches_the_stock_db_except_chinese_text():
    stock_split = STOCK / SPLIT
    names = sorted(p.name for p in stock_split.glob("*.db"))
    assert names == sorted(p.name for p in (EN_DIR / SPLIT).glob("*.db"))
    for name in names:
        a = sqlite3.connect(f"file:{(stock_split / name).as_posix()}?mode=ro", uri=True)
        b = sqlite3.connect(f"file:{(EN_DIR / SPLIT / name).as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in a.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        assert tables == [r[0] for r in b.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for t in tables:
            ra = a.execute(f"SELECT rowid, * FROM `{t}` ORDER BY rowid").fetchall()
            rb = b.execute(f"SELECT rowid, * FROM `{t}` ORDER BY rowid").fetchall()
            assert len(ra) == len(rb), (name, t)
            for x, y in zip(ra, rb):
                for va, vb in zip(x, y):
                    if isinstance(va, str) and CJK.search(va) and va != vb:
                        assert not CJK.search(vb), (name, t, x[0])
                        assert _non_digit_placeholders(va) == _non_digit_placeholders(vb), (name, t, x[0])
                        for d in DIGITS.findall(va):
                            assert d in vb, (name, t, x[0], d)
                    else:
                        assert va == vb and type(va) is type(vb), (name, t, x[0])


# --- spacing and the script source ---------------------------------------------------------

from localise.write import space_for_concat


def test_renderer_keeps_the_padding_spaces_of_the_source():
    r = Renderer({"等级:   ": "Level:", "等级:": "Level:"}, set())
    assert r("等级:   ") == "Level:   "
    assert r("等级:") == "Level:"


def test_concatenated_keys_get_a_separating_space():
    assert space_for_concat("Level", True, False) == "Level "
    assert space_for_concat("Level Cap", True, False) == "Level Cap "
    assert space_for_concat("Owned: ", True, False) == "Owned: "
    assert space_for_concat("pcs", False, True) == " pcs"
    assert space_for_concat(")", False, True) == ")"
    assert space_for_concat("Level", False, False) == "Level"


@needs_output
@pytest.mark.skipif(shutil.which("luajit") is None, reason="luajit not installed")
def test_every_translated_script_still_compiles():
    files = sorted((EN_DIR / "assets/scripts").rglob("*.lua"))
    assert files
    lua = "for _, p in ipairs(arg) do assert(loadfile(p)) end io.write(#arg)"
    proc = subprocess.run(["luajit", "-", *[f.as_posix() for f in files]], input=lua,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == str(len(files))


def test_key_overrides_replace_the_translation_for_that_key_only(tmp_path: Path):
    src = tmp_path / "Language_cn.lua"
    src.write_text('L = {\n    z00004 = "已获得女神",\n    x1 = "已获得女神",\n}\n', encoding="utf-8")
    r = Renderer({"已获得女神": "Angels Obtained"}, set())
    write_lua(src, tmp_path / "en.lua", r)
    out = (tmp_path / "en.lua").read_text(encoding="utf-8")
    assert 'z00004 = "Collected"' in out and 'x1 = "Angels Obtained"' in out


def test_rebirth_count_unit_reads_rebirths_after_the_number(tmp_path: Path):
    # h07008 = "转" follows the rebirth count ("0" .. getTxt("h07008")) on the
    # hero detail and the training cells: "0 Rebirths", not "0 Spin".
    src = tmp_path / "Language_cn.lua"
    src.write_bytes('Language = {\n    h07008 = "转",\n};\n'.encode("utf-8"))
    dst = tmp_path / "Language_en.lua"
    write_lua(src, dst, Renderer({"转": "Spin"}, set()), (set(), {"h07008"}))
    assert 'h07008 = " Rebirths",' in dst.read_text(encoding="utf-8")
