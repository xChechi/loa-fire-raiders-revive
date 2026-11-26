"""Signets (印记, function 80010) and the master-dungeon fight counter
(王者副本, function 80020), plan B2 Wave 3, task B5.

What the client reads (step 1):

- SignetInfo {id, entry, level, main_attrs[], sub_attrs[], equip}; one main
  attribute, read as main_attrs[1] everywhere (StampDataHelp.lua:311,488,
  StampAdvancePanel.lua:78, StampRenderInfoPanel.lua:74).
- The quality a signet shows is signet_quality_info by the NUMBER of sub
  attributes (StampDataHelp.lua:405-411, TipDrop.lua:123-129): amount 0..4 is
  quality 1..5. signet_info.quality is the drop's quality (MMDropItem.lua:
  196-198), so a drop of quality q carries q - 1 sub attributes.
- A "special" signet has fixed attributes in signet_info.main_attr
  ("type|value") and sub_attr ("type|value,type|value"); the rest have '0'
  there (TipDrop.lua:89-112, "特殊印记 属性已经确定").
- The next level's main value is the current one + signet_attribute_info
  (star, main type).grow_value (StampDataHelp.lua:434-438). Sub attributes
  change only when the new level is a multiple of 3 (StampDataHelp.lua:412-
  425, StampAdvancePanel.lua:182,219,254): "add one", "add or strengthen
  one", "strengthen one" (fu00045-fu00047).
- 5_2742 SignetObtainNotify {signets[]} appends to g_roleData.signets
  (RPGGame.lua:1031-1088); 5_2744 SignetBagFullNotify floats fu00073
  "印记已满，请到邮件中领取！" (RPGGame.lua:1090-1096): a full bag mails them.
- The fight counter: LevelManager:getLeftTimes of a type-13 stage is
  ClientPlayer.signet_fight_cnt and getMaxTimes is SIGNET_MAX_CNT
  (LevelManager.lua:787-816); the client never lowers it itself, so the
  server pushes it. Entering with 0 opens the buy panel (DesSweepPanel.lua:
  576-579); a sweep needs as many fights as it asks for (:449-453).

O-W3-7, settled from the tables (the client has no rolling code):
- main: one of signet_info.attribute1..8 (signet_attribute_info entries),
  picked at random, at its base_value;
- subs: signet_info.quality - 1 of them, each a distinct attribute type of the
  signet's star that is not the main one, valued min_value + k x (max_value -
  min_value) / step_number with k uniform in 0..step_number (step_number is a
  count: types 81/88/89 have step 2-4 over a 0.01 range, so it cannot be a
  size). The fixed special signets fit this: '9|176' is star 6 type 9's
  base_value, every sub value lies in its row's range on that grid.
- Rolled once, lazily, on the first send, then stored.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import mail, notify
from server.modules.player import build_signet_info
from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.signet")

STATUS_NO_FIGHTS = 338111        # language.db 地狱关卡挑战次数不足
STATUS_BAG_FULL = 338114         # language.db 印记数量达到上限，请先去清理

BAG_FULL_MAIL = 101200           # mail_info 印记超上限通知

_default_rng = random.SystemRandom()


# --- the fight counter ------------------------------------------------------
def _row(conn: sqlite3.Connection, player_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()


def settle_fights(
    conn: sqlite3.Connection, cfg: Config, player_id: int, now: float | None = None
) -> int:
    """Write the fights recovered since signet_cnt_at (one per
    SIGNET_CNT_RECOVER_CYCLE, down to 0 used) and return the fights left.
    Bought fights are negative `used` and never recover past 0."""
    now = int(time.time() if now is None else now)
    row = _row(conn, player_id)
    used, at = int(row["signet_cnt_used"]), int(row["signet_cnt_at"])
    cycle = cfg.variable_int("SIGNET_CNT_RECOVER_CYCLE", 0)
    if used > 0 and cycle > 0:
        back = min(used, max(0, now - at) // cycle)
        used -= back
        at = now if used == 0 else at + back * cycle
        conn.execute(
            "UPDATE players SET signet_cnt_used = ?, signet_cnt_at = ? WHERE id = ?",
            (used, at, int(player_id)),
        )
        conn.commit()
    return cfg.variable_int("SIGNET_MAX_CNT", 0) - used


def spend_fights(
    conn: sqlite3.Connection, cfg: Config, player_id: int, n: int,
    now: float | None = None,
) -> int | None:
    """Take n fights; None (nothing written) when fewer are left. Returns the
    fights left. The recovery clock starts when the counter leaves full."""
    now = int(time.time() if now is None else now)
    left = settle_fights(conn, cfg, player_id, now)
    if left < n:
        return None
    row = _row(conn, player_id)
    used = int(row["signet_cnt_used"])
    at = now if used <= 0 else int(row["signet_cnt_at"])
    conn.execute(
        "UPDATE players SET signet_cnt_used = ?, signet_cnt_at = ? WHERE id = ?",
        (used + int(n), at, int(player_id)),
    )
    conn.commit()
    return left - int(n)


# --- attributes ---------------------------------------------------------------
def _attr(attr_type: int, value: float) -> dict:
    return {"attr_type": int(attr_type), "attr_value": round(float(value), 6)}


def _fixed(text: str, pair_sep: str) -> list[dict]:
    """signet_info.main_attr 't|v' / sub_attr 't|v,t|v' (TipDrop.lua:96-112)."""
    if pair_sep == "|":
        parts = str(text).split("|")
        return [_attr(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
    return [_attr(*pair.split("|")) for pair in str(text).split(",") if pair]


def _sub_value(row, rng: random.Random) -> float:
    low, high = float(row["min_value"] or 0), float(row["max_value"] or 0)
    steps = int(row["step_number"] or 0)
    if steps <= 0:
        return low
    return low + rng.randint(0, steps) * (high - low) / steps


def _add_sub(cfg: Config, star: int, main: list, subs: list, rng) -> bool:
    taken = {int(a["attr_type"]) for a in main + subs}
    pool = [
        r for r in cfg.signet_attributes()
        if int(r["star"]) == int(star) and int(r["attribute_type"]) not in taken
    ]
    if not pool:
        return False
    row = pool[rng.randrange(len(pool))]
    subs.append(_attr(row["attribute_type"], _sub_value(row, rng)))
    return True


def roll_attrs(
    cfg: Config, entry: int, rng: random.Random | None = None
) -> tuple[list[dict], list[dict]]:
    """(main_attrs, sub_attrs) of a new signet of `entry` (O-W3-7, above)."""
    rng = _default_rng if rng is None else rng
    info = cfg.signet(entry)
    if info is None:
        raise KeyError(f"signet_info has no row for signet {entry}")
    if str(info["main_attr"] or "0") != "0":
        return _fixed(info["main_attr"], "|"), _fixed(info["sub_attr"] or "", ",")
    by_entry = {int(r["entry"]): r for r in cfg.signet_attributes()}
    pool = [
        by_entry[int(info[f"attribute{i}"])] for i in range(1, 9)
        if int(info[f"attribute{i}"] or 0) in by_entry
    ]
    if not pool:
        raise KeyError(f"signet {entry} has no signet_attribute_info in attribute1..8")
    main_row = pool[rng.randrange(len(pool))]
    main = [_attr(main_row["attribute_type"], main_row["base_value"])]
    subs: list[dict] = []
    for _ in range(max(0, int(info["quality"] or 1) - 1)):
        if not _add_sub(cfg, int(info["star"]), main, subs, rng):
            break
    return main, subs


def ensure_rolled(
    conn: sqlite3.Connection, cfg: Config, row: sqlite3.Row,
    rng: random.Random | None = None,
) -> sqlite3.Row:
    """The signets row with its attributes, rolled and stored on first use."""
    if row["main_attrs"]:
        return row
    main, subs = roll_attrs(cfg, int(row["entry"]), rng)
    conn.execute(
        "UPDATE signets SET main_attrs = ?, sub_attrs = ? WHERE id = ?",
        (json.dumps(main), json.dumps(subs), int(row["id"])),
    )
    conn.commit()
    return conn.execute("SELECT * FROM signets WHERE id = ?", (int(row["id"]),)).fetchone()


def signet_info(
    registry: Registry, conn: sqlite3.Connection, cfg: Config, row: sqlite3.Row,
    rng: random.Random | None = None,
):
    return build_signet_info(registry, ensure_rolled(conn, cfg, row, rng))


# --- pushes ---------------------------------------------------------------------
def obtained(
    registry: Registry, conn: sqlite3.Connection, cfg: Config, session: Session,
    ids, rng: random.Random | None = None,
) -> None:
    """5_2742 SignetObtainNotify for new signet rows (no-op for none)."""
    if not ids:
        return
    msg = registry.message_class("SignetObtainNotify")()
    for signet_id in ids:
        row = conn.execute("SELECT * FROM signets WHERE id = ?", (int(signet_id),)).fetchone()
        msg.signets.add().CopyFrom(signet_info(registry, conn, cfg, row, rng))
    fill_required(msg)
    session.queue(5, 2742, msg)


def bag_full(registry: Registry, session: Session) -> None:
    """5_2744 SignetBagFullNotify (empty)."""
    msg = registry.message_class("SignetBagFullNotify")()
    fill_required(msg)
    session.queue(5, 2744, msg)


def fight_cnt_changed(registry: Registry, session: Session, left: int) -> None:
    notify.player_changed(registry, session, {"signet_fight_cnt": int(left)})


def mail_signets(
    conn: sqlite3.Connection, cfg: Config, player_id: int, prizes, now: int
) -> int:
    """The signet prizes a full bag could not take, as one mail 101200."""
    return mail.deliver(conn, cfg, player_id, BAG_FULL_MAIL, prizes, now)
