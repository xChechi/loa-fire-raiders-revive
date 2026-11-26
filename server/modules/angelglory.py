"""Angel Radiance (圣辉, function 90280, level 49): 5_2909 AngelGloryQueryReq,
5_2911 AngelGloryUpgradeReq, 5_2913 AngelGloryInheritReq.

What the client reads (step 1):
- 5_2911 is sent as {angel_entry} (AngelShengHui.lua:472) only when the angel is
  not at the top and the stone count covers the row's cost (:451-466); when short
  the client itself offers store 21 (:458-463).
- The 5_2912 listener reads msg.angel_glory.level/.star and applies them with
  ClientAngel:updateGloryInfo (AngelShengHui.lua:431-437). updateGloryInfo
  (ClientAngel.lua:262-284) returns -1 when nothing changed (the client shows
  h30018 "升级失败，请重试"), 0 on a higher star, 1 on a higher level. So a failed
  roll and every refusal answer the unchanged glory.
- The glory stone is item 2800 (COST_STONE_ID, AngelShengHui.lua:17); the cost is
  the CURRENT row's `cost` (:120-123, :482). The row (level, star) also shows the
  next light's property and rate (:73-78), so lighting row (L, S) rolls its
  `rate` and grants its property. The accumulated bonus is every row strictly
  below (level, star) (AngelShengHuiData.lua:46-92).
- Six balls a level (MAX_BALL_NUM, AngelShengHui.lua:12); stars run 0..5 per
  level in angel_glory_info. Lighting the last star of a level gives level + 1,
  star 0 (updateGloryInfo returns 1, "升阶成功", :573-578). The server takes
  "last star" from the table: no row at (level, star + 1).
- The top is the row with property_id 0 and property 0 (AngelShengHuiData.lua:
  23-28), i.e. (100, 0); isTopLevel is level > top or (level == top and
  star >= top star) (:31-44).
- 5_2913 is sent as {angel_entry_1 = the current angel (receives), angel_entry_2
  = the chosen angel (gives)} (AngelShengHuiInheritancePanel.lua:149-152, proto
  comment :137-141: 1 = 被传承, 2 = 传承). The picker lists only angels whose glory
  is strictly higher than the current one's (AngelSelector.lua:162-182). The cost
  is ANGEL_GLORY_INHERIT_COST diamonds (:575-588). The 5_2914 listener zeroes the
  giver and copies its glory onto the receiver locally, with no check
  (:205-216).
- 5_2909 has no sender (inventory); it answers the stored glory.
- O-W3-12: the radiance property is read only by the angel's own views: the
  title (AngelCell.lua:80-88) and the halo tooltip "圣辉加成" (RoleUISkillTipsPanel
  .lua:73-80, index2attrId maps it onto the six halos). Nothing in the battle or
  hero code reads it, so it changes no hero stats and this module has no bonus().

No Res here has a `status` (AngelGloryQueryRes, AngelGloryUpgradeRes:
{angel_glory}; AngelGloryInheritRes: {}), so a refusal logs a WARNING with the
code it would have used and answers the current state. language.db codes:
- 328457 "女神不存在" (女神)
- 338163 "升级达到上限" (圣辉)
- 338164 "传承只能从高到低" (女神进阶)
- 327942 "没有足够道具" (玩家)
- 327938 "钻石不足" (玩家)

Known gap: the client applies 5_2914 without a status, so a refused inheritance
still shows the moved glory until the next login sends the stored values
(glory_level/glory_star are not notify fields, notify.ANGEL_FIELDS).
"""

from __future__ import annotations

import logging
import random
import sqlite3

from server import db
from server.config import Config
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.angelglory")

STATUS_NOT_OWNED = 328457      # language.db 女神不存在
STATUS_TOP = 338163            # language.db 升级达到上限 (圣辉)
STATUS_HIGH_TO_LOW = 338164    # language.db 传承只能从高到低
STATUS_NOT_ENOUGH_ITEMS = 327942  # language.db 没有足够道具
STATUS_NOT_ENOUGH_DIAMOND = 327938  # language.db 钻石不足

COST_STONE_ID = 2800  # AngelShengHui.lua:17


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    roll = rng or random.Random()

    def _pid(session: Session) -> int:
        if session.player_id is not None:
            return int(session.player_id)
        return int(db.find_player(conn, settings.username)["id"])

    def _angel(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
            (pid, int(entry)),
        ).fetchone()

    def _glory(row) -> tuple[int, int]:
        if row is None:
            return 0, 0
        return int(row["glory_level"]), int(row["glory_star"])

    def _answer(name: str, level: int, star: int):
        res = registry.message_class(name)()
        res.angel_glory.level = level
        res.angel_glory.star = star
        fill_required(res)
        return res

    def _set(pid: int, entry: int, level: int, star: int) -> None:
        conn.execute(
            "UPDATE angels SET glory_level = ?, glory_star = ?"
            " WHERE player_id = ? AND angel_entry = ?",
            (level, star, pid, int(entry)),
        )
        conn.commit()

    def query(session: Session, req):
        pid = _pid(session)
        level, star = _glory(_angel(pid, req.angel_entry))
        return _answer("AngelGloryQueryRes", level, star)

    def upgrade(session: Session, req):
        name = "AngelGloryUpgradeRes"
        pid, entry = _pid(session), int(req.angel_entry)
        angel = _angel(pid, entry)
        if angel is None:
            log.warning("5_2911 angel %d would refuse %d: not owned", entry, STATUS_NOT_OWNED)
            return _answer(name, 0, 0)
        level, star = _glory(angel)
        row = cfg.angel_glory(level, star)
        if row is None or (int(row["property_id"]) == 0 and int(row["property"]) == 0):
            log.warning("5_2911 angel %d would refuse %d: top at %d/%d",
                        entry, STATUS_TOP, level, star)
            return _answer(name, level, star)
        cost = int(row["cost"])
        have = next(
            (int(r["amount"]) for r in db.items_of(conn, pid)
             if int(r["entry"]) == COST_STONE_ID),
            0,
        )
        if have < cost:
            log.warning("5_2911 angel %d would refuse %d: %d/%d of item %d",
                        entry, STATUS_NOT_ENOUGH_ITEMS, have, cost, COST_STONE_ID)
            return _answer(name, level, star)
        left = db.take_item(conn, pid, COST_STONE_ID, cost)
        notify.items_changed(registry, session, [(COST_STONE_ID, left)])
        rate = float(row["rate"])
        if rate >= 1 or roll.random() < rate:
            if cfg.angel_glory(level, star + 1) is None:
                level, star = level + 1, 0
            else:
                star += 1
            _set(pid, entry, level, star)
            log.info("angel %d radiance lit to %d/%d for %d stones", entry, level, star, cost)
        else:
            log.info("angel %d radiance roll failed at %d/%d (rate %s)", entry, level, star, rate)
        return _answer(name, level, star)

    def inherit(session: Session, req):
        res = registry.message_class("AngelGloryInheritRes")()
        fill_required(res)
        pid = _pid(session)
        to_entry, from_entry = int(req.angel_entry_1), int(req.angel_entry_2)
        receiver, giver = _angel(pid, to_entry), _angel(pid, from_entry)
        if receiver is None or giver is None:
            log.warning("5_2913 %d<-%d would refuse %d: not owned",
                        to_entry, from_entry, STATUS_NOT_OWNED)
            return res
        if to_entry == from_entry or _glory(giver) <= _glory(receiver):
            log.warning("5_2913 %d<-%d would refuse %d: %s onto %s",
                        to_entry, from_entry, STATUS_HIGH_TO_LOW,
                        _glory(giver), _glory(receiver))
            return res
        cost = cfg.variable_int("ANGEL_GLORY_INHERIT_COST", 1000)
        diamond = int(conn.execute(
            "SELECT diamond FROM players WHERE id = ?", (pid,)
        ).fetchone()["diamond"])
        if diamond < cost:
            log.warning("5_2913 %d<-%d would refuse %d: %d/%d diamonds",
                        to_entry, from_entry, STATUS_NOT_ENOUGH_DIAMOND, diamond, cost)
            return res
        db.spend(conn, pid, diamond=cost)
        notify.player_changed(registry, session, {"diamond": diamond - cost})
        level, star = _glory(giver)
        _set(pid, to_entry, level, star)
        _set(pid, from_entry, 0, 0)
        log.info("angel radiance %d/%d moved %d -> %d for %d diamonds",
                 level, star, from_entry, to_entry, cost)
        return res

    return {
        (5, 2909): query,
        (5, 2911): upgrade,
        (5, 2913): inherit,
    }
