"""Server-to-client pushes: 5_2008, 5_2036, 5_2012.

5_2008 ClientNotification idents (RoleData.lua:21-38): 1 player, 2 hero,
3 angel, 4 item, 6 task, 7 mail, 9 hero base unit. Idents 1, 2, 3 and 9 share
the byte-indexed flag mask of flags_for, each over its own field order.

These are notify ids with no paired Req, so they are queued on the session and
written by the dispatcher through Session.send.
"""

from __future__ import annotations

import logging

from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.notify")

IDENT_PLAYER = 1
IDENT_HERO = 2
IDENT_ANGEL = 3
IDENT_ITEM = 4
IDENT_TASK = 6
IDENT_MAIL = 7
IDENT_BASE = 9

# ClientPlayer.PLAYER_FIELD_DIC, verbatim and in order. The 1-based index into
# this tuple is the bit RoleData:onPlayerInfoChange tests.
PLAYER_FIELDS = (
    "vip", "vip_expires", "paycount", "xp", "level", "energy", "max_energy",
    "gold", "diamond", "login_month", "login_flags", "award_flags",
    "last_level", "last_elite", "avatar", "angel_money", "arena_point",
    "vvip1", "battlefield_point", "gold_trails_cooldown", "login_award",
    "vip_xp", "paid_user", "guild_id", "nobility_level", "nobility_exp",
    "guild_money", "toparena_money", "artifact_smelt", "gve_money",
    "discount_money", "cross_money", "cross_rise_money", "crusade_point",
    "honor", "signet_essence", "signet_fight_cnt", "card_master_gacha",
    "card_master_points", "magic_money", "recharge_score", "devil_money",
    "star_soul_money", "syb_money", "gemstone_money", "gemstone_prize_money",
    "realname_check", "pet_money",
)

# ClientHero.HERO_FIELDS, ClientHero.lua:41-103, verbatim and in order (the
# two commented-out rune_develop_* lines are not in the list). RoleData:
# onHeroInfoChange (RoleData.lua:487-525) walks it for ident 2.
HERO_FIELDS = (
    "prototype", "quality", "star", "xp", "level", "points",
    "item0", "item1", "item2", "item3", "item4", "item5",
    "spell0", "spell1", "spell2", "spell3",
    "reserved0", "reserved1", "reserved2", "reserved3",
    "max_hp", "power", "defence", "magic", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "block_base",
    "tenacity_base", "spell_damage_add_scale", "treat_damage_add_scale",
    "hit_rate", "duck_rate", "crit_rate", "crit_damage_rate", "block_rate",
    "tenacity_rate", "hp_recovery", "rage_recovery",
    "ability", "spell4", "model", "awaken",
    "signet0", "signet1", "signet2", "signet3", "singet_set",
    "transmigrate_level", "signet_ability", "resistance_base", "max_level",
    "breakthrough_level", "breakthrough_score",
    "god_soul_ability", "upgrade_soul_idx", "upgrade_soul_level",
)

# ClientHero.BASE_UNIT, ClientHero.lua:106-130, verbatim and in order. RoleData:
# onHeroBaseInfoChange (RoleData.lua:591-627) walks it for ident 9.
BASE_UNIT = (
    "max_hp", "power", "defence", "magic", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "block_base",
    "tenacity_base", "spell_damage_add_scale", "treat_damage_add_scale",
    "hit_rate", "duck_rate", "crit_rate", "crit_damage_rate", "block_rate",
    "tenacity_rate", "hp_recovery", "rage_recovery", "resistance_base",
)

# AngelManager.ANGEL_FIELDS, AngelManager.lua:29-44, verbatim and in order.
# RoleData:onAngelInfoChange (RoleData.lua:633-695) walks it for ident 3.
ANGEL_FIELDS = (
    "entry", "level", "star", "exp",
    "aura0", "aura1", "aura2", "aura3", "aura4", "aura5",
    "ability", "spell0", "spell1", "advance_level",
)

# Open question A of Plan B1, NOT yet settled on the emulator (task 9 step 6,
# deferred to task 17): flags is a fixed64, but Lua reads it with string.byte,
# so byte floor((i-1)/8)+1 carries bit 2^((i-1) mod 8) for the 1-based field
# index i. "little" means the bytes reach Lua in the order protobuf writes
# them, which makes the mask plain 1 << (i-1). If the emulator logs the wrong
# field name for a single-field notify, the order is reversed: set this to
# "big" and the mask below is byte-swapped, no other change.
FLAGS_BYTE_ORDER = "little"


def flags_for(names, order=PLAYER_FIELDS) -> int:
    mask = 0
    for name in names:
        mask |= 1 << order.index(name)
    if FLAGS_BYTE_ORDER == "big":
        mask = int.from_bytes(mask.to_bytes(8, "little"), "big")
    return mask


def player_changed(registry: Registry, session: Session, fields: dict) -> None:
    """One notification per change set. data is ordered by field index, and
    carries only the fields whose bit is set."""
    ordered = [n for n in PLAYER_FIELDS if n in fields]
    unknown = set(fields) - set(PLAYER_FIELDS)
    if unknown:
        log.warning("not a ClientPlayer notify field, dropped: %s", sorted(unknown))
    msg = registry.message_class("ClientNotification")(
        ident=IDENT_PLAYER, flags=flags_for(ordered)
    )
    for name in ordered:
        msg.data.append(float(fields[name]))
    fill_required(msg)
    session.queue(5, 2008, msg)


def _fields_changed(
    registry: Registry, session: Session, ident: int, order, refer: int,
    fields: dict,
) -> None:
    """Idents 2, 3 and 9: the same walk as player_changed over another field
    order, with `refer` naming the hero or angel entry."""
    ordered = [n for n in order if n in fields]
    unknown = set(fields) - set(order)
    if unknown:
        log.warning(
            "not an ident-%d notify field, dropped: %s", ident, sorted(unknown)
        )
    msg = registry.message_class("ClientNotification")(
        ident=ident, flags=flags_for(ordered, order), refer=int(refer)
    )
    for name in ordered:
        msg.data.append(float(fields[name]))
    fill_required(msg)
    session.queue(5, 2008, msg)


def hero_changed(registry: Registry, session: Session, entry: int, fields: dict) -> None:
    """Ident 2; `refer` is the hero entry (RoleData:getHeroByEntry)."""
    _fields_changed(registry, session, IDENT_HERO, HERO_FIELDS, entry, fields)


def hero_base_changed(
    registry: Registry, session: Session, entry: int, fields: dict
) -> None:
    """Ident 9; `refer` is the hero entry, fields are BASE_UNIT names."""
    _fields_changed(registry, session, IDENT_BASE, BASE_UNIT, entry, fields)


def angel_changed(
    registry: Registry, session: Session, angel_entry: int, fields: dict
) -> None:
    """Ident 3; `refer` is the angel entry (AngelManager:getAngelByID)."""
    _fields_changed(registry, session, IDENT_ANGEL, ANGEL_FIELDS, angel_entry, fields)


def task_changed(
    registry: Registry, session: Session, entry: int, progress: int, done: bool
) -> None:
    """Ident 6, RoleData:onTaskInfoChange (RoleData.lua:741-786): bit 2 is a
    progress change, bit 3 is done, data[1] is the progress. The done bit is
    only read when the progress bit is clear, so done sends 0b100 alone."""
    msg = registry.message_class("ClientNotification")(
        ident=IDENT_TASK, flags=0b100 if done else 0b10, refer=int(entry)
    )
    msg.data.append(float(progress))
    fill_required(msg)
    session.queue(5, 2008, msg)


def mail_arrived(registry: Registry, session: Session) -> None:
    """Ident 7, RoleData:onEmailInfoChange (RoleData.lua:787-803): bit 1 set
    means new mail."""
    msg = registry.message_class("ClientNotification")(ident=IDENT_MAIL, flags=0b1)
    fill_required(msg)
    session.queue(5, 2008, msg)


def items_changed(registry: Registry, session: Session, pairs) -> None:
    """RoleData:onItemInfoChange reads data as flat (entry, new amount) pairs
    and calls updateItemNum, which sets the absolute amount."""
    if not pairs:
        return
    msg = registry.message_class("ClientNotification")(ident=IDENT_ITEM, flags=0)
    for entry, amount in pairs:
        msg.data.append(float(entry))
        msg.data.append(float(amount))
    fill_required(msg)
    session.queue(5, 2008, msg)


def level_up(registry: Registry, session: Session, old, new) -> None:
    old_level, old_energy, old_max = old
    new_level, new_energy, new_max = new
    msg = registry.message_class("LevelUpNotify")(
        oldLevel=int(old_level), newLevel=int(new_level),
        oldEnergy=int(old_energy), newEnergy=int(new_energy),
        oldMaxEnergy=int(old_max), newMaxEnergy=int(new_max),
    )
    fill_required(msg)
    session.queue(5, 2036, msg)


def hero_added(registry: Registry, session: Session, client_hero) -> None:
    msg = registry.message_class("AddHeroNotify")()
    msg.hero.CopyFrom(client_hero)
    fill_required(msg)
    session.queue(5, 2012, msg)
