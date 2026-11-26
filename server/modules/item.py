"""Inventory: ClientStock shapes and prize granting.

Categories are the client's own constants (ClientPlayer.lua:146-186) and are the
same numbers as drop_base.drop_type: 1 gold, 2 energy, 9 diamond, 11 player xp,
12 hero xp, 13 angel xp, 20 item, 30 hero, 40 angel, 51 arena coin, 52
goddess-trial coin; Wave 3 adds 21 signet, 61 artifact smelt essence, 70
gve_money (blessing decompose), 75 signet essence and 86 pet money. The
fourteen this server can actually apply are below; any other one raises, because a reward that silently
shrinks is worse than a crash in a log Stefan reads.

There is no ClientItem message in allProtos.pb: an owned item is a ClientStock
(one row per item entry, `amount` absolute), which is what QueryMyselfRes
carries in its repeated `inventory` field.

A stock never passes item_info.stackable; what does not fit goes into one
mail 99999 物品超限提醒 per call. A hero the player already owns arrives as
HERO_DISCOUNT_STAR_{hero_info.star} of hero_info.item, the conversion the
client itself shows (MMAwardDropItem.lua:70-97). An owned angel arrives as
ANGEL_DISCOUNT_STAR_{star} of activation_item, both read off the angel's first
angel_info row (MMAwardDropItem.lua:105-129), which is its star-1 row.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import mail, notify
from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.item")

CATEGORY_GOLD = 1
CATEGORY_ENERGY = 2
CATEGORY_DIAMOND = 9
CATEGORY_PLAYER_XP = 11
CATEGORY_ITEM = 20
CATEGORY_HERO = 30
CATEGORY_ANGEL = 40
CATEGORY_ARENA_COIN = 51
CATEGORY_ANGEL_TRY_COIN = 52
CATEGORY_SIGNET = 21           # COST_MARK_TYPE, refer = signet_info.entry
CATEGORY_SIGNET_ESSENCE = 75   # COST_SIGNET_TYPE 印记精华
CATEGORY_PET_MONEY = 86        # PRIZE_PET_MONEY 神兽之魂 (ClientPlayer.lua:149,165,177)
CATEGORY_GVE_MONEY = 70        # COST_GVE_TYPE (ClientPlayer.lua:157,666-667), blessing decompose
CATEGORY_ARTIFACT_SMELT = 61   # ARTIFACT_COM_TYPE 神器精华 (ClientPlayer.lua:156,188,664-665)

# The players column (and ClientPlayer / notify field) each coin lands on,
# ClientPlayer.lua:150-151,652-655.
COIN_FIELDS = {
    CATEGORY_ARENA_COIN: "arena_point", CATEGORY_ANGEL_TRY_COIN: "angel_money",
    CATEGORY_SIGNET_ESSENCE: "signet_essence", CATEGORY_PET_MONEY: "pet_money",
    CATEGORY_GVE_MONEY: "gve_money", CATEGORY_ARTIFACT_SMELT: "artifact_smelt",
}

STATUS_SIGNET_BAG_FULL = 338114  # language.db 印记数量达到上限，请先去清理


class SignetBagFull(ValueError):
    """A category-21 grant would pass SIGNET_MAX_NUMBER; nothing was written.
    The caller answers `status` (and B5 pushes 5_2744 SignetBagFullNotify)."""

    status = STATUS_SIGNET_BAG_FULL

# mail_info 99999 物品超限提醒; its body has one "|" for the item names.
OVERFLOW_MAIL = 99999

KNOWN_CATEGORIES = frozenset({
    CATEGORY_GOLD, CATEGORY_ENERGY, CATEGORY_DIAMOND, CATEGORY_PLAYER_XP,
    CATEGORY_ITEM, CATEGORY_HERO, CATEGORY_ANGEL, CATEGORY_ARENA_COIN,
    CATEGORY_ANGEL_TRY_COIN, CATEGORY_SIGNET, CATEGORY_SIGNET_ESSENCE,
    CATEGORY_PET_MONEY, CATEGORY_GVE_MONEY, CATEGORY_ARTIFACT_SMELT,
})


def build_client_stock(registry: Registry, row: sqlite3.Row, index: int):
    msg = registry.message_class("ClientStock")(
        id=int(row["id"]),
        entry=int(row["entry"]),
        amount=int(row["amount"]),
        state=0,
        index=int(index),
    )
    fill_required(msg)
    return msg


def build_inventory(
    registry: Registry, conn: sqlite3.Connection, player_id: int
) -> list:
    return [
        build_client_stock(registry, row, index)
        for index, row in enumerate(db.items_of(conn, player_id))
    ]


def _checked(cfg: Config, prizes) -> list[tuple[int, int, int]]:
    """Every triple, cast to int, with the whole list vetted before a single
    write happens: that is what makes one grant_prizes call atomic even though
    the db helpers commit per write."""
    out: list[tuple[int, int, int]] = []
    for raw_category, raw_refer, raw_amount in prizes:
        category, refer, amount = int(raw_category), int(raw_refer), int(raw_amount)
        if category not in KNOWN_CATEGORIES:
            raise ValueError(
                f"prize category {category} is not implemented in Plan B1"
                f" (refer {refer}, amount {amount})"
            )
        if category == CATEGORY_ITEM and cfg.item(refer) is None:
            raise KeyError(f"item_info has no row for item {refer}")
        if category == CATEGORY_SIGNET and cfg.signet(refer) is None:
            raise KeyError(f"signet_info has no row for signet {refer}")
        if category == CATEGORY_HERO and not cfg.hero_qualities(refer):
            raise KeyError(f"hero_quality has no row for hero {refer}")
        if category == CATEGORY_HERO:
            _hero_stones(cfg, refer)
        if category == CATEGORY_ANGEL:
            _angel_stones(cfg, refer)
        out.append((category, refer, amount))
    return out


def _angel_stones(cfg: Config, angel: int) -> tuple[int, int]:
    """(activation item, count) a duplicate of this angel turns into. Only an
    angel with a summonable star-1 row can be granted at all."""
    info = cfg.angel_by_star(angel, 1)
    if info is None:
        raise ValueError(f"angel {angel} has no summonable star-1 row in angel_info")
    key = f"ANGEL_DISCOUNT_STAR_{int(info['star'])}"
    if cfg.variable(key) in (None, ""):
        raise KeyError(f"variables.{key} is missing (angel {angel})")
    stone = int(info["activation_item"])
    if cfg.item(stone) is None:
        raise KeyError(f"item_info has no row for item {stone} (angel {angel})")
    return stone, cfg.variable_int(key, 0)


def _hero_stones(cfg: Config, hero: int) -> tuple[int, int]:
    """(soul stone item, count) a duplicate of this hero turns into."""
    info = cfg.hero(hero)
    if info is None:
        raise KeyError(f"hero_info has no row for hero {hero}")
    key = f"HERO_DISCOUNT_STAR_{int(info['star'])}"
    if cfg.variable(key) in (None, ""):
        raise KeyError(f"variables.{key} is missing (hero {hero})")
    stone = int(info["item"])
    if cfg.item(stone) is None:
        raise KeyError(f"item_info has no row for item {stone} (hero {hero})")
    return stone, cfg.variable_int(key, 0)


def grant_prizes(
    conn: sqlite3.Connection, cfg: Config, player_id: int, prizes,
    energy_over_cap: bool = False,
) -> dict:
    """Apply (category, refer, amount) triples and report what changed.

    Energy stops at the level's max_energy unless energy_over_cap (the lunch /
    dinner daily prize, see events).

    The return value is what both the persistence and the client notification
    need: the new absolute gold, diamond and energy, the new absolute amount of
    every item touched, the row id of every hero created, and the id of the
    overflow mail if one was sent (the caller queues notify.mail_arrived).
    `xp` is db.add_player_xp's before/after/levelled over the whole call, or
    None without player xp; `angels` lists the angel entries granted;
    `converted` the indices into `prizes` of the hero prizes that arrived as
    soul stones (mark_converted flags them for the client); `coins` the new
    absolute arena_point / angel_money / signet_essence / pet_money / gve_money / artifact_smelt, only for
    the ones a prize touched; `signets` the row id of every signet created.
    A signet grant that would pass SIGNET_MAX_NUMBER raises SignetBagFull
    before anything is written.
    """
    out: dict = {
        "gold": 0, "diamond": 0, "energy": 0, "items": [], "heroes": [],
        "mails": [], "xp": None, "angels": [], "converted": [], "coins": {},
        "signets": [],
    }
    overflow: dict[int, int] = {}
    checked = _checked(cfg, prizes)
    new_signets = sum(max(1, a) for (c, _r, a) in checked if c == CATEGORY_SIGNET)
    if new_signets:
        owned = conn.execute(
            "SELECT id FROM signets WHERE player_id = ?", (int(player_id),)
        ).fetchall()
        cap = cfg.variable_int("SIGNET_MAX_NUMBER", 0)
        if len(owned) + new_signets > cap:
            raise SignetBagFull(
                f"player {player_id} owns {len(owned)} signets, {new_signets} more"
                f" would pass SIGNET_MAX_NUMBER {cap} ({STATUS_SIGNET_BAG_FULL})"
            )

    def _item(refer: int, amount: int) -> None:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
            (int(player_id), refer),
        ).fetchone()
        have = int(row["amount"]) if row else 0
        cap = int(cfg.item(refer)["stackable"] or 0)
        give = amount if cap <= 0 else max(0, min(amount, cap - have))
        if amount > give:
            overflow[refer] = overflow.get(refer, 0) + amount - give
        if give:
            out["items"].append((refer, db.grant_item(conn, player_id, refer, give)))

    for index, (category, refer, amount) in enumerate(checked):
        if category == CATEGORY_GOLD:
            conn.execute(
                "UPDATE players SET gold = gold + ? WHERE id = ?",
                (amount, int(player_id)),
            )
        elif category == CATEGORY_DIAMOND:
            conn.execute(
                "UPDATE players SET diamond = diamond + ? WHERE id = ?",
                (amount, int(player_id)),
            )
        elif category == CATEGORY_ENERGY:
            db.add_energy(conn, cfg, player_id, amount, over_cap=energy_over_cap)
        elif category == CATEGORY_ITEM:
            _item(refer, amount)
        elif category == CATEGORY_PLAYER_XP:
            change = db.add_player_xp(conn, cfg, player_id, amount)
            if out["xp"] is not None:
                change["before"] = out["xp"]["before"]
                change["levelled"] = change["after"][0] != change["before"][0]
            out["xp"] = change
        elif category in COIN_FIELDS:
            field = COIN_FIELDS[category]
            conn.execute(
                f"UPDATE players SET {field} = {field} + ? WHERE id = ?",
                (amount, int(player_id)),
            )
            out["coins"][field] = 0
        elif category == CATEGORY_SIGNET:
            for _ in range(max(1, amount)):
                out["signets"].append(db.add_signet(conn, player_id, refer))
        elif category == CATEGORY_ANGEL:
            for _ in range(max(1, amount)):
                owned = conn.execute(
                    "SELECT 1 FROM angels WHERE player_id = ? AND angel_entry = ?",
                    (int(player_id), refer),
                ).fetchone()
                if owned:
                    _item(*_angel_stones(cfg, refer))
                else:
                    # angel.summon starts an angel at its star-1 min_level too.
                    level = int(cfg.angel_by_star(refer, 1)["min_level"] or 1)
                    db.grant_angel(conn, player_id, refer, level=level, star=1)
                    out["angels"].append(refer)
        else:
            # The lowest hero_quality row is the one a summon starts at, and
            # hero.quality_row_for reads the same row back on the way out.
            # Star and level are hero_info.star / init_level, the same start
            # the soul-stone summon (hero.summon, 5_2105) gives: a 3-star
            # hero such as 304000 is born at star 3, level 5, not 1/1.
            quality = int(cfg.hero_qualities(refer)[0]["quality"])
            info = cfg.hero(refer)
            star = int(info["star"] or 1) if info is not None else 1
            init_level = int(info["init_level"] or 1) if info is not None else 1
            for _ in range(max(1, amount)):
                owned = conn.execute(
                    "SELECT 1 FROM heroes WHERE player_id = ? AND entry = ?",
                    (int(player_id), refer),
                ).fetchone()
                if owned:
                    _item(*_hero_stones(cfg, refer))
                    if out["converted"][-1:] != [index]:
                        out["converted"].append(index)
                else:
                    out["heroes"].append(
                        db.grant_hero(
                            conn, player_id, refer, quality,
                            star=star, level=init_level,
                        )
                    )
    conn.commit()
    if overflow:
        names = ", ".join(str(cfg.item(r)["name"]) for r in overflow)
        out["mails"].append(mail.deliver(
            conn, cfg, player_id, OVERFLOW_MAIL,
            [(CATEGORY_ITEM, r, n) for r, n in overflow.items()],
            int(time.time()), body=names,
        ))
    row = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    out["gold"] = int(row["gold"])
    out["diamond"] = int(row["diamond"])
    out["energy"] = int(row["energy"])
    for field in out["coins"]:
        out["coins"][field] = int(row[field])
    return out


def mark_converted(entries, out: dict) -> None:
    """Flag the ClientPrizeEntry of every hero prize that arrived as soul
    stones: MMAwardDropItem.lua:74 (and TavernUtil.lua:22,365, TavernCoin.lua:
    115,200) show the conversion only when extra.type == 1. `entries` lines up
    with the prizes list grant_prizes was given."""
    for index in out["converted"]:
        if index < len(entries):
            entries[index].extra.type = 1


def announce(registry: Registry, session: Session, out: dict) -> None:
    """The client side of grant_prizes' overflow mails, player xp and coins, which
    every caller needs; items, heroes and balances stay with the caller.

    A granted angel has no push the client listens to: AngelNotify 5_2932 has
    no Lua listener, and ident 3 skips an angel without serverInfo
    (ClientAngel.lua:131-133). AngelManager:parseAngel picks it up from the
    next QueryMyselfRes, so it is only logged here.
    """
    if out["mails"]:
        notify.mail_arrived(registry, session)
    if out["coins"]:
        notify.player_changed(registry, session, out["coins"])
    if out["xp"] is not None:
        before, after = out["xp"]["before"], out["xp"]["after"]
        notify.player_changed(registry, session, {
            "level": after[0], "xp": after[1], "energy": out["energy"],
            "max_energy": after[3],
        })
        if out["xp"]["levelled"]:
            notify.level_up(registry, session, (before[0], before[2], before[3]),
                            (after[0], after[2], after[3]))
    for angel_entry in out["angels"]:
        log.info("angel %d granted; the client sees it at the next login", angel_entry)
