"""Patch 12: the English text-layout hook, run under luajit with a fake engine.

The fake CCLabelTTF measures 10 px per character at size 20 (scaled by size)
and 20 px line height, so the expected wraps can be worked out by hand.
"""

import shutil
import subprocess

import pytest

from client.build_assets import ENGLISH_TEXT_HOOK, PATCHES

pytestmark = pytest.mark.skipif(shutil.which("luajit") is None, reason="luajit not installed")

FAKE_ENGINE = r"""
DEFAULT_TEXT_FONT = "msyh.ttf"; DEFAULT_TEXT_SIZE = 20
LOA_TEXT_STROKE_PAD = 0
local function size(w, h) return {width = w, height = h} end
CCSize = size
function ccp(x, y) return {x = x, y = y} end
CCLabelTTF = {}
CCLabelTTF.__index = CCLabelTTF
function CCLabelTTF.create(cls, text, font, fs, dims)
    local o = setmetatable({text = text, font = font, fs = fs, dims = dims}, CCLabelTTF)
    return o
end
function CCLabelTTF:getContentSize()
    local longest, lines = 0, 0
    for line in (self.text .. "\n"):gmatch("(.-)\n") do
        lines = lines + 1
        if #line > longest then longest = #line end
    end
    return size(longest * self.fs / 2, lines * self.fs)
end
function CCLabelTTF:getDimensions() return self.dims or size(0, 0) end
function CCLabelTTF:getFontSize() return self.fs end
function CCLabelTTF:getFontName() return self.font end
function CCLabelTTF:setFontSize(s) self.fs = s end
function CCLabelTTF:setString(t) self.text = t end
function CCLabelTTF:setRotation(r) self.rot = r end
function CCLabelTTF:setAnchorPoint(p) self.anchor = p end
Label = {}
Label.__index = Label
function Label.create(cls) return setmetatable({}, Label) end
function Label:setText(t) self.text = t end
function Label:setFontSize(s) self.fs = s end
function Label:setTextAreaSize(s) self.area = s end
"""


def run(lua: str) -> str:
    script = FAKE_ENGINE + ENGLISH_TEXT_HOOK + lua
    proc = subprocess.run(["luajit", "-"], input=script, capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_patch_12_puts_the_hook_before_the_gui_creator():
    (patch,) = [p for p in PATCHES if p.relpath.endswith("MMGUICreator.lua")]
    assert patch.new == ENGLISH_TEXT_HOOK + patch.old


def test_english_wraps_on_spaces_not_inside_words():
    out = run(
        'local l = CCLabelTTF:create("Tap here to summon an Angel", "f", 20, {width = 120, height = 200})\n'
        "io.write(l.text)"
    )
    # 10 px per char, limit 103.2 px: "Tap here" | "to summon" | "an Angel"
    assert out == "Tap here\nto summon\nan Angel"


def test_chinese_is_left_to_the_engine():
    out = run(
        'local l = CCLabelTTF:create("点击这里召唤女神", "f", 20, {width = 40, height = 200})\n'
        "io.write(l.text, ' ', l.fs)"
    )
    assert out == "点击这里召唤女神 20"


def test_a_word_wider_than_the_area_shrinks_the_font():
    out = run(
        'local l = CCLabelTTF:create("Breakthrough", "f", 24, {width = 100, height = 40})\n'
        "io.write(l.text, ' ', l.fs)"
    )
    # one-line box (40 < 1.8 * 24): 144 px at 24 onto 86 px -> floor(24 * 86 / 144) = 14
    assert out == "Breakthrough 14"


def test_a_tall_narrow_tab_is_turned_sideways():
    out = run(
        'local l = CCLabelTTF:create("Equip", "f", 24, {width = 33, height = 80})\n'
        "l:setAnchorPoint(ccp(1, 0.5))\n"
        "io.write(l.text, ' ', l.fs, ' ', l.rot, ' ', l.dims.width, 'x', l.dims.height,"
        " ' ', l.anchor.x, ',', l.anchor.y)"
    )
    # "Equip" is 60 px at 24 > 33: laid out 80 x 33, turned 90, anchor (1, .5) -> (.5, 1)
    assert out == "Equip 24 90 80x33 0.5,1"


def test_a_tall_tab_whose_word_fits_stays_upright():
    out = run(
        'local l = CCLabelTTF:create("Go", "f", 24, {width = 33, height = 80})\n'
        "io.write(tostring(l.rot))"
    )
    assert out == "nil"


def test_too_many_lines_shrink_until_they_fit_the_height():
    out = run(
        'local l = CCLabelTTF:create("aaaa bbbb cccc dddd", "f", 20, {width = 60, height = 45})\n'
        "io.write(l.fs)"
    )
    # 20: 4 lines * 20 = 80 > 49.5; 19..: still 4 lines until width allows two
    # words per line (9 chars * s/2 <= 57 -> s <= 12) -> 12 is the floor anyway
    assert out == "12"


def test_set_string_rewraps_from_the_original_size():
    out = run(
        'local l = CCLabelTTF:create("x", "f", 20, {width = 120, height = 200})\n'
        'l:setString("Breakthroughs everywhere")\n'
        "local a = l.fs\n"
        'l:setString("Short one")\n'
        "io.write(a, ' ', l.fs, ' ', l.text)"
    )
    # "Breakthroughs" (130 px) > 103.2 px -> 15; the next text starts again from 20
    assert out == "15 20 Short one"


def test_label_widget_wraps_once_the_area_is_known():
    out = run(
        "local l = Label:create()\n"
        'l:setText("Answering the call of the Princess")\n'
        "l:setFontSize(20)\n"
        "l:setTextAreaSize({width = 160, height = 200})\n"
        "io.write(l.text)"
    )
    assert out == "Answering the\ncall of the\nPrincess"


def test_existing_line_breaks_and_indent_are_kept():
    out = run(
        'local l = CCLabelTTF:create("Rules:\\n  i. one two", "f", 20, {width = 300, height = 200})\n'
        "io.write(l.text)"
    )
    assert out == "Rules:\n  i. one two"
