"""localise/scripts.py: which hard-coded Lua strings get translated."""

from localise.scripts import classify


def verdicts(src: str) -> list[tuple[str, str]]:
    return [(s.value, s.verdict) for s in classify(src, "scripts/x.lua")]


def test_ui_text_is_translated_and_comments_skipped():
    src = (
        "-- 注释不算\n"
        "--[[ 块注释 ]]\n"
        'local t = g_cocoGUI_creator:createLabel("我已详细阅读并同意", 24)\n'
        "local u = [[长字符串]]\n"
    )
    assert verdicts(src) == [("我已详细阅读并同意", "translate"), ("长字符串", "translate")]


def test_log_calls_are_excluded_even_when_nested():
    src = (
        'print("显示页签")\n'
        '__LogR("加载资源错误 .. " .. tostring(x("内层")))\n'
        'trace(string.format("%s 成功", a))\n'
    )
    assert [v for _, v in verdicts(src)] == ["log", "log", "log", "log"]


def test_lookups_are_listed_as_unsure():
    src = (
        'if name == "女神" then end\n'
        'local v = t["英雄"]\n'
        'local p = string.find(s, "的")\n'
        'local i = "图片/中文.png"\n'
    )
    assert [v for _, v in verdicts(src)] == [
        "unsure: compared with ==/~=",
        "unsure: table key",
        "unsure: argument of find()",
        "unsure: looks like a path",
    ]


def test_spans_point_at_the_literal():
    src = 'x = "你好" .. y\n'
    (s,) = classify(src, "scripts/x.lua")
    assert src[s.start : s.end] == '"你好"' and s.line == 1
