"""Fetch the cocos2d-x 2.2.2 Android Java runtime straight from GitHub.

Two origins, because the stock client is not built on stock cocos2d-x:

1. cocos2d-x at tag cocos2d-x-2.2.2 supplies the 15 files of
   cocos2dx/platform/android/java/src/org/cocos2dx/lib (see LISTING_URL).
2. Cocos2dxLuaJavaBridge.java does not exist anywhere in cocos2d-x at that tag.
   libgame.so exports Java_org_cocos2dx_lib_Cocos2dxLuaJavaBridge_* and carries the
   mangled symbol _ZN15CCLuaJavaBridge8CallInfoC1EPKcS2_S2_, and CCLuaJavaBridge is a
   quick-cocos2d-x class, so the game is built on quick-cocos2d-x 2.2.x. The class comes
   from chukong/quick-cocos2d-x, pinned to commit
   d2aa161a62e03327b22895ca55f628ad9fba85b9 (18-06-2013) so a re-fetch is reproducible:
   https://raw.githubusercontent.com/chukong/quick-cocos2d-x/d2aa161a62e03327b22895ca55f628ad9fba85b9/lib/cocos2d-x/cocos2dx/platform/android/java/src/org/cocos2dx/lib/Cocos2dxLuaJavaBridge.java

PATCHES then repairs the one fetched file that cannot compile against compileSdk 36, so
running this script again always reproduces a tree that builds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

LISTING_URL = (
    "https://api.github.com/repos/cocos2d/cocos2d-x/contents/"
    "cocos2dx/platform/android/java/src/org/cocos2dx/lib?ref=cocos2d-x-2.2.2"
)
QUICK_SHA = "d2aa161a62e03327b22895ca55f628ad9fba85b9"
EXTRA_URLS = {
    "Cocos2dxLuaJavaBridge.java": (
        f"https://raw.githubusercontent.com/chukong/quick-cocos2d-x/{QUICK_SHA}/"
        "lib/cocos2d-x/cocos2dx/platform/android/java/src/org/cocos2dx/lib/"
        "Cocos2dxLuaJavaBridge.java"
    ),
}

# android.util.FloatMath was deprecated at API 22 and removed at API 23; we compile
# against compileSdk 36. Math.ceil returns a double, and all three call sites already
# cast to (int), so the values are unchanged.
PATCHES = {
    "Cocos2dxBitmap.java": [
        ("import android.util.FloatMath;\n", ""),
        ("FloatMath.ceil(", "Math.ceil("),
    ],
}
DEST = Path("client/android/app/src/main/java/org/cocos2dx/lib")


class FindClassError(RuntimeError):
    pass


class PatchError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "loa-private-server"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def apply_patches(dest: Path, names: list[str]) -> None:
    """Rewrite fetched files that cannot compile as published. Fails loud when the text
    we expect to replace is absent, so an upstream change cannot pass silently."""
    for name, edits in PATCHES.items():
        if name not in names:
            continue
        path = dest / name
        text = path.read_text(encoding="utf-8")
        for old, new in edits:
            if old not in text:
                raise PatchError(f"{name}: expected text not found: {old!r}")
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8", newline="")


def fetch(
    dest: Path,
    listing: list[dict] | None = None,
    extra: dict[str, str] | None = None,
) -> list[str]:
    if listing is None:
        listing = json.loads(_get(LISTING_URL))
    if extra is None:
        extra = EXTRA_URLS
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for entry in listing:
        if entry.get("type") != "file" or not entry["name"].endswith(".java"):
            continue
        body = _get(entry["download_url"])
        (dest / entry["name"]).write_bytes(body)
        written.append(entry["name"])
    for name, url in extra.items():
        (dest / name).write_bytes(_get(url))
        written.append(name)
    apply_patches(dest, written)
    return sorted(written)


def verify_natives(root: Path, expected: dict[str, list[str]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for cls, methods in expected.items():
        path = root / f"{cls}.java"
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        gone = [m for m in methods if not re.search(rf"\b{re.escape(m)}\s*\(", text)]
        if gone:
            missing[cls] = gone
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args(argv)
    names = fetch(args.dest)
    print(f"wrote {len(names)} java files into {args.dest}")
    expected = json.loads(Path("client/cocos_natives.json").read_text(encoding="utf-8"))
    missing = verify_natives(args.dest, expected)
    if missing:
        raise FindClassError(f"missing native declarations: {missing}")
    print("every native libgame.so needs is declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
