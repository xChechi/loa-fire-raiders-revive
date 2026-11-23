"""Translate digit-masked templates to English with Claude (spec 3.3).

Templates go out in line-numbered batches of 40 (plain text, not JSON); the
reply must have the same line numbers and keep every placeholder, else the
batch is retried once and then recorded as failed. Results are cached per
(template, effort) in localise/cache.sqlite, so a rerun only sends what is
missing. Names (heroes, angels, items, skills, stages, NPCs) are translated
first and fed to every later batch as a glossary.

Only the sample mode exists so far:
  py -3.14 -m localise.translate --sample 200 --efforts low,medium
writes localise/sample-report.md with usage, cost and a projection.

The API key is read from C:/Users/Stefan.Nasev/.config/loa/.env
(ANTHROPIC_API_KEY=...) and never printed.
"""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from localise.extract import (
    CJK,
    Template,
    build_templates,
    is_name_column,
    iter_entries,
)

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
BATCH = 40
ENV_FILE = Path("C:/Users/Stefan.Nasev/.config/loa/.env")
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache.sqlite"
REPORT = HERE / "sample-report.md"
FULL_REPORT = HERE / "full-run-report.md"
SPOTCHECK = HERE / "spotcheck-skills.md"
# Every rejected line (or whole reply when unparseable): effort, pass,
# attempt, reason, template, output; tab-separated, appended.
REJECTED = HERE / "rejected.log"
MAX_BATCH_CHARS = 4000

# USD per million tokens (owner's figures, 23-11-2026).
PRICE_IN = 4.0
PRICE_OUT = 20.0
PRICE_CACHE_READ = 0.20
PRICE_CACHE_WRITE = PRICE_IN * 1.25

# Tokens the model must carry over unchanged: digit slots, printf slots (the
# stock text only has %s and %d; a slot followed by two letters is English
# like "10%damage", not a slot),
# {n} slots, escaped line breaks/tabs, the game's own `$` slot and `|`
# separator.
PLACEHOLDER = re.compile(r"#|%[sd](?![a-z]{2})|\{[A-Za-z0-9_#]*\}|\\n|\\t|\$|\|")
TAG = re.compile(r"</?([A-Za-z!][\w-]*)")
LINE = re.compile(r"^\s*(\d+)\.\s?(.*)$")

SYSTEM_PROMPT = """\
You are the English localiser of League of Angels: Fire Raiders, a fantasy \
mobile RPG (heroes, angels/goddesses, gear, runes, campaign stages, guilds) \
that GTArcade originally released in English. You translate the Chinese \
client text of a private server back into natural, concise game English, the \
way an official Western release would read.

Rules:
- Every input line is `<number>. <Chinese text>`. Reply with exactly the same \
numbers in the same order, one line each: `<number>. <English text>`. No \
preamble, no notes, no blank-line commentary, no JSON.
- Never split one translation over several lines and never merge lines. A line \
break inside a text is written as the two characters \\n; keep each \\n where \
it is.
- `#` stands for a number. Keep every `#` exactly (same count); never write a \
digit for it. Example: `消耗#点体力` -> `Costs # Stamina`.
- Keep `%s`, `%d`, `{0}`-style slots, `$`, `|`, `\\t` and every markup tag \
(`<content>`, `<text value="..." color="..." .../>`, colour codes) exactly; \
inside a tag translate only the human text in value="...", never attribute \
names or colour values.
- UI strings are button and label text: keep them as short as the Chinese \
(one or two words for buttons, Title Case for names and buttons).
- Proper names (heroes, angels, items, skills, places) get an evocative \
fantasy English name, not a literal gloss; use the glossary when one is \
given, character for character.
- Game terms: 体力 Stamina, 钻石 Diamonds, 金币 Gold, 怒气 Rage, 女神/天使 \
Angel, 英雄 Hero, 公会 Guild, 关卡 Stage, 副本 Dungeon, 竞技场 Arena, 扫荡 \
Sweep, 觉醒 Awaken, 进阶 Advance, 符文 Rune, 神器 Artifact, VIP stays VIP.
- Leave Latin text, number slots and punctuation-only parts as they are.
- Never add a `#` of your own: `#` only ever stands for a number that is in \
the Chinese. For ranks and ordinals write words, not a number sign: \
`排行第|` -> `ranked |`, never `ranking #|` or `No. #|`.
"""


@dataclass(frozen=True)
class Item:
    template: str
    kind: str  # glossary kind (hero, item, ...) or a text category


# --- pure helpers (unit-tested, no network) ---------------------------------


def placeholders(text: str) -> Counter:
    return Counter(PLACEHOLDER.findall(text))


def tags(text: str) -> list[str]:
    return TAG.findall(text)


def check_line(src: str, en: str) -> str | None:
    """None if `en` is an acceptable translation of `src`, else the reason."""
    if not en.strip():
        return "empty"
    a, b = placeholders(src), placeholders(en)
    if a != b:
        missing = a - b
        extra = b - a
        return f"placeholders differ (missing {dict(missing)}, extra {dict(extra)})"
    if tags(src) != tags(en):
        return f"tags differ ({tags(src)} vs {tags(en)})"
    if CJK.search(en):
        return "Chinese left in output"
    return None


def format_batch(templates: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(templates, 1))


def parse_numbered(text: str, n: int) -> list[str]:
    """Parse `1. foo` ... `n. bar` into a list of n strings; ValueError if off."""
    out: dict[int, str] = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE.match(raw)
        if not m:
            raise ValueError(f"unnumbered line: {raw[:60]!r}")
        k = int(m.group(1))
        if k in out:
            raise ValueError(f"line {k} twice")
        out[k] = m.group(2).rstrip()
    if sorted(out) != list(range(1, n + 1)):
        raise ValueError(f"expected lines 1..{n}, got {len(out)} lines")
    return [out[i] for i in range(1, n + 1)]


def validate_batch(templates: list[str], reply: str) -> tuple[list[str], list[str]]:
    """Return (translations, problems). Problems empty = batch accepted."""
    try:
        lines = parse_numbered(reply, len(templates))
    except ValueError as exc:
        return [], [str(exc)]
    problems = []
    for i, (src, en) in enumerate(zip(templates, lines), 1):
        why = check_line(src, en)
        if why:
            problems.append(f"line {i}: {why}")
    return lines, problems


def system_text(glossary: list[tuple[str, str]]) -> str:
    if not glossary:
        return SYSTEM_PROMPT
    body = "\n".join(f"{zh} = {en}" for zh, en in glossary)
    return f"{SYSTEM_PROMPT}\nGlossary (use these English names exactly):\n{body}\n"


def cost(usage: dict) -> float:
    return (
        usage["input_tokens"] * PRICE_IN
        + usage["output_tokens"] * PRICE_OUT
        + usage["cache_read_input_tokens"] * PRICE_CACHE_READ
        + usage["cache_creation_input_tokens"] * PRICE_CACHE_WRITE
    ) / 1e6


def read_api_key(path: Path = ENV_FILE) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"ANTHROPIC_API_KEY missing in {path}")


# --- cache ------------------------------------------------------------------


def open_cache(path: Path = CACHE) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS translations (
            template TEXT NOT NULL, effort TEXT NOT NULL, en TEXT NOT NULL,
            kind TEXT, PRIMARY KEY (template, effort));
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY, run TEXT, effort TEXT, pass TEXT,
            n INTEGER, chars INTEGER, stop_reason TEXT, ok INTEGER,
            input_tokens INTEGER, output_tokens INTEGER,
            cache_creation_input_tokens INTEGER, cache_read_input_tokens INTEGER,
            seconds REAL, at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY, run TEXT, effort TEXT, pass TEXT,
            templates TEXT, reason TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);
        """
    )
    return db


def cached(db: sqlite3.Connection, effort: str) -> dict[str, str]:
    return dict(
        db.execute("SELECT template, en FROM translations WHERE effort=?", (effort,))
    )


# --- API --------------------------------------------------------------------


def call_claude(client, system: str, user: str, effort: str):
    """One request. Returns (text or None, stop_reason, usage dict, error)."""
    import anthropic

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort},
        )
    except anthropic.RateLimitError as exc:
        return None, "rate_limit", None, f"rate limited: {exc.status_code}"
    except anthropic.APIStatusError as exc:
        return None, "api_error", None, f"HTTP {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError as exc:
        return None, "connection", None, f"connection error: {exc}"
    u = resp.usage
    usage = {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
    }
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None, resp.stop_reason, usage, f"stop_reason {resp.stop_reason}"
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.stop_reason, usage, None


def reject_records(templates, lines, problems, reply) -> list[str]:
    """Tab-separated log records for one rejected reply."""
    out = []
    for p in problems:
        m = re.match(r"line (\d+): (.*)", p)
        if m and lines:
            i = int(m.group(1))
            out.append(f"{m.group(2)}\t{templates[i - 1]}\t{lines[i - 1]}")
        else:
            raw = (reply or "").replace("\n", "\\n")[:4000]
            out.append(f"{p}\t(whole batch)\t{raw}")
    return out


def log_rejects(effort, pass_, attempt, templates, lines, problems, reply) -> None:
    with REJECTED.open("a", encoding="utf-8", newline="\n") as f:
        for rec in reject_records(templates, lines, problems, reply):
            f.write(f"{effort}\t{pass_}\tattempt {attempt}\t{rec}\n")


def split_result(items: list[Item], lines: list[str], problems: list[str]):
    """Split one reply into (accepted (item, en) pairs, items to retry).

    A reply that did not parse (no lines) rejects every item; otherwise only
    the lines named in `line N: ...` problems are rejected.
    """
    if not lines:
        return [], list(items)
    bad = {int(m.group(1)) for p in problems if (m := re.match(r"line (\d+):", p))}
    good = [(it, en) for i, (it, en) in enumerate(zip(items, lines), 1) if i not in bad]
    return good, [it for i, it in enumerate(items, 1) if i in bad]


def missing_pins(templates, lines, pins: dict[str, list[tuple[str, str]]]) -> list[str]:
    """`line N: ...` problems for lines lacking a pinned English name."""
    out = []
    for i, (tpl, en) in enumerate(zip(templates, lines), 1):
        lost = [e for _, e in pins.get(tpl, []) if e.lower() not in en.lower()]
        if lost:
            out.append(f"line {i}: pinned name missing {lost}")
    return out


def translate_batch(
    client, db, items: list[Item], glossary, effort, run, pass_, pins=None
):
    """Translate one batch; lines that fail validation are retried once on
    their own, the good lines of a rejected reply are kept. `pins` maps a
    template to (Chinese, English) names its translation must use verbatim.
    Returns ok flag."""
    system = system_text(glossary)
    reason = ""
    todo = list(items)
    pins = pins or {}
    for attempt in (1, 2):
        templates = [it.template for it in todo]
        kinds = sorted({it.kind for it in todo})
        pinned = sorted({p for t in templates for p in pins.get(t, [])})
        note = (
            "Use these names exactly as written, character for character: "
            + "; ".join(f"{zh} = {en}" for zh, en in pinned)
            + ".\n"
            if pinned
            else ""
        )
        user = (
            f"Text type: {', '.join(kinds)}.\n{note}"
            f"Translate these {len(templates)} lines.\n\n{format_batch(templates)}"
        )
        t0 = time.monotonic()
        text, stop, usage, err = call_claude(client, system, user, effort)
        secs = time.monotonic() - t0
        problems = [err] if err else []
        lines: list[str] = []
        if text is not None:
            lines, problems = validate_batch(templates, text)
            if lines:
                problems += missing_pins(templates, lines, pins)
        ok = not problems
        u = usage or dict.fromkeys(
            (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ),
            0,
        )
        db.execute(
            "INSERT INTO calls (run, effort, pass, n, chars, stop_reason, ok,"
            " input_tokens, output_tokens, cache_creation_input_tokens,"
            " cache_read_input_tokens, seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run, effort, pass_, len(templates), sum(map(len, templates)), stop,
                int(ok), u["input_tokens"], u["output_tokens"],
                u["cache_creation_input_tokens"], u["cache_read_input_tokens"], secs,
            ),
        )
        db.commit()
        print(
            f"  [{effort}/{pass_}] {len(templates)} lines, attempt {attempt}: "
            f"{'ok' if ok else 'FAILED'} in {secs:.1f}s, in={u['input_tokens']} "
            f"out={u['output_tokens']} cw={u['cache_creation_input_tokens']} "
            f"cr={u['cache_read_input_tokens']}"
        )
        good, todo = split_result(todo, lines, problems)
        if good:
            db.executemany(
                "INSERT OR REPLACE INTO translations VALUES (?,?,?,?)",
                [(it.template, effort, en, it.kind) for it, en in good],
            )
            db.commit()
        if not todo:
            return True
        reason = "; ".join(problems)[:2000]
        print(f"    kept {len(good)}, retrying {len(todo)}: {reason[:300]}")
        log_rejects(effort, pass_, attempt, templates, lines, problems, text)
        if stop == "rate_limit":
            time.sleep(30)
    db.execute(
        "INSERT INTO failures (run, effort, pass, templates, reason) VALUES (?,?,?,?,?)",
        (run, effort, pass_, "\n".join(it.template for it in todo), reason),
    )
    db.commit()
    return False


# --- sample -----------------------------------------------------------------

GLOSSARY_QUOTA = {"hero": 12, "angel": 8, "item": 14, "skill": 14, "stage": 6, "npc": 6}

# category -> (quota, predicate on a Template)
OTHER_QUOTA = {
    "UI string": 40,
    "server message": 20,
    "skill/buff description": 35,
    "stage/story text": 25,
    "item/event/mail text": 20,
}

_SKILL_COLS = re.compile(
    r"^(spell_info\.(description\d|levelup_desc)|buff_info\.description"
    r"|angeltrials_buff_info\.desc\d?|awaken_info\.desc|rune_info\.description"
    r"|artifact_set\.description\d+|signet_set_info\.description)$"
)
_STORY_COLS = re.compile(
    r"^(stage_info\.description|chapter_info\.description|npc_info\.description\d"
    r"|new_player_guide_info\.talk|memory_chapter_info\.description|mail_info\.body)$"
)
_OTHER_COLS = re.compile(
    r"^(item_info\.description\d|event_info\.desc|mail_info\.subject|function\.name"
    r"|open_activity_event\.desc|guild_technology_info\.des|nobility_level_info\.des1?"
    r"|vip_info\.func_name|reward_display_info\.name)$"
)


def category(t: Template) -> str | None:
    if "ui" in t.sources or "script" in t.sources:
        return "UI string"
    if "server" in t.sources:
        return "server message"
    cols = t.columns
    if any(_SKILL_COLS.match(c) for c in cols):
        return "skill/buff description"
    if any(_STORY_COLS.match(c) for c in cols):
        return "stage/story text"
    if any(_OTHER_COLS.match(c) for c in cols):
        return "item/event/mail text"
    return None


def glossary_kind(t: Template) -> str | None:
    for c in sorted(t.columns):
        k = is_name_column(c)
        if k:
            return k
    return None


def select_sample(templates: dict[str, Template], n: int = 200, seed: int = 23):
    """Return (glossary items, other items): ~30% names, the rest mixed."""
    rng = random.Random(seed)
    scale = n / 200
    chosen: set[str] = set()
    names: list[Item] = []
    for kind, quota in GLOSSARY_QUOTA.items():
        pool = sorted(
            t.template
            for t in templates.values()
            if glossary_kind(t) == kind and "#" not in t.template
        )
        for tpl in rng.sample(pool, min(len(pool), round(quota * scale))):
            chosen.add(tpl)
            names.append(Item(tpl, kind))
    others: list[Item] = []
    for cat, quota in OTHER_QUOTA.items():
        pool = sorted(
            t.template
            for t in templates.values()
            if t.template not in chosen
            and glossary_kind(t) is None
            and category(t) == cat
        )
        for tpl in rng.sample(pool, min(len(pool), round(quota * scale))):
            chosen.add(tpl)
            others.append(Item(tpl, cat))
    return names, others


def run_pass(client, db, items: list[Item], glossary, effort, run, pass_):
    done = cached(db, effort)
    todo = [it for it in items if it.template not in done]
    print(f"[{effort}/{pass_}] {len(items)} items, {len(todo)} to translate")
    for i in range(0, len(todo), BATCH):
        translate_batch(client, db, todo[i : i + BATCH], glossary, effort, run, pass_)


def run_sample(n: int, efforts: list[str], stock: Path) -> None:
    import anthropic

    templates = build_templates(iter_entries(stock))
    names, others = select_sample(templates, n)
    client = anthropic.Anthropic(api_key=read_api_key())
    db = open_cache()
    for effort in efforts:
        run_pass(client, db, names, [], effort, "sample", "glossary")
        done = cached(db, effort)
        glossary = [(it.template, done[it.template]) for it in names if it.template in done]
        run_pass(client, db, others, glossary, effort, "sample", "text")
    write_report(db, client, templates, names, others, efforts)


# --- full run ---------------------------------------------------------------

# Hero and angel names go first, so every later name (soulstones, skins,
# skills named after a hero) can already use them.
FIRST_NAMES = {"hero", "angel"}


def batches(items: list[Item], max_n: int = BATCH, max_chars: int = MAX_BATCH_CHARS):
    """Split into batches of at most max_n items and (unless single) max_chars."""
    cur: list[Item] = []
    chars = 0
    for it in items:
        if cur and (len(cur) == max_n or chars + len(it.template) > max_chars):
            yield cur
            cur, chars = [], 0
        cur.append(it)
        chars += len(it.template)
    if cur:
        yield cur


def spend(db, run: str | None = None) -> float:
    q = (
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
        " COALESCE(SUM(cache_creation_input_tokens),0),"
        " COALESCE(SUM(cache_read_input_tokens),0) FROM calls"
    )
    row = db.execute(q + " WHERE run=?", (run,)).fetchone() if run else db.execute(q).fetchone()
    return cost(
        dict(
            zip(
                (
                    "input_tokens", "output_tokens",
                    "cache_creation_input_tokens", "cache_read_input_tokens",
                ),
                row,
            )
        )
    )


def full_plan(templates: dict[str, Template]):
    """Return (first names, other names, texts) as Item lists, deterministic."""
    first, names, texts = [], [], []
    for tpl in sorted(templates):
        t = templates[tpl]
        kind = glossary_kind(t)
        if kind in FIRST_NAMES:
            first.append(Item(tpl, kind))
        elif kind:
            names.append(Item(tpl, kind))
        else:
            texts.append(Item(tpl, category(t) or "game text"))
    names.sort(key=lambda it: (it.kind, it.template))
    texts.sort(key=lambda it: (it.kind, it.template))
    return first, names, texts


def glossary_from(db, effort: str, items: list[Item]) -> list[tuple[str, str]]:
    done = cached(db, effort)
    return sorted((it.template, done[it.template]) for it in items if it.template in done)


def run_full(effort: str, stock: Path, budget_stop: float, max_seconds: float) -> int:
    """0 = all passes done, 3 = time slice used up (rerun), 4 = budget stop."""
    import anthropic

    templates = build_templates(iter_entries(stock))
    first, names, texts = full_plan(templates)
    client = anthropic.Anthropic(api_key=read_api_key())
    db = open_cache()
    t_end = time.monotonic() + max_seconds
    worst = 0.0  # most expensive batch so far, the margin kept below the stop
    passes = [
        ("names-1", first, lambda: []),
        ("names-2", names, lambda: glossary_from(db, effort, first)),
        ("text", texts, lambda: glossary_from(db, effort, first + names)),
    ]
    for pass_, items, gl in passes:
        done = cached(db, effort)
        todo = [it for it in items if it.template not in done]
        print(f"[{effort}/{pass_}] {len(items)} items, {len(todo)} to translate")
        if not todo:
            continue
        glossary = gl()
        print(f"  glossary entries: {len(glossary)}")
        for batch in batches(todo):
            if time.monotonic() > t_end:
                print("time slice used up; rerun to resume")
                return 3
            total = spend(db)
            if total + worst > budget_stop:
                print(
                    f"BUDGET STOP: spent ${total:.4f}, next batch could pass "
                    f"${budget_stop:.2f}"
                )
                return 4
            translate_batch(client, db, batch, glossary, effort, "full", pass_)
            after = spend(db)
            worst = max(worst, after - total)
            print(f"    running total ${after:.4f} (full run ${spend(db, 'full'):.4f})")
    return 0


def glossary_mismatches(glossary: dict[str, str], texts: dict[str, str]):
    """Names whose glossary English is absent from a text containing the name.

    Returns [(zh, en, mismatches, total uses, example zh, example en)] sorted
    by mismatch count. Names under two characters or with `#` are skipped.
    """
    out = []
    for zh, en in glossary.items():
        if len(zh) < 2 or "#" in zh:
            continue
        uses = [(tz, te) for tz, te in texts.items() if zh in tz]
        bad = [(tz, te) for tz, te in uses if en.lower() not in te.lower()]
        if bad:
            out.append((zh, en, len(bad), len(uses), bad[0][0], bad[0][1]))
    out.sort(key=lambda r: (-r[2], r[0]))
    return out


# Names whose glossary English drifted in other texts, picked by hand from the
# 3+ character mismatches of the full run (23-11-2026). Left out: names that
# the Chinese also uses as plain words in those texts (守护女神, 入侵者,
# 震撼大地, 无人能挡, 火元素, 守护者 as a typo of 守护着, 致命一击, ...), and
# skill names used as verbs in their own description (疯狂撕咬, 二连斩).
DRIFT_NAMES = (
    "泰坦巨岩", "奥创灭世", "守夜人", "血族末裔", "狂暴之爪", "符文战熊",
    "紫耀石之杖", "紫耀石之盔", "金耀石至宝", "冥剑伯爵", "烈焰之怒", "光明神使",
    "幻雷魔灵", "雪之誓言", "魔法炮车火", "魔法炮车雷", "光明圣剑",
)
DRIFT_REPORT = HERE / "drift-fixes.md"


def drift_targets(glossary: dict[str, str], texts: dict[str, str], names) -> dict:
    """template -> [(zh, en)] for texts that contain a drift name (not only as
    part of a longer glossary name) but not its glossary English."""
    out: dict[str, list[tuple[str, str]]] = {}
    longer = [g for g in glossary if len(g) >= 3 and "#" not in g]
    for tz, te in texts.items():
        for zh in names:
            if zh not in tz or zh not in glossary:
                continue
            if any(zh != o and zh in o and o in tz for o in longer):
                continue
            if glossary[zh].lower() not in te.lower():
                out.setdefault(tz, []).append((zh, glossary[zh]))
    return out


def run_drift(effort: str, stock: Path, budget_stop: float) -> int:
    import anthropic

    templates = build_templates(iter_entries(stock))
    first, names, texts = full_plan(templates)
    db = open_cache()
    done = cached(db, effort)
    glossary = glossary_from(db, effort, first + names)
    gl = dict(glossary)
    by_tpl = {it.template: it for it in texts}
    targets = drift_targets(
        gl, {t: done[t] for t in by_tpl if t in done}, DRIFT_NAMES
    )
    before = {t: done[t] for t in targets}
    print(f"[{effort}/drift] {len(targets)} templates to re-translate")
    client = anthropic.Anthropic(api_key=read_api_key())
    for batch in batches([by_tpl[t] for t in sorted(targets)]):
        total = spend(db)
        if total > budget_stop - 0.10:
            print(f"BUDGET STOP: spent ${total:.4f}")
            return 4
        translate_batch(client, db, batch, glossary, effort, "drift", "drift", pins=targets)
        print(f"    running total ${spend(db):.4f}")
    after = cached(db, effort)
    out = [
        "# Glossary drift corrections",
        "",
        f"Names re-pinned: {', '.join(DRIFT_NAMES)}. Each listed template was "
        "re-translated with its glossary names pinned in the request; the "
        "reply had to contain the pinned English.",
        "",
        "| Chinese | pinned | before | after |",
        "|---|---|---|---|",
    ]
    for t in sorted(targets):
        pins = ", ".join(f"{zh} = {en}" for zh, en in targets[t])
        out.append(
            f"| {_md(t)} | {_md(pins)} | {_md(before[t])} | {_md(after[t])} |"
        )
    DRIFT_REPORT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {DRIFT_REPORT}")
    return 0


def write_full_report(db, stock: Path, effort: str) -> None:
    templates = build_templates(iter_entries(stock))
    first, names, texts = full_plan(templates)
    done = cached(db, effort)
    out = [
        f"# English localisation: full run (effort {effort})",
        "",
        f"Model `{MODEL}`, normal Messages API, batches of up to {BATCH} lines "
        f"/ {MAX_BATCH_CHARS} chars. Order: hero and angel names, the other "
        "names with the hero/angel glossary, then all other text with the full "
        "glossary. Medium-effort rows from the sample were reused, not re-paid.",
        "",
        "## Counts",
        "",
        "| pass | templates | translated | missing after retry |",
        "|---|---|---|---|",
    ]
    missing_all = []
    for pass_, items in (("names-1", first), ("names-2", names), ("text", texts)):
        miss = [it for it in items if it.template not in done]
        missing_all += [(pass_, it) for it in miss]
        out.append(f"| {pass_} | {len(items):,} | {len(items) - len(miss):,} | {len(miss):,} |")
    n_all = len(first) + len(names) + len(texts)
    out.append(f"| total | {n_all:,} | {n_all - len(missing_all):,} | {len(missing_all):,} |")

    rows = db.execute(
        "SELECT run, COUNT(*), SUM(1-ok), SUM(input_tokens), SUM(output_tokens),"
        " SUM(cache_creation_input_tokens), SUM(cache_read_input_tokens), SUM(seconds)"
        " FROM calls WHERE effort=? OR run='full' GROUP BY run ORDER BY run",
        (effort,),
    ).fetchall()
    out += [
        "",
        "## Tokens and cost",
        "",
        "| run | calls | rejected calls | input | output | cache write | cache read "
        "| API time min | USD |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run, n, bad, i, o, cw, cr, secs in rows:
        usd = spend(db, run) if run == "full" else cost(
            {"input_tokens": i, "output_tokens": o,
             "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}
        )
        out.append(
            f"| {run} ({effort if run == 'sample' else 'all'}) | {n} | {bad} | {i:,} "
            f"| {o:,} | {cw:,} | {cr:,} | {secs / 60:.0f} | {usd:.4f} |"
        )
    out.append("")
    out.append(f"All API spend on this project so far (both sample efforts + full run): "
               f"${spend(db):.4f}.")

    out += ["", "## Templates missing after retry", ""]
    if not missing_all:
        out.append("None.")
    for pass_, it in missing_all:
        out.append(f"- {pass_} ({it.kind}): `{it.template}`")
    reasons = db.execute(
        "SELECT pass, reason FROM failures WHERE run='full' ORDER BY id"
    ).fetchall()
    if reasons:
        out += ["", "Failure reasons per batch (last attempt):", ""]
        out += [f"- {p}: {_md(r[:400])}" for p, r in reasons]

    gl = dict(glossary_from(db, effort, first + names))
    tx = {it.template: done[it.template] for it in texts if it.template in done}
    mism = glossary_mismatches(gl, tx)
    out += [
        "",
        "## Glossary consistency (top 30)",
        "",
        f"{len(mism)} glossary names have at least one non-name translation "
        "that contains the Chinese name but not its glossary English "
        "(case-insensitive substring check; names under 2 chars or with `#` "
        "skipped). Some are inflections or plurals, not real mismatches.",
        "",
        "| Chinese name | glossary English | mismatches / uses | example text | its English |",
        "|---|---|---|---|---|",
    ]
    for zh, en, bad, uses, ez, ee in mism[:30]:
        out.append(f"| {_md(zh)} | {_md(en)} | {bad} / {uses} | {_md(ez)} | {_md(ee)} |")
    FULL_REPORT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {FULL_REPORT}")

    skills = sorted(it.template for it in texts
                    if it.kind == "skill/buff description" and it.template in done)
    pick = sorted(random.Random(100).sample(skills, min(100, len(skills))))
    sc = [
        f"# Spot check: 100 random skill/buff descriptions (effort {effort})",
        "",
        f"Drawn with seed 100 from {len(skills):,} translated skill/buff "
        "description templates. `#` is a number slot.",
        "",
        "| # | Chinese | English |",
        "|---|---|---|",
    ]
    sc += [f"| {i} | {_md(t)} | {_md(done[t])} |" for i, t in enumerate(pick, 1)]
    SPOTCHECK.write_text("\n".join(sc) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {SPOTCHECK}")


# --- report -----------------------------------------------------------------


def _usage_sum(db, effort: str, run: str = "sample") -> dict:
    row = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
        " COALESCE(SUM(cache_creation_input_tokens),0),"
        " COALESCE(SUM(cache_read_input_tokens),0), COALESCE(SUM(seconds),0),"
        " COALESCE(SUM(1-ok),0)"
        " FROM calls WHERE run=? AND effort=?",
        (run, effort),
    ).fetchone()
    keys = (
        "calls", "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "seconds", "failed_calls",
    )
    return dict(zip(keys, row))


def _md(s: str) -> str:
    return s.replace("|", "\\|")


def write_report(db, client, templates, names, others, efforts) -> None:
    items = names + others
    sample_chars = sum(len(it.template) for it in items)
    full_chars = sum(map(len, templates))
    n_glossary_full = sum(1 for t in templates.values() if glossary_kind(t))
    n_batches_full = -(-(len(templates) - n_glossary_full) // BATCH)

    out = [
        "# English localisation: 200-template sample (Claude API)",
        "",
        f"Model `{MODEL}`, batches of {BATCH}, line-numbered plain text, "
        "system prompt (instructions + glossary) marked `cache_control: ephemeral`. "
        "Prices: $4/MTok input, $20/MTok output, $0.20/MTok cache read, "
        "$5/MTok cache write (1.25x input).",
        "",
        f"Sample: {len(names)} names (glossary pass, translated first) + "
        f"{len(others)} other templates; {sample_chars:,} template chars. "
        f"Full set: {len(templates):,} templates, {full_chars:,} chars "
        f"(scale factor {full_chars / sample_chars:.1f}x).",
        "",
        "## Usage and cost per effort level",
        "",
        "| effort | calls | failed calls | input | output | cache write | cache read "
        "| API time s | sample cost $ | full projection $ | full via Batches API $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for effort in efforts:
        u = _usage_sum(db, effort)
        c = cost(u)
        proj = c * full_chars / sample_chars
        out.append(
            f"| {effort} | {u['calls']} | {u['failed_calls']} | {u['input_tokens']:,} "
            f"| {u['output_tokens']:,} | {u['cache_creation_input_tokens']:,} "
            f"| {u['cache_read_input_tokens']:,} | {u['seconds']:.0f} | {c:.4f} "
            f"| {proj:.2f} | {proj / 2:.2f} |"
        )

    # Glossary overhead: the full run carries every name in the system prompt.
    out += ["", "## Glossary overhead in the full run", ""]
    try:
        base = client.messages.count_tokens(
            model=MODEL, system=system_text([]),
            messages=[{"role": "user", "content": "x"}],
        ).input_tokens
        done = cached(db, efforts[-1])
        gl = [(it.template, done[it.template]) for it in names if it.template in done]
        with_gl = client.messages.count_tokens(
            model=MODEL, system=system_text(gl),
            messages=[{"role": "user", "content": "x"}],
        ).input_tokens
        per_entry = (with_gl - base) / max(1, len(gl))
        full_gl = per_entry * n_glossary_full
        read_cost = full_gl * n_batches_full * PRICE_CACHE_READ / 1e6
        out += [
            f"Instructions alone: {base:,} tokens; with the {len(gl)}-name sample "
            f"glossary: {with_gl:,} tokens ({per_entry:.1f} tokens per entry).",
            f"The full set has {n_glossary_full:,} name templates, so a complete "
            f"glossary is about {full_gl:,.0f} tokens. Sent cached with each of the "
            f"{n_batches_full} non-name batches that is about "
            f"{full_gl * n_batches_full / 1e6:.1f} MTok of cache reads, "
            f"${read_cost:.2f} (plus one cache write of "
            f"${full_gl * PRICE_CACHE_WRITE / 1e6:.2f} per 5-minute window). "
            "The char-scaled projection above does not include this; add it. "
            "Sending only the glossary entries that occur in each batch would "
            "make it negligible.",
        ]
        if not any(_usage_sum(db, e)["cache_read_input_tokens"] for e in efforts):
            out += [
                "",
                "No cache reads in the sample: its system prompt is below the "
                "model's minimum cacheable length; the full glossary prompt is "
                "far above it.",
            ]
    except Exception as exc:  # count_tokens is informational only
        out.append(f"(token count unavailable: {type(exc).__name__})")

    # Side-by-side table.
    tr = {e: cached(db, e) for e in efforts}
    rng = random.Random(7)
    pick = rng.sample(names, min(10, len(names))) + rng.sample(others, min(30, len(others)))
    pick.sort(key=lambda it: (it.kind, it.template))
    out += [
        "",
        "## 40 representative rows",
        "",
        "| kind | Chinese | " + " | ".join(efforts) + " |",
        "|---|---|" + "---|" * len(efforts),
    ]
    for it in pick:
        cells = [_md(tr[e].get(it.template, "(missing)")) for e in efforts]
        out.append(f"| {it.kind} | {_md(it.template)} | " + " | ".join(cells) + " |")

    out += ["", "## Batches that failed validation", ""]
    fails = db.execute(
        "SELECT effort, pass, reason, templates FROM failures WHERE run='sample' ORDER BY id"
    ).fetchall()
    retried = db.execute(
        "SELECT effort, pass, COUNT(*) FROM calls WHERE run='sample' AND ok=0 "
        "GROUP BY effort, pass"
    ).fetchall()
    if retried:
        out.append(
            "Calls rejected and retried: "
            + ", ".join(f"{e}/{p}: {n}" for e, p, n in retried)
            + "."
        )
        out.append("")
    if not fails:
        out.append("None after the one retry.")
    for effort, pass_, reason, tpls in fails:
        out.append(
            f"- {effort}/{pass_}, {len(tpls.splitlines())} lines: {_md(reason[:500])}"
        )
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {REPORT}")


def main(argv: list[str] | None = None) -> int:
    from server.settings import load as load_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", type=int, help="sample size")
    mode.add_argument("--full", action="store_true", help="translate every template")
    mode.add_argument("--full-report", action="store_true", help="only write the reports")
    mode.add_argument("--fix-drift", action="store_true", help="re-pin drifted names")
    parser.add_argument("--efforts", default="low,medium", help="sample mode")
    parser.add_argument("--effort", default="medium", help="full mode")
    parser.add_argument("--budget-stop", type=float, default=15.0, help="USD, all runs")
    parser.add_argument("--max-seconds", type=float, default=540.0,
                        help="stop between batches after this long; rerun resumes")
    args = parser.parse_args(argv)
    stock = load_settings(args.settings).stock_dir
    if args.sample:
        efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
        run_sample(args.sample, efforts, stock)
        return 0
    if args.fix_drift:
        status = run_drift(args.effort, stock, args.budget_stop)
        if status:
            return status
    if args.full:
        status = run_full(args.effort, stock, args.budget_stop, args.max_seconds)
        if status:
            return status
    write_full_report(open_cache(), stock, args.effort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
