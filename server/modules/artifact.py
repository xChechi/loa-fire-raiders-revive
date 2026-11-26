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
current state. Codes: 327937 金币不足, 327942 没有足够道具, 327957
未满足此玩法的等级, 337001 材料不够, 337002 材料不可被吞噬, 337003 神器等级不够,
337004 神器阶级已满, 337005 未装备的神器不可升级或进阶, 337007 材料不可被熔炼,
337008 神器已达到最大等级, 337009 神器不存在, 337010 神器已装备, 337011
神器升级材料数量非法.

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
CLASS_FRAGMENT = 131             # item_info.class 碎片 (ArtifactDataHelp.lua:509)
EQUIPPED = 1                     # artifacts.hero of an equipped artifact
ADVANCE_STONE = 1400             # 神器进阶石, the smelt potion (ArtifactComposeUI.lua:456)
# item_info class 133 (神器晶石 小/中/大), largest exp_score first: the smelt
# xp refund (ArtifactComposeUI.lua:458-468). test_crystals_are_every_class_133_item
# checks this against item_info.
CRYSTALS = (1500003, 1500002, 1500001)

STATUS_NO_GOLD = 327937          # language.db 金币不足
STATUS_NO_ITEMS = 327942         # language.db 没有足够道具
STATUS_LEVEL = 327957            # language.db 未满足此玩法的等级
STATUS_NO_MATERIAL = 337001      # language.db 材料不够
STATUS_NOT_FOOD = 337002         # language.db 材料不可被吞噬
STATUS_LEVEL_LOW = 337003        # language.db 神器等级不够
STATUS_MAX_ADVANCE = 337004      # language.db 神器阶级已满
STATUS_NOT_EQUIPPED = 337005     # language.db 未装备的神器不可升级或进阶
STATUS_NOT_SMELTABLE = 337007    # language.db 材料不可被熔炼
STATUS_MAX_LEVEL = 337008        # language.db 神器已达到最大等级
STATUS_NO_ARTIFACT = 337009      # language.db 神器不存在
STATUS_EQUIPPED = 337010         # language.db 神器已装备
STATUS_BAD_AMOUNT = 337011       # language.db 神器升级材料数量非法

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


def _var(cfg: Config, key: str) -> float:
    raw = cfg.variable(key)
    if raw in (None, ""):
        raise KeyError(f"variables.{key} is missing")
    return float(raw)


def _quality(cfg: Config, entry: int) -> int:
    row = cfg.item(entry)
    if row is None:
        raise KeyError(f"item_info has no row for artifact {entry}")
    return int(row["quality"])


def max_advance(cfg: Config, quality: int) -> int:
    """ARTIFACT_MAX_ADVANCE 'quality|advance,...'."""
    raw = cfg.variable("ARTIFACT_MAX_ADVANCE")
    if not raw:
        raise KeyError("variables.ARTIFACT_MAX_ADVANCE is missing")
    for part in raw.split(","):
        if part:
            q, cap = part.split("|")
            if int(q) == int(quality):
                return int(cap)
    raise KeyError(f"variables.ARTIFACT_MAX_ADVANCE has no quality {quality}")


def level_need(cfg: Config, level: int, quality: int, player_level: int) -> int:
    """The xp to the next level; 0 at the top (getMaxExp: never past the
    player level, no row or upgrade_exp 0 is the max)."""
    if int(level) >= int(player_level):
        return 0
    row = cfg.artifact_level(level)
    return 0 if row is None else int(row[f"upgrade_exp{int(quality)}"] or 0)


def total_xp(cfg: Config, entry: int, level: int, exp: int) -> int:
    """getExpTotal: exp plus every level below `level` (ArtifactDataHelp.lua:403-420)."""
    quality = _quality(cfg, entry)
    out = int(exp)
    for lvl in range(1, int(level)):
        row = cfg.artifact_level(lvl)
        if row is None:
            raise KeyError(f"artifact_level_info has no row for level {lvl}")
        out += int(row[f"upgrade_exp{quality}"] or 0)
    return out


def absorb(
    cfg: Config, quality: int, level: int, exp: int, add: int, player_level: int
) -> tuple[int, int, int, int]:
    """(level, exp, absorbed, overflow) after feeding `add` xp."""
    absorbed = 0
    while add > 0:
        need = level_need(cfg, level, quality, player_level)
        if need <= 0:
            exp = 0
            break
        if exp + add < need:
            exp, absorbed, add = exp + add, absorbed + add, 0
            break
        absorbed += need - exp
        add -= need - exp
        level, exp = level + 1, 0
    return level, exp, absorbed, add


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


def build_artifact_info(registry: Registry, cfg: Config, row, entry: int | None = None):
    """ArtifactInfo of one artifact; with `entry`, the preview of that entry
    at the row's level (af_advance_info, id 0: "神器id是无效的")."""
    msg = registry.message_class("ArtifactInfo")()
    base = build_base_info(registry, row)
    if entry is not None:
        base.id, base.entry = 0, int(entry)
    msg.base_info.CopyFrom(base)
    _fill_attrs(msg, attrs(cfg, int(base.entry), int(row["level"])))
    fill_required(msg)
    return msg


def advance_preview(registry: Registry, cfg: Config, row):
    nxt = int(_info(cfg, int(row["entry"]))["next_entry"] or 0)
    return build_artifact_info(registry, cfg, row, nxt or int(row["entry"]))


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

    def _have(pid: int, entry: int) -> int:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, int(entry))
        ).fetchone()
        return int(row["amount"]) if row else 0

    def _food_stocks(name: str, food) -> dict[int, int] | None:
        """ArtifactMaterial.stocks summed per entry; None (warned) on a
        non-positive amount."""
        out: dict[int, int] = {}
        for stock in food.stocks:
            if int(stock.amount) < 1:
                _warn(name, STATUS_BAD_AMOUNT, f"stock {stock.entry} x {stock.amount}")
                return None
            out[int(stock.entry)] = out.get(int(stock.entry), 0) + int(stock.amount)
        return out

    def _amounts(pid: int, entries) -> list[tuple[int, int]]:
        return [(e, _have(pid, e)) for e in sorted(set(entries))]

    def _develop_res(name: str, pid: int, artifact_id: int, up_field: str):
        """ArtifactLevelUpRes / ArtifactAdvanceUpRes over the current state."""
        res = registry.message_class(name)()
        row = _row(pid, artifact_id)
        if row is not None:
            getattr(res, up_field).CopyFrom(build_artifact_info(registry, cfg, row))
            res.af_next_advance_info.CopyFrom(advance_preview(registry, cfg, row))
        rows = _equipped(conn, pid)
        res.af_info.CopyFrom(build_total_info(registry, cfg, rows))
        for r in rows:
            res.equiped.add().CopyFrom(build_base_info(registry, r))
        for r in _rows(conn, pid):
            res.artifacts.add().CopyFrom(build_base_info(registry, r))
        fill_required(res)
        return res

    def _equipped_row(name: str, player, artifact_id: int):
        """The equipped row to develop, or None (warned)."""
        if _locked(player):
            _warn(name, STATUS_LEVEL, f"player level {player['level']}")
            return None
        row = _row(int(player["id"]), artifact_id)
        if row is None:
            _warn(name, STATUS_NO_ARTIFACT, f"artifact {artifact_id}")
            return None
        if not int(row["hero"]):
            _warn(name, STATUS_NOT_EQUIPPED, f"artifact {artifact_id}")
            return None
        return row

    # 5_2535 ArtifactDevelopeInfoReq {id} -> {af_info, af_advance_info, artifacts}
    def develop_info(session: Session, req):
        pid = int(_player(session)["id"])
        res = registry.message_class("ArtifactDevelopeInfoRes")()
        row = _row(pid, int(req.id))
        if row is None:
            _warn("5_2536 ArtifactDevelopeInfoRes", STATUS_NO_ARTIFACT, f"artifact {req.id}")
        else:
            res.af_info.CopyFrom(build_artifact_info(registry, cfg, row))
            res.af_advance_info.CopyFrom(advance_preview(registry, cfg, row))
        for r in _rows(conn, pid):
            res.artifacts.add().CopyFrom(build_base_info(registry, r))
        fill_required(res)
        return res

    # 5_2537 ArtifactLevelUpReq {id, food} -> {af_level_up_info, af_info,
    #   equiped, artifacts, af_next_advance_info}
    def level_up(session: Session, req):
        player = _player(session)
        pid, artifact_id = int(player["id"]), int(req.id)
        name = "5_2538 ArtifactLevelUpRes"

        def answer():
            return _develop_res("ArtifactLevelUpRes", pid, artifact_id, "af_level_up_info")

        row = _equipped_row(name, player, artifact_id)
        if row is None:
            return answer()
        if len(req.food.afs):
            _warn(name, STATUS_NOT_FOOD, f"artifacts {list(req.food.afs)} (有id的神器不能被吞噬)")
            return answer()
        stocks = _food_stocks(name, req.food)
        if stocks is None:
            return answer()
        if not stocks:
            _warn(name, STATUS_NO_MATERIAL, "no food")
            return answer()
        xp = 0
        for entry, n in stocks.items():
            info = cfg.item(entry)
            score = int(info["exp_score"] or 0) if info is not None else 0
            if score <= 0:
                _warn(name, STATUS_NOT_FOOD, f"item {entry} has no exp_score")
                return answer()
            if _have(pid, entry) < n:
                _warn(name, STATUS_NO_ITEMS, f"item {entry}: has {_have(pid, entry)}, needs {n}")
                return answer()
            xp += score * n
        entry, level, exp = int(row["entry"]), int(row["level"]), int(row["exp"])
        quality = _quality(cfg, entry)
        if level_need(cfg, level, quality, int(player["level"])) <= 0:
            _warn(name, STATUS_MAX_LEVEL, f"artifact {artifact_id} at level {level}")
            return answer()
        new_level, new_exp, absorbed, overflow = absorb(
            cfg, quality, level, exp, xp, int(player["level"]))
        gold = math.floor(absorbed * _var(cfg, "ARTIFACT_EXP_GOLD_SCALE"))
        essence = math.floor(overflow * _var(cfg, "XP_TO_ARTIFACT_SMELT"))
        if int(player["gold"]) < gold:
            _warn(name, STATUS_NO_GOLD, f"needs {gold} gold, has {player['gold']}")
            return answer()
        before = _sum(cfg, _equipped(conn, pid))
        db.spend(conn, pid, gold=gold)
        for e, n in stocks.items():
            db.take_item(conn, pid, e, n)
        conn.execute(
            "UPDATE artifacts SET level = ?, exp = ? WHERE id = ?",
            (new_level, new_exp, artifact_id),
        )
        conn.execute(
            "UPDATE players SET artifact_smelt = artifact_smelt + ? WHERE id = ?", (essence, pid)
        )
        conn.commit()
        fresh = _player(session)
        notify.items_changed(registry, session, _amounts(pid, stocks))
        notify.player_changed(registry, session, {
            "gold": int(fresh["gold"]), "artifact_smelt": int(fresh["artifact_smelt"]),
        })
        attrs_changed(registry, session, before, _sum(cfg, _equipped(conn, pid)))
        log.info("player %d: artifact %d +%d xp (%d absorbed, %d -> %d essence) level %d -> %d,"
                 " %d gold", pid, artifact_id, xp, absorbed, overflow, essence, level,
                 new_level, gold)
        return answer()

    # 5_2539 ArtifactAdvanceUpReq {id} -> {af_advance_up_info, af_info,
    #   equiped, artifacts, af_next_advance_info}
    def advance(session: Session, req):
        player = _player(session)
        pid, artifact_id = int(player["id"]), int(req.id)
        name = "5_2540 ArtifactAdvanceUpRes"

        def answer():
            return _develop_res("ArtifactAdvanceUpRes", pid, artifact_id, "af_advance_up_info")

        row = _equipped_row(name, player, artifact_id)
        if row is None:
            return answer()
        entry, level = int(row["entry"]), int(row["level"])
        nxt = int(_info(cfg, entry)["next_entry"] or 0)
        if not nxt:
            _warn(name, STATUS_MAX_ADVANCE, f"artifact {entry} has no next_entry")
            return answer()
        nxt_info = _info(cfg, nxt)
        cap = max_advance(cfg, _quality(cfg, entry))
        if int(nxt_info["advance"]) > cap:
            _warn(name, STATUS_MAX_ADVANCE, f"advance {nxt_info['advance']} > {cap}")
            return answer()
        if level < int(nxt_info["needlevel"]):
            _warn(name, STATUS_LEVEL_LOW, f"level {level} < {nxt_info['needlevel']}")
            return answer()
        recipe = cfg.item_composite(nxt)
        if recipe is None or int(recipe["item0"]) != entry:
            raise KeyError(f"item_composite has no advance recipe {entry} -> {nxt}")
        need: dict[int, int] = {}
        for i in range(1, 4):
            e = int(recipe[f"item{i}"] or 0)
            if e:
                need[e] = need.get(e, 0) + int(recipe[f"amount{i}"] or 0)
        for e, n in need.items():
            if _have(pid, e) < n:
                _warn(name, STATUS_NO_MATERIAL, f"item {e}: has {_have(pid, e)}, needs {n}")
                return answer()
        cost = int(recipe["cost"] or 0)
        if int(player["gold"]) < cost:
            _warn(name, STATUS_NO_GOLD, f"needs {cost} gold, has {player['gold']}")
            return answer()
        before = _sum(cfg, _equipped(conn, pid))
        db.spend(conn, pid, gold=cost)
        for e, n in need.items():
            db.take_item(conn, pid, e, n)
        conn.execute("UPDATE artifacts SET entry = ? WHERE id = ?", (nxt, artifact_id))
        conn.commit()
        notify.items_changed(registry, session, _amounts(pid, need))
        notify.player_changed(registry, session, {"gold": int(_player(session)["gold"])})
        attrs_changed(registry, session, before, _sum(cfg, _equipped(conn, pid)))
        log.info("player %d: artifact %d advanced %d -> %d for %d gold", pid, artifact_id,
                 entry, nxt, cost)
        return answer()

    # 5_2555 ArtifactSmeltMainReq {} -> {artifacts}
    def smelt_main(session: Session, req):
        pid = int(_player(session)["id"])
        res = registry.message_class("ArtifactSmeltMainRes")()
        for r in _rows(conn, pid):
            res.artifacts.add().CopyFrom(build_base_info(registry, r))
        fill_required(res)
        return res

    # 5_2545 ArtifactSmeltReq {food} -> {prizes}
    def smelt(session: Session, req):
        player = _player(session)
        pid = int(player["id"])
        name = "5_2546 ArtifactSmeltRes"
        res = registry.message_class("ArtifactSmeltRes")()

        def answer():
            fill_required(res)
            return res

        if _locked(player):
            _warn(name, STATUS_LEVEL, f"player level {player['level']}")
            return answer()
        ids = [int(x) for x in req.food.afs]
        rows = [_row(pid, x) for x in ids]
        if len(set(ids)) != len(ids) or any(r is None for r in rows):
            _warn(name, STATUS_NO_ARTIFACT, f"artifacts {ids}")
            return answer()
        if any(int(r["hero"]) for r in rows):
            _warn(name, STATUS_EQUIPPED, f"artifacts {ids} include an equipped one")
            return answer()
        stocks = _food_stocks(name, req.food)
        if stocks is None:
            return answer()
        if not rows and not stocks:
            _warn(name, STATUS_NO_MATERIAL, "nothing to smelt")
            return answer()
        for e, n in stocks.items():
            info = cfg.item(e)
            if info is None or int(info["smelt_score"] or 0) <= 0:
                _warn(name, STATUS_NOT_SMELTABLE, f"item {e} has no smelt_score")
                return answer()
            if _have(pid, e) < n:
                _warn(name, STATUS_NO_ITEMS, f"item {e}: has {_have(pid, e)}, needs {n}")
                return answer()
        point_scale = _var(cfg, "ARTIFACT_SMELT_POINT_SCALE")
        gold_scale = _var(cfg, "ARTIFACT_SMELT_GOLD_SCALE")
        potion_scale = _var(cfg, "ARTIFACT_SMELT_POTION_SCALE")
        exp_scale = _var(cfg, "ARTIFACT_SMELT_EXP_SCALE")
        exp_gold = _var(cfg, "ARTIFACT_EXP_GOLD_SCALE")
        point = gold = potion = xp = 0
        for row in rows:
            entry = int(row["entry"])
            info, art = cfg.item(entry), _info(cfg, entry)
            total = total_xp(cfg, entry, int(row["level"]), int(row["exp"]))
            point += math.ceil(int(info["smelt_score"] or 0) * point_scale)
            gold += math.ceil(int(art["smelt_gold_return"] or 0) * gold_scale)
            gold += math.ceil(total * exp_gold * gold_scale)
            potion += math.ceil(int(art["smelt_potion_return"] or 0) * potion_scale)
            xp += math.ceil(total * exp_scale)
        for e, n in stocks.items():
            point += math.ceil(int(cfg.item(e)["smelt_score"] or 0) * point_scale) * n
            art = cfg.artifact(e)
            if art is not None:
                gold += math.ceil(int(art["smelt_gold_return"] or 0) * gold_scale) * n
                potion += math.ceil(int(art["smelt_potion_return"] or 0) * potion_scale) * n
        prizes = [(item.CATEGORY_ARTIFACT_SMELT, 0, point), (item.CATEGORY_GOLD, 0, gold),
                  (item.CATEGORY_ITEM, ADVANCE_STONE, potion)]
        for crystal in CRYSTALS:
            score = int(cfg.item(crystal)["exp_score"])
            prizes.append((item.CATEGORY_ITEM, crystal, xp // score))
            xp %= score
        prizes = [p for p in prizes if p[2] > 0]
        granted = item.grant_prizes(conn, cfg, pid, prizes)
        conn.executemany("DELETE FROM artifacts WHERE id = ?", [(x,) for x in ids])
        conn.commit()
        for e, n in stocks.items():
            db.take_item(conn, pid, e, n)
        for category, refer, amount in prizes:
            res.prizes.add(category=category, refer=refer, amount=amount)
        touched = list(stocks) + [r for (c, r, _a) in prizes if c == item.CATEGORY_ITEM]
        notify.items_changed(registry, session, _amounts(pid, touched))
        item.announce(registry, session, granted)
        notify.player_changed(registry, session, {"gold": granted["gold"]})
        log.info("player %d smelted artifacts %s and stocks %s for %s", pid, ids, stocks, prizes)
        return answer()

    # 5_2553 ArtifactComposeReq {item} -> {illustrations, prize}
    def compose(session: Session, req):
        player = _player(session)
        pid, target = int(player["id"]), int(req.item)
        name = "5_2554 ArtifactComposeRes"
        res = registry.message_class("ArtifactComposeRes")()

        def answer():
            res.illustrations.CopyFrom(illustrations(registry, conn, cfg, pid))
            fill_required(res)
            return res

        if _locked(player):
            _warn(name, STATUS_LEVEL, f"player level {player['level']}")
            return answer()
        recipe = cfg.item_composite(target) if cfg.artifact(target) is not None else None
        first = cfg.item(int(recipe["item0"])) if recipe is not None else None
        if first is None or int(first["class"]) != CLASS_FRAGMENT:
            _warn(name, STATUS_NO_ARTIFACT, f"no fragment recipe for {target}")
            return answer()
        need: dict[int, int] = {}
        for i in range(4):
            e = int(recipe[f"item{i}"] or 0)
            if e:
                need[e] = need.get(e, 0) + int(recipe[f"amount{i}"] or 0)
        for e, n in need.items():
            if _have(pid, e) < n:
                _warn(name, STATUS_NO_MATERIAL, f"item {e}: has {_have(pid, e)}, needs {n}")
                return answer()
        cost = int(recipe["cost"] or 0)
        if int(player["gold"]) < cost:
            _warn(name, STATUS_NO_GOLD, f"needs {cost} gold, has {player['gold']}")
            return answer()
        prize = (item.CATEGORY_ITEM, target, 1)
        granted = item.grant_prizes(conn, cfg, pid, [prize])
        db.spend(conn, pid, gold=cost)
        for e, n in need.items():
            db.take_item(conn, pid, e, n)
        res.prize.category, res.prize.refer, res.prize.amount = prize
        notify.items_changed(registry, session, _amounts(pid, list(need) + [target]))
        item.announce(registry, session, granted)
        notify.player_changed(registry, session, {"gold": int(_player(session)["gold"])})
        log.info("player %d composed artifact %d for %s and %d gold", pid, target, need, cost)
        return answer()

    return {
        (5, 2533): main,
        (5, 2535): develop_info,
        (5, 2537): level_up,
        (5, 2539): advance,
        (5, 2541): equip,
        (5, 2545): smelt,
        (5, 2549): bag,
        (5, 2553): compose,
        (5, 2555): smelt_main,
    }
