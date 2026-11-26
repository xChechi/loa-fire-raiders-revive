"""Blessing (护佑, function 10420, level 45): 5_2577 BlessQueryReq,
5_2571 BlessBuyLocationReq, 5_2573 BlessHeroAddReq, 5_2597
BlessQuickAddUnitReq, 5_2575 BlessFusingReq, 5_2671 BlessDecomposeReq;
pushes 5_2594 BlessInfoNotify and 5_2588 BlessLevelUpNotify.

What the client reads (step 1):

- The screen opens on 5_2578 only when `msg.status == 0`
  (FunctionType.lua:988-992). BlessQueryRes has no `status` field
  (allProtos.proto:1974-1978), so the native layer supplies 0 and the screen
  always opens: below the level the answer is an empty list.
- `bless_infos` replaces the whole list ProtectUI keeps (ProtectUI.lua:128-143,
  256-258), so every answer that carries `bless_infos` carries every medal.
- ClientBlessInfo (allProtos.proto:1904-1934):
  - `id`: what the client sends back as `id` in every Req
    (MedalDetailInfoUI.lua:176,325; CombinePanel.lua:95). The server uses the
    medal entry.
  - `entry`: the bless_medal_info entry (ProtectUI.lua:136).
  - `units`: six values, index 0 the angel, 1-5 heroes; 0 = locked,
    1 = open and empty, anything else the placed entry
    (BlessMedalDataHelp.lua:23,154-188).
  - `scores`: one per unit, shown under it (BlessMedalDataHelp.lua:160-175,
    HeroItem.lua:171, AngelItem.lua:143).
  - `medalsore`: the medal score (NumericInfoPanel.lua:92); the break bar
    shows it against the rank row's `score` (BlessBreakView.lua:74).
  - `level`: the crystal level (MedalDetailInfoUI.lua:523-524,
    BlessMedalDataHelp.lua:482-489).
  - `crystalbonus`: shown ×100 as a percentage (NumericInfoPanel.lua:94); the
    client multiplies the attributes by (1 + crystalbonus)
    (BlessMedalDataHelp.lua:360). It is the crystal row's `crystal_effect`.
  - `ranklevel`: a bless_medal_ranklevel `entry`, not a level
    (BlessMedalDataHelp.lua:466, BlessBreakView.lua:30).
  - `fightbonus` (NumericInfoPanel.lua:100) and `ability` (summed into the
    total at ProtectUI.lua:134): the client has no formula, so 0, as for the
    angel ability (angel.py).
  - `medal_red_point`/`unit_red_point`: only drive red dots
    (MedalDetailInfoUI.lua:539-549); False.
  - `infos`/`info`: only read when viewing another player
    (BlessMedalDataHelp.lua:207-283); filled from the placed units anyway.
- Rank: a rank row's `score` is the score that leaves that level (the bar,
  BlessBreakView.lua:74); the top row (level 15) has score 0 and no next row
  (BlessBreakView.lua:38-48). So the level is how many rows, from 0 up, have
  a non-zero `score` the medal score has reached. A rise is pushed as
  5_2588 {pre_ranklevel_entry, cur_ranklevel_entry, crystalbonus}
  (RPGGame.lua:282-284, BlessUpgradeView.lua:18-37).
- Slots: open_level0..5 and diamond_cost0..5 (BlessMedalDataHelp.lua:190-201).
  A hero slot past the count of non-zero hero1..5 never opens (:146-152,197).
  The client sends 5_2571 for the first locked slot (MedalDetailInfoUI.lua:
  364-380) and, whatever the answer, sets that unit to 1 itself on 5_2572
  (OpenMedalFieldPanel.lua:193-197, ProtectUI.lua:220-228), so a refusal is
  followed by 5_2594 with the real state (ProtectUI.lua:256-258,
  MedalDetailInfoUI.lua:478-487).
- Slot price: diamond_costN / BLESS_HOLE_PRICE punches (item
  BLESS_HOLE_ITEM_ID 1500); owned punches go first and diamonds pay the rest
  at BLESS_HOLE_PRICE each (OpenMedalFieldPanel.lua:41-48,123-128).
- Eligible units: angel1..3 at index 0, hero1..9 elsewhere
  (BlessMedalDataHelp.lua:25-77); placing is a drag onto an open slot
  (MedalDetailInfoUI.lua:323-327,562-579).
- Crystal level-up: the row at the current level costs `gold` and
  item0..3 × amount0..3; a row whose items are all 0 is the top
  (BlessMedalDataHelp.lua:478-534). The answer's `bless_infos` replace the
  list (CombinePanel.lua:110-127, MedalDetailInfoUI.lua:463-474).
- Attributes (NumericInfoPanel.lua:104, BlessMedalDataHelp.lua:288-377): per
  attribute, (rank row value + medal value × medal score) × (1 + crystalbonus),
  floored, with a value in (0, 1) shown as 1. Twelve attributes; the medal's
  resistance_base column is not among them. The medal describes who gains
  them: medal_effect_type 1 = a vocation, 2 = a gender, with
  medal_effect_type_arg the vocation 1/2/3 or gender 1/2
  (BlessMedalDataHelp.lua:546-570, bless_medal_info.describe).

Not in the client, so decided here (see the B1 report):

- The unit score. The client never computes one: the 13 BLESS_SCORE_*
  variables are read by no Lua file. A hero scores
  floor(BLESS_SCORE_HERO_RATE × its ClientHero.ability), an angel
  floor(BLESS_SCORE_ANGEL_RATE × its ClientAngel.ability); the medal score is
  their sum.
- Free slots (diamond_costN 0) are open as soon as their open_levelN is met.
- Placing a unit that already sits in another slot of the medal moves it.
- Quick add re-seats every open slot with the best-scoring owned eligible
  units, ties by entry.
- 5_2671 BlessDecomposeReq {id = item entry, amount} (BagResolvePanel.lua:
  193, BagCtr.lua:92-96) pays category 70, gve_money (costIcon70,
  BagResolvePanel.lua:108; 338005 秘藏币不足). Only a tag 50, class 70/71
  item shows the button (BagLeftPanel.lua:160-161). One item is worth
  floor(arg0 / BLESS_MONEY_VALUE × BLESS_ITEM_RECOVERY_RATE), and the class-70
  item with arg0 0 (the punch 1500) floor(BLESS_HOLE_PRICE / BLESS_MONEY_VALUE
  × BLESS_ITEM_RECOVERY_RATE) (BagResolvePanel.lua:18-22,144-147); the total
  is that times the amount (:162). The answer's `prizes` go to
  MMDropRewardPanel (BagCtr.lua:98-100).

No Bless*Res has a `status` field, so nothing here refuses on the wire: a
shortfall changes nothing, logs a WARNING with the language.db code, and
answers the current state.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3

from server import db
from server.config import Config
from server.modules import hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.bless")

FUNCTION_BLESS = 10420

STATUS_INTERNAL_ERROR = 327681      # language.db 系统内部错误
STATUS_NOT_ENOUGH_GOLD = 327937     # language.db 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938  # language.db 钻石不足
STATUS_NOT_ENOUGH_ITEMS = 327942    # language.db 没有足够道具
STATUS_LEVEL = 327957               # language.db 未满足此玩法的等级
STATUS_SLOT_CLOSED = 338001         # language.db 护佑栏位未开启
STATUS_CRYSTAL_MAX = 338002         # language.db 护佑水晶等级已满
STATUS_NO_UNIT = 338009             # language.db 没有英雄可以添加到护佑中

LOCATIONS = 6                       # units[0] angel, units[1..5] heroes
ANGEL_LOCATION = 0
HERO_SLOT_COLUMNS = 5               # hero1..5 decide how many hero slots exist
ELIGIBLE_HEROES = 9                 # hero1..9
ELIGIBLE_ANGELS = 3                 # angel1..3
CRYSTAL_ITEMS = 4                   # item0..3 / amount0..3

EFFECT_VOCATION = 1
EFFECT_GENDER = 2

# Decomposable items (BagLeftPanel.lua:160-161): tag 50, class 70 or 71.
DECOMPOSE_TAG = 50
DECOMPOSE_CLASSES = (70, 71)
PUNCH_CLASS = 70                    # arg0 0: priced from BLESS_HOLE_PRICE

# getAttrisByEntry's twelve attributes (BlessMedalDataHelp.lua:289-338):
# (bless_medal_info / bless_medal_ranklevel column, ClientHeroUnit field).
ATTRS = (
    ("max_hp", "max_hp"), ("power", "power"), ("defence", "defence"),
    ("magic", "magic"), ("magic_defense", "magic_defence"),
    ("agility", "agility"), ("hit_base", "hit_base"),
    ("duck_base", "duck_base"), ("crit_base", "crit_base"),
    ("crit_damage_base", "crit_damage_base"),
    ("tenacity_base", "tenacity_base"), ("block_base", "block_base"),
)

# angel.py sends ClientAngel.ability = 0: the client has no formula for it.
ANGEL_ABILITY = 0


def _variable(cfg: Config, key: str) -> float:
    raw = cfg.variable(key)
    if raw is None or raw == "":
        raise KeyError(f"variables.{key} is missing")
    return float(raw)


def medal_info(cfg: Config, medal: int):
    for row in cfg.bless_medals():
        if int(row["entry"]) == int(medal):
            return row
    return None


def _stored(conn: sqlite3.Connection, player_id: int, medal: int):
    return conn.execute(
        "SELECT * FROM bless WHERE player_id = ? AND medal = ?",
        (int(player_id), int(medal)),
    ).fetchone()


def placed_units(row) -> list[int]:
    """The six placed entries (0 = none) of a bless row; [] and None read as
    nothing placed."""
    units = [int(u) for u in json.loads(row["units"])] if row is not None else []
    return (units + [0] * LOCATIONS)[:LOCATIONS]


def bought_slots(row) -> set[int]:
    return {int(s) for s in json.loads(row["slots"])} if row is not None else set()


def crystal_level(row) -> int:
    return int(row["crystal_level"]) if row is not None else 0


def is_open(medal_row, location: int, player_level: int, bought: set[int]) -> bool:
    if not 0 <= location < LOCATIONS:
        return False
    if location != ANGEL_LOCATION:
        heroes = sum(
            1 for i in range(1, HERO_SLOT_COLUMNS + 1) if int(medal_row[f"hero{i}"] or 0)
        )
        if location > heroes:
            return False
    if int(medal_row[f"open_level{location}"] or 0) > player_level:
        return False
    return location in bought or not int(medal_row[f"diamond_cost{location}"] or 0)


def eligible(medal_row, location: int) -> list[int]:
    if location == ANGEL_LOCATION:
        names = [f"angel{i}" for i in range(1, ELIGIBLE_ANGELS + 1)]
    else:
        names = [f"hero{i}" for i in range(1, ELIGIBLE_HEROES + 1)]
    return [int(medal_row[n]) for n in names if int(medal_row[n] or 0)]


def _hero_row(conn: sqlite3.Connection, player_id: int, entry: int):
    return conn.execute(
        "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
        (int(player_id), int(entry)),
    ).fetchone()


def _angel_row(conn: sqlite3.Connection, player_id: int, entry: int):
    return conn.execute(
        "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
        (int(player_id), int(entry)),
    ).fetchone()


def _prototype_npc(cfg: Config, hero_row):
    proto = hero.prototype_for(cfg, int(hero_row["entry"]), int(hero_row["quality"]))
    npc_row = cfg.npc(proto)
    if npc_row is None:
        raise KeyError(f"npc_info has no row for prototype {proto}")
    return npc_row


def unit_score(conn: sqlite3.Connection, cfg: Config, player_id: int,
               location: int, entry: int) -> int:
    """The score of one placed unit, 0 for an empty slot or a unit no longer
    owned. A hero's ability is its prototype's npc_info.ability, the value
    build_client_hero sends."""
    if not entry:
        return 0
    if location == ANGEL_LOCATION:
        if _angel_row(conn, player_id, entry) is None:
            return 0
        return int(math.floor(_variable(cfg, "BLESS_SCORE_ANGEL_RATE") * ANGEL_ABILITY))
    row = _hero_row(conn, player_id, entry)
    if row is None:
        return 0
    ability = int(_prototype_npc(cfg, row)["ability"] or 0)
    return int(math.floor(_variable(cfg, "BLESS_SCORE_HERO_RATE") * ability))


def unit_scores(conn: sqlite3.Connection, cfg: Config, player_id: int,
                units: list[int]) -> list[int]:
    return [unit_score(conn, cfg, player_id, i, u) for i, u in enumerate(units)]


def rank_level(cfg: Config, medal: int, score: int) -> int:
    level = 0
    while True:
        row = cfg.bless_rank(medal, level)
        if row is None:
            raise KeyError(f"bless_medal_ranklevel has no row for {medal} level {level}")
        step = int(row["score"] or 0)
        if not step or score < step or cfg.bless_rank(medal, level + 1) is None:
            return level
        level += 1


def rank_entry(cfg: Config, medal: int, score: int) -> int:
    return int(cfg.bless_rank(medal, rank_level(cfg, medal, score))["entry"])


def crystal_row(cfg: Config, medal_row, level: int):
    row = cfg.bless_crystal(int(medal_row["crystal_id"]), level)
    if row is None:
        raise KeyError(
            f"bless_crystal_level_info has no row for {medal_row['crystal_id']}"
            f" level {level}"
        )
    return row


def crystal_bonus(cfg: Config, medal_row, level: int) -> float:
    return float(crystal_row(cfg, medal_row, level)["crystal_effect"] or 0)


def medal_attributes(cfg: Config, medal_row, score: int, level: int) -> dict[str, float]:
    """getAttrisByEntry with the medal row and score: the numbers the detail
    panel shows, keyed by ClientHeroUnit field, zeros dropped."""
    rank = cfg.bless_rank(int(medal_row["entry"]), rank_level(cfg, int(medal_row["entry"]), score))
    scale = 1 + crystal_bonus(cfg, medal_row, level)
    out: dict[str, float] = {}
    for column, field in ATTRS:
        value = (float(rank[column] or 0) + float(medal_row[column] or 0) * score) * scale
        value = 1.0 if 0 < value < 1 else float(math.floor(value))
        if value > 0:
            out[field] = value
    return out


def _benefits(cfg: Config, medal_row, hero_row) -> bool:
    npc_row = _prototype_npc(cfg, hero_row)
    kind = int(medal_row["medal_effect_type"] or 0)
    arg = int(medal_row["medal_effect_type_arg"] or 0)
    if kind == EFFECT_VOCATION:
        return int(npc_row["vocation_id"] or 0) == arg
    if kind == EFFECT_GENDER:
        return int(npc_row["gender"] or 0) == arg
    return False


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row) -> dict[str, float]:
    """The blessing stats one hero gains: every stored medal whose effect names
    the hero's vocation or gender adds its attributes (medal_attributes)."""
    out: dict[str, float] = {}
    player_id = int(hero_row["player_id"])
    for row in conn.execute(
        "SELECT * FROM bless WHERE player_id = ? ORDER BY medal", (player_id,)
    ):
        medal_row = medal_info(cfg, int(row["medal"]))
        if medal_row is None or not _benefits(cfg, medal_row, hero_row):
            continue
        score = sum(unit_scores(conn, cfg, player_id, placed_units(row)))
        for field, value in medal_attributes(cfg, medal_row, score, crystal_level(row)).items():
            out[field] = out.get(field, 0.0) + value
    return out


def build_info(registry: Registry, conn: sqlite3.Connection, cfg: Config,
               player_row, medal_row):
    player_id, level = int(player_row["id"]), int(player_row["level"])
    medal = int(medal_row["entry"])
    row = _stored(conn, player_id, medal)
    placed, bought = placed_units(row), bought_slots(row)
    scores = unit_scores(conn, cfg, player_id, placed)
    score = sum(scores)
    crystal = crystal_level(row)
    msg = registry.message_class("ClientBlessInfo")(
        id=medal, entry=medal, ability=0, level=crystal, medalsore=score,
        crystalbonus=crystal_bonus(cfg, medal_row, crystal), fightbonus=0,
        ranklevel=rank_entry(cfg, medal, score),
        medal_red_point=False, unit_red_point=False,
    )
    for location, entry in enumerate(placed):
        if entry:
            msg.units.append(entry)
        else:
            msg.units.append(1 if is_open(medal_row, location, level, bought) else 0)
    msg.scores.extend(scores)
    for location in range(1, LOCATIONS):
        hero_row = _hero_row(conn, player_id, placed[location]) if placed[location] else None
        info = msg.infos.add()
        if hero_row is not None:
            info.entry, info.star = int(hero_row["entry"]), int(hero_row["star"])
            info.quality, info.model = int(hero_row["quality"]), 0
    angel_row = _angel_row(conn, player_id, placed[0]) if placed[0] else None
    if angel_row is not None:
        msg.info.entry, msg.info.star = int(angel_row["angel_entry"]), int(angel_row["star"])
    fill_required(msg)
    return msg


def decompose_value(cfg: Config, item_row) -> int | None:
    """The gve_money one item decomposes into (BagResolvePanel.lua:144-147),
    None for an item the bag offers no decompose for."""
    if int(item_row["tag"] or 0) != DECOMPOSE_TAG:
        return None
    if int(item_row["class"] or 0) not in DECOMPOSE_CLASSES:
        return None
    base = float(item_row["arg0"] or 0)
    if not base and int(item_row["class"]) == PUNCH_CLASS:
        base = _variable(cfg, "BLESS_HOLE_PRICE")
    return int(math.floor(
        base / _variable(cfg, "BLESS_MONEY_VALUE") * _variable(cfg, "BLESS_ITEM_RECOVERY_RATE")
    ))


def open_medals(cfg: Config, player_level: int) -> list:
    return [
        m for m in cfg.bless_medals() if int(m["bless_open_level"] or 0) <= player_level
    ]


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _infos(player_row) -> list:
        if int(player_row["level"]) < cfg.function_unlock(FUNCTION_BLESS):
            return []
        return [
            build_info(registry, conn, cfg, player_row, m)
            for m in open_medals(cfg, int(player_row["level"]))
        ]

    def _push_infos(session: Session, player_row) -> None:
        msg = registry.message_class("BlessInfoNotify")()
        for info in _infos(player_row):
            msg.bless_infos.add().CopyFrom(info)
        fill_required(msg)
        session.queue(5, 2594, msg)

    def _medal(player_row, medal: int, what: str):
        """The bless_medal_info row the player may use, else None (logged)."""
        level = int(player_row["level"])
        medal_row = medal_info(cfg, medal)
        if medal_row is None:
            log.warning("%s: no bless_medal_info row %s (%d)", what, medal, STATUS_INTERNAL_ERROR)
            return None
        need = max(cfg.function_unlock(FUNCTION_BLESS), int(medal_row["bless_open_level"] or 0))
        if level < need:
            log.warning(
                "%s: medal %d opens at level %d, player is %d (%d)",
                what, medal, need, level, STATUS_LEVEL,
            )
            return None
        return medal_row

    def _save(player_id: int, medal: int, **columns) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO bless (player_id, medal) VALUES (?, ?)",
            (player_id, medal),
        )
        # Column names are literals from this module, never request data.
        sets = ", ".join(f"{name} = ?" for name in columns)
        conn.execute(
            f"UPDATE bless SET {sets} WHERE player_id = ? AND medal = ?",
            (*columns.values(), player_id, medal),
        )
        conn.commit()

    def _place(session: Session, player_row, medal_row, units: list[int]) -> None:
        """Store `units`, the new score with it, and push 5_2588 on a rank
        change."""
        player_id, medal = int(player_row["id"]), int(medal_row["entry"])
        before = sum(unit_scores(conn, cfg, player_id, placed_units(_stored(conn, player_id, medal))))
        after = sum(unit_scores(conn, cfg, player_id, units))
        _save(player_id, medal, units=json.dumps(units), score=after)
        pre, cur = rank_entry(cfg, medal, before), rank_entry(cfg, medal, after)
        if pre != cur:
            msg = registry.message_class("BlessLevelUpNotify")(
                pre_ranklevel_entry=pre, cur_ranklevel_entry=cur,
                crystalbonus=crystal_bonus(
                    cfg, medal_row, crystal_level(_stored(conn, player_id, medal))
                ),
            )
            fill_required(msg)
            session.queue(5, 2588, msg)
            log.info("medal %d of player %d: rank %d -> %d", medal, player_id, pre, cur)

    def query(session: Session, req):
        res = registry.message_class("BlessQueryRes")()
        player_row = _player(session)
        if player_row is None:
            log.warning("5_2577 with no player (%d)", STATUS_INTERNAL_ERROR)
        elif int(player_row["level"]) < cfg.function_unlock(FUNCTION_BLESS):
            log.warning(
                "5_2577: blessing opens at level %d, player is %d (%d)",
                cfg.function_unlock(FUNCTION_BLESS), int(player_row["level"]), STATUS_LEVEL,
            )
        else:
            for info in _infos(player_row):
                res.bless_infos.add().CopyFrom(info)
        fill_required(res)
        return res

    def buy_location(session: Session, req):
        res = registry.message_class("BlessBuyLocationRes")()
        fill_required(res)
        player_row = _player(session)
        if player_row is None:
            log.warning("5_2571 with no player (%d)", STATUS_INTERNAL_ERROR)
            return res
        medal, location = int(req.id), int(req.location)
        refusal = _buy(session, player_row, medal, location)
        if refusal:
            log.warning("5_2571 medal %d location %d: %s", medal, location, refusal)
            # The client opens the slot on its own on 5_2572; put it back.
            _push_infos(session, player_row)
        return res

    def _buy(session: Session, player_row, medal: int, location: int) -> str | None:
        medal_row = _medal(player_row, medal, "5_2571")
        if medal_row is None:
            return "medal not open"
        player_id, level = int(player_row["id"]), int(player_row["level"])
        row = _stored(conn, player_id, medal)
        bought = bought_slots(row)
        if is_open(medal_row, location, level, bought):
            return "already open"
        if not is_open(medal_row, location, level, bought | {location}):
            return f"slot cannot open at level {level} ({STATUS_SLOT_CLOSED})"
        price = int(_variable(cfg, "BLESS_HOLE_PRICE"))
        punch = int(_variable(cfg, "BLESS_HOLE_ITEM_ID"))
        need = int(medal_row[f"diamond_cost{location}"]) // price
        owned = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (player_id, punch)
        ).fetchone()
        used = min(need, int(owned["amount"]) if owned else 0)
        diamonds = (need - used) * price
        if int(player_row["diamond"]) < diamonds:
            return (
                f"{used} x item {punch} and {diamonds} diamonds needed,"
                f" player has {player_row['diamond']} ({STATUS_NOT_ENOUGH_DIAMOND})"
            )
        if diamonds:
            db.spend(conn, player_id, diamond=diamonds)
            notify.player_changed(
                registry, session, {"diamond": int(player_row["diamond"]) - diamonds}
            )
        if used:
            notify.items_changed(
                registry, session, [(punch, db.take_item(conn, player_id, punch, used))]
            )
        _save(player_id, medal, slots=json.dumps(sorted(bought | {location})))
        log.info(
            "medal %d of player %d: slot %d opened for %d x item %d + %d diamonds",
            medal, player_id, location, used, punch, diamonds,
        )
        return None

    def hero_add(session: Session, req):
        res = registry.message_class("BlessHeroAddRes")()
        player_row = _player(session)
        medal, entry, location = int(req.id), int(req.entry), int(req.location)
        medal_row = _medal(player_row, medal, "5_2573") if player_row is not None else None
        if medal_row is not None:
            player_id, level = int(player_row["id"]), int(player_row["level"])
            row = _stored(conn, player_id, medal)
            units = placed_units(row)
            owned = (
                _angel_row(conn, player_id, entry) if location == ANGEL_LOCATION
                else _hero_row(conn, player_id, entry)
            )
            if not is_open(medal_row, location, level, bought_slots(row)):
                log.warning(
                    "5_2573 medal %d: location %d is not open (%d)",
                    medal, location, STATUS_SLOT_CLOSED,
                )
            elif entry not in eligible(medal_row, location) or owned is None:
                log.warning(
                    "5_2573 medal %d location %d: %d is not an owned eligible unit (%d)",
                    medal, location, entry, STATUS_INTERNAL_ERROR,
                )
            else:
                units = [0 if u == entry else u for u in units]
                units[location] = entry
                _place(session, player_row, medal_row, units)
                log.info("medal %d of player %d: %d at location %d", medal, player_id, entry, location)
            res.bless_info.CopyFrom(build_info(registry, conn, cfg, player_row, medal_row))
        fill_required(res)
        return res

    def quick_add(session: Session, req):
        res = registry.message_class("BlessQuickAddUnitRes")()
        player_row = _player(session)
        medal = int(req.id)
        medal_row = _medal(player_row, medal, "5_2597") if player_row is not None else None
        if medal_row is not None:
            player_id, level = int(player_row["id"]), int(player_row["level"])
            row = _stored(conn, player_id, medal)
            bought = bought_slots(row)
            units = placed_units(row)
            for kind in ("angel", "hero"):
                slots = [
                    loc for loc in range(LOCATIONS)
                    if (loc == ANGEL_LOCATION) == (kind == "angel")
                    and is_open(medal_row, loc, level, bought)
                ]
                if not slots:
                    continue
                owned = [
                    e for e in eligible(medal_row, slots[0])
                    if (_angel_row(conn, player_id, e) if kind == "angel"
                        else _hero_row(conn, player_id, e)) is not None
                ]
                owned.sort(key=lambda e: (-unit_score(conn, cfg, player_id, slots[0], e), e))
                for loc in slots:
                    units[loc] = owned.pop(0) if owned else 0
            if units == placed_units(row) and not any(units):
                log.warning("5_2597 medal %d: no owned eligible unit (%d)", medal, STATUS_NO_UNIT)
            else:
                _place(session, player_row, medal_row, units)
                log.info("medal %d of player %d: quick add %s", medal, player_id, units)
            res.bless_info.CopyFrom(build_info(registry, conn, cfg, player_row, medal_row))
        fill_required(res)
        return res

    def fusing(session: Session, req):
        res = registry.message_class("BlessFusingRes")()
        player_row = _player(session)
        medal = int(req.id)
        medal_row = _medal(player_row, medal, "5_2575") if player_row is not None else None
        if medal_row is not None:
            refusal = _fuse(session, player_row, medal_row)
            if refusal:
                log.warning("5_2575 medal %d: %s", medal, refusal)
            player_row = _player(session)
        if player_row is not None:
            for info in _infos(player_row):
                res.bless_infos.add().CopyFrom(info)
        fill_required(res)
        return res

    def _fuse(session: Session, player_row, medal_row) -> str | None:
        player_id, medal = int(player_row["id"]), int(medal_row["entry"])
        level = crystal_level(_stored(conn, player_id, medal))
        row = crystal_row(cfg, medal_row, level)
        costs = [
            (int(row[f"item{i}"] or 0), int(row[f"amount{i}"] or 0))
            for i in range(CRYSTAL_ITEMS)
        ]
        costs = [(e, n) for e, n in costs if e and n]
        if not any(int(row[f"item{i}"] or 0) for i in range(CRYSTAL_ITEMS)):
            return f"crystal level {level} is the top ({STATUS_CRYSTAL_MAX})"
        gold = int(row["gold"] or 0)
        if int(player_row["gold"]) < gold:
            return f"needs {gold} gold, player has {player_row['gold']} ({STATUS_NOT_ENOUGH_GOLD})"
        for entry, amount in costs:
            owned = conn.execute(
                "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
                (player_id, entry),
            ).fetchone()
            if (int(owned["amount"]) if owned else 0) < amount:
                return f"needs {amount} x item {entry} ({STATUS_NOT_ENOUGH_ITEMS})"
        if gold:
            db.spend(conn, player_id, gold=gold)
            notify.player_changed(registry, session, {"gold": int(player_row["gold"]) - gold})
        notify.items_changed(
            registry, session,
            [(entry, db.take_item(conn, player_id, entry, amount)) for entry, amount in costs],
        )
        _save(player_id, medal, crystal_level=level + 1)
        log.info("medal %d of player %d: crystal %d -> %d", medal, player_id, level, level + 1)
        return None

    def decompose(session: Session, req):
        res = registry.message_class("BlessDecomposeRes")()
        player_row = _player(session)
        entry, amount = int(req.id), int(req.amount)
        if player_row is None:
            log.warning("5_2671 with no player (%d)", STATUS_INTERNAL_ERROR)
            fill_required(res)
            return res
        player_id = int(player_row["id"])
        item_row = cfg.item(entry)
        value = decompose_value(cfg, item_row) if item_row is not None else None
        owned = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (player_id, entry)
        ).fetchone()
        have = int(owned["amount"]) if owned else 0
        if value is None:
            log.warning("5_2671: item %d cannot be decomposed (%d)", entry, STATUS_INTERNAL_ERROR)
        elif amount <= 0 or have < amount:
            log.warning(
                "5_2671: %d x item %d asked, player has %d (%d)",
                amount, entry, have, STATUS_NOT_ENOUGH_ITEMS,
            )
        else:
            prizes = [(item.CATEGORY_GVE_MONEY, 0, value * amount)]
            granted = item.grant_prizes(conn, cfg, player_id, prizes)
            notify.items_changed(
                registry, session, [(entry, db.take_item(conn, player_id, entry, amount))]
            )
            item.announce(registry, session, granted)
            for category, refer, total in prizes:
                res.prizes.add(category=category, refer=refer, amount=total)
            log.info(
                "player %d decomposed %d x item %d for %d gve_money",
                player_id, amount, entry, value * amount,
            )
        fill_required(res)
        return res

    return {
        (5, 2577): query,
        (5, 2571): buy_location,
        (5, 2573): hero_add,
        (5, 2597): quick_add,
        (5, 2575): fusing,
        (5, 2671): decompose,
    }
