"""Extract every player-visible Chinese string from the stock client (spec 3.3).

Three sources:
  ui      res/language/Language_cn.lua and Language_start_cn.lua (UI keys)
  server  res/data/split/language.db, column content (server status texts)
  config  every TEXT column of the other res/data/split/*.db tables that holds
          Chinese (names and descriptions of heroes, items, skills, ...)

A string counts when it contains at least one CJK character. Each string is
masked into a template: every ASCII digit run becomes `#`, a real newline
becomes the two characters `\\n` and a tab `\\t`, so a template is one line and
`1 级` / `25 级` share one translation.

Run: py -3.14 -m localise.extract
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from server.settings import load as load_settings

CJK = re.compile(r"[\u3400-\u9fff]")
DIGITS = re.compile(r"[0-9]+")

LUA_FILES = ("Language_cn.lua", "Language_start_cn.lua")

# Columns with Chinese that the player never sees: developer notes on server
# variables and the module label of each server status text.
EXCLUDED_COLUMNS = {
    ("variables", "memo"),
    ("language", "desc"),
}

# Config columns whose values are proper names: they form the glossary pass.
NAME_TABLES = {
    "hero_info": "hero",
    "angel_info": "angel",
    "item_info": "item",
    "spell_info": "skill",
    "npc_info": "npc",
    "stage_info": "stage",
    "chapter_info": "stage",
    "rune_info": "item",
    "artifact_set": "item",
    "pet_info": "angel",
}


def mask(text: str) -> tuple[str, list[str]]:
    """Return (template, digit runs in order)."""
    digits = DIGITS.findall(text)
    tpl = DIGITS.sub("#", text)
    tpl = tpl.replace("\r\n", "\n").replace("\n", "\\n").replace("\t", "\\t")
    return tpl, digits


def unmask(template: str, digits: list[str]) -> str:
    """Put the digit runs back into the `#` slots in order.

    `\\n` stays two characters: the config tables already store line breaks
    that way (279 stock strings), and a Lua writer emits `\\n` inside a quoted
    string anyway, so the escaped form is what both targets need.
    """
    parts = template.split("#")
    if len(parts) - 1 != len(digits):
        raise ValueError(
            f"template has {len(parts) - 1} '#' slots, {len(digits)} digit runs given"
        )
    out = parts[0]
    for d, p in zip(digits, parts[1:]):
        out += d + p
    return out


_LUA_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}


def _lua_unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_LUA_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_lua_strings(src: str) -> list[tuple[str, str]]:
    """Return [(key, value)] for every `key = "..."` / `'...'` / `[[...]]`.

    A small lexer, so `--` inside a string is not a comment and `--[[ ]]`
    block comments are skipped.
    """
    return [(k, v) for k, _, _, v in lua_string_spans(src)]


def lua_string_spans(src: str) -> list[tuple[str, int, int, str]]:
    """Like parse_lua_strings, with the [start, end) span of each literal."""
    out: list[tuple[str, int, int, str]] = []
    i, n = 0, len(src)
    last_ident: str | None = None
    pending_key: str | None = None
    tables: list[list] = []  # open `{`: [key it was assigned to, positional count]
    long_open = re.compile(r"\[(=*)\[")
    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    while i < n:
        c = src[i]
        start = i
        if src.startswith("--", i):
            m = long_open.match(src, i + 2)
            if m:
                end = src.find("]" + m.group(1) + "]", m.end())
                i = n if end < 0 else end + len(m.group(1)) + 2
            else:
                end = src.find("\n", i)
                i = n if end < 0 else end + 1
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            value = _lua_unescape(src[i + 1 : j])
            i = j + 1
        elif c == "[" and long_open.match(src, i):
            m = long_open.match(src, i)
            close = "]" + m.group(1) + "]"
            end = src.find(close, m.end())
            body = src[m.end() : end]
            if body.startswith("\r\n"):
                body = body[2:]
            elif body.startswith("\n"):
                body = body[1:]
            value = body.replace("\r\n", "\n")
            i = end + len(close)
        else:
            m = ident.match(src, i)
            if m:
                last_ident = m.group(0)
                pending_key = None
                i = m.end()
            elif c == "=" and not src.startswith("==", i):
                pending_key = last_ident
                last_ident = None
                i += 1
            else:
                if c == "{":
                    tables.append([pending_key or "", 0])
                elif c == "}" and tables:
                    tables.pop()
                if not c.isspace():
                    last_ident = None
                    if c != "=":
                        pending_key = None
                i += 1
            continue
        # Inside a nested table (e.g. `mojun1 = { "...", "..." }`) the key is
        # `parent.key`, or `parent[n]` for the n-th positional string.
        parent = tables[-1][0] if len(tables) >= 2 else ""
        if pending_key is not None:
            out.append((f"{parent}.{pending_key}" if parent else pending_key, start, i, value))
        elif parent:
            tables[-1][1] += 1
            out.append((f"{parent}[{tables[-1][1]}]", start, i, value))
        pending_key = None
        last_ident = None
    return out


@dataclass
class Entry:
    source: str  # ui | server | config | script | story
    location: str  # e.g. lua:Language_cn.lua:all10104, db:item_info.item_info.name:17
    column: str  # lua file, or table.column
    text: str


@dataclass
class Template:
    template: str
    sources: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    locations: list[str] = field(default_factory=list)


def _text_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in db.execute(f"PRAGMA table_info(`{table}`)")]


def iter_entries(stock_dir: Path):
    res = Path(stock_dir) / "assets/res"
    for name in LUA_FILES:
        path = res / "language" / name
        src = path.read_text(encoding="utf-8")
        for key, value in parse_lua_strings(src):
            if CJK.search(value):
                yield Entry("ui", f"lua:{name}:{key}", name, value)
    for path in sorted((res / "data/split").glob("*.db")):
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            for table in tables:
                for col in _text_columns(db, table):
                    if (table, col) in EXCLUDED_COLUMNS:
                        continue
                    source = "server" if path.name == "language.db" else "config"
                    rows = db.execute(
                        f"SELECT rowid, `{col}` FROM `{table}` "
                        f"WHERE typeof(`{col}`)='text'"
                    )
                    for rowid, value in rows:
                        if CJK.search(value):
                            yield Entry(
                                source,
                                f"db:{path.name}:{table}.{col}:{rowid}",
                                f"{table}.{col}",
                                value,
                            )
        finally:
            db.close()
    # Fourth source: Chinese literals hard-coded in the Lua (localise.scripts).
    from localise.scripts import iter_script_strings

    for s in iter_script_strings(stock_dir):
        if s.verdict == "translate":
            yield Entry("script", f"lua:{s.relpath}:{s.line}", s.relpath, s.value)
    # Fifth source: the story dialogue and speaker names (localise.story).
    from localise.story import iter_story_strings

    for s in iter_story_strings(stock_dir):
        column = "story.name" if s.is_name else "story.talk"
        yield Entry("story", f"lua:{s.relpath}:{s.line}", column, s.value)


def build_templates(entries) -> dict[str, Template]:
    out: dict[str, Template] = {}
    for e in entries:
        tpl, _ = mask(e.text)
        t = out.get(tpl)
        if t is None:
            t = out[tpl] = Template(tpl)
        t.sources.add(e.source)
        t.columns.add(e.column)
        t.locations.append(e.location)
    return out


def is_name_column(column: str) -> str | None:
    """Glossary kind for a `table.column` holding proper names, else None."""
    table, _, col = column.partition(".")
    if col == "name" and table in NAME_TABLES:
        return NAME_TABLES[table]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    args = parser.parse_args(argv)
    stock = load_settings(args.settings).stock_dir

    entries = list(iter_entries(stock))
    templates = build_templates(entries)
    print(f"{'source':8} {'strings':>8} {'unique':>8} {'chars':>9} {'templates':>9}")
    for source in ("ui", "server", "config", "script", "story"):
        es = [e for e in entries if e.source == source]
        uniq = {e.text for e in es}
        tpls = {mask(t)[0] for t in uniq}
        print(
            f"{source:8} {len(es):8} {len(uniq):8} "
            f"{sum(map(len, uniq)):9} {len(tpls):9}"
        )
    uniq = {e.text for e in entries}
    lens = sorted(len(t) for t in templates)
    print(
        f"total: {len(entries)} strings, {len(uniq)} unique, "
        f"{sum(map(len, uniq))} chars -> {len(templates)} templates, "
        f"{sum(lens)} chars, median {lens[len(lens) // 2]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
