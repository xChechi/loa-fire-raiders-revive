"""ClientHero shapes, built from the client own hero tables.

Field names of ClientHeroUnit are npc_info column names one for one, so a
level-1 hero is its prototype npc row verbatim; each level above the first adds
one hero_growth(hero, star) row. hero_quality maps (hero, quality) to the
prototype npc entry, and ClientHero:getNpcProperty on the client does the same
lookup with no nil check, so quality must always be a hero_quality key.

Gear: a hero has six slots, heroes.item0..item5 (0 = empty). `unit` is the
gear-free stats plus the item_info stats of every equipped item, and
`base_unit` stays gear-free, because the hero panel shows unit - base_unit as
the gear bonus (RoleAttrPanel.lua:164-165, GameAttrManager.lua:250-267).
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.config import Config
from server.modules import notify
from server.modules.notify import HERO_FIELDS
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.hero")

# ClientHeroUnit fields that exist as npc_info columns with the same name.
NPC_UNIT_FIELDS = (
    "max_hp", "power", "defence", "magic", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "block_base",
    "tenacity_base", "resistance_base", "spell_damage_add_scale",
    "treat_damage_add_scale", "hit_rate", "duck_rate", "crit_rate",
    "crit_damage_rate", "block_rate", "tenacity_rate", "hp_recovery",
    "rage_recovery", "initial_energy", "max_energy",
)

# The 13 columns hero_growth carries, added once per level above the first.
GROWTH_FIELDS = (
    "max_hp", "power", "magic", "defence", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "tenacity_base",
    "resistance_base", "block_base",
)

# BattleUnit:initByHeroData builds the hero active skills from this list and its
# normal attack from the prototype row (open question D in the plan).
SPELL_FIELDS = ("skill0", "skill1", "skill2", "skill3", "skill4")

# ClientFightUnit.type 3: an npc, refer is the npc_info entry itself
# (BattleUnit:initByServerFightHero, BattleUnit.lua:3947-3957). Type 1, the
# player hero, lives in server/modules/team.py where the hero units are built.
UNIT_TYPE_NPC = 3

GEAR_SLOTS = 6


def quality_row_for(cfg: Config, entry: int, quality: int) -> sqlite3.Row:
    """The hero_quality row the client will look up for this hero.

    hero_info.quality is 0 for every hero and hero_quality has no row for 0, so
    a stored quality that is not a key falls back to the lowest real one rather
    than naming a prototype npc_info has no row for, which kills the Lua VM.
    """
    rows = cfg.hero_qualities(entry)
    if not rows:
        raise KeyError(f"hero_quality has no row for hero {entry}")
    for row in rows:
        if int(row["quality"]) == int(quality):
            return row
    log.warning(
        "hero %d has no hero_quality row for quality %d, using the lowest",
        entry, quality,
    )
    return rows[0]


def prototype_for(cfg: Config, entry: int, quality: int) -> int:
    return int(quality_row_for(cfg, entry, quality)["prototype"])


def build_client_hero_unit(
    registry: Registry, cfg: Config, npc_row, growth_row, level: int,
    bonus: dict | None = None,
):
    msg = registry.message_class("ClientHeroUnit")()
    steps = max(0, int(level) - 1)
    for field in NPC_UNIT_FIELDS:
        value = float(npc_row[field] or 0)
        if steps and field in GROWTH_FIELDS:
            value += steps * float(growth_row[field] or 0)
        if bonus:
            value += bonus.get(field, 0.0)
        if field == "max_hp":
            msg.max_hp = int(value)
        else:
            setattr(msg, field, value)
    fill_required(msg)
    return msg


def gear_slots(row: sqlite3.Row) -> list[int]:
    return [int(row[f"item{i}"]) for i in range(GEAR_SLOTS)]


def gear_bonus(cfg: Config, row: sqlite3.Row) -> dict[str, float]:
    """The item_info stats of every equipped item, summed per NPC_UNIT_FIELDS
    name that is also an item_info column. item_info stores TEXT."""
    bonus: dict[str, float] = {}
    for item_id in gear_slots(row):
        if not item_id:
            continue
        item_row = cfg.item(item_id)
        if item_row is None:
            raise KeyError(f"item_info has no row for equipped item {item_id}")
        columns = item_row.keys()
        for field in NPC_UNIT_FIELDS:
            if field in columns:
                bonus[field] = bonus.get(field, 0.0) + float(item_row[field] or 0)
    return bonus


def build_client_hero(registry: Registry, cfg: Config, row: sqlite3.Row):
    entry = int(row["entry"])
    star = int(row["star"])
    level = int(row["level"])
    quality_row = quality_row_for(cfg, entry, int(row["quality"]))
    quality = int(quality_row["quality"])
    prototype = int(quality_row["prototype"])
    npc_row = cfg.npc(prototype)
    if npc_row is None:
        raise KeyError(
            f"npc_info has no row for prototype {prototype}"
            f" (hero {entry} quality {quality} level {level})"
        )
    # Only a hero above level 1 reads hero_growth, so a missing row is an error
    # exactly when its values would have been used.
    growth_row = cfg.hero_growth(entry, star)
    if level > 1 and growth_row is None:
        raise KeyError(
            f"hero_growth has no row for hero {entry} star {star}"
            f" (level {level})"
        )
    msg = registry.message_class("ClientHero")(
        id=int(row["id"]),
        entry=entry,
        prototype=prototype,
        quality=quality,
        star=star,
        xp=int(row["xp"]),
        level=level,
        ability=int(npc_row["ability"] or 0),
    )
    msg.unit.CopyFrom(
        build_client_hero_unit(
            registry, cfg, npc_row, growth_row, level, gear_bonus(cfg, row)
        )
    )
    msg.base_unit.CopyFrom(
        build_client_hero_unit(registry, cfg, npc_row, growth_row, level)
    )
    for key in SPELL_FIELDS:
        spell = int(npc_row[key] or 0)
        if spell:
            msg.spells.append(spell)
    msg.items.extend(gear_slots(row))
    msg.model = 0
    msg.awaken = 0
    msg.max_level = level
    fill_required(msg)
    return msg


def hero_notify_fields(registry: Registry, cfg: Config, row: sqlite3.Row) -> dict:
    """The ident-2 field set for one heroes row (ClientHero:updateByFields):
    the six slots, the unit stats that are HERO_FIELDS names (they go to
    ClientHero.unit), ability, level, xp, star, quality, prototype, max_level.
    The values are the ones build_client_hero sends, so the two never drift."""
    hero = build_client_hero(registry, cfg, row)
    fields: dict = {f"item{i}": int(v) for i, v in enumerate(hero.items)}
    for name in NPC_UNIT_FIELDS:
        if name in HERO_FIELDS:
            fields[name] = getattr(hero.unit, name)
    for name in ("ability", "level", "xp", "star", "quality", "prototype",
                 "max_level"):
        fields[name] = getattr(hero, name)
    return fields


def build_npc_fight_unit(
    registry: Registry, cfg: Config, npc_entry: int, position: int
):
    """One ClientFightUnit of type 3 for an npc_info row, at position.

    Type 3 is "an npc, refer is the npc_info entry": initByServerFightHero
    looks npc_info up by refer directly, with no hero_quality hop
    (BattleUnit.lua:3947-3957), and takes the normal attack from that row.
    An npc has no hero_growth table, its row is already the final one, so the
    stats block is built with no growth steps while the unit's own level field
    carries the row's level.
    """
    npc_entry = int(npc_entry)
    npc_row = cfg.npc(npc_entry)
    if npc_row is None:
        raise KeyError(f"npc_info {npc_entry} is missing")
    npc_level = int(npc_row["level"] or 1)
    unit = registry.message_class("ClientFightUnit")(
        type=UNIT_TYPE_NPC,
        refer=npc_entry,
        position=int(position),
        star=int(npc_row["star"] or 0),
        quality=int(npc_row["quality"] or 0),
        level=npc_level,
        max_level=npc_level,
        ability=int(npc_row["ability"] or 0),
        model=0,
    )
    for key in SPELL_FIELDS:
        spell = int(npc_row[key] or 0)
        if spell:
            unit.spells.append(spell)
    unit.unit.CopyFrom(build_client_hero_unit(registry, cfg, npc_row, None, 1))
    fill_required(unit)
    return unit


# --- Gear, crafting, quality-up (plan B2 T7) ----------------------------------
# Status codes are language.db ids.
STATUS_OK = 0
STATUS_INTERNAL_ERROR = 327681       # 系统内部错误 (a slot index outside 0..5)
STATUS_NOT_ENOUGH_GOLD = 327937      # 金币不足
STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_LEVEL_TOO_LOW = 327944        # 等级不够
STATUS_ITEM_CAP = 327970             # 物品达到上限
STATUS_SLOT_FULL = 328961            # 此装备栏位上已经有装备了
STATUS_TOP_QUALITY = 328966          # 英雄已经是最高品质
STATUS_SLOTS_NOT_FULL = 328967       # 英雄没有穿齐进阶所需装备
STATUS_NO_COMPOSITE = 328968         # 没有可以合成的装备

# The unit stats ClientHero:updateByFields copies into ClientHero.unit.
STAT_NAMES = tuple(n for n in NPC_UNIT_FIELDS if n in HERO_FIELDS)
COMPOSITE_PARTS = 4                  # item_composite item0..item3 / amount0..amount3


def composite_parts(row) -> list[tuple[int, int]]:
    """(material, amount) pairs of one item_composite row, empty pairs dropped."""
    parts = []
    for i in range(COMPOSITE_PARTS):
        material, amount = int(row[f"item{i}"] or 0), int(row[f"amount{i}"] or 0)
        if material and amount:
            parts.append((material, amount))
    return parts


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
        """Every hero field on the wire is a hero entry, not a heroes.id
        (RoleUICtr.lua:116,153,179,267; RoleListCtr.lua:214)."""
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (pid, int(entry)),
        ).fetchone()

    def _bag(pid: int) -> dict[int, int]:
        return {int(r["entry"]): int(r["amount"]) for r in db.items_of(conn, pid)}

    def _gold(pid: int) -> int:
        return int(conn.execute(
            "SELECT gold FROM players WHERE id = ?", (pid,)
        ).fetchone()["gold"])

    def _res(name: str, status: int | None = None, **fields):
        res = registry.message_class(name)(**fields)
        if status is not None:
            res.status = status
        fill_required(res)
        return res

    def _refused(name: str, status: int, why: str, **fields):
        log.info("%s refused %d: %s", name, status, why)
        return _res(name, status, **fields)

    def _hero_fields(hero_id: int, names) -> dict:
        row = conn.execute("SELECT * FROM heroes WHERE id = ?", (hero_id,)).fetchone()
        full = hero_notify_fields(registry, cfg, row)
        return {k: v for k, v in full.items() if k in names}

    def _take_all(pid: int, costs: dict[int, int]) -> list[tuple[int, int]]:
        """Remove already-checked amounts; return (entry, new amount) pairs."""
        return [
            (entry, db.take_item(conn, pid, entry, amount))
            for entry, amount in costs.items() if amount
        ]

    def equip(session: Session, req):
        name = "HeroEquipRes"
        pid = int(_player(session)["id"])
        index = int(req.index)
        row = _hero(pid, req.hero)
        if row is None:
            return _refused(name, STATUS_NO_HERO, f"hero {req.hero}", index=index)
        if not 0 <= index < GEAR_SLOTS:
            return _refused(name, STATUS_INTERNAL_ERROR, f"slot {index}", index=index)
        if int(row[f"item{index}"]):
            return _refused(name, STATUS_SLOT_FULL, f"slot {index} full", index=index)
        quality_row = quality_row_for(cfg, int(row["entry"]), int(row["quality"]))
        target = int(quality_row[f"item{index}"] or 0)
        if not target or _bag(pid).get(target, 0) < 1:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, f"item {target}", index=index)
        item_row = cfg.item(target)
        if item_row is None:
            raise KeyError(f"item_info has no row for gear item {target}")
        if int(item_row["required_level"] or 0) > int(row["level"]):
            return _refused(
                name, STATUS_LEVEL_TOO_LOW,
                f"item {target} needs level {item_row['required_level']}", index=index,
            )
        left = db.take_item(conn, pid, target, 1)
        slots = gear_slots(row)
        slots[index] = target
        db.set_hero_items(conn, int(row["id"]), slots)
        notify.items_changed(registry, session, [(target, left)])
        notify.hero_changed(
            registry, session, int(row["entry"]),
            _hero_fields(int(row["id"]), {f"item{index}", "ability", *STAT_NAMES}),
        )
        log.info("hero %d of player %d equips %d in slot %d", row["entry"], pid,
                 target, index)
        return _res(name, STATUS_OK, index=index)

    def equip_all(session: Session, req):
        """HeroEquipAllRes has no status (the header supplies 0), so this
        cannot refuse: when nothing applies it changes nothing and logs."""
        name = "HeroEquipAllRes"
        pid = int(_player(session)["id"])
        row = _hero(pid, req.hero)
        if row is None:
            log.warning("5_2163 for hero %s the player does not own", req.hero)
            return _res(name)
        quality_row = quality_row_for(cfg, int(row["entry"]), int(row["quality"]))
        bag, gold = _bag(pid), _gold(pid)
        costs: dict[int, int] = {}
        gold_cost = 0
        slots = gear_slots(row)
        changed: list[int] = []
        # Validate the whole plan against a simulated bag before any write.
        for index in range(GEAR_SLOTS):
            target = int(quality_row[f"item{index}"] or 0)
            if slots[index] or not target:
                continue
            item_row = cfg.item(target)
            if item_row is None or int(item_row["required_level"] or 0) > int(row["level"]):
                continue
            if bag.get(target, 0) - costs.get(target, 0) >= 1:
                costs[target] = costs.get(target, 0) + 1
            else:
                # One composite level only (plan O7: getOneEquipStatus == 2).
                comp = cfg.item_composite(target)
                if comp is None:
                    continue
                parts = composite_parts(comp)
                cost = int(comp["cost"] or 0)
                if not parts or gold - gold_cost < cost or any(
                    bag.get(m, 0) - costs.get(m, 0) < n for m, n in parts
                ):
                    continue
                for m, n in parts:
                    costs[m] = costs.get(m, 0) + n
                gold_cost += cost
            slots[index] = target
            changed.append(index)
        if not changed:
            log.warning("5_2163 for hero %d: nothing to equip or craft", row["entry"])
            return _res(name)
        pairs = _take_all(pid, costs)
        db.spend(conn, pid, gold=gold_cost)
        db.set_hero_items(conn, int(row["id"]), slots)
        notify.items_changed(registry, session, pairs)
        notify.player_changed(registry, session, {"gold": _gold(pid)})
        notify.hero_changed(
            registry, session, int(row["entry"]),
            _hero_fields(
                int(row["id"]),
                {*(f"item{i}" for i in changed), "ability", *STAT_NAMES},
            ),
        )
        log.info("hero %d of player %d equips all: slots %s, %d gold", row["entry"],
                 pid, changed, gold_cost)
        return _res(name)

    def _craft(session: Session, pid: int, target: int, comp, copies: int) -> None:
        costs = {m: n * copies for m, n in composite_parts(comp)}
        pairs = _take_all(pid, costs)
        db.spend(conn, pid, gold=int(comp["cost"] or 0) * copies)
        pairs.append((target, db.grant_item(conn, pid, target, copies)))
        notify.items_changed(registry, session, pairs)
        notify.player_changed(registry, session, {"gold": _gold(pid)})
        log.info("player %d crafts %dx %d", pid, copies, target)

    def composite(session: Session, req):
        name = "ItemCompositeRes"
        pid = int(_player(session)["id"])
        target = int(req.item)
        comp = cfg.item_composite(target)
        if comp is None or not composite_parts(comp):
            return _refused(name, STATUS_NO_COMPOSITE, f"item {target}")
        bag = _bag(pid)
        if any(bag.get(m, 0) < n for m, n in composite_parts(comp)):
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, f"materials of {target}")
        if _gold(pid) < int(comp["cost"] or 0):
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, f"{comp['cost']} gold")
        item_row = cfg.item(target)
        if item_row is None:
            raise KeyError(f"item_info has no row for composite {target}")
        if bag.get(target, 0) >= int(item_row["stackable"] or 0):
            return _refused(name, STATUS_ITEM_CAP, f"item {target} at its stack cap")
        _craft(session, pid, target, comp, 1)
        return _res(name, STATUS_OK)

    def composite_all(session: Session, req):
        """ItemCompositeAllRes has no status: craft min(materials, gold,
        stackable - owned) copies, or change nothing and log."""
        name = "ItemCompositeAllRes"
        pid = int(_player(session)["id"])
        target = int(req.entry)
        comp = cfg.item_composite(target)
        item_row = cfg.item(target)
        parts = composite_parts(comp) if comp is not None else []
        if not parts or item_row is None:
            log.warning("5_2725 for item %d, which has no composite", target)
            return _res(name)
        bag = _bag(pid)
        copies = min(bag.get(m, 0) // n for m, n in parts)
        cost = int(comp["cost"] or 0)
        if cost:
            copies = min(copies, _gold(pid) // cost)
        copies = min(copies, int(item_row["stackable"] or 0) - bag.get(target, 0))
        if copies <= 0:
            log.warning("5_2725 for item %d: nothing can be crafted", target)
            return _res(name)
        _craft(session, pid, target, comp, copies)
        return _res(name)

    def quality_up(session: Session, req):
        """The client clears its own items and sets quality = next of the OLD
        row on the Res (RoleUICtr.lua:397-424), then counts exactly one
        INFO_CHANGE_NTF_HERO for the success panel (settled point 11)."""
        name = "HeroQualityUpRes"
        pid = int(_player(session)["id"])
        row = _hero(pid, req.hero)
        if row is None:
            return _refused(name, STATUS_NO_HERO, f"hero {req.hero}")
        if not all(gear_slots(row)):
            return _refused(name, STATUS_SLOTS_NOT_FULL, f"hero {row['entry']}")
        old = quality_row_for(cfg, int(row["entry"]), int(row["quality"]))
        nxt = int(old["next"] or 0)
        if not nxt:
            return _refused(name, STATUS_TOP_QUALITY, f"hero {row['entry']}")
        conn.execute(
            "UPDATE heroes SET quality = ? WHERE id = ?", (nxt, int(row["id"]))
        )
        conn.commit()
        db.set_hero_items(conn, int(row["id"]), [0] * GEAR_SLOTS)
        new_row = conn.execute(
            "SELECT * FROM heroes WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        built = build_client_hero(registry, cfg, new_row)
        fields = _hero_fields(
            int(row["id"]),
            {"quality", "prototype", "ability", *STAT_NAMES,
             *(f"item{i}" for i in range(GEAR_SLOTS))},
        )
        # The new prototype can unlock a skill (100000 -> 100010 adds
        # skill1); ClientHero:updateByFields copies spellN into spells[N+1].
        for i, spell in enumerate(built.spells):
            fields[f"spell{i}"] = int(spell)
        notify.hero_changed(registry, session, int(row["entry"]), fields)
        notify.hero_base_changed(
            registry, session, int(row["entry"]),
            {n: getattr(built.base_unit, n) for n in notify.BASE_UNIT},
        )
        log.info("hero %d of player %d raised to quality %d", row["entry"], pid, nxt)
        return _res(name, STATUS_OK)

    return {
        (5, 2105): equip,
        (5, 2163): equip_all,
        (5, 2111): composite,
        (5, 2725): composite_all,
        (5, 2109): quality_up,
    }
