"""Angel advance (女神进阶, function 90030, level 60): 5_2779
AngelAdvanceQueryReq, 5_2781 AngelAdvanceReq, 5_2783 AngelAdvanceAutoReq,
5_2785 AngelAdvanceReportQueryReq, 5_2803 AngelInheritanceReq (plan B2 Wave 3,
task B10).

What the client reads (the spec):

- The top level is the angel_advance_info row count - 1 = 21 (AngelAdvance.lua:
  22-24); at the top the client floats h08021 and sends nothing (:423-433), and
  greys both buttons (:500-508). The server takes "top" from the table: no row
  at level + 1 (row 21 has rate '0:0' and max_score 0).
- The panel reads angel_advance_info by `level` (:91-93). The stone is item
  1900 (g_roleData:getItemNum(1900), :173,189); a try costs the CURRENT row's
  advance_stone (:168,188). The client checks only the stones before sending
  (isCanOffer :183-196, isCanAdvance :423-452; when short it offers store 21,
  :442-445); it never checks the row's `gold`, so a gold shortfall reaches the
  server.
- 5_2779 {entry} is sent on open and after the success panel closes
  (:61, :593). The 5_2780 listener copies advance_level, advance_score and
  advance_fight and calls angelInfo:updateAdvanceLevel (:519-526). The bar is
  advance_score / the current row's max_score (:101-105).
- 5_2781/5_2783 {entry} (:657-669). The 5_2782/5_2784 listeners copy
  advance_level and advance_score (the bar value, so the CURRENT score, not the
  gain the proto comment names) and on state 1 run AdvanceSuccess(advance_fight)
  (:535-581), which passes advance_fight as `perAbility`, the pre-advance
  ability the success panel compares with serverInfo.ability
  (:198-202, AngelAdvanceSucPanel.lua:37-45,192). The query's advance_fight is
  listed as h08012 "加成战力" (AngelAdvance.lua:622).
- advance_fight: angel ability has no formula in the client (angel.py sends
  ability 0, plan open question O2), so both meanings are 0 here.
- advance_diamond (AngelAdvanceAutoRes field 3, proto comment "进阶所需进阶石")
  is never read by the client (:564-581), and no Lua offers diamonds in place
  of stones, so auto spends no diamonds and sends 0.
- O-W3-12: halo1..6 is read only by the advance views (AngelAdvance.lua:
  609-618, AngelInheritancePanel.lua:624-631) and the halo tooltip "进阶加成+"
  (RoleUISkillTipsPanel.lua:64-69); rage_rate is read only in commented-out
  lines (AngelAdvance.lua:623-629, AngelInheritancePanel.lua:640-645). Nothing
  in the battle or hero Lua reads either, so advance changes no hero stats and
  this module has no bonus().
- 5_2785 {advance_level} lists other players' advances; a single-player world
  has none, so the Res is empty.
- 5_2803 {entry_1 = the current angel (被传承, receives), entry_2 = the chosen
  angel (传承, gives)} (AngelInheritancePanel.lua:134-149). The picker lists only
  angels whose advance_level is strictly above the current one's
  (AngelSelector.lua:125-134). The cost is ANGEL_INHERITANCE_DIAMOND diamonds
  (AngelInheritancePanel.lua:601-615). h10008 "传承后的进阶等级为传承女神的进阶等级":
  the receiver takes the giver's level. The 5_2804 listener applies it locally
  with no check: receiver + (giver - receiver), giver 0 (:206-217); `ability`
  is "女神战力" (:203-204), 0 here as above.

Success rule (O-W3-8, the score ladder like breakthrough): each try pays the
row's gold and stones and adds randint(advance_min, advance_max) to the score;
it succeeds when random() < p, p being the ladder rate of the highest bracket
<= the new score, and p = 1 from max_score on. Success raises the level and
resets the score to 0. Auto repeats until a success or a shortfall.

None of these Res has `status` (proto), so nothing here can refuse: a
shortfall logs a WARNING with the code it would have used and answers the
current state. language.db codes:
  328457 女神不存在, 327937 金币不足, 327942 没有足够道具, 327938 钻石不足,
  327957 未满足此玩法的等级, 339175 已达最大进阶等级, 338164 传承只能从高到低.

Not done here: h08008 "进阶值每周一凌晨5点清空" (AngelAdvance.lua:460-462) says the
score clears every Monday 05:00; nothing in the Lua does it.

Known gap: the client applies 5_2804 without a status, so a refused
inheritance still shows the moved level until the angel notifies of the next
change or the next login.
"""

from __future__ import annotations

import logging
import random
import sqlite3

from server import db
from server.config import Config, parse_rate_ladder
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.angeladvance")

FUNCTION = 90030                     # 女神进阶
STONE_ITEM = 1900                    # AngelAdvance.lua:173,189

STATUS_NOT_OWNED = 328457            # 女神不存在
STATUS_NOT_ENOUGH_GOLD = 327937      # 金币不足
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_NOT_ENOUGH_DIAMOND = 327938   # 钻石不足
STATUS_FUNCTION_LOCKED = 327957      # 未满足此玩法的等级
STATUS_TOP_LEVEL = 339175            # 已达最大进阶等级
STATUS_HIGH_TO_LOW = 338164          # 传承只能从高到低


def success_rate(row, score: int) -> float:
    """O-W3-8: the ladder rate of the highest bracket <= score; 1 from
    max_score on."""
    max_score = int(row["max_score"] or 0)
    if max_score and score >= max_score:
        return 1.0
    rate = 0.0
    for bracket, value in parse_rate_ladder(row["rate"]):
        if bracket <= score:
            rate = value
    return rate


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    rand = rng or random.Random()

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _angel(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
            (pid, int(entry)),
        ).fetchone()

    def _stones(pid: int) -> int:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
            (pid, STONE_ITEM),
        ).fetchone()
        return int(row["amount"]) if row else 0

    def _set(row, level: int, score: int) -> None:
        conn.execute(
            "UPDATE angels SET advance_level = ?, advance_score = ? WHERE id = ?",
            (level, score, int(row["id"])),
        )
        conn.commit()

    def _res(name: str, row, state: int | None = None):
        res = registry.message_class(name)(advance_fight=0)
        if row is not None:
            res.advance_level = int(row["advance_level"])
            res.advance_score = int(row["advance_score"])
        if state is not None:
            res.state = state
        if name == "AngelAdvanceAutoRes":
            res.advance_diamond = 0
        fill_required(res)
        return res

    def _warn(name: str, status: int, why: str) -> None:
        log.warning("%s would refuse %d (no status field): %s", name, status, why)

    def _attempt(player, row) -> tuple[str, int, int]:
        """One try on an angel below the top: ('gold'|'stones'|'ok'|'success',
        gold, stones). A shortfall writes nothing."""
        pid = int(player["id"])
        info = cfg.angel_advance(int(row["advance_level"]))
        gold = int(info["gold"] or 0)
        stones = int(info["advance_stone"] or 0)
        have_gold = int(conn.execute(
            "SELECT gold FROM players WHERE id = ?", (pid,)
        ).fetchone()["gold"])
        if have_gold < gold:
            return "gold", 0, 0
        if _stones(pid) < stones:
            return "stones", 0, 0
        db.take_item(conn, pid, STONE_ITEM, stones)
        db.spend(conn, pid, gold=gold)
        score = int(row["advance_score"]) + rand.randint(
            int(info["advance_min"]), int(info["advance_max"])
        )
        level = int(row["advance_level"])
        success = rand.random() < success_rate(info, score)
        if success:
            level, score = level + 1, 0
        _set(row, level, score)
        return ("success" if success else "ok"), gold, stones

    def _run(session: Session, req, name: str, auto: bool):
        player = _player(session)
        pid = int(player["id"])
        row = _angel(pid, req.entry)
        if row is None:
            _warn(name, STATUS_NOT_OWNED, f"angel {req.entry}")
            return _res(name, None, 0)
        unlock = cfg.function_unlock(FUNCTION)
        if int(player["level"]) < unlock:
            _warn(name, STATUS_FUNCTION_LOCKED, f"player level {player['level']} < {unlock}")
            return _res(name, row, 0)
        start_level = int(row["advance_level"])
        state, tries, gold_spent, stones_spent = 0, 0, 0, 0
        while True:
            level = int(row["advance_level"])
            if cfg.angel_advance(level + 1) is None:
                if not tries:
                    _warn(name, STATUS_TOP_LEVEL, f"angel {row['angel_entry']} at level {level}")
                break
            outcome, gold, stones = _attempt(player, row)
            if outcome in ("gold", "stones"):
                if not tries:
                    if outcome == "gold":
                        _warn(name, STATUS_NOT_ENOUGH_GOLD, f"needs {level}'s gold")
                    else:
                        _warn(name, STATUS_NOT_ENOUGH_ITEMS, f"needs stones {STONE_ITEM}")
                break
            tries += 1
            gold_spent += gold
            stones_spent += stones
            row = conn.execute(
                "SELECT * FROM angels WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if outcome == "success":
                state = 1
                break
            if not auto:
                break
        if tries:
            notify.items_changed(registry, session, [(STONE_ITEM, _stones(pid))])
            gold_left = int(conn.execute(
                "SELECT gold FROM players WHERE id = ?", (pid,)
            ).fetchone()["gold"])
            notify.player_changed(registry, session, {"gold": gold_left})
            if int(row["advance_level"]) != start_level:
                notify.angel_changed(registry, session, int(row["angel_entry"]), {
                    "advance_level": int(row["advance_level"]),
                })
            log.info(
                "angel %d of player %d: %d advance tries, %d gold + %dx %d, level %d score %d%s",
                row["angel_entry"], pid, tries, gold_spent, stones_spent, STONE_ITEM,
                row["advance_level"], row["advance_score"], " (success)" if state else "",
            )
        return _res(name, row, state)

    def query(session: Session, req):
        pid = int(_player(session)["id"])
        row = _angel(pid, req.entry)
        if row is None:
            _warn("AngelAdvanceQueryRes", STATUS_NOT_OWNED, f"angel {req.entry}")
        return _res("AngelAdvanceQueryRes", row)

    def attempt(session: Session, req):
        return _run(session, req, "AngelAdvanceRes", auto=False)

    def attempt_auto(session: Session, req):
        return _run(session, req, "AngelAdvanceAutoRes", auto=True)

    def reports(session: Session, req):
        """Other players' advances; a single-player world has none."""
        res = registry.message_class("AngelAdvanceReportQueryRes")()
        fill_required(res)
        return res

    def inherit(session: Session, req):
        name = "AngelInheritanceRes"
        res = registry.message_class(name)(ability=0)
        fill_required(res)
        player = _player(session)
        pid = int(player["id"])
        to_entry, from_entry = int(req.entry_1), int(req.entry_2)
        receiver, giver = _angel(pid, to_entry), _angel(pid, from_entry)
        if receiver is None or giver is None:
            _warn(name, STATUS_NOT_OWNED, f"{to_entry} <- {from_entry}")
            return res
        if to_entry == from_entry or (
            int(giver["advance_level"]) <= int(receiver["advance_level"])
        ):
            _warn(name, STATUS_HIGH_TO_LOW, f"{to_entry} <- {from_entry}: level "
                  f"{giver['advance_level']} onto {receiver['advance_level']}")
            return res
        cost = cfg.variable_int("ANGEL_INHERITANCE_DIAMOND", 1000)
        diamond = int(player["diamond"])
        if diamond < cost:
            _warn(name, STATUS_NOT_ENOUGH_DIAMOND, f"{diamond}/{cost} diamonds")
            return res
        db.spend(conn, pid, diamond=cost)
        level, score = int(giver["advance_level"]), int(giver["advance_score"])
        _set(receiver, level, score)
        _set(giver, 0, 0)
        notify.player_changed(registry, session, {"diamond": diamond - cost})
        notify.angel_changed(registry, session, to_entry, {"advance_level": level})
        notify.angel_changed(registry, session, from_entry, {"advance_level": 0})
        log.info("angel advance %d (score %d) moved %d -> %d for %d diamonds",
                 level, score, from_entry, to_entry, cost)
        return res

    return {
        (5, 2779): query,
        (5, 2781): attempt,
        (5, 2783): attempt_auto,
        (5, 2785): reports,
        (5, 2803): inherit,
    }
