"""Hero runes: 5_2161 RuneLevelUp and 5_2565 QueryHeroRune.

A hero has five runes, hero_rune_info rune0..rune4 (rune_info entries); each
rune_info row names its rune_level_up key `rune` and the hero level that
unlocks it (RuneDataHelp.lua:168-218). rune_level_up(rune, L) holds the
energy `rune_need`, `gold` and `diamond` of the step L -> L+1, the hero level
`unlock_level` needed to reach L, and the rune's total stats at L. The rune
panel caps a rune at the highest L whose unlock_level the hero has
(getRuneMaxLevel, RuneDataHelp.lua:511-530).

RuneCtr sends three ops (RuneCtr.lua:396-472, 595-609):
- op 1, feed `items[]`: energy = item_info.rune_val x amount; gold =
  energy x gold/rune_need of the level each part lands in, rounded
  (getRuneCost, RuneDataHelp.lua:297-347; toint = math.round). The rune
  levels up while it may; past the hero-level cap the energy is kept.
- op 2, `up_level` levels for diamonds: the rest of the current level pro
  rata, rounded up, plus each further row's diamond (getDiamondCost /
  getDiamondCostToLevel, RuneDataHelp.lua:710-742).
- op 3, energy kept past the cap becomes levels, free (gethandlerOP,
  RuneCtr.lua:461-472).

RuneLevelUpRes has no status field, so the handler cannot refuse: on any
shortfall it logs WARNING with the language code it would have used and
answers the unchanged rune.
"""

from __future__ import annotations

import logging
import math
import sqlite3

from server import db
from server.config import Config
from server.modules import events, hero, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.rune")

RUNE_FUNCTION = 10170                # function 符文系统 (FunctionType.lua:88)
OP_FEED, OP_DIAMOND, OP_OVERFLOW = 1, 2, 3
CRYSTAL_CLASS = 50                   # 符文晶石: usable for rune levels arg0..arg1-1

# language.db ids, logged only (the Res has no status).
STATUS_INTERNAL_ERROR = 327681       # 系统内部错误
STATUS_NOT_ENOUGH_GOLD = 327937      # 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938   # 钻石不足
STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_LEVEL_TOO_LOW = 327944        # 等级不够
STATUS_RUNE_TOP = 333057             # 已经是当前最高符文等级
STATUS_RUNE_LOCKED = 333058          # 符文还未解锁
STATUS_RUNE_PAST_MAX = 333059        # 超出当前最大符文等级


def _round(value: float) -> int:
    """Lua toint: math.round, i.e. floor(x + 0.5)."""
    return int(math.floor(value + 0.5))


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
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

    def _row(rune_key: int, level: int):
        row = cfg.rune_level(rune_key, level)
        if row is None:
            raise KeyError(f"rune_level_up has no row for {rune_key} level {level}")
        return row

    def _top(rune_key: int, hero_level: int) -> tuple[int, int]:
        """(cap at this hero level, last level of the table)."""
        cap, level = 0, 0
        while (row := cfg.rune_level(rune_key, level)) is not None:
            if int(row["unlock_level"] or 0) <= hero_level:
                cap = level
            level += 1
        return cap, level - 1

    def _rune_res(entry: int, idx: int, level: int, rune_val: int):
        res = registry.message_class("RuneLevelUpRes")(hero=int(entry), idx=int(idx))
        res.rune.idx, res.rune.level, res.rune.rune_val = int(idx), level, rune_val
        fill_required(res)
        return res

    def _feed_gold(rune_key: int, level: int, exp: int, energy: int, top: int) -> int:
        """getRuneCost, walked to the table's last level as the client does."""
        cost, row = 0.0, _row(rune_key, level)
        while True:
            need, gold = int(row["rune_need"]), int(row["gold"])
            if not need:
                break
            if exp + energy > need:
                cost += (need - exp) * gold / need
                energy -= need - exp
                level, exp = level + 1, 0
                row = _row(rune_key, level)
                if level == top:
                    break
            else:
                cost += energy * gold / need
                break
        return _round(cost)

    def _settle(rune_key: int, level: int, exp: int, cap: int) -> tuple[int, int]:
        """Level up while the energy covers rune_need and the cap allows
        (getfutureExp, RuneDataHelp.lua:280-294)."""
        while level < cap:
            need = int(_row(rune_key, level)["rune_need"])
            if not need or exp < need:
                break
            exp, level = exp - need, level + 1
        return level, exp

    def level_up(session: Session, req):
        entry, idx, op = int(req.hero), int(req.idx), int(req.op)
        player = _player(session)
        pid = int(player["id"])
        row = _hero(pid, entry)

        def unchanged(status: int, why: str):
            level, val = 0, 0
            if row is not None and 0 <= idx < hero.RUNE_SLOTS:
                level, val = hero.runes_of(conn, row)[idx]
            log.warning("5_2161 hero %d rune %d op %d not applied (%d): %s",
                        entry, idx, op, status, why)
            return _rune_res(entry, idx, level, val)

        if row is None:
            return unchanged(STATUS_NO_HERO, "hero not owned")
        if not 0 <= idx < hero.RUNE_SLOTS:
            return unchanged(STATUS_INTERNAL_ERROR, "idx outside 0..4")
        unlock = cfg.function_unlock(RUNE_FUNCTION)
        if int(player["level"]) < unlock:
            return unchanged(STATUS_RUNE_LOCKED, f"player level {player['level']} < {unlock}")
        slots = cfg.hero_runes(entry)
        info = cfg.rune(slots[idx]) if slots else None
        if info is None:
            return unchanged(STATUS_RUNE_LOCKED, "no hero_rune_info / rune_info row")
        hero_level = int(row["level"])
        if hero_level < int(info["unlock_level"] or 0):
            return unchanged(
                STATUS_RUNE_LOCKED, f"hero level {hero_level} < {info['unlock_level']}"
            )
        rune_key = int(info["rune"])
        cap, top = _top(rune_key, hero_level)
        level, exp = hero.runes_of(conn, row)[idx]
        gold = diamond = 0
        costs: dict[int, int] = {}

        if op == OP_FEED:
            if level >= cap:
                return unchanged(STATUS_RUNE_TOP, f"level {level} at cap {cap}")
            need = int(_row(rune_key, level)["rune_need"])
            if exp >= need:
                return unchanged(STATUS_RUNE_TOP, f"energy {exp} already fills {need}")
            energy = 0
            for use in req.items:
                refer, amount = int(use.refer), int(use.amount)
                item = cfg.item(refer)
                rune_val = int(item["rune_val"] or 0) if item is not None else 0
                if amount <= 0 or rune_val <= 0:
                    return unchanged(STATUS_INTERNAL_ERROR, f"item {refer} x{amount}")
                if int(item["class"] or 0) == CRYSTAL_CLASS and not (
                    int(item["arg0"] or 0) <= level < int(item["arg1"] or 0)
                ):
                    return unchanged(
                        STATUS_LEVEL_TOO_LOW, f"crystal {refer} not for rune level {level}"
                    )
                costs[refer] = costs.get(refer, 0) + amount
                energy += rune_val * amount
            if not energy:
                return unchanged(STATUS_NOT_ENOUGH_ITEMS, "no items")
            bag = {int(r["entry"]): int(r["amount"]) for r in db.items_of(conn, pid)}
            short = [r for r, n in costs.items() if bag.get(r, 0) < n]
            if short:
                return unchanged(STATUS_NOT_ENOUGH_ITEMS, f"items {short}")
            gold = _feed_gold(rune_key, level, exp, energy, top)
            if int(player["gold"]) < gold:
                return unchanged(STATUS_NOT_ENOUGH_GOLD, f"{gold} gold")
            new_level, new_exp = _settle(rune_key, level, exp + energy, cap)
        elif op == OP_DIAMOND:
            up = int(req.up_level) if req.HasField("up_level") else 1
            target = level + max(up, 1)
            if level >= cap:
                return unchanged(STATUS_RUNE_TOP, f"level {level} at cap {cap}")
            if target > cap:
                return unchanged(STATUS_RUNE_PAST_MAX, f"target {target} past cap {cap}")
            row_now = _row(rune_key, level)
            need, rate = int(row_now["rune_need"]), int(row_now["diamond"])
            diamond = math.ceil(max(0, need - exp) * rate / need) if need else 0
            for lv in range(level + 1, target):
                diamond += int(_row(rune_key, lv)["diamond"])
            if int(player["diamond"]) < diamond:
                return unchanged(STATUS_NOT_ENOUGH_DIAMOND, f"{diamond} diamonds")
            new_level, new_exp = target, 0
        elif op == OP_OVERFLOW:
            new_level, new_exp = _settle(rune_key, level, exp, cap)
            if new_level == level:
                return unchanged(STATUS_RUNE_TOP, f"energy {exp} levels nothing at cap {cap}")
        else:
            return unchanged(STATUS_INTERNAL_ERROR, f"op {op}")

        # Everything is validated: write.
        pairs = [(r, db.take_item(conn, pid, r, n)) for r, n in costs.items()]
        if gold or diamond:
            db.spend(conn, pid, gold=gold, diamond=diamond)
        conn.execute(
            "INSERT INTO runes (player_id, hero, idx, level, rune_val) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(player_id, hero, idx) DO UPDATE SET level = ?, rune_val = ?",
            (pid, entry, idx, new_level, new_exp, new_level, new_exp),
        )
        conn.commit()
        if pairs:
            notify.items_changed(registry, session, pairs)
        if gold or diamond:
            money = conn.execute(
                "SELECT gold, diamond FROM players WHERE id = ?", (pid,)
            ).fetchone()
            notify.player_changed(
                registry, session,
                {k: int(money[k]) for k, v in (("gold", gold), ("diamond", diamond)) if v},
            )
        fields = hero.hero_notify_fields_with_runes(
            registry, cfg, row, hero.runes_of(conn, row), conn=conn
        )
        notify.hero_changed(
            registry, session, entry,
            {k: v for k, v in fields.items() if k in {"ability", *hero.STAT_NAMES}},
        )
        events.bump(conn, cfg, registry, session, pid, events.KIND_HERO_RUNE)
        log.info("hero %d of player %d rune %d op %d: level %d -> %d, rune_val %d,"
                 " %d gold, %d diamonds", entry, pid, idx, op, level, new_level,
                 new_exp, gold, diamond)
        return _rune_res(entry, idx, new_level, new_exp)

    def query(session: Session, req):
        """QueryHeroRuneRes for the player's own hero (MedalDetailInfoUI.lua:362
        sends owner = the own player id); another owner is multiplayer and
        gets an empty answer. ability follows Wave 1 O1."""
        res = registry.message_class("QueryHeroRuneRes")()
        pid = int(_player(session)["id"])
        owner = int(req.owner)
        row = _hero(pid, int(req.entry)) if owner in (0, pid) else None
        if row is None:
            log.warning("5_2565 owner %d hero %d: not one of player %d's heroes",
                        owner, int(req.entry), pid)
        else:
            built = hero.build_client_hero_with_runes(
                registry, cfg, row, hero.runes_of(conn, row), conn=conn
            )
            res.ability = built.ability
            res.runes.extend(built.runes)
        fill_required(res)
        return res

    return {
        (5, 2161): level_up,
        (5, 2565): query,
    }
