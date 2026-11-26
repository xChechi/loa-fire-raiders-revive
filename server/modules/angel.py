"""Angels (goddesses): 5_2303 SummonAngelReq, 5_2305 UpgradeAngelStarReq,
5_2323 UpgradeAngelSpellReq, 5_2309 UpgradeAngelAuraReq.

Spell and aura levels are stored (angels.spell0_lv.., aura0_lv..) and the ids
are walked from the current star row's bases, so levels carry across star-up
(plan B2-wave2 O-W2-6).

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
from server.modules.hero import spell_at_level
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
STATUS_AURA_MAX = 328453             # language.db 女神光环已达最大等级
STATUS_AURA_AT_ANGEL_LEVEL = 328454  # language.db 女神光环等级已达女神等级
STATUS_SPELL_MAX = 328460            # language.db 女神技能已达最大等级
STATUS_SPELL_AT_ANGEL_LEVEL = 328461 # language.db 女神技能等级已达女神等级
STATUS_NO_SUCH_AURA = 328462         # language.db 女神没有该光环
STATUS_INTERNAL = 327681             # language.db 系统内部错误

SPELL_SLOTS = 2
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
        advance_level=int(row["advance_level"]),
        # Not notify fields (notify.ANGEL_FIELDS): Res and login only.
        glory_level=int(row["glory_level"]),
        glory_star=int(row["glory_star"]),
    )
    msg.spells.extend(
        [_resolved(cfg, info, row, f"spell{i}") for i in range(SPELL_SLOTS)]
    )
    msg.auras.extend([_resolved(cfg, info, row, f"aura{i}") for i in range(AURA_SLOTS)])
    fill_required(msg)
    return msg


def _resolved(cfg: Config, info, row: sqlite3.Row, slot: str) -> int:
    """The slot's id at its stored level, walked from the star row's base
    (O-W2-6); an empty (0) slot stays 0."""
    base = int(info[slot] or 0)
    return spell_at_level(cfg, base, int(row[f"{slot}_lv"])) if base else 0


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

    def _walk(row, kind: str, wanted: int, target: int):
        """Plan the upgrade of the `kind` slot ("spell" or "aura") whose current
        id is `wanted`: one step, or up to `target` when it is set. A step costs
        the CURRENT row's upgrade_cost (AngelSkillCell.lua:168-209,
        AngelCircleCell.lua:300) and is allowed while the row's level is below
        the angel level and angel_info.max_level (AngelSkillCell.lua:220-226,
        441-442). Returns (index, steps, new_id, cost, None) or
        (None, 0, 0, 0, (reason, why))."""
        info = cfg.angel_by_star(int(row["angel_entry"]), int(row["star"]))
        slots = SPELL_SLOTS if kind == "spell" else AURA_SLOTS
        index = next(
            (i for i in range(slots)
             if wanted and _resolved(cfg, info, row, f"{kind}{i}") == wanted),
            None,
        )
        if index is None:
            return None, 0, 0, 0, ("none", f"{kind} {wanted} is not in any slot")
        angel_level, max_level = int(row["level"]), int(info["max_level"])
        spell, steps, cost = wanted, 0, 0
        while not (steps and (target == 0 or spell == target)):
            cur = cfg.spell(spell)
            level, nxt = int(cur["level"]), int(cur["next"] or 0)
            if level >= max_level or not nxt:
                return None, 0, 0, 0, ("max", f"{spell} level {level} at max {max_level}")
            if level >= angel_level:
                return None, 0, 0, 0, (
                    "angel", f"{spell} level {level} at angel level {angel_level}"
                )
            cost += int(cur["upgrade_cost"] or 0)
            spell, steps = nxt, steps + 1
        return index, steps, spell, cost, None

    def _apply(session: Session, pid: int, row, kind: str, index: int,
               steps: int, cost: int) -> None:
        """The caller checked the gold, so spend does not raise."""
        column = f"{kind}{index}_lv"  # one of the fixed angels columns
        db.spend(conn, pid, gold=cost)
        conn.execute(
            f"UPDATE angels SET {column} = {column} + ? WHERE id = ?",
            (int(steps), int(row["id"])),
        )
        conn.commit()
        new_gold = conn.execute(
            "SELECT gold FROM players WHERE id = ?", (pid,)
        ).fetchone()["gold"]
        notify.player_changed(registry, session, {"gold": int(new_gold)})

    def spell_up(session: Session, req):
        """5_2323. UpgradeAngelSpellRes has no status, so it cannot refuse
        (plan global constraint): a refusal logs the language code and answers
        the unchanged angel. AngelSkill:onUpskill indexes the angel by
        msg.angel.angel_entry with no nil check (AngelSkill.lua:96-97)."""
        name = "UpgradeAngelSpellRes"
        entry, wanted = int(req.angel_entry), int(req.spell)
        target = int(req.upgrade_spell)
        player = _player(session)
        pid = int(player["id"])
        row = _owned(pid, entry)
        if row is None:
            # No angel to answer with: a made-up one would crash the lookup or
            # mark an unowned angel as owned. The client unlocks after 3 s
            # (AngelSkill:lockUI, AngelSkill.lua:237-253).
            log.warning(
                "%s for angel %d of player %d would be refused %d: not owned;"
                " sending nothing", name, entry, pid, STATUS_NOT_OWNED,
            )
            return None
        index, steps, new_id, cost, why = _walk(row, "spell", wanted, target)
        if why is None and int(player["gold"]) < cost:
            why = ("gold", f"{cost} gold")
        if why is not None:
            status = {
                "none": STATUS_INTERNAL, "max": STATUS_SPELL_MAX,
                "angel": STATUS_SPELL_AT_ANGEL_LEVEL, "gold": STATUS_NOT_ENOUGH_GOLD,
            }[why[0]]
            log.warning(
                "%s for angel %d of player %d would be refused %d: %s;"
                " answering the unchanged angel", name, entry, pid, status, why[1],
            )
        else:
            _apply(session, pid, row, "spell", index, steps, cost)
            notify.angel_changed(registry, session, entry, {f"spell{index}": new_id})
            log.info(
                "angel %d of player %d: spell%d %d -> %d for %d gold",
                entry, pid, index, wanted, new_id, cost,
            )
        res = registry.message_class(name)(upgrade_spell=target)
        res.angel.CopyFrom(build_client_angel(registry, cfg, _owned(pid, entry)))
        fill_required(res)
        return res

    def aura_up(session: Session, req):
        """5_2309. AngelCircle:onUpgradeAura writes msg.aura into
        auras[aura_index + 1] and msg.angel_ability into the angel
        (AngelCircle.lua:102-123)."""
        name = "UpgradeAngelAuraRes"
        entry, wanted = int(req.angel_entry), int(req.aura)
        target = int(req.upgrade_aura)
        player = _player(session)
        pid = int(player["id"])
        row = _owned(pid, entry)
        if row is None:
            return _refused(name, STATUS_NOT_OWNED, entry, "not owned")
        index, steps, new_id, cost, why = _walk(row, "aura", wanted, target)
        if why is not None:
            status = {
                "none": STATUS_NO_SUCH_AURA, "max": STATUS_AURA_MAX,
                "angel": STATUS_AURA_AT_ANGEL_LEVEL,
            }[why[0]]
            return _refused(name, status, entry, why[1])
        if int(player["gold"]) < cost:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, entry, f"{cost} gold")
        _apply(session, pid, row, "aura", index, steps, cost)
        log.info(
            "angel %d of player %d: aura%d %d -> %d for %d gold",
            entry, pid, index, wanted, new_id, cost,
        )
        # angel_ability has no formula in the client (Wave 1 O2), so 0.
        res = registry.message_class(name)(
            status=STATUS_OK, angel_entry=entry, angel_ability=0, aura=new_id,
            aura_index=index, upgrade_aura=target,
        )
        fill_required(res)
        return res

    return {
        (5, 2303): summon, (5, 2305): star_up,
        (5, 2309): aura_up, (5, 2323): spell_up,
    }
