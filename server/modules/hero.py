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

from server.config import Config
from server.modules.notify import HERO_FIELDS
from server.net.registry import Registry
from server.net.server import fill_required

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
