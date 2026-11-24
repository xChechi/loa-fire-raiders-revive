"""Angels (goddesses): 5_2303 SummonAngelReq, 5_2305 UpgradeAngelStarReq.

Guide 10293 sends 5_2303 {angel_entry} (AngelPreviewCircle.lua:195-197), and
AngelUI:onSummonGod reads msg.angel with no nil check (AngelUI.lua:80,100), so
a summon that succeeds always carries the full ClientAngel. AngelSkill:
onUpgradeStar does the same for star-up (AngelSkill.lua:44-50,196-206).

Costs: a summon takes angel_info(star 1).activation_item_num of
activation_item (AngelCard.lua:352-353) plus ANGEL_STAR_UP_COST_1 gold; a
star-up takes the NEXT star row's activation_item_num
(ClientAngel:upstarDiamondNum, ClientAngel.lua:224-231) plus
ANGEL_STAR_UP_COST_{star+1} gold (AngelDiamondPanel.lua:167).

The ClientAngel shape follows the real server dump in BattleUnit.lua:3762-3777:
two spell ids, six auras with the zeros kept. `ability` has no formula in the
client and no table (plan open question O2), so it is 0.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.config import Config
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.angel")

STATUS_OK = 0
STATUS_NOT_ENOUGH_GOLD = 327937      # language.db 金币不足
STATUS_NOT_ENOUGH_ITEMS = 327942     # language.db 没有足够道具
STATUS_ALREADY_OWNED = 328449        # language.db 已拥有该女神
STATUS_MAX_STAR = 328450             # language.db 女神星级已达最大
STATUS_NOT_OWNED = 328457            # language.db 女神不存在
STATUS_CANNOT_SUMMON = 328459        # language.db 该女神无法召唤

AURA_SLOTS = 6


def build_client_angel(registry: Registry, cfg: Config, row: sqlite3.Row):
    entry, star = int(row["angel_entry"]), int(row["star"])
    info = cfg.angel_by_star(entry, star)
    if info is None:
        raise KeyError(f"angel_info has no row for angel {entry} star {star}")
    msg = registry.message_class("ClientAngel")(
        angel_entry=entry,
        level=int(row["level"]),
        exp=int(row["exp"]),
        star=star,
        ability=0,
        advance_level=0,
    )
    msg.spells.extend([int(info["spell0"] or 0), int(info["spell1"] or 0)])
    msg.auras.extend([int(info[f"aura{i}"] or 0) for i in range(AURA_SLOTS)])
    fill_required(msg)
    return msg


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _owned(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
            (pid, entry),
        ).fetchone()

    def _refused(name: str, status: int, entry: int, why: str):
        log.info("%s for angel %d refused %d: %s", name, entry, status, why)
        res = registry.message_class(name)(status=status)
        fill_required(res)
        return res

    def _have(pid: int, item_entry: int) -> int:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
            (pid, item_entry),
        ).fetchone()
        return int(row["amount"]) if row else 0

    def _pay(session: Session, pid: int, item_entry: int, stones: int, gold: int):
        """Both costs were checked by the caller, so neither helper raises."""
        left = db.take_item(conn, pid, item_entry, stones)
        db.spend(conn, pid, gold=gold)
        notify.items_changed(registry, session, [(item_entry, left)])
        new_gold = conn.execute(
            "SELECT gold FROM players WHERE id = ?", (pid,)
        ).fetchone()["gold"]
        notify.player_changed(registry, session, {"gold": int(new_gold)})

    def summon(session: Session, req):
        name = "SummonAngelRes"
        entry = int(req.angel_entry)
        player = _player(session)
        pid = int(player["id"])
        if _owned(pid, entry) is not None:
            return _refused(name, STATUS_ALREADY_OWNED, entry, "already owned")
        info = cfg.angel_by_star(entry, 1)
        if info is None:
            return _refused(name, STATUS_CANNOT_SUMMON, entry, "no star-1 row")
        stone, stones = int(info["activation_item"]), int(info["activation_item_num"])
        gold = cfg.variable_int("ANGEL_STAR_UP_COST_1", 0)
        if _have(pid, stone) < stones:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, entry, f"{stones}x {stone}")
        if int(player["gold"]) < gold:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, entry, f"{gold} gold")
        _pay(session, pid, stone, stones, gold)
        db.grant_angel(conn, pid, entry, level=int(info["min_level"] or 1), star=1)
        res = registry.message_class(name)(status=STATUS_OK)
        res.angel.CopyFrom(build_client_angel(registry, cfg, _owned(pid, entry)))
        log.info("angel %d summoned by player %d for %dx %d", entry, pid, stones, stone)
        fill_required(res)
        return res

    def star_up(session: Session, req):
        name = "UpgradeAngelStarRes"
        entry = int(req.angel_entry)
        player = _player(session)
        pid = int(player["id"])
        row = _owned(pid, entry)
        if row is None:
            return _refused(name, STATUS_NOT_OWNED, entry, "not owned")
        star = int(row["star"]) + 1
        info = cfg.angel_by_star(entry, star)
        if info is None:
            return _refused(name, STATUS_MAX_STAR, entry, f"no star-{star} row")
        stone, stones = int(info["activation_item"]), int(info["activation_item_num"])
        gold = cfg.variable_int(f"ANGEL_STAR_UP_COST_{star}", 0)
        if _have(pid, stone) < stones:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, entry, f"{stones}x {stone}")
        if int(player["gold"]) < gold:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, entry, f"{gold} gold")
        _pay(session, pid, stone, stones, gold)
        conn.execute("UPDATE angels SET star = ? WHERE id = ?", (star, int(row["id"])))
        conn.commit()
        notify.angel_changed(registry, session, entry, {"star": star})
        res = registry.message_class(name)(status=STATUS_OK)
        res.angel.CopyFrom(build_client_angel(registry, cfg, _owned(pid, entry)))
        log.info("angel %d of player %d raised to star %d", entry, pid, star)
        fill_required(res)
        return res

    return {(5, 2303): summon, (5, 2305): star_up}
