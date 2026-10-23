"""Server-to-client pushes: 5_2008, 5_2036, 5_2012.

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
IDENT_ITEM = 4

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

# Open question A of Plan B1, NOT yet settled on the emulator (task 9 step 6,
# deferred to task 17): flags is a fixed64, but Lua reads it with string.byte,
# so byte floor((i-1)/8)+1 carries bit 2^((i-1) mod 8) for the 1-based field
# index i. "little" means the bytes reach Lua in the order protobuf writes
# them, which makes the mask plain 1 << (i-1). If the emulator logs the wrong
# field name for a single-field notify, the order is reversed: set this to
# "big" and the mask below is byte-swapped, no other change.
FLAGS_BYTE_ORDER = "little"


def flags_for(names) -> int:
    mask = 0
    for name in names:
        mask |= 1 << PLAYER_FIELDS.index(name)
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
