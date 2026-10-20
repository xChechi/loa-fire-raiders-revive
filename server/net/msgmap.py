"""Parse the client msgIDMap.lua into {(service, cmd): message_name}."""

from __future__ import annotations

import re
from pathlib import Path

_ENTRY = re.compile(r"id_(\d+)_(\d+)\s*=\s*\"(\w+)\"")

MAP_RELPATH = Path("assets/res/utils/net/msgIDMap.lua")


def parse(text: str) -> dict[tuple[int, int], str]:
    """Later duplicate keys overwrite earlier ones, as a Lua table constructor does."""
    ids: dict[tuple[int, int], str] = {}
    for service, cmd, name in _ENTRY.findall(text):
        ids[(int(service), int(cmd))] = name
    return ids


def load(stock_dir: Path) -> dict[tuple[int, int], str]:
    return parse((Path(stock_dir) / MAP_RELPATH).read_text(encoding="utf-8-sig"))


def res_key(
    ids: dict[tuple[int, int], str], service: int, cmd: int
) -> tuple[int, int] | None:
    """The (service, cmd) of the Res paired with a Req, or None when there is none."""
    name = ids.get((service, cmd))
    if name is None or not name.endswith("Req"):
        return None
    candidate = (service, cmd + 1)
    return candidate if ids.get(candidate) == name[:-3] + "Res" else None
