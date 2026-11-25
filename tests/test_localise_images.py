"""localise/images.py: the mapping table and the re-draw of image text.

The table checks against .stock skip when the stock client is not extracted.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from localise.extract import CJK
from localise.images import (
    FONT,
    STOCK_ASSETS,
    TABLE,
    Entry,
    _block,
    _stroke,
    build,
    inpaint,
    layout,
    load_table,
    name_entries,
    render,
    text_mask,
)

STOCK = Path(".stock")
GROUPS = {"main-city-buttons", "main-city-activity-buttons", "class-badges", "word-images",
          "title-words", "on-screen", "logo-login"}


# --- the table -------------------------------------------------------------------


def test_table_loads_with_one_entry_per_image_in_known_groups():
    entries = load_table()
    assert len(entries) == len({e.path for e in entries})
    assert {e.group for e in entries} <= GROUPS
    counts = {g: sum(e.group == g for e in entries) for g in GROUPS}
    assert counts["main-city-buttons"] == 31
    assert counts["class-badges"] == 6


def test_every_entry_has_chinese_source_and_english_target():
    for e in load_table():
        assert CJK.search(e.zh), e.path
        for text in [e.en] + [p["en"] for p in e.parts]:
            assert not CJK.search(text), e.path
        assert e.en or e.path.endswith("seven_txt_day.png"), e.path


def test_class_badges_use_the_glossary_class_names():
    names = {Path(e.path).name: e.en for e in load_table() if e.group == "class-badges"}
    assert names["RoleListCarrerBg1.png"] == names["roleUICardCarrer1.png"] == "Warrior"
    assert names["RoleListCarrerBg2.png"] == names["roleUICardCarrer2.png"] == "Mage"
    assert names["RoleListCarrerBg3.png"] == names["roleUICardCarrer3.png"] == "Marksman"


def test_logo_login_group_draws_league_of_angels_and_reads_discounts_as_paid_tenths():
    entries = {Path(e.path).name: e for e in load_table() if e.group == "logo-login"}
    assert len(entries) == 17
    # Option 1 of docs/screens/en-images-stage3/logo-options.jpg (owner, 24-11-2026).
    for name in ("gameLogin_Bigbg.png", "nslm_logo.png"):
        e = entries[name]
        assert e.en == "LEAGUE OF\nANGELS" and len(e.logo) == 2, name
    assert entries["gameLogin_Bigbg.png"].logo == [40, 92]
    # n折 = pay n tenths (game text 折扣:%d折 is "Discount: Pay %d0%").
    for n in range(1, 10):
        e = entries[f"discountLogo_{n}.png"]
        assert e.zh == f"{n}折!" and e.en == f"{100 - 10 * n}% OFF"


def test_unknown_key_in_the_table_fails_loudly(tmp_path: Path):
    t = tmp_path / "t.toml"
    t.write_text('[[image]]\npath = "a.png"\nzh = "字"\nen = "A"\ngroup = "g"\nbogus = 1\n',
                 encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        load_table(t)


def test_font_and_its_licence_are_in_the_repo():
    assert FONT.is_file()
    assert "SIL Open Font License" in (FONT.parent / "LilitaOne-OFL.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(not (STOCK / STOCK_ASSETS).is_dir(), reason=".stock not extracted")
def test_every_table_path_exists_in_stock_and_boxes_lie_inside():
    for e in load_table():
        src = STOCK / STOCK_ASSETS / e.path
        assert src.is_file(), e.path
        w, h = Image.open(src).size
        boxes = []
        if e.erase:
            boxes += e.erase if isinstance(e.erase[0], list) else [e.erase]
        boxes += [b for b in [e.text] + [p.get("text") for p in e.parts] if b]
        for x0, y0, x1, y1 in boxes:
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h, (e.path, (x0, y0, x1, y1), (w, h))


# --- erasing ---------------------------------------------------------------------


def _plate(w=60, h=30, plate=(40, 80, 160, 255)):
    a = np.zeros((h, w, 4), np.uint8)
    a[...] = plate
    return a


def test_light_mask_takes_white_glyphs_and_their_outline_inside_the_box_only():
    a = _plate()
    a[10:14, 10:14] = (255, 255, 255, 255)  # inside the box
    a[10:14, 50:54] = (255, 255, 255, 255)  # outside the box
    e = Entry(path="x", zh="字", en="A", group="g", mask="light", grow=1, erase=[0, 0, 30, 30])
    m = text_mask(a, e)
    assert m[10:14, 10:14].all() and m[9, 9] and m[14, 14]
    assert not m[10:14, 50:54].any()
    assert not m[0, 0]


def test_several_erase_boxes_are_unioned():
    a = _plate()
    e = Entry(path="x", zh="字", en="", group="g", mask="all",
              erase=[[0, 0, 5, 5], [50, 20, 60, 30]])
    m = text_mask(a, e)
    assert m.sum() == 25 + 100


def test_inpaint_fills_the_mask_with_the_surrounding_plate():
    a = _plate()
    mask = np.zeros(a.shape[:2], bool)
    a[8:20, 20:40] = (255, 255, 255, 255)
    mask[8:20, 20:40] = True
    out = inpaint(a, mask)
    assert np.abs(out[mask].astype(int) - [40, 80, 160, 255]).max() <= 1
    assert (out[~mask] == a[~mask]).all()


def test_inpaint_keeps_transparent_surroundings_transparent():
    a = np.zeros((20, 20, 4), np.uint8)
    mask = np.zeros((20, 20), bool)
    a[5:15, 5:15] = (255, 255, 255, 255)
    mask[5:15, 5:15] = True
    assert inpaint(a, mask)[mask][:, 3].max() == 0


# --- drawing ---------------------------------------------------------------------


@pytest.mark.parametrize("text,w,h", [("Leaderboard", 76, 28), ("Divine Soul", 80, 36),
                                      ("You got a new Angel!", 380, 56), ("Day", 30, 24)])
def test_layout_fits_the_text_block_inside_the_box(text, w, h):
    e = Entry(path="x", zh="字", en=text, group="g")
    lines, size = layout(text, e, w, h)
    bw, bh, _ = _block(lines, size, _stroke(e, size))
    assert " ".join(lines) == text
    assert bw <= w and bh <= h


def test_layout_splits_two_words_onto_two_lines_when_that_is_larger():
    e = Entry(path="x", zh="字", en="Divine Soul", group="g")
    lines, _ = layout("Divine Soul", e, 70, 40)
    assert lines == ["Divine", "Soul"]
    one = Entry(path="x", zh="字", en="Divine Soul", group="g", lines=1)
    assert layout("Divine Soul", one, 70, 40)[0] == ["Divine Soul"]


def _write_stock(root: Path, rel: str, arr: np.ndarray, mode="RGBA") -> None:
    p = root / STOCK_ASSETS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(arr, "RGBA")
    (img.convert("RGB").quantize(64) if mode == "P" else img).save(p)


def test_render_keeps_the_size_and_leaves_pixels_outside_the_box_alone(tmp_path: Path):
    a = _plate(100, 40)
    a[10:30, 30:70] = (255, 255, 255, 255)
    _write_stock(tmp_path, "ui/b.png", a)
    e = Entry(path="ui/b.png", zh="字", en="Bag", group="g", mask="light", grow=2,
              erase=[20, 5, 80, 35])
    out = np.asarray(render(e, tmp_path / STOCK_ASSETS))
    assert out.shape == a.shape
    outside = np.ones(a.shape[:2], bool)
    outside[5:35, 20:80] = False
    assert (out[outside] == a[outside]).all()
    assert (out[5:35, 20:80] != a[5:35, 20:80]).any()


def test_inpaint_leaves_transparent_pixels_next_to_a_label_transparent(tmp_path: Path):
    a = np.zeros((40, 60, 4), np.uint8)
    a[:20] = (200, 60, 40, 255)  # art above
    a[22:30, 10:50] = (255, 255, 255, 255)  # label hanging below the art
    _write_stock(tmp_path, "ui/l.png", a)
    e = Entry(path="ui/l.png", zh="字", en="", group="g", mask="light", grow=3, halo=2,
              erase=[0, 20, 60, 40])
    out = np.asarray(render(e, tmp_path / STOCK_ASSETS))
    assert out[35:, :, 3].max() == 0  # was transparent, still is
    assert out[26, 30, 3] < 255  # the label fades instead of turning into a block


def test_halo_takes_dark_pixels_round_the_glyph_only():
    a = _plate(40, 20, plate=(200, 200, 40, 255))
    a[8:12, 8:12] = (255, 255, 255, 255)
    a[8:12, 13:15] = (20, 10, 5, 255)  # dark shadow 1-2 px off the glyph
    a[8:12, 3:5] = (240, 230, 60, 255)  # bright plate, same distance
    e = Entry(path="x", zh="字", en="", group="g", mask="light", grow=0, halo=3)
    m = text_mask(a, e)
    assert m[8:12, 13:15].all()
    assert not m[8:12, 3:5].any()


def test_render_reads_paletted_pngs_and_writes_rgba(tmp_path: Path):
    a = _plate(40, 20)
    _write_stock(tmp_path, "ui/p.png", a, mode="P")
    e = Entry(path="ui/p.png", zh="字", en="Hi", group="g", mode="clear", mask="opaque")
    img = render(e, tmp_path / STOCK_ASSETS)
    assert img.mode == "RGBA" and img.size == (40, 20)


def test_clear_mode_with_empty_english_leaves_a_transparent_image(tmp_path: Path):
    _write_stock(tmp_path, "ui/t.png", _plate(30, 28))
    e = Entry(path="ui/t.png", zh="天", en="", group="g", mode="clear", mask="opaque")
    assert np.asarray(render(e, tmp_path / STOCK_ASSETS))[..., 3].max() == 0


def test_build_mirrors_the_stock_path_under_the_overlay(tmp_path: Path):
    stock, out = tmp_path / "stock", tmp_path / "en"
    _write_stock(stock, "ui/sub/w.png", _plate(50, 20))
    table = tmp_path / "t.toml"
    table.write_text('[[image]]\npath = "ui/sub/w.png"\nzh = "字"\nen = "Word"\n'
                     'group = "g"\nmode = "clear"\nmask = "opaque"\n', encoding="utf-8")
    entries = build(stock, out, table)
    assert [e.path for e in entries] == ["ui/sub/w.png"]
    written = out / STOCK_ASSETS / "ui/sub/w.png"
    assert Image.open(written).size == (50, 20)
    assert (stock / STOCK_ASSETS / "ui/sub/w.png").is_file()  # stock untouched


def test_logo_mask_takes_the_blob_at_the_centre_not_specks_of_the_same_colour():
    a = _plate(80, 40, plate=(60, 90, 160, 255))
    a[12:28, 25:55] = (255, 210, 40, 255)  # the gold logo in the middle
    a[2:5, 72:76] = (255, 210, 40, 255)  # a gold speck of background art
    e = Entry(path="x", zh="字", en="", group="g", mask="logo", grow=1,
              erase=[0, 0, 80, 40])
    m = text_mask(a, e)
    assert m[12:28, 25:55].all() and m[11, 24]
    assert not m[2:5, 72:76].any()


def test_detached_mask_takes_the_glyphs_inside_a_stamp_frame_not_the_frame():
    a = np.zeros((40, 80, 4), np.uint8)
    a[2:38, 2:78] = (220, 60, 40, 255)  # the stamp frame, a ring
    a[6:34, 6:74] = 0
    a[12:28, 20:30] = (220, 60, 40, 255)  # two glyphs floating inside it
    a[12:28, 40:60] = (220, 60, 40, 255)
    e = Entry(path="x", zh="字", en="", group="g", mask="detached", erase=[0, 0, 80, 40])
    m = text_mask(a, e)
    assert m[12:28, 20:30].all() and m[12:28, 40:60].all()
    assert m.sum() == 16 * 10 + 16 * 20


def test_sold_and_claimed_stamps_and_the_check_in_ribbon_are_in_the_table():
    entries = {e.path: e for e in load_table()}
    assert entries["ui/img/img_hadSold.png"].en == "Sold"
    assert entries["ui/ui_img_yilingqu.png"].en == "Claimed"
    assert entries["ui/ui_img_yilingqu.png"].mask == "detached"
    assert entries["ui/sign_gift_bg.png"].zh == "累计签到礼包"


def test_quality_up_panel_words_and_angel_badges_are_in_the_table():
    entries = {e.path: e for e in load_table()}
    assert entries["ui/role_progressBd7.png"].zh == "进阶成功"
    assert entries["ui/role_progressBd11.png"].en == "Power:"
    assert entries["ui/role_progressBd5.png"].zh == "技能觉醒:"
    for kind in ("icon", "bar"):
        assert [entries[f"ui/angel_type_{kind}_{n}.png"].en for n in (1, 2, 3)] == [
            "Damage", "Heal", "Control"]


def test_logo_entry_draws_the_lines_centred_on_the_box_in_the_same_size(tmp_path: Path):
    a = _plate(300, 140)
    a[50:90, 100:200] = (255, 210, 40, 255)
    _write_stock(tmp_path, "ui/logo.png", a)
    e = Entry(path="ui/logo.png", zh="女神联盟", en="LEAGUE OF\nANGELS", group="g",
              mask="logo", grow=2, logo=[14, 32], erase=[90, 40, 210, 100],
              text=[90, 30, 210, 90])
    out = np.asarray(render(e, tmp_path / STOCK_ASSETS))
    assert out.shape == a.shape
    assert (out[:, :20] == a[:, :20]).all() and (out[:, -20:] == a[:, -20:]).all()
    # gold glyphs left and right of the centre, the old gold block gone round them
    gold = (out[..., 0] > 220) & (out[..., 1] > 150) & (out[..., 2] < 120)
    ys, xs = np.nonzero(gold)
    assert abs((xs.min() + xs.max()) / 2 - 150) <= 3
    assert xs.max() - xs.min() > 80
    with pytest.raises(ValueError, match="logo sizes"):
        render(Entry(path="ui/logo.png", zh="字", en="ONE LINE", group="g", mask="logo",
                     logo=[14, 32], erase=[90, 40, 210, 100]), tmp_path / STOCK_ASSETS)


@pytest.mark.skipif(not (STOCK / STOCK_ASSETS).is_dir(), reason=".stock not extracted")
def test_login_background_loses_the_chinese_logo_and_its_seal():
    e = next(x for x in load_table() if x.path == "ui/gameLogin_Bigbg.png")
    src = Image.open(STOCK / STOCK_ASSETS / e.path)
    out = render(e, STOCK / STOCK_ASSETS)
    assert out.size == src.size == (1200, 720)
    a = np.asarray(out.convert("RGB")).astype(int)
    s = np.asarray(src.convert("RGB")).astype(int)
    # the 手游 seal: bright yellow plate right of the word block, now none of it
    seal = (slice(345, 415), slice(758, 798))
    yellow = lambda p: ((p[..., 0] > 230) & (p[..., 1] > 170) & (p[..., 2] < 90)).sum()
    assert yellow(s[seal]) > 300 and yellow(a[seal]) < 20
    # the art away from the logo is the stock art
    assert (a[:300] == s[:300]).all() and (a[560:] == s[560:]).all()


def test_the_committed_table_is_the_default():
    assert TABLE.name == "images.toml" and TABLE.is_file()


# --- hero and angel names: image -> id -> the translated game text ---------------

SPLIT = Path("assets/res/data/split")


def _db(root: Path, table: str, rows: list[tuple], cols=("entry", "name")) -> None:
    import sqlite3

    p = root / SPLIT / f"{table}.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.execute(f"create table {table} ({', '.join(cols)})")
    c.executemany(f"insert into {table} values ({', '.join('?' * len(cols))})", rows)
    c.commit()
    c.close()


def _names_world(tmp_path: Path):
    stock, en = tmp_path / "stock", tmp_path / "en"
    for i in (100000, 346000):
        _write_stock(stock, f"img/hero/name/{i}.png", _plate(160, 55))
    for i in (901000, 9010002):
        _write_stock(stock, f"img/angel/name/{i}.png", _plate(160, 55))
    _db(stock, "hero_info", [(100000, "玫瑰骑士")])
    _db(en, "hero_info", [(100000, "Rose Knight")])
    _db(stock, "awaken_info", [("346000", "珍宝公主")])
    _db(en, "awaken_info", [("346000", "Treasure Princess")])
    cols = ("entry", "angel_entry", "name")
    _db(stock, "angel_info", [(1, 901000, "烈焰女神"), (2, 901000, "烈焰女神")], cols)
    _db(en, "angel_info", [(1, 901000, "Angel of Flames"), (2, 901000, "Angel of Flames")], cols)
    table = tmp_path / "t.toml"
    table.write_text(
        '[preset.hero_name]\ngroup = "hero-names"\nmode = "clear"\nmask = "opaque"\n'
        '[preset.angel_name]\ngroup = "angel-names"\nmode = "clear"\nmask = "opaque"\n'
        '[[names]]\nfolder = "img/hero/name"\npreset = "hero_name"\nmargin = [4, 3]\n'
        'sources = [["hero_info", "entry"], ["awaken_info", "entry"]]\n'
        '[[names]]\nfolder = "img/angel/name"\npreset = "angel_name"\nmargin = [4, 3]\n'
        'sources = [["angel_info", "angel_entry"]]\nalias = {"9010002" = 901000}\n',
        encoding="utf-8")
    return stock, en, table


def test_name_images_take_the_english_of_the_game_tables_by_id(tmp_path: Path):
    stock, en, table = _names_world(tmp_path)
    got = {Path(e.path).name: (e.zh, e.en, e.group, e.text) for e in name_entries(stock, en, table)}
    assert got["100000.png"] == ("玫瑰骑士", "Rose Knight", "hero-names", [4, 3, 156, 52])
    # not in hero_info: the next source (awaken_info, text ids) answers
    assert got["346000.png"][:2] == ("珍宝公主", "Treasure Princess")
    # several angel_info rows share one angel_entry and one name
    assert got["901000.png"][:2] == ("烈焰女神", "Angel of Flames")
    # the festival skin 9010002 is angel 901000 (SqlManager.lua)
    assert got["9010002.png"][:2] == ("烈焰女神", "Angel of Flames")


def test_a_name_image_with_no_row_or_two_names_fails_loudly(tmp_path: Path):
    stock, en, table = _names_world(tmp_path)
    _write_stock(stock, "img/hero/name/555000.png", _plate(160, 55))
    with pytest.raises(ValueError, match="555000"):
        name_entries(stock, en, table)
    (stock / STOCK_ASSETS / "img/hero/name/555000.png").unlink()
    import sqlite3

    c = sqlite3.connect(en / SPLIT / "angel_info.db")
    c.execute("update angel_info set name = 'Flame Angel' where entry = 2")
    c.commit()
    c.close()
    with pytest.raises(ValueError, match="901000"):
        name_entries(stock, en, table)


def test_build_renders_the_name_images_too(tmp_path: Path):
    stock, en, table = _names_world(tmp_path)
    out = tmp_path / "out"
    _db(out, "hero_info", [(100000, "Rose Knight")])
    _db(out, "awaken_info", [("346000", "Treasure Princess")])
    _db(out, "angel_info", [(1, 901000, "Angel of Flames"), (2, 901000, "Angel of Flames")],
        ("entry", "angel_entry", "name"))
    entries = build(stock, out, table)
    assert len(entries) == 4
    assert Image.open(out / STOCK_ASSETS / "img/hero/name/346000.png").size == (160, 55)


@pytest.mark.skipif(not (STOCK / STOCK_ASSETS).is_dir() or not (Path("data/en") / SPLIT).is_dir(),
                    reason=".stock or data/en not built")
def test_real_name_images_use_the_translated_game_names():
    es = name_entries(STOCK, Path("data/en"))
    by = {Path(e.path).stem: e for e in es}
    assert sum(e.group == "hero-names" for e in es) == 78
    assert sum(e.group == "angel-names" for e in es) == 31
    assert (by["100000"].zh, by["100000"].en) == ("玫瑰骑士", "Rose Knight")
    assert by["104000"].en == "Mage"
    assert by["346000"].en == "Treasure Princess"
    assert by["9010002"].en == by["901000"].en == "Angel of Flames"
    for e in es:
        assert CJK.search(e.zh) and e.en and not CJK.search(e.en), e.path
