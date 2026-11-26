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

The handlers (5_2621, 5_2733-5_2739, 5_2805). None of their Res has a
`status` field (proto), so a refusal changes nothing, logs a WARNING with the
code it would have used and answers the current state:

- 5_2805 {} -> {signets}: every signet, rolled lazily (FunctionType.lua:
  1016-1027 stores them as g_roleData.signets).
- 5_2733 {hero_entry, signet_id}: the slot is signet_info.part, the hero's
  signets[part] is ClientHero.signet{part-1} (ClientHero.lua:352-366). A
  signet already in that slot DISAPPEARS (fu00032, StampUI.lua:268-284,
  330-340 removes it from the bag). Pushes hero signet{part-1}.
- 5_2735: costs SIGNET_UNEQUIP_COST[star] diamonds (costIcon9,
  DebusStampPanel.lua:46; the variable's memo says 钻石), free only under
  RoleData.signet_unequip_free, which this server never sends.
- 5_2737 {signet_id, is_extreme, extreme_count}: costs of the CURRENT
  signet_upgrade_info(star, level) row; normal = cost_gold + cost_essence
  (StampAdvancePanel.lua:112-127), extreme = cost_diamond per try, up to
  extreme_count tries, stopping at the first success (fu00076 "进阶成功后自动
  停止，不消耗多余钻石"); the Res carries the tries and diamonds spent
  (fu00077, StampUI.lua:515-516). success_rate 0 is the top (isBestLevel,
  StampDataHelp.lua:443-456). A failed roll is 338109, which the client cannot
  be told: it floats fu00026 进阶成功 over the unchanged signet.
- 5_2739 {signet_ids}: resolve_essence/resolve_gold of each signet's
  (star, level) row (getResolveGain, StampDataHelp.lua:111-130), paid as
  categories 75 and 1. Only bag signets (an equipped one shows 卸下 instead,
  StampRenderInfoPanel.lua:171-189); one bad id refuses the whole list.
- 5_2621 {times}: the price is MMTools:getCost over SIGNET_BUY_CNT_COST from
  today's buys (LevelDes.lua:343-345). The DAILY cap is vip_info 20260 at the
  player's VIP (0 below VIP 8) -> 338112; SIGNET_MAX_BUY_CNT (50) caps the
  fights HELD (LevelDes.lua:219-233, "可购买到的次数上限") -> 338107. Bought
  fights sit below 0 used and do not recover. Answer {signet_fight_cnt,
  signet_buy_cnt} (LevelDes.lua:209-217).
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import hero as hero_mod
from server.modules import item, mail, notify
from server.modules.player import SIGNET_DAY_HOUR, build_signet_info
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.signet")

FUNCTION_SIGNET = 80010          # 印记 (FunctionType.lua:1446-1457)
VIP_BUY_ENTRY = 20260            # vip_info 主线地狱难度可购买次数 (LevelDes.lua:226)

STATUS_BUY_OVER = 338107         # language.db 数量购买超限
STATUS_NO_ESSENCE = 338108       # language.db 印记精华不足
STATUS_FAILED = 338109           # language.db 进阶失败
STATUS_MAX_LEVEL = 338110        # language.db 已达到最大等级
STATUS_NO_FIGHTS = 338111        # language.db 地狱关卡挑战次数不足
STATUS_BUY_LIMIT = 338112        # language.db 达到购买次数上限
STATUS_BAG_FULL = 338114         # language.db 印记数量达到上限，请先去清理
STATUS_NO_SIGNET = 338117        # language.db 印记不存在
STATUS_NO_GOLD = 327937          # language.db 金币不足
STATUS_NO_DIAMOND = 327938       # language.db 钻石不足
STATUS_NO_HERO = 327941          # language.db 英雄不存在
STATUS_LEVEL = 327957            # language.db 未满足此玩法的等级

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


# --- level-up -------------------------------------------------------------------
def _attr_row(cfg: Config, star: int, attr_type: int):
    return next(
        (r for r in cfg.signet_attributes()
         if int(r["star"]) == int(star) and int(r["attribute_type"]) == int(attr_type)),
        None,
    )


def level_up_attrs(
    cfg: Config, star: int, new_level: int, main: list, subs: list, rng
) -> None:
    """The attribute change of reaching `new_level`, in place: the main value
    grows by its grow_value; at a signet_change_info level (2, 5, 8, 11, 14)
    a new sub appears with add_chance(current count), else an existing one is
    strengthened by a fresh roll of its range (fu00045-fu00047)."""
    row = _attr_row(cfg, star, main[0]["attr_type"])
    if row is not None:
        main[0] = _attr(main[0]["attr_type"], main[0]["attr_value"] + float(row["grow_value"] or 0))
    change = next(
        (r for r in cfg.signet_changes()
         if int(r["star"]) == int(star) and int(r["upgrade_level"]) == int(new_level)
         and int(r["current_amount"]) == len(subs)),
        None,
    )
    if change is None:
        return
    if rng.random() < float(change["add_chance"] or 0) and _add_sub(cfg, star, main, subs, rng):
        return
    if subs:
        k = rng.randrange(len(subs))
        sub_row = _attr_row(cfg, star, subs[k]["attr_type"])
        if sub_row is not None:
            subs[k] = _attr(subs[k]["attr_type"], subs[k]["attr_value"] + _sub_value(sub_row, rng))


# --- stats ----------------------------------------------------------------------
# Attribute type -> ClientHeroUnit fields (GameAttrManager.lua:30-96,166-240).
# 8 全系列防御 and 9 全系列攻击力 are both defences / both attacks.
ATTR_FIELDS = {
    1: ("max_hp",), 2: ("power",), 3: ("defence",), 4: ("magic",),
    5: ("magic_defence",), 6: ("agility",), 8: ("defence", "magic_defence"),
    9: ("power", "magic"), 10: ("hit_base",), 11: ("duck_base",),
    12: ("crit_base",), 13: ("crit_damage_base",), 14: ("block_base",),
    16: ("tenacity_base",), 17: ("resistance_base",),
}
# The 比率修正 types (GameAttrManager.lua:214-229): a share of the base unit.
RATIO_FIELDS = {
    81: ("max_hp",), 82: ("power",), 83: ("defence",), 84: ("magic",),
    85: ("magic_defence",), 86: ("agility",), 88: ("defence", "magic_defence"),
    89: ("power", "magic"),
}


def base_unit(cfg: Config, hero_row) -> dict[str, float]:
    """The hero's unit before any bonus: npc_info of its prototype plus
    (level - 1) x hero_growth, as hero.build_client_hero_unit computes it."""
    quality_row = hero_mod.quality_row_for(cfg, int(hero_row["entry"]), int(hero_row["quality"]))
    npc_row = cfg.npc(int(quality_row["prototype"]))
    growth = cfg.hero_growth(int(hero_row["entry"]), int(hero_row["star"]))
    steps = max(0, int(hero_row["level"]) - 1)
    out = {}
    for field in hero_mod.NPC_UNIT_FIELDS:
        value = float(npc_row[field] or 0)
        if steps and growth is not None and field in hero_mod.GROWTH_FIELDS:
            value += steps * float(growth[field] or 0)
        out[field] = value
    return out


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row) -> dict[str, float]:
    """The main and sub attributes of every signet the hero wears, on unit
    fields; ratio types are a share of base_unit. Set bonuses are not here
    (no signet_set_info lookup in server/config, see the B5 report)."""
    out: dict[str, float] = {}
    base = None
    for row in conn.execute(
        "SELECT * FROM signets WHERE player_id = ? AND hero = ? ORDER BY id",
        (int(hero_row["player_id"]), int(hero_row["entry"])),
    ):
        for attr in json.loads(row["main_attrs"] or "[]") + json.loads(row["sub_attrs"] or "[]"):
            kind, value = int(attr["attr_type"]), float(attr["attr_value"])
            if kind in RATIO_FIELDS:
                base = base_unit(cfg, hero_row) if base is None else base
                for field in RATIO_FIELDS[kind]:
                    out[field] = out.get(field, 0.0) + value * base[field]
            for field in ATTR_FIELDS.get(kind, ()):
                out[field] = out.get(field, 0.0) + value
    return out


def _cost_tiers(text: str, done: int, n: int) -> int:
    """MMTools:getCost (MMTools.lua:33-54): 'price|count,...' cumulative
    tiers; buys done+1..done+n each pay their tier's price, past the last
    tier the last price."""
    tiers = [tuple(int(x) for x in part.split("|")) for part in str(text).split(",") if part]
    total = 0
    for k in range(done + 1, done + n + 1):
        reach, price = 0, 0
        for price, count in tiers:
            reach += count
            if reach >= k:
                break
        total += price
    return total


def _unequip_cost(cfg: Config, star: int) -> int:
    """SIGNET_UNEQUIP_COST 'star|diamonds,...' (StampDataHelp.lua:25-32)."""
    for part in str(cfg.variable("SIGNET_UNEQUIP_COST") or "").split(","):
        if part:
            s, cost = part.split("|")
            if int(s) == int(star):
                return int(cost)
    raise KeyError(f"variables.SIGNET_UNEQUIP_COST has no star {star}")


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
            return _row(conn, session.player_id)
        return db.find_player(conn, settings.username)

    def _signet(pid: int, signet_id: int):
        return conn.execute(
            "SELECT * FROM signets WHERE id = ? AND player_id = ?", (int(signet_id), pid)
        ).fetchone()

    def _hero(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (pid, int(entry)),
        ).fetchone()

    def _warn(what: str, status: int, why: str) -> None:
        log.warning("%s would refuse %d (no status field): %s", what, status, why)

    def _res(name: str, **fields):
        res = registry.message_class(name)(**fields)
        fill_required(res)
        return res

    def _locked(player) -> bool:
        need = cfg.function_unlock(FUNCTION_SIGNET)
        return int(player["level"]) < need

    # 5_2805 SignetQueryReq {} -> {signets}
    def query(session: Session, req):
        pid = int(_player(session)["id"])
        res = registry.message_class("SignetQueryRes")()
        for row in conn.execute("SELECT * FROM signets WHERE player_id = ? ORDER BY id", (pid,)):
            res.signets.add().CopyFrom(signet_info(registry, conn, cfg, row, rand))
        fill_required(res)
        return res

    # 5_2621 BuyHeroSignetReq {times} -> {signet_fight_cnt, signet_buy_cnt}
    def buy(session: Session, req):
        player = _player(session)
        pid, times = int(player["id"]), int(req.times)
        left = settle_fights(conn, cfg, pid)
        today = db.day_key(SIGNET_DAY_HOUR)     # O-W3-9: buys roll at 05:00
        bought = int(player["signet_buy_cnt"]) if player["signet_day"] == today else 0
        name = "5_2621 BuyHeroSignetRes"

        def answer():
            return _res("BuyHeroSignetRes", signet_fight_cnt=settle_fights(conn, cfg, pid),
                        signet_buy_cnt=bought)

        allowed = int(cfg.vip_value(VIP_BUY_ENTRY, int(player["vip"])) or 0)
        hold = cfg.variable_int("SIGNET_MAX_BUY_CNT", 0)
        if times < 1:
            _warn(name, STATUS_BUY_LIMIT, f"times {times}")
            return answer()
        if bought + times > allowed:
            _warn(name, STATUS_BUY_LIMIT,
                  f"{bought} + {times} buys > {allowed} at VIP {player['vip']}")
            return answer()
        if hold and left + times > hold:
            _warn(name, STATUS_BUY_OVER, f"{left} + {times} fights > {hold}")
            return answer()
        cost = _cost_tiers(cfg.variable("SIGNET_BUY_CNT_COST") or "", bought, times)
        if int(player["diamond"]) < cost:
            _warn(name, STATUS_NO_DIAMOND, f"needs {cost} diamonds, has {player['diamond']}")
            return answer()
        db.spend(conn, pid, diamond=cost)
        bought += times
        conn.execute(
            "UPDATE players SET signet_cnt_used = signet_cnt_used - ?, signet_buy_cnt = ?,"
            " signet_day = ? WHERE id = ?", (times, bought, today, pid),
        )
        conn.commit()
        fresh = _row(conn, pid)
        left = settle_fights(conn, cfg, pid)
        notify.player_changed(registry, session, {
            "diamond": int(fresh["diamond"]), "signet_fight_cnt": left,
        })
        log.info("player %d bought %d signet fights for %d diamonds (%d today)",
                 pid, times, cost, bought)
        return answer()

    # 5_2733 SignetEquipReq {hero_entry, signet_id} -> {}
    def equip(session: Session, req):
        player = _player(session)
        pid, entry, sid = int(player["id"]), int(req.hero_entry), int(req.signet_id)
        name = "5_2733 SignetEquipRes"
        row, hero_row = _signet(pid, sid), _hero(pid, entry)
        if _locked(player):
            _warn(name, STATUS_LEVEL, f"player level {player['level']}")
        elif row is None:
            _warn(name, STATUS_NO_SIGNET, f"signet {sid}")
        elif hero_row is None:
            _warn(name, STATUS_NO_HERO, f"hero {entry}")
        elif int(row["hero"]) not in (0, entry):
            log.warning("%s: signet %d is worn by hero %d", name, sid, int(row["hero"]))
        else:
            part = int(cfg.signet(int(row["entry"]))["part"])
            for other in conn.execute(
                "SELECT * FROM signets WHERE player_id = ? AND hero = ? AND id != ?",
                (pid, entry, sid),
            ).fetchall():
                if int(cfg.signet(int(other["entry"]))["part"]) == part:
                    # fu00032: the signet in the slot disappears (StampUI.lua:336-340).
                    conn.execute("DELETE FROM signets WHERE id = ?", (int(other["id"]),))
                    log.info("signet %d replaced on hero %d and destroyed", int(other["id"]), entry)
            conn.execute("UPDATE signets SET hero = ? WHERE id = ?", (entry, sid))
            conn.commit()
            notify.hero_changed(registry, session, entry, {f"signet{part - 1}": sid})
        return _res("SignetEquipRes")

    # 5_2735 SignetUnequipReq {hero_entry, signet_id} -> {}
    def unequip(session: Session, req):
        player = _player(session)
        pid, entry, sid = int(player["id"]), int(req.hero_entry), int(req.signet_id)
        name = "5_2735 SignetUnequipRes"
        row = _signet(pid, sid)
        if row is None or int(row["hero"]) != entry:
            _warn(name, STATUS_NO_SIGNET, f"signet {sid} on hero {entry}")
            return _res("SignetUnequipRes")
        info = cfg.signet(int(row["entry"]))
        cost = _unequip_cost(cfg, int(info["star"]))
        if int(player["diamond"]) < cost:
            _warn(name, STATUS_NO_DIAMOND, f"needs {cost} diamonds, has {player['diamond']}")
            return _res("SignetUnequipRes")
        db.spend(conn, pid, diamond=cost)
        conn.execute("UPDATE signets SET hero = 0 WHERE id = ?", (sid,))
        conn.commit()
        notify.hero_changed(registry, session, entry, {f"signet{int(info['part']) - 1}": 0})
        notify.player_changed(registry, session, {"diamond": int(_row(conn, pid)["diamond"])})
        return _res("SignetUnequipRes")

    # 5_2737 SignetLevelUpReq {signet_id, is_extreme, extreme_count}
    #   -> {signet, extreme_count, extreme_diamond}
    def level_up(session: Session, req):
        player = _player(session)
        pid, sid = int(player["id"]), int(req.signet_id)
        name = "5_2737 SignetLevelUpRes"
        row = _signet(pid, sid)
        if row is None:
            _warn(name, STATUS_NO_SIGNET, f"signet {sid}")
            res = registry.message_class("SignetLevelUpRes")()
            fill_required(res)
            return res
        row = ensure_rolled(conn, cfg, row, rand)
        star = int(cfg.signet(int(row["entry"]))["star"])
        extreme = bool(req.is_extreme)
        tries, diamonds, level = 0, 0, int(row["level"])
        main, subs = json.loads(row["main_attrs"]), json.loads(row["sub_attrs"])
        limit = max(1, int(req.extreme_count)) if extreme else 1
        while tries < limit:
            up = cfg.signet_upgrade(star, level)
            if up is None or float(up["success_rate"] or 0) <= 0:
                if not tries:
                    _warn(name, STATUS_MAX_LEVEL, f"signet {sid} at level {level}")
                break
            fresh = _row(conn, pid)
            gold, essence = int(up["cost_gold"] or 0), int(up["cost_essence"] or 0)
            diamond = int(up["cost_diamond"] or 0)
            if extreme and int(fresh["diamond"]) < diamond:
                if not tries:
                    _warn(name, STATUS_NO_DIAMOND, f"needs {diamond} diamonds")
                break
            if not extreme and int(fresh["signet_essence"]) < essence:
                _warn(name, STATUS_NO_ESSENCE, f"needs {essence} essence")
                break
            if not extreme and int(fresh["gold"]) < gold:
                _warn(name, STATUS_NO_GOLD, f"needs {gold} gold")
                break
            if extreme:
                db.spend(conn, pid, diamond=diamond)
                diamonds += diamond
            else:
                db.spend(conn, pid, gold=gold)
                conn.execute(
                    "UPDATE players SET signet_essence = signet_essence - ? WHERE id = ?",
                    (essence, pid),
                )
                conn.commit()
            tries += 1
            if rand.random() < float(up["success_rate"]):
                level += 1
                level_up_attrs(cfg, star, level, main, subs, rand)
                conn.execute(
                    "UPDATE signets SET level = ?, main_attrs = ?, sub_attrs = ? WHERE id = ?",
                    (level, json.dumps(main), json.dumps(subs), sid),
                )
                conn.commit()
                break
        if tries:
            fresh = _row(conn, pid)
            notify.player_changed(registry, session, {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "signet_essence": int(fresh["signet_essence"]),
            })
            log.info("player %d: signet %d %d level-up tries (%d diamonds), +%d -> +%d",
                     pid, sid, tries, diamonds, int(row["level"]), level)
        if tries and level == int(row["level"]):
            _warn(name, STATUS_FAILED, f"signet {sid} stays +{level} after {tries} tries")
        res = registry.message_class("SignetLevelUpRes")()
        res.signet.CopyFrom(build_signet_info(registry, _signet(pid, sid)))
        if extreme:
            res.extreme_count, res.extreme_diamond = tries, diamonds
        fill_required(res)
        return res

    # 5_2739 SignetDecomposeReq {signet_ids} -> {prizes}
    def decompose(session: Session, req):
        player = _player(session)
        pid = int(player["id"])
        ids = [int(x) for x in req.signet_ids]
        res = registry.message_class("SignetDecomposeRes")()
        rows = [_signet(pid, sid) for sid in ids]
        bad = [sid for sid, row in zip(ids, rows) if row is None or int(row["hero"])]
        if not ids or bad or len(set(ids)) != len(ids):
            _warn("5_2739 SignetDecomposeRes", STATUS_NO_SIGNET, f"ids {ids}, unusable {bad}")
            fill_required(res)
            return res
        essence = gold = 0
        for row in rows:
            up = cfg.signet_upgrade(int(cfg.signet(int(row["entry"]))["star"]), int(row["level"]))
            if up is None:
                raise KeyError(f"signet_upgrade_info has no row for signet {row['id']}")
            essence += int(up["resolve_essence"] or 0)
            gold += int(up["resolve_gold"] or 0)
        prizes = [(c, 0, n) for c, n in ((item.CATEGORY_SIGNET_ESSENCE, essence),
                                         (item.CATEGORY_GOLD, gold)) if n]
        granted = item.grant_prizes(conn, cfg, pid, prizes)
        conn.executemany("DELETE FROM signets WHERE id = ?", [(sid,) for sid in ids])
        conn.commit()
        for category, refer, amount in prizes:
            res.prizes.add(category=category, refer=refer, amount=amount)
        item.announce(registry, session, granted)
        notify.player_changed(registry, session, {"gold": granted["gold"]})
        log.info("player %d decomposed signets %s for %d essence, %d gold",
                 pid, ids, essence, gold)
        fill_required(res)
        return res

    return {
        (5, 2621): buy,
        (5, 2733): equip,
        (5, 2735): unequip,
        (5, 2737): level_up,
        (5, 2739): decompose,
        (5, 2805): query,
    }
