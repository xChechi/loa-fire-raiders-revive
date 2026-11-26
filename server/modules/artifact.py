"""Artifacts (神器, function 50010, level 57), plan B2 Wave 3, task B9.

What the client reads (step 1):

- Artifacts belong to the PLAYER, not to a hero: eight slots, one per
  artifact_info.position 1..8 (ArtifactPandectView.lua:97-102), and their
  stats lift "全体上阵英雄" (item_info.description1 of every artifact).
  ArtifactMainRes {af_info, equiped[]} is the whole equipped set
  (FunctionType.lua:983-985 opens UI_ARTIFACT with it); af_info.base_attrs,
  set_attrs and ability are the set's totals (ArtifactTotalPower.lua:61-119).
- Two kinds of artifact (ArtifactDataHelp.lua:477-498): a fresh one is an
  ordinary inventory item of item_info.class 130 (no id, level 1); one that
  was equipped, levelled or advanced is a server row with an id. The bag Res
  5_2550 {artifacts, illustrations} therefore carries the ROWS only; the
  client adds the class-130 stocks of g_roleData.inventory itself
  (getArtifactTable). `illustrations.entries` lights the artifact_info.node
  entries of the codex (SuitListPanel.lua:132-157, getIllustratedInfo).
- An attribute is floor(basic_value{i} + grow_value{i} x level) for i 0..7
  with basic_value{i} != 0 (getAttribute/getActiveAttribut,
  ArtifactDataHelp.lua:140-192). The client's power preview weighs them with
  DataManager:getAttributeParameter (DataManager.lua:956-989: type 1 x0.1,
  2-6 x0.5, 8-14 and 16 x1, else 0; ArtifactBaseAttr.lua:74-94 against
  ArtifactInfoView.lua:344), so `ability` is that weighted sum.
- 5_2541 {id} equips a row, {entry} an inventory artifact
  (ArtifactBag.lua:187-193, ChangePanel.lua:94-101); the one in the same
  position goes back to the bag. Res {af_info, equiped}.
- 5_2535 {id} (ArtifactUI.lua:203-207, a click on an EQUIPPED artifact) ->
  {af_info of it, af_advance_info (next_entry preview, id invalid),
  artifacts}; the listener reads af_advance_info.base_info unconditionally
  (ArtifactUI.lua:227-237), so at the top it previews the artifact itself.
- 5_2537 {id, food{afs, stocks}} (PromotPanel.lua:158-166). The xp source is
  item_info.exp_score of inventory stocks (getCanSwallowData,
  ArtifactDataHelp.lua:596-634: crystals class 133 are 100/500/2000, fresh
  class-130 artifacts 50-200; item 1400 is the advance stone, exp_score 0).
  "有id的神器是不能被吞噬的" (ArtifactDataHelp.lua:599): afs is refused. A
  level needs artifact_level_info(level).upgrade_exp{item quality}; the
  level stops below the player level and where that value is 0 (getMaxExp,
  isMaxLevel, ArtifactDataHelp.lua:636-704). Gold is
  floor(absorbed xp x ARTIFACT_EXP_GOLD_SCALE) (PromotPanel.lua:266-269 on
  previewInfo.addAllExp, the xp actually absorbed). The overflow becomes
  artifact_smelt at XP_TO_ARTIFACT_SMELT (its memo: 溢出经验转化为神器精华的比例).
- 5_2539 {id} advances to artifact_info.next_entry (0 = top, isBestAdvance)
  by item_composite(item_id = next_entry): item0 is the artifact itself,
  item1..3 come from the inventory, `cost` is gold, and the level must reach
  next.needlevel (getCompositeByEntry, ArtifactDataHelp.lua:194-249).
  ARTIFACT_MAX_ADVANCE ('quality|advance,...', memo 每个品质的神器进阶上限)
  caps it per item quality. Level and exp carry over.
- 5_2555 {} -> {artifacts} feeds the smelt screen, which adds the inventory
  stocks with smelt_score > 0 and never offers an equipped artifact
  (ArtifactComposeUI.lua:139-159,333; x08007). 5_2545 {food} pays exactly
  what updateDropShow previews (ArtifactComposeUI.lua:411-486): category 61
  ceil(smelt_score x POINT_SCALE); gold ceil(smelt_gold_return x GOLD_SCALE)
  plus, for a row, ceil(total xp x EXP_GOLD_SCALE x GOLD_SCALE); item 1400
  ceil(smelt_potion_return x POTION_SCALE); and, for a row, its total xp
  (getExpTotal: exp + upgrade_exp of the levels below, :403-420) x EXP_SCALE
  as class-133 crystals, largest first. (The Lua reads POTION_SCALE for the
  xp rate; both are 1, this server reads ARTIFACT_SMELT_EXP_SCALE.)
- 5_2553 {item} composes a fresh artifact (an inventory item) from the
  fragment recipe item_composite(item_id = item), `cost` gold
  (ArtifactBagLeft.lua:168-174,268-286, getComposeInfo :772-792); Res
  {illustrations, prize} (ArtifactBag.lua:196-203).
- 5_2558 ArtifactAttrChangedNotify {ability, attrs[{attr_type, attr_delta}],
  add, remove} floats the change of the equipped set (ArtifactUI.lua:362-439).

No drop or prize category is an artifact: a fresh artifact is a category-20
item (ARTIFACT_INIT, the fragment recipes, store 11). Sets (artifact_set) are
battle buffs (set_buff*) plus an `ability` number; server/config has no
artifact_set lookup, so set_attrs/add/remove stay empty (see the B9 report).

Every Artifact*Res lacks `status` (proto): a refusal changes nothing, logs a
WARNING with the language.db code it would have used and answers the
current state. Codes: 327942 没有足够道具, 327957 未满足此玩法的等级,
337009 神器不存在, 337010 神器已装备.

The `artifacts.hero` column is the equipped flag here (EQUIPPED, 0 = bag):
artifacts have no hero.
"""

from __future__ import annotations

import logging
import math
import sqlite3

from server import db
from server.config import Config
from server.modules import item, notify
from server.modules.signet import ATTR_FIELDS
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.artifact")

FUNCTION_ARTIFACT = 50010        # FunctionType.ARTIFACT_TYPE 神器入口 (FunctionType.lua:165)
CLASS_ARTIFACT = 130             # item_info.class 神器 (ArtifactDataHelp.lua:492,620)
EQUIPPED = 1                     # artifacts.hero of an equipped artifact

STATUS_NO_ITEMS = 327942         # language.db 没有足够道具
STATUS_LEVEL = 327957            # language.db 未满足此玩法的等级
STATUS_NO_ARTIFACT = 337009      # language.db 神器不存在
STATUS_EQUIPPED = 337010         # language.db 神器已装备

# DataManager:getAttributeParameter (DataManager.lua:956-989).
POWER_WEIGHTS = {
    1: 0.1, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5, 6: 0.5,
    8: 1, 9: 1, 10: 1, 11: 1, 12: 1, 13: 1, 14: 1, 16: 1,
}


# --- config -------------------------------------------------------------------
def _info(cfg: Config, entry: int):
    row = cfg.artifact(entry)
    if row is None:
        raise KeyError(f"artifact_info has no row for artifact {entry}")
    return row


def start_kit(cfg: Config) -> list[tuple[int, int, int]]:
    """ARTIFACT_INIT 'entry|count,...' (memo 神器功能开启时初始神器) as
    category-20 prizes: eight artifacts, the smelt-only 1500100, two small
    crystals and 50 advance stones."""
    raw = cfg.variable("ARTIFACT_INIT")
    if not raw:
        raise KeyError("variables.ARTIFACT_INIT is missing")
    out = []
    for part in raw.split(","):
        if part:
            entry, count = part.split("|")
            out.append((item.CATEGORY_ITEM, int(entry), int(count)))
    return out


# --- attributes -----------------------------------------------------------------
def attrs(cfg: Config, entry: int, level: int) -> dict[int, int]:
    """{attr_type: value} of one artifact at `level` (getActiveAttribut)."""
    info = _info(cfg, entry)
    out: dict[int, int] = {}
    for i in range(8):
        kind = int(info[f"attribute_type{i}"] or 0)
        basic = float(info[f"basic_value{i}"] or 0)
        if kind and basic != 0:
            value = math.floor(basic + float(info[f"grow_value{i}"] or 0) * int(level))
            out[kind] = out.get(kind, 0) + value
    return out


def power(values: dict[int, int]) -> int:
    return math.floor(sum(v * POWER_WEIGHTS.get(k, 0) for k, v in values.items()))


def _sum(cfg: Config, rows) -> dict[int, int]:
    out: dict[int, int] = {}
    for row in rows:
        for kind, value in attrs(cfg, int(row["entry"]), int(row["level"])).items():
            out[kind] = out.get(kind, 0) + value
    return out


def _rows(conn: sqlite3.Connection, pid: int) -> list:
    return conn.execute(
        "SELECT * FROM artifacts WHERE player_id = ? ORDER BY id", (int(pid),)
    ).fetchall()


def _equipped(conn: sqlite3.Connection, pid: int) -> list:
    return conn.execute(
        "SELECT * FROM artifacts WHERE player_id = ? AND hero != 0 ORDER BY id", (int(pid),)
    ).fetchall()


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row) -> dict[str, float]:
    """The equipped set's attributes on unit fields. Artifacts are the
    player's, so every hero of hero_row's player gets the same numbers
    ("全体上阵英雄"; which heroes count as 上阵 is C1's call)."""
    out: dict[str, float] = {}
    for kind, value in _sum(cfg, _equipped(conn, int(hero_row["player_id"]))).items():
        for field in ATTR_FIELDS.get(kind, ()):
            out[field] = out.get(field, 0.0) + float(value)
    return out


# --- messages -------------------------------------------------------------------
def build_base_info(registry: Registry, row):
    msg = registry.message_class("ArtifactBaseInfo")(
        id=int(row["id"]), entry=int(row["entry"]), level=int(row["level"]),
        exp=int(row["exp"]), equiped=bool(int(row["hero"])),
    )
    fill_required(msg)
    return msg


def _fill_attrs(msg, values: dict[int, int]) -> None:
    for kind in sorted(values):
        msg.base_attrs.add(attr_type=int(kind), attr_value=max(0, int(values[kind])))
    msg.ability = max(0, power(values))


def build_total_info(registry: Registry, cfg: Config, rows):
    """ArtifactInfo of the equipped set: no base_info, the summed attributes."""
    msg = registry.message_class("ArtifactInfo")()
    _fill_attrs(msg, _sum(cfg, rows))
    fill_required(msg)
    return msg


def illustrations(registry: Registry, conn: sqlite3.Connection, cfg: Config, pid: int):
    """The codex nodes of every artifact the player owns now (rows and
    class-130 stocks). There is no history table, so an artifact smelted
    away goes dark again."""
    entries = [int(r["entry"]) for r in _rows(conn, pid)]
    for stock in db.items_of(conn, pid):
        row = cfg.item(int(stock["entry"]))
        if row is not None and int(row["class"]) == CLASS_ARTIFACT:
            entries.append(int(stock["entry"]))
    nodes = sorted({int(cfg.artifact(e)["node"] or 0) for e in entries if cfg.artifact(e)} - {0})
    msg = registry.message_class("ArtifactIllustrations")(entries=nodes)
    fill_required(msg)
    return msg


def attrs_changed(
    registry: Registry, session: Session, before: dict[int, int], after: dict[int, int]
) -> None:
    """5_2558 for a change of the equipped set; nothing when nothing moved."""
    deltas = {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after)}
    deltas = {k: d for k, d in deltas.items() if d}
    gain = power(after) - power(before)
    if not deltas and not gain:
        return
    msg = registry.message_class("ArtifactAttrChangedNotify")(ability=int(gain))
    for kind in sorted(deltas):
        msg.attrs.add(attr_type=int(kind), attr_delta=int(deltas[kind]))
    fill_required(msg)
    session.queue(5, 2558, msg)


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
) -> dict[tuple[int, int], Handler]:

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (int(session.player_id),)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _warn(what: str, status: int, why: str) -> None:
        log.warning("%s would refuse %d (no status field): %s", what, status, why)

    def _locked(player) -> bool:
        return int(player["level"]) < cfg.function_unlock(FUNCTION_ARTIFACT)

    def _row(pid: int, artifact_id: int):
        return conn.execute(
            "SELECT * FROM artifacts WHERE id = ? AND player_id = ?", (int(artifact_id), pid)
        ).fetchone()

    def _main_res(name: str, pid: int):
        rows = _equipped(conn, pid)
        res = registry.message_class(name)()
        res.af_info.CopyFrom(build_total_info(registry, cfg, rows))
        for row in rows:
            res.equiped.add().CopyFrom(build_base_info(registry, row))
        fill_required(res)
        return res

    # 5_2533 ArtifactMainReq {} -> {af_info, equiped}; grants ARTIFACT_INIT
    # once, at the first open at or above the unlock level (O-W3-10).
    def main(session: Session, req):
        player = _player(session)
        pid = int(player["id"])
        if _locked(player):
            _warn("5_2534 ArtifactMainRes", STATUS_LEVEL, f"player level {player['level']}")
            return _main_res("ArtifactMainRes", pid)
        if not int(player["artifact_init"]):
            granted = item.grant_prizes(conn, cfg, pid, start_kit(cfg))
            conn.execute("UPDATE players SET artifact_init = 1 WHERE id = ?", (pid,))
            conn.commit()
            notify.items_changed(registry, session, granted["items"])
            item.announce(registry, session, granted)
            log.info("player %d: artifact start kit granted", pid)
        return _main_res("ArtifactMainRes", pid)

    # 5_2549 ArtifactBagReq {} -> {artifacts, illustrations}
    def bag(session: Session, req):
        pid = int(_player(session)["id"])
        res = registry.message_class("ArtifactBagRes")()
        for row in _rows(conn, pid):
            res.artifacts.add().CopyFrom(build_base_info(registry, row))
        res.illustrations.CopyFrom(illustrations(registry, conn, cfg, pid))
        fill_required(res)
        return res

    # 5_2541 ArtifactEquipReq {id | entry} -> {af_info, equiped}
    def equip(session: Session, req):
        player = _player(session)
        pid = int(player["id"])
        name = "5_2542 ArtifactEquipRes"
        artifact_id, entry = int(req.id), int(req.entry)
        if _locked(player):
            _warn(name, STATUS_LEVEL, f"player level {player['level']}")
            return _main_res("ArtifactEquipRes", pid)
        row = None
        if artifact_id:
            row = _row(pid, artifact_id)
            if row is None:
                _warn(name, STATUS_NO_ARTIFACT, f"artifact {artifact_id}")
                return _main_res("ArtifactEquipRes", pid)
            if int(row["hero"]):
                _warn(name, STATUS_EQUIPPED, f"artifact {artifact_id}")
                return _main_res("ArtifactEquipRes", pid)
            entry = int(row["entry"])
        else:
            stock = cfg.item(entry)
            if stock is None or int(stock["class"]) != CLASS_ARTIFACT or cfg.artifact(entry) is None:
                _warn(name, STATUS_NO_ARTIFACT, f"entry {entry} is not an artifact")
                return _main_res("ArtifactEquipRes", pid)
            have = conn.execute(
                "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
            ).fetchone()
            if have is None or int(have["amount"]) < 1:
                _warn(name, STATUS_NO_ITEMS, f"no artifact {entry} in the inventory")
                return _main_res("ArtifactEquipRes", pid)
        position = int(_info(cfg, entry)["position"])
        before_rows = _equipped(conn, pid)
        before = _sum(cfg, before_rows)
        for other in before_rows:
            if int(_info(cfg, int(other["entry"]))["position"]) == position:
                conn.execute("UPDATE artifacts SET hero = 0 WHERE id = ?", (int(other["id"]),))
        if row is None:
            left = db.take_item(conn, pid, entry, 1)
            artifact_id = db.add_artifact(conn, pid, entry)
            # A fresh artifact is level 1 (createInfoByEntry, ArtifactDataHelp.lua:867-876).
            conn.execute("UPDATE artifacts SET level = 1 WHERE id = ?", (artifact_id,))
            notify.items_changed(registry, session, [(entry, left)])
        conn.execute("UPDATE artifacts SET hero = ? WHERE id = ?", (EQUIPPED, artifact_id))
        conn.commit()
        attrs_changed(registry, session, before, _sum(cfg, _equipped(conn, pid)))
        log.info("player %d equipped artifact %d (%d) at position %d",
                 pid, artifact_id, entry, position)
        return _main_res("ArtifactEquipRes", pid)

    return {
        (5, 2533): main,
        (5, 2541): equip,
        (5, 2549): bag,
    }
