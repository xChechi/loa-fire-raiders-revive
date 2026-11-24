"""localise/story.py: the story scripts as the fifth text source."""

import shutil
import subprocess
from pathlib import Path

import pytest

from localise.extract import CJK, Template, build_templates, iter_entries
from localise.story import STORY, iter_story_strings, story_strings
from localise.translate import category, story_pins
from localise.write import EN_DIR, Renderer, write_story

STOCK = Path(".stock")
needs_stock = pytest.mark.skipif(not (STOCK / STORY).is_dir(), reason="no .stock")

SAMPLE = (
    "local story = \r\n"
    "\t{type=\"say2\",talks={\r\n"
    "\t {url=\"10110\",name=\"公主·丽雅\",side=1,talk=\"好不容易逃出来了……\",time=1,last=2}\r\n"
    "\t,{url=\"100000\",name=\"玫瑰骑士\",side=2,talk=\"?\",time=1,last=2}\r\n"
    "\t-- {name=\"注释\"}\r\n"
    "\t}\r\n"
    "}\r\n"
    "story.fight_1_s={\r\n"
    "\t{type=\"defNpc\",url=\"304000\",id=\"cunmin1\",name=\"村民\",delay=0}\r\n"
    "\t,{type=\"say\",id=\"cunmin1\",frame=1,time=2,talk=\"救命啊，有2只怪兽！\",delay=4}\r\n"
    "}\r\n"
    "return story;\r\n"
)


def test_story_strings_are_the_chinese_talks_and_names_outside_comments():
    got = [(s.key, s.value, s.is_name, s.line) for s in story_strings(SAMPLE, "x.lua")]
    assert got == [
        ("name", "公主·丽雅", True, 3),
        ("talk", "好不容易逃出来了……", False, 3),
        ("name", "玫瑰骑士", True, 4),
        ("name", "村民", True, 9),
        ("talk", "救命啊，有2只怪兽！", False, 10),
    ]
    s = story_strings(SAMPLE, "x.lua")[0]
    assert SAMPLE[s.start : s.end] == '"公主·丽雅"'


def test_story_templates_get_their_own_categories():
    assert category(Template("你好", {"story"}, {"story.talk"})) == "story dialogue"
    assert category(Template("村民", {"story"}, {"story.name"})) == "story speaker name"
    both = Template("村民", {"story"}, {"story.name", "story.talk"})
    assert category(both) == "story dialogue"
    # A text the UI also uses stays a UI string.
    assert category(Template("确定", {"ui", "story"}, {"x.lua", "story.talk"})) == "UI string"


def test_story_pins_hero_angel_and_place_names_but_not_inside_longer_names():
    glossary = {"玫瑰骑士": "Rose Knight", "骑士": "Knight", "妖精之乡": "Fairy Realm",
                "冰雪女皇": "Snow Empress", "骷髅": "Skeleton", "女皇": "Empress"}
    kinds = {"玫瑰骑士": "hero", "骑士": "hero", "妖精之乡": "stage",
             "冰雪女皇": "npc", "骷髅": "npc", "女皇": "angel"}
    pins = story_pins(["玫瑰骑士去了妖精之乡", "骷髅和冰雪女皇", "你好"], glossary, kinds)
    assert pins == {
        "玫瑰骑士去了妖精之乡": [("妖精之乡", "Fairy Realm"), ("玫瑰骑士", "Rose Knight")],
    }
    # Names the story uses as plain words are never pinned.
    assert story_pins(["抓到你啦，入侵者..."], {"入侵者": "Invaders"}, {"入侵者": "stage"}) == {}


def test_write_story_replaces_the_literals_and_keeps_the_rest(tmp_path: Path):
    stock = tmp_path / "stock"
    (stock / STORY).mkdir(parents=True)
    (stock / STORY / "Story_1.lua").write_bytes(SAMPLE.encode("utf-8"))
    (stock / STORY / "Story_2001.lua").write_bytes("talk=\"快逃！\"".encode("gbk"))
    tr = {"公主·丽雅": "Princess Leia", "好不容易逃出来了……": "We finally got out...",
          "玫瑰骑士": "Rose Knight", "村民": "Villager",
          "救命啊，有#只怪兽！": "Help, # \"monsters\"!"}
    render = Renderer(tr, set())
    out = tmp_path / "en"
    assert write_story(stock, out, render) == (1, 5, 0)
    en = (out / STORY / "Story_1.lua").read_bytes().decode("utf-8")
    assert 'name="Princess Leia",side=1,talk="We finally got out..."' in en
    assert 'talk="Help, 2 \\"monsters\\"!",delay=4}\r\n' in en
    assert 'talk="?"' in en and '-- {name="注释"}' in en
    assert not (out / STORY / "Story_2001.lua").exists()


@needs_stock
def test_story_is_the_fifth_source_and_skips_the_gbk_file():
    strings = list(iter_story_strings(STOCK))
    files = {s.relpath for s in strings}
    assert len(files) == 89 and not any(f.endswith("Story_2001.lua") for f in files)
    assert {s.key.rsplit(".", 1)[-1] for s in strings} == {"talk", "name"}
    templates = build_templates(e for e in iter_entries(STOCK) if e.source == "story")
    assert "魔法师" in templates


@pytest.mark.skipif(not (EN_DIR / STORY).is_dir(), reason="localise.write not run")
@pytest.mark.skipif(shutil.which("luajit") is None, reason="luajit not installed")
def test_every_english_story_compiles_where_the_stock_one_does_and_has_no_chinese():
    files = sorted((EN_DIR / STORY).glob("*.lua"))
    assert len(files) == 89
    for f in files:
        assert not CJK.search(f.read_bytes().decode("utf-8")), f.name
    # Prints the files that do not compile. The stock ships two that never
    # did (Story_200002 and Story_20041 lack a comma between two talks).
    lua = "for _, p in ipairs(arg) do if not loadfile(p) then io.write(p, '\\n') end end"

    def broken(paths):
        proc = subprocess.run(["luajit", "-", *[p.as_posix() for p in paths]], input=lua,
                              capture_output=True, text=True, check=True)
        return sorted(Path(line).name for line in proc.stdout.splitlines())

    stock = broken(STOCK / STORY / f.name for f in files)
    assert stock == ["Story_200002.lua", "Story_20041.lua"]
    assert broken(files) == stock
