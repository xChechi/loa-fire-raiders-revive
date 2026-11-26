"""Hero rebirth (转生): 5_2695 HeroTransmigrateReq (plan B2 Wave 3, task B7).

What the client reads (the spec):

- The rebirth button sits on a hero's training cell (TrainCell.lua:428-438,
  dispatching TRAIN_REBIRTH_BTN_CLICK) and shows only when the hero has a next
  hero_transmigrate row and its level >= that row's need_level
  (TrainCell:isCanRebirth, TrainCell.lua:588-598); otherwise the cell shows
  h07019 "重生次数已达上限" or "need level N" (:456-464). The click opens
  RoleRebirthPanel (TrainCtr.lua:118-125).
- RoleRebirthPanel reads hero_transmigrate by transmigrate_level, the hero's
  current row and the next (RoleRebirthPanel.lua:25-26); it shows the next
  row's gold_cost, the growth_add of both rows as percentages (:223-233), and
  the level after rebirth from RoleData:getHeroInfoAfterRebirth (:226,239).
  It checks gold client-side (isCanofferCost, :266-275, the player's gold
  asset) and sends 5_2695 {entry} only when the gold is there (:253-265).
- RoleData:getHeroInfoAfterRebirth (RoleData.lua:2397-2449), "display only":
  the xp of every level from the next row's need_level up to the hero's level
  (hero_xp_for_next_level of lvl need_level..level-1, plus the current xp) is
  re-levelled from level 1 along xp_for_level; the result is the new level and
  xp. If the xp outruns the whole table the last lvl with xp 0 comes out
  (:2431-2440). The server applies the same rule, so the hero lands where the
  panel said it would.
- 5_2696 HeroTransmigrateRes is empty (proto) and its listener does nothing
  (TrainCtr.lua:127-132). The change reaches the client only as the ident-2
  hero notify: the INFO_CHANGE_NTF_HERO listener calls
  TrainCell:updateAfterRebirth(data) (TrainCtr.lua:146-151), which needs
  data.transmigrate_level different from the cell's and takes data.level and
  data.xp (TrainCell.lua:471-499); ClientHero:updateByFields copies
  transmigrate_level and max_level (ClientHero.lua:389-395).
- growth_add is h07007 "属性成长加成" and h07009 "属性成长加成影响每次升级时属性的
  增加量" (RoleRebirthPanel.lua:121,148): a share of the per-level stat gain.
  Each row carries the total (0.1, 0.2, ... 1.5), the panel shows the current
  row's value against the next one's. bonus() applies it to the hero's
  hero_growth gain, as breakthrough's grow_add.
- The level cap does not change: the client caps a hero at
  xp_for_level(player level).hero_max_level only (LevelHelp:checkLevel,
  train/LevelHelp.lua:16-36), so train.py and level.py stay as they are.
- max_level is "历史最高等级" (ClientHero.lua:164); the server sends it equal to
  level (hero.build_client_hero_with_runes), and the notify here follows that
  convention through hero_notify_fields_with_runes.
- Function 90000 英雄转生, unlock_level 55.

HeroTransmigrateRes has no `status`, so nothing here can refuse: a miss logs
a WARNING with the code it would have used and answers the empty Res.

Status codes (language.db):
  327937 金币不足, 327941 英雄不存在, 327944 等级不够,
  327957 未满足此玩法的等级. No code exists for "no next row" (the client
  shows the lan text h07019 and never sends), so that miss logs none.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Callable

from server import db
from server.config import Config
from server.modules import hero as hero_mod
from server.modules import notify, train
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.rebirth")

FUNCTION = 90000                     # 英雄转生, unlock_level 55

STATUS_NOT_ENOUGH_GOLD = 327937      # 金币不足
STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_LEVEL_TOO_LOW = 327944        # 等级不够
STATUS_FUNCTION_LOCKED = 327957      # 未满足此玩法的等级


def level_after(cfg: Config, level: int, xp: int, need_level: int) -> tuple[int, int]:
    """RoleData:getHeroInfoAfterRebirth (RoleData.lua:2399-2449)."""
    needs: list[tuple[int, int]] = []
    lvl = 1
    while (row := cfg.xp_for_level(lvl)) is not None:
        needs.append((lvl, int(row["hero_xp_for_next_level"] or 0)))
        lvl += 1
    left = 0
    for lvl, need in needs:
        if lvl < need_level:
            continue
        if lvl < level:
            left += need
        elif lvl == level:
            left += int(xp)
        else:
            break
    result_level, result_xp = 1, 0
    for lvl, need in needs:
        result_level = lvl
        if need <= left:
            left -= need
        else:
            result_xp = left
            break
    return result_level, result_xp


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row) -> dict[str, float]:
    """growth_add of the hero's transmigrate level as a share of its growth
    gain: (level - 1) x hero_growth(hero, star)[field] x growth_add for every
    hero_growth column (h07009, RoleRebirthPanel.lua:148)."""
    level = int(hero_row["transmigrate_level"])
    steps = max(0, int(hero_row["level"]) - 1)
    if not level or not steps:
        return {}
    row = cfg.hero_transmigrate(level)
    if row is None:
        raise KeyError(f"hero_transmigrate has no row for level {level}")
    grow = float(row["growth_add"] or 0)
    growth = cfg.hero_growth(int(hero_row["entry"]), int(hero_row["star"]))
    if not grow or growth is None:
        return {}
    out: dict[str, float] = {}
    for field in hero_mod.GROWTH_FIELDS:
        value = steps * float(growth[field] or 0) * grow
        if value:
            out[field] = value
    return out


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], float] | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _hero(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (pid, int(entry)),
        ).fetchone()

    def _res():
        res = registry.message_class("HeroTransmigrateRes")()
        fill_required(res)
        return res

    def _warn(status: int | None, why: str):
        code = "" if status is None else f" {status}"
        log.warning("HeroTransmigrateRes would refuse%s (no status field): %s", code, why)
        return _res()

    def transmigrate(session: Session, req):
        player = _player(session)
        pid = int(player["id"])
        if _hero(pid, req.entry) is None:
            return _warn(STATUS_NO_HERO, f"hero {req.entry}")
        unlock = cfg.function_unlock(FUNCTION)
        if int(player["level"]) < unlock:
            return _warn(STATUS_FUNCTION_LOCKED,
                         f"player level {player['level']} < {unlock}")
        # The cell the panel opens from ticks training xp locally; settle the
        # slot so the level check and the reset see the same xp.
        train.settle(registry, cfg, conn, session, player, now_of())
        row = _hero(pid, req.entry)
        current = int(row["transmigrate_level"])
        nxt = cfg.hero_transmigrate(current + 1)
        if nxt is None:
            return _warn(None, f"hero {row['entry']} at the top, transmigrate level {current}")
        need_level = int(nxt["need_level"])
        if int(row["level"]) < need_level:
            return _warn(STATUS_LEVEL_TOO_LOW,
                         f"hero {row['entry']} level {row['level']} < {need_level}")
        cost = int(nxt["gold_cost"])
        try:
            db.spend(conn, pid, gold=cost)
        except ValueError as exc:
            return _warn(STATUS_NOT_ENOUGH_GOLD, str(exc))
        level, xp = level_after(cfg, int(row["level"]), int(row["xp"]), need_level)
        conn.execute(
            "UPDATE heroes SET transmigrate_level = ?, level = ?, xp = ? WHERE id = ?",
            (current + 1, level, xp, int(row["id"])),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM heroes WHERE id = ?", (int(row["id"]),)).fetchone()
        gold = int(conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()["gold"])
        notify.player_changed(registry, session, {"gold": gold})
        fields = hero_mod.hero_notify_fields_with_runes(
            registry, cfg, row, hero_mod.runes_of(conn, row), conn=conn
        )
        fields["transmigrate_level"] = current + 1
        notify.hero_changed(registry, session, int(row["entry"]), fields)
        log.info(
            "hero %d of player %d reborn to transmigrate level %d for %d gold:"
            " level %d xp %d", row["entry"], pid, current + 1, cost, level, xp,
        )
        return _res()

    return {(5, 2695): transmigrate}
