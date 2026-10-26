"""Rolling a drop id into concrete prizes.

The chain is the one the client walks in DataManager:getDropBaseAry
(DataManager.lua:444-474):

    drop id -> drop_group rows with that drop_id -> for each, its drop_group_id
            -> drop_base rows of that group -> one of them, by weight

probability is per group row. frequency is ignored: no Lua reads it and it is 0
or 1 everywhere this plan looks (open question B in the plan).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from server.config import Config
from server.net.registry import Registry

_default_rng = random.SystemRandom()


@dataclass(frozen=True)
class Drop:
    category: int   # drop_base.drop_type, the ClientPrizeEntry category
    refer: int      # drop_base.item_id: item entry, hero entry, or 0 for money
    amount: int


def roll(cfg: Config, drop_id: int, rng: random.Random | None = None) -> list[Drop]:
    rng = _default_rng if rng is None else rng
    out: list[Drop] = []
    for group in cfg.drop_groups(drop_id):
        probability = float(group["probability"] or 0)
        if probability < 1.0 and rng.random() >= probability:
            continue
        rows = cfg.drop_rows(int(group["drop_group_id"]))
        if not rows:
            # Dead config: plenty of drop ids point at groups with no rows.
            continue
        total = sum(max(0, r["weight"]) for r in rows)
        if total <= 0:
            continue
        pick = rng.randrange(total)
        for row in rows:
            pick -= max(0, row["weight"])
            if pick < 0:
                out.append(Drop(row["drop_type"], row["item_id"], row["amount"]))
                break
    return out


def to_prize_entries(registry: Registry, drops) -> list:
    entries = []
    for drop in drops:
        msg = registry.message_class("ClientPrizeEntry")(
            category=drop.category, refer=drop.refer, amount=drop.amount
        )
        entries.append(msg)
    return entries


def as_triples(drops) -> list[tuple[int, int, int]]:
    return [(d.category, d.refer, d.amount) for d in drops]
