"""Write the English client and server data from localise/cache.sqlite.

Output (git-ignored), a mirror of the stock layout:
  data/en/assets/res/language/Language_en.lua        (from Language_cn.lua)
  data/en/assets/res/language/Language_start_en.lua  (from Language_start_cn.lua)
  data/en/assets/res/data/split/*.db                 (all 144 tables copied,
                                                      Chinese text cells replaced)
  data/en/assets/scripts/**/*.lua                    (hard-coded UI text)
  data/en/assets/res/assets/story/Story_*.lua        (story dialogue, speakers)

Every Lua file keeps its keys, order, comments and line endings; only the
string literals that hold Chinese are replaced (as double-quoted literals).
Every .db copy keeps its rows and non-text values; only TEXT cells that hold
Chinese are UPDATEd, by rowid. .stock is only read.

The digit runs masked out by extract.py go back in. A translation may reorder
the number slots ("持续#回合，提升#%" -> "+#% for # turns"), so slots are
matched by the unit next to them (%, turns, times, ...) before the digits are
put back; slots without a recognisable unit keep their order.

Run: py -3.14 -m localise.write
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from localise.extract import (
    CJK,
    EXCLUDED_COLUMNS,
    LUA_FILES,
    build_templates,
    iter_entries,
    lua_string_spans,
    mask,
    unmask,
)
from localise.scripts import iter_script_strings
from localise.story import iter_story_strings
from localise.translate import CACHE, category, cached, open_cache
from server.settings import load as load_settings

EN_DIR = Path("data/en")
SPLIT = Path("assets/res/data/split")
LANG = Path("assets/res/language")

# --- number slots ----------------------------------------------------------

SLOT = re.compile(r"#(?:\.#)?")

# Only units that the English writes right after the number and that cannot
# be confused. Counts (个/名/把/件 vs "enemies", "Heroes", "-Piece") and levels
# ("Lv.#" comes before the number) moved digits to the wrong slot in the
# 23-11-2026 probe, so those slots keep their order instead.
_ZH_UNITS = [
    ("pct", r"%"), ("turn", r"回合"), ("time", r"次"), ("sec", r"秒"),
    ("star", r"星"), ("stack", r"层"), ("day", r"天"), ("hour", r"小时"),
    ("min", r"分钟"), ("mult", r"倍"),
]
_EN_UNITS = [
    ("pct", r"%"), ("turn", r"\s*-?turns?\b"), ("time", r"\s*-?times?\b"),
    ("sec", r"\s*-?s(?:ec(?:ond)?s?)?\b"), ("star", r"\s*-?stars?\b"),
    ("stack", r"\s*-?(?:stacks?|layers?)\b"), ("day", r"\s*-?days?\b"),
    ("hour", r"\s*-?(?:hours?|h)\b"), ("min", r"\s*-?(?:minutes?|min)\b"),
    ("mult", r"x\b"),
]


def _slots(text: str, units) -> list[tuple[str, int]]:
    """[(class, number of '#' in the slot)] in order of appearance."""
    out = []
    for m in SLOT.finditer(text):
        tail = text[m.end():]
        cls = "?"
        for name, pat in units:
            if re.match(pat, tail, re.I):
                cls = name
                break
        out.append((cls, m.group(0).count("#")))
    return out


def align_digits(zh_template: str, en_template: str, digits: list[str]) -> list[str]:
    """Digit runs reordered to the slot order of the English template."""
    zs = _slots(zh_template, _ZH_UNITS)
    es = _slots(en_template, _EN_UNITS)
    if len(zs) != len(es) or sum(n for _, n in zs) != len(digits):
        return digits
    groups, k = [], 0
    for _, n in zs:
        groups.append(digits[k : k + n])
        k += n
    used = [False] * len(zs)
    pick: list[int | None] = [None] * len(es)
    for j, (cls, n) in enumerate(es):
        if cls == "?":
            continue
        for i, (zc, zn) in enumerate(zs):
            if not used[i] and zc == cls and zn == n:
                used[i], pick[j] = True, i
                break
    for j, (cls, n) in enumerate(es):
        if pick[j] is None:
            for i, (zc, zn) in enumerate(zs):
                if not used[i] and zn == n:
                    used[i], pick[j] = True, i
                    break
    if None in pick:
        return digits
    return [d for i in pick for d in groups[i]]


# --- status effects ----------------------------------------------------------

# One rule: in skill/buff descriptions the status effects are capitalised,
# as most of the run already wrote them ("Stun", "Silence"); -ing forms stay.
STATUS = re.compile(
    r"\b(stun|stuns|stunned|silence|silences|silenced|bleed|bleeds|burn|burns"
    r"|poison|poisons|poisoned|frozen|petrify|petrified|polymorph)\b"
)


def cap_status(en: str) -> str:
    return STATUS.sub(lambda m: m.group(1).capitalize(), en)


# --- rendering -----------------------------------------------------------------


class Renderer:
    def __init__(self, tr: dict[str, str], skill_templates: set[str]) -> None:
        self.tr = tr
        self.skill = skill_templates
        self.missing: Counter = Counter()
        self.reordered: dict[str, str] = {}

    def __call__(self, text: str) -> str | None:
        """English for one stock string, or None when not translated."""
        tpl, digits = mask(text)
        en = self.tr.get(tpl)
        if en is None:
            self.missing[tpl] += 1
            return None
        if tpl in self.skill:
            en = cap_status(en)
        aligned = align_digits(tpl, en, digits)
        if aligned != digits:
            self.reordered[tpl] = en
        out = unmask(en, aligned)
        # A cell that stored real line breaks gets real ones back.
        if "\n" in text and "\\n" not in text:
            out = out.replace("\\n", "\n").replace("\\t", "\t")
        # Padding spaces of the source ("等级:   " before a value) survive;
        # the translation pass strips them.
        lead = len(text) - len(text.lstrip(PAD))
        trail = len(text) - len(text.rstrip(PAD))
        if lead or trail:
            out = " " * lead + out.strip(PAD) + " " * trail
        return out


PAD = " 　"

# Language keys whose label sits in a box sized for 3-5 Chinese characters,
# with a value or another label right next to it. Shorter English that keeps
# the meaning; picked on the 23-11-2026 screenshots.
KEY_OVERRIDES = {
    "h07001": "Rebirth Lv:",   # 转生等级: hero detail, value follows
    "h07002": "Rebirth Req:",  # 转生需求: hero detail, value follows
    "c00140": "Select",        # 选区: login, under the button at x 250; longer sticks out left
    "h07008": "Rebirths",      # 转: unit after the rebirth count ("0 Rebirths"), not "Spin"
    "z00004": "Collected",     # 已获得女神: angel screen, "0/30" 130 px to the right
    "z00006": "Locked",        # 未召唤: angel screen, right-aligned under the name
    "x07016": "Drops",         # 可能掉落: stage info, icons follow
    "z00201": "Drops",         # 可能掉落: item source panel, 120 px box
    "z00221": "Cost:",         # 消耗体力: stage info, 120 px box, stamina icon follows
}

# g_lan:getTxt("key") .. value  /  value .. g_lan:getTxt("key")
_CONCAT_AFTER = re.compile(r'getTxt\(\s*"(\w+)"\s*\)\s*\.\.')
_CONCAT_BEFORE = re.compile(r'\.\.\s*g_lan:getTxt\(\s*"(\w+)"\s*\)')


def concat_keys(scripts_dir: Path) -> tuple[set[str], set[str]]:
    """Language keys glued to a value with `..` (after, before) somewhere in
    the stock Lua. Chinese needs no space there, English does ("Level2")."""
    after, before = set(), set()
    for path in Path(scripts_dir).rglob("*.lua"):
        src = path.read_bytes().decode("utf-8", errors="replace")
        after.update(_CONCAT_AFTER.findall(src))
        before.update(_CONCAT_BEFORE.findall(src))
    return after, before


def space_for_concat(en: str, after: bool, before: bool) -> str:
    if after and en and not en.endswith((" ", "(", "[", "\n", "\\n", "/", "+", "-", "x", "*")):
        en += " "
    if before and en and not en.startswith((" ", ")", "]", ",", ".", ":", ";", "!", "?", "%", "/", "\n", "\\n")):
        en = " " + en
    return en


def lua_quote(s: str) -> str:
    """Double-quoted Lua literal; `\\n` / `\\t` escapes already in s are kept."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and s[i + 1 : i + 2] in ("n", "t"):
            out.append(s[i : i + 2])
            i += 2
            continue
        out.append(
            {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": ""}.get(c, c)
        )
        i += 1
    return '"' + "".join(out) + '"'


def write_lua(src: Path, dst: Path, render: Renderer,
              concat: tuple[set[str], set[str]] = (set(), set())) -> tuple[int, int]:
    """Returns (strings replaced, strings left in Chinese)."""
    raw = src.read_bytes().decode("utf-8")
    parts, pos, done, left = [], 0, 0, 0
    for key, start, end, value in lua_string_spans(raw):
        if not CJK.search(value):
            continue
        en = KEY_OVERRIDES.get(key) or render(value)
        if en is None:
            left += 1
            continue
        en = space_for_concat(en, key in concat[0], key in concat[1])
        parts.append(raw[pos:start])
        parts.append(lua_quote(en))
        pos = end
        done += 1
    parts.append(raw[pos:])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes("".join(parts).encode("utf-8"))
    return done, left


def write_db(src: Path, dst: Path, render: Renderer) -> tuple[int, int]:
    """Copy one .db and replace its Chinese TEXT cells. (replaced, left)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    db = sqlite3.connect(dst)
    done = left = 0
    try:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for col in [r[1] for r in db.execute(f"PRAGMA table_info(`{table}`)")]:
                if (table, col) in EXCLUDED_COLUMNS:
                    continue
                rows = db.execute(
                    f"SELECT rowid, `{col}` FROM `{table}` WHERE typeof(`{col}`)='text'"
                ).fetchall()
                updates = []
                for rowid, value in rows:
                    if not CJK.search(value):
                        continue
                    en = render(value)
                    if en is None:
                        left += 1
                    else:
                        updates.append((en, rowid))
                db.executemany(
                    f"UPDATE `{table}` SET `{col}` = ? WHERE rowid = ?", updates
                )
                done += len(updates)
        db.commit()
    finally:
        db.close()
    return done, left


def write_scripts(stock: Path, out: Path, render: Renderer) -> tuple[int, int, int]:
    """English copies of the Lua files with hard-coded Chinese UI text.
    Returns (files written, literals replaced, literals left)."""
    by_file: dict[str, list] = {}
    for s in iter_script_strings(stock):
        if s.verdict == "translate":
            by_file.setdefault(s.relpath, []).append(s)
    files = done = left = 0
    for rel, strings in sorted(by_file.items()):
        raw = (stock / "assets" / rel).read_bytes().decode("utf-8")
        parts, pos = [], 0
        for s in sorted(strings, key=lambda s: s.start):
            en = render(s.value)
            if en is None:
                left += 1
                continue
            parts.append(raw[pos : s.start])
            parts.append(lua_quote(en))
            pos = s.end
            done += 1
        parts.append(raw[pos:])
        dst = out / "assets" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes("".join(parts).encode("utf-8"))
        files += 1
    return files, done, left


def write_story(stock: Path, out: Path, render: Renderer) -> tuple[int, int, int]:
    """English copies of the story scripts (localise.story), same file names.
    Returns (files written, literals replaced, literals left)."""
    by_file: dict[str, list] = {}
    for s in iter_story_strings(stock):
        by_file.setdefault(s.relpath, []).append(s)
    files = done = left = 0
    for rel, strings in sorted(by_file.items()):
        raw = (stock / rel).read_bytes().decode("utf-8")
        parts, pos = [], 0
        for s in strings:
            en = render(s.value)
            if en is None:
                left += 1
                continue
            parts.append(raw[pos : s.start])
            parts.append(lua_quote(en))
            pos = s.end
            done += 1
        parts.append(raw[pos:])
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes("".join(parts).encode("utf-8"))
        files += 1
    return files, done, left


def lua_name(stock_name: str) -> str:
    return stock_name.replace("_cn.lua", "_en.lua")


def write_all(stock: Path, out: Path = EN_DIR, effort: str = "medium",
              cache: Path = CACHE) -> Renderer:
    templates = build_templates(iter_entries(stock))
    skill = {t for t, v in templates.items() if category(v) == "skill/buff description"}
    render = Renderer(cached(open_cache(cache), effort), skill)
    concat = concat_keys(stock / "assets/scripts")
    for name in LUA_FILES:
        done, left = write_lua(stock / LANG / name, out / LANG / lua_name(name), render, concat)
        print(f"{lua_name(name)}: {done} strings in English, {left} left")
    files, done, left = write_scripts(stock, out, render)
    print(f"scripts: {files} files, {done} literals in English, {left} left")
    files, done, left = write_story(stock, out, render)
    print(f"story: {files} files, {done} literals in English, {left} left")
    total_done = total_left = 0
    for src in sorted((stock / SPLIT).glob("*.db")):
        done, left = write_db(src, out / SPLIT / src.name, render)
        total_done += done
        total_left += left
    print(f"split/*.db: {total_done} cells in English, {total_left} left")
    print(f"number slots reordered in {len(render.reordered)} templates")
    return render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--out", type=Path, default=EN_DIR)
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args(argv)
    write_all(load_settings(args.settings).stock_dir, args.out, args.effort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
