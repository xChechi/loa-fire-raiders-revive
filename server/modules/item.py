"""Inventory: ClientStock shapes and prize granting.

Categories are the client's own constants (ClientPlayer.lua:146-186) and are the
same numbers as drop_base.drop_type: 1 gold, 2 energy, 9 diamond, 11 player xp,
12 hero xp, 13 angel xp, 20 item, 30 hero, 40 angel. The five this plan can
actually apply are below; any other one raises, because a reward that silently
shrinks is worse than a crash in a log Stefan reads.

There is no ClientItem message in allProtos.pb: an owned item is a ClientStock
(one row per item entry, `amount` absolute), which is what QueryMyselfRes
carries in its repeated `inventory` field.
"""

from __future__ import annotations

import sqlite3

from server import db
from server.config import Config
from server.net.registry import Registry
from server.net.server import fill_required

CATEGORY_GOLD = 1
CATEGORY_ENERGY = 2
CATEGORY_DIAMOND = 9
CATEGORY_ITEM = 20
CATEGORY_HERO = 30

KNOWN_CATEGORIES = frozenset(
    {CATEGORY_GOLD, CATEGORY_ENERGY, CATEGORY_DIAMOND, CATEGORY_ITEM, CATEGORY_HERO}
)


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
        if category == CATEGORY_HERO and not cfg.hero_qualities(refer):
            raise KeyError(f"hero_quality has no row for hero {refer}")
        out.append((category, refer, amount))
    return out


def grant_prizes(
    conn: sqlite3.Connection, cfg: Config, player_id: int, prizes
) -> dict:
    """Apply (category, refer, amount) triples and report what changed.

    The return value is what both the persistence and the client notification
    need: the new absolute gold, diamond and energy, the new absolute amount of
    every item touched, and the row id of every hero created.
    """
    out: dict = {
        "gold": 0, "diamond": 0, "energy": 0, "items": [], "heroes": [],
    }
    for category, refer, amount in _checked(cfg, prizes):
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
            db.add_energy(conn, cfg, player_id, amount)
        elif category == CATEGORY_ITEM:
            out["items"].append((refer, db.grant_item(conn, player_id, refer, amount)))
        else:
            # The lowest hero_quality row is the one a summon starts at, and
            # hero.quality_row_for reads the same row back on the way out.
            quality = int(cfg.hero_qualities(refer)[0]["quality"])
            for _ in range(max(1, amount)):
                out["heroes"].append(
                    db.grant_hero(conn, player_id, refer, quality)
                )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    out["gold"] = int(row["gold"])
    out["diamond"] = int(row["diamond"])
    out["energy"] = int(row["energy"])
    return out
