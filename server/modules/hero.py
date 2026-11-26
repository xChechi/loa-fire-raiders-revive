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
from server.modules import events, notify
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


RUNE_SLOTS = 5                       # hero_rune_info rune0..rune4


def runes_of(conn: sqlite3.Connection, row: sqlite3.Row) -> list[tuple[int, int]]:
    """(level, rune_val) of rune idx 0..4 for one heroes row; a missing runes
    row is a level-0 rune with no rune_val."""
    stored = {
        int(r["idx"]): (int(r["level"]), int(r["rune_val"]))
        for r in conn.execute(
            "SELECT idx, level, rune_val FROM runes WHERE player_id = ? AND hero = ?",
            (int(row["player_id"]), int(row["entry"])),
        )
    }
    return [stored.get(i, (0, 0)) for i in range(RUNE_SLOTS)]


def rune_bonus(
    cfg: Config, entry: int, runes: list[tuple[int, int]], bonus: dict[str, float]
) -> dict[str, float]:
    """Add the rune_level_up(rune, level) stats of every levelled rune to
    `bonus`, as gear_bonus does for items. A row holds the rune's total at that
    level (RuneDataHelp.lua:44-50,285-287), so only the current row counts."""
    slots = cfg.hero_runes(entry)
    for idx, (level, _val) in enumerate(runes):
        if not level:
            continue
        info = cfg.rune(slots[idx]) if slots else None
        if info is None:
            raise KeyError(f"hero {entry} has no rune_info for rune idx {idx}")
        level_row = cfg.rune_level(int(info["rune"]), level)
        if level_row is None:
            raise KeyError(f"rune_level_up has no row for {info['rune']} level {level}")
        columns = level_row.keys()
        for field in NPC_UNIT_FIELDS:
            if field in columns:
                bonus[field] = bonus.get(field, 0.0) + float(level_row[field] or 0)
    return bonus


def wave3_bonus(
    conn: sqlite3.Connection, cfg: Config, row: sqlite3.Row, bonus: dict[str, float]
) -> dict[str, float]:
    """Add the bonus() of hero develop, blessing, signets, breakthrough,
    rebirth and artifacts to `bonus`, as rune_bonus does for runes. The
    artifact numbers are the player's equipped set, the same for every hero
    (artifact.bonus). Imported here: those modules import this one."""
    from server.modules import artifact, bless, breakthrough, herodevelop, rebirth, signet

    for module in (herodevelop, bless, signet, breakthrough, rebirth, artifact):
        for field, value in module.bonus(conn, cfg, row).items():
            bonus[field] = bonus.get(field, 0.0) + value
    return bonus


LEVELLED_SPELLS = 4                  # skill0..skill3; skill4 (awaken) is W3


def spell_at_level(cfg: Config, base: int, level: int) -> int:
    """The spell_info id `level - 1` steps along `next` from a level-1 base
    (O-W2-6). Raises when the chain ends early."""
    spell = int(base)
    for _ in range(int(level) - 1):
        row = cfg.spell(spell)
        nxt = int(row["next"] or 0) if row is not None else 0
        if not nxt:
            raise KeyError(
                f"spell_info chain of {base} ends at {spell} before level {level}"
            )
        spell = nxt
    return spell


def build_client_hero(
    registry: Registry, cfg: Config, row: sqlite3.Row,
    conn: sqlite3.Connection | None = None,
):
    """Five level-0 runes: right for a hero born this moment; any other caller
    that has the connection should use build_client_hero_with_runes."""
    return build_client_hero_with_runes(
        registry, cfg, row, [(0, 0)] * RUNE_SLOTS, conn=conn
    )


def build_client_hero_with_runes(
    registry: Registry, cfg: Config, row: sqlite3.Row, runes: list[tuple[int, int]],
    conn: sqlite3.Connection | None = None,
):
    """`runes` is runes_of(conn, row): ClientHero.runes and their unit stats.
    With `conn`, unit also carries the Wave 3 bonuses (wave3_bonus); every
    server caller passes it, so a notify never drops them."""
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
    bonus = rune_bonus(cfg, entry, runes, gear_bonus(cfg, row))
    if conn is not None:
        wave3_bonus(conn, cfg, row, bonus)
    msg.unit.CopyFrom(
        build_client_hero_unit(registry, cfg, npc_row, growth_row, level, bonus)
    )
    msg.base_unit.CopyFrom(
        build_client_hero_unit(registry, cfg, npc_row, growth_row, level)
    )
    for i, key in enumerate(SPELL_FIELDS):
        spell = int(npc_row[key] or 0)
        if spell and i < LEVELLED_SPELLS:
            spell = spell_at_level(cfg, spell, int(row[f"spell{i}_lv"]))
        if spell:
            msg.spells.append(spell)
    msg.items.extend(gear_slots(row))
    for idx, (rune_level, rune_val) in enumerate(runes):
        msg.runes.add(idx=idx, level=rune_level, rune_val=rune_val)
    msg.model = 0
    msg.awaken = 0
    msg.max_level = level
    # Wave 3 A5: B6 breakthrough and B7 rebirth write these; their stats
    # reach `unit` in C1.
    msg.breakthrough_level = int(row["breakthrough_level"])
    msg.breakthrough_score = int(row["breakthrough_score"])
    msg.transmigrate_level = int(row["transmigrate_level"])
    fill_required(msg)
    return msg


def hero_notify_fields(registry: Registry, cfg: Config, row: sqlite3.Row) -> dict:
    """hero_notify_fields_with_runes with five level-0 runes."""
    return hero_notify_fields_with_runes(registry, cfg, row, [(0, 0)] * RUNE_SLOTS)


def hero_notify_fields_with_runes(
    registry: Registry, cfg: Config, row: sqlite3.Row, runes: list[tuple[int, int]],
    conn: sqlite3.Connection | None = None,
) -> dict:
    """The ident-2 field set for one heroes row (ClientHero:updateByFields):
    the six slots, the unit stats that are HERO_FIELDS names (they go to
    ClientHero.unit), ability, level, xp, star, quality, prototype, max_level.
    The values are the ones build_client_hero sends, so the two never drift."""
    hero = build_client_hero_with_runes(registry, cfg, row, runes, conn=conn)
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
STATUS_HERO_OWNED = 327940           # 英雄已经存在
STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_LEVEL_TOO_LOW = 327944        # 等级不够
STATUS_FUNCTION_LOCKED = 327957      # 未满足此玩法的等级
STATUS_ITEM_CAP = 327970             # 物品达到上限
STATUS_SKILL_TOP = 328962            # 已经是当前最高等级
STATUS_SKILL_LOCKED = 328963         # 此技能未激活
STATUS_SLOT_FULL = 328961            # 此装备栏位上已经有装备了
STATUS_TOP_STAR = 328965             # 此英雄已经是最高星级
STATUS_TOP_QUALITY = 328966          # 英雄已经是最高品质
STATUS_SLOTS_NOT_FULL = 328967       # 英雄没有穿齐进阶所需装备
STATUS_NO_COMPOSITE = 328968         # 没有可以合成的装备

SKILL_FUNCTION = 10050               # function 英雄技能 (RoleUI.lua:353)

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
        full = hero_notify_fields_with_runes(registry, cfg, row, runes_of(conn, row), conn=conn)
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
        built = build_client_hero_with_runes(
            registry, cfg, new_row, runes_of(conn, new_row), conn=conn
        )
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

    def star_up(session: Session, req):
        """Stones are hero_info.item, or break_item from star 5 on; the count
        is hero_growth(hero, star+1).star_up_cost and the gold
        HERO_STAR_UP_COST_{star+1} (ClientHero.lua:595-624, RoleUICtr.lua:91).
        One ident-2 notify follows the Res (settled point 11)."""
        name = "HeroStarUpRes"
        player = _player(session)
        pid = int(player["id"])
        row = _hero(pid, req.hero)
        if row is None:
            return _refused(name, STATUS_NO_HERO, f"hero {req.hero}")
        entry, star = int(row["entry"]), int(row["star"]) + 1
        growth = cfg.hero_growth(entry, star)
        if growth is None:
            return _refused(name, STATUS_TOP_STAR, f"hero {entry} has no star {star}")
        info = cfg.hero(entry)
        if info is None:
            raise KeyError(f"hero_info has no row for hero {entry}")
        stone = int(info["break_item"] if star - 1 >= 5 else info["item"])
        stones = int(growth["star_up_cost"] or 0)
        gold = cfg.variable_int(f"HERO_STAR_UP_COST_{star}", 0)
        if _bag(pid).get(stone, 0) < stones:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, f"{stones}x {stone}")
        if int(player["gold"]) < gold:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, f"{gold} gold")
        pairs = _take_all(pid, {stone: stones})
        db.spend(conn, pid, gold=gold)
        conn.execute("UPDATE heroes SET star = ? WHERE id = ?", (star, int(row["id"])))
        conn.commit()
        new_row = conn.execute(
            "SELECT * FROM heroes WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        built = build_client_hero_with_runes(
            registry, cfg, new_row, runes_of(conn, new_row), conn=conn
        )
        notify.items_changed(registry, session, pairs)
        notify.player_changed(registry, session, {"gold": _gold(pid)})
        notify.hero_changed(
            registry, session, entry,
            _hero_fields(int(row["id"]), {"star", "ability", *STAT_NAMES}),
        )
        notify.hero_base_changed(
            registry, session, entry,
            {n: getattr(built.base_unit, n) for n in notify.BASE_UNIT},
        )
        log.info("hero %d of player %d raised to star %d", entry, pid, star)
        return _res(name, STATUS_OK)

    def call(session: Session, req):
        """Summon from soul stones: sum of star_up_cost for star <= hero_info.
        star in hero_info.item, and sum of HERO_STAR_UP_COST_1..star in gold
        (RoleListCtr.lua:88-113,194-214)."""
        name = "HeroCallRes"
        player = _player(session)
        pid = int(player["id"])
        entry = int(req.hero)
        if _hero(pid, entry) is not None:
            return _refused(name, STATUS_HERO_OWNED, f"hero {entry}")
        info = cfg.hero(entry)
        if info is None or not cfg.hero_qualities(entry):
            return _refused(name, STATUS_NO_HERO, f"hero {entry} not configured")
        top = int(info["star"] or 1)
        stone = int(info["item"])
        stones = 0
        for star in range(1, top + 1):
            growth = cfg.hero_growth(entry, star)
            stones += int(growth["star_up_cost"] or 0) if growth else 0
        gold = sum(
            cfg.variable_int(f"HERO_STAR_UP_COST_{star}", 0) for star in range(1, top + 1)
        )
        if _bag(pid).get(stone, 0) < stones:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, f"{stones}x {stone}")
        if int(player["gold"]) < gold:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, f"{gold} gold")
        pairs = _take_all(pid, {stone: stones})
        db.spend(conn, pid, gold=gold)
        quality = int(cfg.hero_qualities(entry)[0]["quality"])
        hero_id = db.grant_hero(
            conn, pid, entry, quality, star=top, level=int(info["init_level"] or 1)
        )
        new_row = conn.execute("SELECT * FROM heroes WHERE id = ?", (hero_id,)).fetchone()
        notify.hero_added(registry, session, build_client_hero(registry, cfg, new_row, conn=conn))
        notify.items_changed(registry, session, pairs)
        notify.player_changed(registry, session, {"gold": _gold(pid)})
        events.refresh(conn, cfg, registry, session, pid)
        log.info("hero %d called by player %d for %dx %d and %d gold", entry, pid,
                 stones, stone, gold)
        return _res(name, STATUS_OK)

    def skill_up(session: Session, req):
        """{hero, index} raises one level (RoleUICtr.lua:220-223); with
        spell_entry it raises every level up to that id (RoleUICtr.lua:225-228,
        RoleSkillRender.lua:265-302). Each level costs the NEXT row's
        upgrade_cost and may not pass spell_level_up(hero level).spell{index}.
        On spell_entry 0 the client keeps the old id until the ident-2
        spell{index} arrives (RoleUICtr.lua:427-442, RoleSkillPanel.lua:116-130)."""
        name = "HeroSkillUpRes"
        player = _player(session)
        pid = int(player["id"])
        index = int(req.index)
        target = int(req.spell_entry)
        echo = {"index": index, "spell_entry": target}
        unlock = cfg.function_unlock(SKILL_FUNCTION)
        if int(player["level"]) < unlock:
            return _refused(
                name, STATUS_FUNCTION_LOCKED,
                f"player level {player['level']} < {unlock}", **echo,
            )
        row = _hero(pid, req.hero)
        if row is None:
            return _refused(name, STATUS_NO_HERO, f"hero {req.hero}", **echo)
        npc_row = cfg.npc(prototype_for(cfg, int(row["entry"]), int(row["quality"])))
        base = int(npc_row[f"skill{index}"] or 0) if 0 <= index < LEVELLED_SPELLS else 0
        if not base:
            return _refused(
                name, STATUS_SKILL_LOCKED, f"hero {row['entry']} skill {index}", **echo
            )
        level = int(row[f"spell{index}_lv"])
        spell = spell_at_level(cfg, base, level)
        if target:
            # The target must lie ahead on this skill's own chain.
            ahead, walk = set(), cfg.spell(spell)
            while walk is not None and int(walk["next"] or 0) and len(ahead) < 1000:
                ahead.add(int(walk["next"]))
                walk = cfg.spell(int(walk["next"]))
            if target not in ahead:
                return _refused(
                    name, STATUS_INTERNAL_ERROR,
                    f"spell {target} is not ahead of {spell}", **echo,
                )
        caps = cfg.spell_level_up(int(row["level"]))
        if caps is None:
            raise KeyError(f"spell_level_up has no row for level {row['level']}")
        cap = int(caps[f"spell{index}"] or 0)
        cost = 0
        while True:
            nxt = int(cfg.spell(spell)["next"] or 0)
            nxt_row = cfg.spell(nxt) if nxt else None
            if nxt_row is None or int(nxt_row["level"]) > cap:
                return _refused(
                    name, STATUS_SKILL_TOP,
                    f"hero {row['entry']} skill {index} at level {level}, cap {cap}",
                    **echo,
                )
            cost += int(nxt_row["upgrade_cost"] or 0)
            spell, level = nxt, level + 1
            if not target or spell == target:
                break
        if int(player["gold"]) < cost:
            return _refused(name, STATUS_NOT_ENOUGH_GOLD, f"{cost} gold", **echo)
        db.spend(conn, pid, gold=cost)
        # The column name is a literal: index was checked to be 0..3 above.
        conn.execute(
            f"UPDATE heroes SET spell{index}_lv = ? WHERE id = ?", (level, int(row["id"]))
        )
        conn.commit()
        notify.player_changed(registry, session, {"gold": _gold(pid)})
        notify.hero_changed(registry, session, int(row["entry"]), {f"spell{index}": spell})
        events.bump(conn, cfg, registry, session, pid, events.KIND_HERO_SKILL)
        log.info("hero %d of player %d skill %d to level %d (%d) for %d gold",
                 row["entry"], pid, index, level, spell, cost)
        return _res(name, STATUS_OK, **echo)

    return {
        (5, 2103): skill_up,
        (5, 2105): equip,
        (5, 2163): equip_all,
        (5, 2111): composite,
        (5, 2725): composite_all,
        (5, 2109): quality_up,
        (5, 2107): star_up,
        (5, 2127): call,
    }
