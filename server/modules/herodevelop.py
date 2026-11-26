"""Hero develop (英雄养成, function 90040): 5_2701 HeroDevelopQueryReq,
5_2703 HeroDevelopReq, 5_2705 HeroDevelopEnsureReq (plan B2 Wave 3, task B2).

What the client reads (step 1, heroGrowth/HeroGrowthInfo.lua unless named):

- 5_2701 {entry} is sent when a hero is picked in the list (:788-796). The
  list shows only heroes with quality >= HERO_QUALITY_OPEN[1]
  (HeroGrowthListView.lua:24-27,160-167). The feature is function 90040
  (FunctionType.lua:190,1617-1618).
- 5_2702: the listener reads element [1] of the first eight repeated blocks
  propertySP..propertyTX (:869-872) as constellations 1-8, each with
  property0..3 (floats in allProtos.pb). propertySS/JN/BY/SY exist in the
  proto and are never read; they are sent as one zero block each.
- A tab (constellation) opens at hero quality >= HERO_QUALITY_OPEN[i]
  (`41|43|50|50|50|51|52|52`, :679-708), compared with ClientHero.quality.
  The client refuses a closed tab itself (:605-617).
- hero_constellation_info, keyed by idx 0-7 (:1178-1207): property_id0..3 are
  attribute types (GameAttrManager:getAttrNameByType), perperty_limit0..3 the
  caps. A tab is full when every value reaches its cap; the client then
  floats h09017 itself (:486-502).
- 5_2703 {entry, constellation = tab - 1, method, times} (:711-732). times is
  1 (one roll, :389-398), 2 (ten, :400-407) or 3 (a hundred: the 培养百次
  button, :409-419,454-461, isCanGrowUp(100)). method: 1 common (stone),
  2 gold (stone + gold), 3 diamond, 4 special (item 2200). The gold option is
  commented out of the radio list, so the live UI sends 1, 3 and 4
  (:198-221); method 4 shows only when g_roleData.special_prop_open == 1.
- Costs per roll (getCostInfo, :1209-1225; scaled by the roll count in
  getCurCostNum, :1021-1045): HERO_DEVELOP_COMMON_STONE x item 2000;
  HERO_DEVELOP_GOLD_STONE x item 2000 + HERO_DEVELOP_GOLD gold;
  HERO_DEVELOP_DIAMOND diamonds; HERO_DEVELOP_SPECIAL_PROPS_AMOUNT x item
  2200. The client checks them before sending (:504-511).
- 5_2704 {property0..3} is a preview: the absolute values after the roll. The
  client shows new - shown as +/- per line and swaps in the confirm/cancel
  buttons (showPerview, :583-598; updateGrowthInfo :320-352).
- Confirm sends 5_2705 {insure 1, entry, constellation} (:437-441,735-751).
  Cancel does NOT send anything: its dealWithResult(false) is commented out
  and it only redraws the stored values (:443-448). Leaving the tab, the hero
  or the screen with a preview open also only redraws (:88-97,
  HeroGrowthCell.lua:51-60, HeroGrowthUI.lua:103-117). A stale pending
  preview is therefore normal and is replaced by the next roll; insure 0 is
  still honoured if it ever arrives.
- 5_2706 {property0..3}: the stored values, copied into the tab (showReal,
  :517-537,776-785).
- INFO_CHANGE_NTF_HERO for the hero floats h09028 "英雄战力提升 +n" when its
  ability rose (:880-899).

The roll (O-W3-5, a reading of the table, not client evidence): rate is a
ladder `frac:up:down:step|...`; each roll raises each of the four properties
by step x limit, step being the one of the highest frac <= value/limit, and
caps the result at limit. The 1:0 up/down fields mean the value never falls.
rate, rate_1 and rate_2 are identical on every row, so the method changes only
the cost. The roll counts 1/10/100 are rolled one after another.

No Res of the three has a status field, so nothing can be refused on the
wire: a refusal logs a WARNING with its language.db code, changes nothing and
answers the current values.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from server import db
from server.config import Config
from server.modules import hero, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.herodevelop")

FUNCTION_HERO_GROWTH = 90040    # FunctionType.HERO_GROWTH 英雄养成

# language.db ids, logged only (no Res here has a status).
STATUS_INTERNAL_ERROR = 327681  # 系统内部错误
STATUS_NOT_ENOUGH_GOLD = 327937     # 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938  # 钻石不足
STATUS_NO_HERO = 327941         # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942    # 没有足够道具
STATUS_LEVEL = 327957           # 未满足此玩法的等级
STATUS_QUALITY = 338017         # 英雄品质不够

STONE = 2000                    # 英雄培养石
SPECIAL_STONE = 2200            # 特殊培养石
CONSTELLATIONS = 8              # HeroGrowthInfo.totalOpenFunc
ROLLS = {1: 1, 2: 10, 3: 100}   # HeroDevelopReq.times -> roll count

# HeroDevelopQueryRes blocks in field order; the client reads the first eight.
BLOCKS = ("SP", "SZ", "ZZ", "MJ", "JX", "CN", "TC", "TX", "SS", "JN", "BY", "SY")

# Attribute type -> ClientHeroUnit fields (GameAttrManager.lua:30-58,66-96).
# 8 全系列防御 is both defences, as getAttrKey returns; 9 全系列攻击力 is read
# the same way as both attacks (getAttrKey returns only "power", but the
# battle reads type 9 as the effective attack, BattleUnit.lua:619-620).
ATTR_FIELDS = {
    1: ("max_hp",), 2: ("power",), 3: ("defence",), 4: ("magic",),
    5: ("magic_defence",), 6: ("agility",), 8: ("defence", "magic_defence"),
    9: ("power", "magic"), 10: ("hit_base",), 11: ("duck_base",),
    12: ("crit_base",), 13: ("crit_damage_base",), 14: ("block_base",),
    16: ("tenacity_base",), 17: ("resistance_base",),
}


def _costs(cfg: Config, method: int) -> tuple[dict[int, int], int, int] | None:
    """(items, gold, diamond) for one roll of `method`, or None."""
    var = cfg.variable_int
    if method == 1:
        return {STONE: var("HERO_DEVELOP_COMMON_STONE", 1)}, 0, 0
    if method == 2:
        return {STONE: var("HERO_DEVELOP_GOLD_STONE", 1)}, var("HERO_DEVELOP_GOLD", 10000), 0
    if method == 3:
        return {}, 0, var("HERO_DEVELOP_DIAMOND", 300)
    if method == 4:
        return {SPECIAL_STONE: var("HERO_DEVELOP_SPECIAL_PROPS_AMOUNT", 1)}, 0, 0
    return None


def _ladder(text: str) -> list[tuple[float, float]]:
    """'frac:up:down:step|...' as (frac, step) pairs, ascending by frac."""
    out = []
    for part in str(text or "").split("|"):
        if part:
            frac, _up, _down, step = part.split(":")
            out.append((float(frac), float(step)))
    return sorted(out)


def _quality_open(cfg: Config) -> list[int]:
    raw = cfg.variable("HERO_QUALITY_OPEN")
    if not raw:
        raise KeyError("variables.HERO_QUALITY_OPEN is missing")
    return [int(float(x)) for x in raw.split("|")]


def roll(row: sqlite3.Row, values: list[float], count: int) -> list[float]:
    """`count` rolls of O-W3-5 over one hero_constellation_info row."""
    ladder = _ladder(row["rate"])
    out = list(values)
    for _ in range(count):
        for k in range(4):
            limit = float(row[f"perperty_limit{k}"] or 0)
            if limit <= 0:
                continue
            frac = out[k] / limit
            step = next((s for f, s in reversed(ladder) if f <= frac), 0.0)
            out[k] = min(limit, round(out[k] + step * limit, 4))
    return out


def stored(conn: sqlite3.Connection, pid: int, entry: int) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM hero_develop WHERE player_id = ? AND hero = ?", (pid, int(entry))
    )
    return {int(r["constellation"]): r for r in rows}


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row: sqlite3.Row) -> dict[str, float]:
    """The stored (confirmed) values of every constellation of this hero, on
    the unit fields their property_id names. Pending previews do not count."""
    out: dict[str, float] = {}
    rows = {int(r["idx"]): r for r in cfg.hero_constellations()}
    for c, saved in stored(conn, int(hero_row["player_id"]), int(hero_row["entry"])).items():
        info = rows.get(c)
        if info is None:
            continue
        for k in range(4):
            value = float(saved[f"p{k}"])
            if not value:
                continue
            for name in ATTR_FIELDS.get(int(info[f"property_id{k}"] or 0), ()):
                out[name] = out.get(name, 0.0) + value
    return out


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

    def _values(pid: int, entry: int, c: int) -> list[float]:
        row = stored(conn, pid, entry).get(c)
        return [0.0] * 4 if row is None else [float(row[f"p{k}"]) for k in range(4)]

    def _props(name: str, values: list[float]):
        res = registry.message_class(name)()
        for k, value in enumerate(values):
            setattr(res, f"property{k}", float(value))
        fill_required(res)
        return res

    def _set_pending(pid: int, entry: int, c: int, pending: str) -> None:
        conn.execute(
            "INSERT INTO hero_develop (player_id, hero, constellation, pending)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(player_id, hero, constellation) DO UPDATE SET pending = ?",
            (pid, int(entry), c, pending, pending),
        )
        conn.commit()

    def _gate(msg: str, player, row, entry: int) -> int | None:
        """The language.db code that refuses this player/hero, else None."""
        if player is None:
            log.warning("%s hero %d before any character exists", msg, entry)
            return STATUS_INTERNAL_ERROR
        unlock = cfg.function_unlock(FUNCTION_HERO_GROWTH)
        if int(player["level"]) < unlock:
            log.warning("%s hero %d refused (%d): player level %d < %d",
                        msg, entry, STATUS_LEVEL, int(player["level"]), unlock)
            return STATUS_LEVEL
        if row is None:
            log.warning("%s hero %d refused (%d): hero not owned", msg, entry, STATUS_NO_HERO)
            return STATUS_NO_HERO
        return None

    def query(session: Session, req):
        entry = int(req.entry)
        player = _player(session)
        res = registry.message_class("HeroDevelopQueryRes")()
        saved: dict[int, sqlite3.Row] = {}
        if player is not None:
            session.player_id = int(player["id"])
            if _gate("5_2701", player, _hero(int(player["id"]), entry), entry) is None:
                saved = stored(conn, int(player["id"]), entry)
        for c, name in enumerate(BLOCKS):
            block = getattr(res, f"property{name}").add()
            row = saved.get(c)
            for k in range(4):
                setattr(block, f"property{k}", float(row[f"p{k}"]) if row else 0.0)
        fill_required(res)
        return res

    def develop(session: Session, req):
        entry, c = int(req.entry), int(req.constellation)
        method, times = int(req.method), int(req.times)
        player = _player(session)
        if player is not None:
            session.player_id = int(player["id"])
        row = None if player is None else _hero(int(player["id"]), entry)
        if _gate("5_2703", player, row, entry) is not None:
            return _props("HeroDevelopRes", [0.0] * 4)
        pid = int(player["id"])
        info = {int(r["idx"]): r for r in cfg.hero_constellations()}.get(c)
        current = _values(pid, entry, c) if 0 <= c < CONSTELLATIONS else [0.0] * 4

        def unchanged(status: int | None, why: str):
            if 0 <= c < CONSTELLATIONS:
                _set_pending(pid, entry, c, "")
            code = "no language.db code" if status is None else str(status)
            log.warning("5_2703 hero %d constellation %d method %d times %d of player"
                        " %d not rolled (%s): %s; HeroDevelopRes has no status,"
                        " answering the current values",
                        entry, c, method, times, pid, code, why)
            return _props("HeroDevelopRes", current)

        if not 0 <= c < CONSTELLATIONS or info is None:
            return unchanged(STATUS_INTERNAL_ERROR, "constellation outside 0..7")
        need = _quality_open(cfg)[c]
        quality = int(hero.quality_row_for(cfg, entry, int(row["quality"]))["quality"])
        if quality < need:
            return unchanged(STATUS_QUALITY, f"hero quality {quality} < {need}")
        count = ROLLS.get(times)
        costs = _costs(cfg, method)
        if count is None or costs is None:
            return unchanged(STATUS_INTERNAL_ERROR, "method not 1-4 or times not 1-3")
        if all(current[k] >= float(info[f"perperty_limit{k}"] or 0) for k in range(4)):
            return unchanged(None, "every property at its limit (the client floats h09017)")
        items, gold, diamond = costs
        items = {r: n * count for r, n in items.items()}
        gold, diamond = gold * count, diamond * count
        bag = {int(r["entry"]): int(r["amount"]) for r in db.items_of(conn, pid)}
        short = [r for r, n in items.items() if bag.get(r, 0) < n]
        if short:
            return unchanged(STATUS_NOT_ENOUGH_ITEMS, f"items {short} for {count} roll(s)")
        if int(player["gold"]) < gold:
            return unchanged(STATUS_NOT_ENOUGH_GOLD, f"{gold} gold")
        if int(player["diamond"]) < diamond:
            return unchanged(STATUS_NOT_ENOUGH_DIAMOND, f"{diamond} diamonds")

        # Everything is validated: write.
        pairs = [(r, db.take_item(conn, pid, r, n)) for r, n in items.items()]
        if gold or diamond:
            db.spend(conn, pid, gold=gold, diamond=diamond)
        preview = roll(info, current, count)
        _set_pending(pid, entry, c, json.dumps(preview))
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
        log.info("5_2703 hero %d constellation %d of player %d: method %d x%d,"
                 " %s -> preview %s", entry, c, pid, method, count, current, preview)
        return _props("HeroDevelopRes", preview)

    def ensure(session: Session, req):
        entry, c, insure = int(req.entry), int(req.constellation), int(req.insure)
        player = _player(session)
        if player is not None:
            session.player_id = int(player["id"])
        row = None if player is None else _hero(int(player["id"]), entry)
        if _gate("5_2705", player, row, entry) is not None:
            return _props("HeroDevelopEnsureRes", [0.0] * 4)
        pid = int(player["id"])
        if not 0 <= c < CONSTELLATIONS:
            log.warning("5_2705 hero %d constellation %d refused (%d): outside 0..7",
                        entry, c, STATUS_INTERNAL_ERROR)
            return _props("HeroDevelopEnsureRes", [0.0] * 4)
        saved = stored(conn, pid, entry).get(c)
        pending = "" if saved is None else str(saved["pending"])
        if insure == 1 and pending:
            values = [float(v) for v in json.loads(pending)]
            conn.execute(
                "UPDATE hero_develop SET p0 = ?, p1 = ?, p2 = ?, p3 = ?, pending = ''"
                " WHERE player_id = ? AND hero = ? AND constellation = ?",
                (*values, pid, entry, c),
            )
            conn.commit()
            # The stats reach ClientHero.unit in C1; until then only ability.
            fields = hero.hero_notify_fields_with_runes(
                registry, cfg, row, hero.runes_of(conn, row), conn=conn
            )
            notify.hero_changed(registry, session, entry, {"ability": fields["ability"]})
            log.info("5_2705 hero %d constellation %d of player %d confirmed: %s",
                     entry, c, pid, values)
        elif insure == 1:
            log.warning("5_2705 hero %d constellation %d of player %d: confirm with"
                        " no pending roll (%d), answering the stored values",
                        entry, c, pid, STATUS_INTERNAL_ERROR)
        elif pending:
            _set_pending(pid, entry, c, "")
            log.info("5_2705 hero %d constellation %d of player %d: preview discarded",
                     entry, c, pid)
        return _props("HeroDevelopEnsureRes", _values(pid, entry, c))

    return {(5, 2701): query, (5, 2703): develop, (5, 2705): ensure}
