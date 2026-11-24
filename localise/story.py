"""Fifth text source: the story scripts res/assets/story/Story_*.lua.

Each file returns a table of story steps; the player sees the `talk="..."`
lines (dialogue panel or speech bubble) and the `name="..."` speakers (the
name plate of the dialogue panel, also the name a `defNpc` step gives an NPC
that talks later). Every Chinese literal in these files is one of the two, so
all of them are translated; comments are skipped by the lexer.

Story_2001.lua is GBK, not UTF-8, and does not compile (`delay"=0` in its
second step), so the client can never load it; it is skipped.

Where the text is shown:
  StoryManager (talks lists, `say2`): CCLabelTTF size 30 in a box
      (sceneWidth - 600) x 150, fitted and wrapped by patch 12;
      speaker on a 296 x 68 plate scaled 1.3, size 32, no box.
  MMChatBubble (`say`): size 24, at most 200 wide, grows downwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localise.extract import CJK, lua_string_spans

STORY = Path("assets/res/assets/story")


@dataclass(frozen=True)
class StoryString:
    relpath: str  # path under the stock root, forward slashes
    key: str  # "talk" or "name" (prefixed by the parent key inside nested tables)
    line: int
    start: int  # [start, end) of the literal in the decoded file text
    end: int
    value: str

    @property
    def is_name(self) -> bool:
        return self.key.rsplit(".", 1)[-1] == "name"


def story_strings(src: str, relpath: str) -> list[StoryString]:
    out = []
    for key, start, end, value in lua_string_spans(src):
        if CJK.search(value):
            line = src.count("\n", 0, start) + 1
            out.append(StoryString(relpath, key, line, start, end, value))
    return out


def iter_story_strings(stock_dir: Path):
    root = Path(stock_dir)
    for path in sorted((root / STORY).glob("*.lua")):
        try:
            src = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue  # Story_2001.lua: GBK and broken, never loaded
        yield from story_strings(src, path.relative_to(root).as_posix())
