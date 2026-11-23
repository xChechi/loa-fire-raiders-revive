"""Fourth text source: Chinese string literals hard-coded in the client Lua.

Every .lua under assets/scripts except the language files is tokenised
(strings, comments, names, punctuation). A string literal with Chinese is a
candidate unless it is

  * inside a comment (comments are skipped by the lexer),
  * an argument of a log / debug call (print, trace, __LogR, MMDump, ...),
  * a lookup key: compared with == / ~=, used as a table key ["..."] or
    `key = ` inside a table constructor is fine, but `t["中文"]` is not,
  * an argument of a string search / pattern call (find, gsub, match, split),
    or of require / a resource path (contains '/' or a file extension).

Those exclusions that are not plainly debug output are listed as "unsure"
instead of translated, with file and line.

The UI layout files (res/assets/ui/*.json, the armature .xml/.ExportJson) were
checked on 23-11-2026: their Chinese is bone/layer names, the font name
微软雅黑 and three placeholder texts that the Lua overwrites, so the Lua is the
only fourth source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from localise.extract import CJK, _lua_unescape

SCRIPTS = Path("assets/scripts")

LOG_CALL = re.compile(
    r"^(print|printf|printInfo|printError|printLog|release_print|trace|traceback"
    r"|__Log\w*|_Log\w*|MMDump|dump|echo\w*|cclog|CCLuaLog|log\w*|Log\w*|debug\w*"
    r"|error|assert|warn\w*|LOG\w*|TRACE\w*|MMLog\w*)$"
)
PATTERN_CALL = re.compile(
    r"^(find|gsub|match|gmatch|split|string_split|split\w*|\w*[Ss]plit|require"
    r"|indexOf|startsWith|endsWith|byte|format_lookup)$"
)


@dataclass(frozen=True)
class ScriptString:
    relpath: str  # path under assets/, forward slashes
    line: int
    start: int  # [start, end) of the literal in the decoded file text
    end: int
    value: str
    verdict: str  # "translate" | "log" | "unsure: <why>"


_TOKEN = re.compile(
    r"""(?P<lcomment>--\[(?P<leq>=*)\[)|(?P<comment>--[^\n]*)
      |(?P<lstr>\[(?P<seq>=*)\[)
      |(?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
      |(?P<name>[A-Za-z_][A-Za-z0-9_]*)
      |(?P<num>0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)
      |(?P<op>==|~=|<=|>=|\.\.\.|\.\.|::|[-+*/%^#<>=(){}\[\];:,.])
      |(?P<ws>\s+)
      |(?P<other>.)""",
    re.X | re.S,
)


def tokens(src: str):
    """Yield (kind, text, start, end); comments are dropped."""
    i, n = 0, len(src)
    while i < n:
        m = _TOKEN.match(src, i)
        if m.group("lcomment"):
            close = "]" + m.group("leq") + "]"
            end = src.find(close, m.end())
            i = n if end < 0 else end + len(close)
            continue
        if m.group("lstr"):
            close = "]" + m.group("seq") + "]"
            end = src.find(close, m.end())
            end = n if end < 0 else end
            body = src[m.end() : end]
            if body.startswith("\r\n"):
                body = body[2:]
            elif body.startswith("\n"):
                body = body[1:]
            yield "str", body.replace("\r\n", "\n"), i, end + len(close)
            i = end + len(close)
            continue
        kind = m.lastgroup
        if kind == "str":
            yield "str", _lua_unescape(m.group(0)[1:-1]), i, m.end()
        elif kind not in ("comment", "ws"):
            yield kind, m.group(0), i, m.end()
        i = m.end()


def classify(src: str, relpath: str) -> list[ScriptString]:
    toks = list(tokens(src))
    out = []
    # Stack of open brackets: (char, name of the call it opens or None).
    stack: list[tuple[str, str | None]] = []
    for k, (kind, text, start, end) in enumerate(toks):
        if kind == "op" and text in "([{":
            callee = None
            if text == "(" and k and toks[k - 1][0] == "name":
                callee = toks[k - 1][1]
            stack.append((text, callee))
            continue
        if kind == "op" and text in ")]}":
            if stack:
                stack.pop()
            continue
        if kind != "str" or not CJK.search(text):
            continue
        prev = toks[k - 1][1] if k else ""
        nxt = toks[k + 1][1] if k + 1 < len(toks) else ""
        callees = [c for b, c in stack if b == "(" and c]
        if any(LOG_CALL.match(c) for c in callees):
            verdict = "log"
        elif prev in ("==", "~=") or nxt in ("==", "~="):
            verdict = "unsure: compared with ==/~="
        elif prev == "[" and nxt == "]":
            verdict = "unsure: table key"
        elif callees and PATTERN_CALL.match(callees[-1]):
            verdict = f"unsure: argument of {callees[-1]}()"
        elif re.search(r"[/\\]|\.(png|jpg|lua|mp3|plist|json|db)\b", text):
            verdict = "unsure: looks like a path"
        else:
            verdict = "translate"
        line = src.count("\n", 0, start) + 1
        out.append(ScriptString(relpath, line, start, end, text, verdict))
    return out


def iter_script_strings(stock_dir: Path):
    root = Path(stock_dir) / "assets"
    for path in sorted((root / "scripts").rglob("*.lua")):
        raw = path.read_bytes()
        try:
            src = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # one GBK file (MainSceneRolePosData.lua): positions only
        rel = path.relative_to(root).as_posix()
        yield from classify(src, rel)


def main() -> int:
    """Write localise/script-strings.md: counts and the unsure list."""
    from collections import Counter

    from server.settings import load as load_settings

    strings = list(iter_script_strings(load_settings().stock_dir))
    counts = Counter(s.verdict.split(":")[0] for s in strings)
    unsure = [s for s in strings if s.verdict.startswith("unsure")]
    out = [
        "# Chinese literals hard-coded in the client Lua",
        "",
        f"{len(strings)} literals with Chinese outside comments: "
        f"{counts['translate']} translated, {counts['log']} log/debug output "
        f"(print, trace, __LogR, __LogI, __Log, __LogE) left alone, "
        f"{counts['unsure']} unsure and left alone:",
        "",
        "| file | line | text | why |",
        "|---|---|---|---|",
    ]
    out += [f"| {s.relpath} | {s.line} | {s.value!r} | {s.verdict[8:]} |" for s in unsure]
    path = Path(__file__).resolve().parent / "script-strings.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
