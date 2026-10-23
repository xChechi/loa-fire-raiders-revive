"""5_2327 QuerySelfTeamReq: the player's own fight team, built from the heroes
table.

The client asks for this between LevelIntoRes and openFight, and the answer is
not optional: FunctionType.lua:763-770 takes the success branch (QuerySelfTeamRes
has no status field, so the native handler supplies 0), then
FightData:initSelfTeam hands msg.team_base to LineTeam:initByServerTeamBase,
which indexes it with no nil check (LineTeam.lua:34). An empty 5_2328 therefore
kills the Lua VM before the fight opens - the blocker Task 17 found on the
emulator.

Slots. FunctionType.lua:1104-1133 builds the request as param[pos+1] = the
layout unit's hero entry, with the angel at param[1] and seven slots always
sent, where pos is the layout position (LineFrame:getLayoutTeam numbers heroes
from 1 and puts the angel at 8). So req.units[0] is the angel slot and
req.units[i] is layout position i. The answer carries that same number back in
ClientFightUnit.position, which is what BattleFactoryBase:getServerAttackerInfo
matches the layout place against (BattleFactoryBase.lua:171-184, with place 8
mapped to ANGEL_PLACE 0).

Values. refer is the hero entry, not our heroes row id: for type 1
BattleUnit:initByServerFightHero looks hero_quality up by (refer, quality) and
takes the prototype from it (BattleUnit.lua:3937-3950), and the real server's
own dump quoted in ClientHero.lua:249-262 shows refer 300000 with position 1.
The row supplies star, quality and level; the stats block is the same
ClientHeroUnit QueryMyselfRes already sent, so nothing here is a literal.
"""

from __future__ import annotations

import logging
import random
import sqlite3

from server import db
from server.config import Config
from server.modules import hero, level
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.team")

# ClientFightUnit.type: 1 is "a player hero, refer is its entry" and 3 is "an
# npc, refer is the prototype" (BattleUnit:initByServerFightHero).
UNIT_TYPE_HERO = 1

# req.units[0] carries the angel entry, not a hero (FunctionType.lua:1117).
ANGEL_SLOT = 0


def build_fight_unit(
    registry: Registry, cfg: Config, hero_row: sqlite3.Row, position: int
):
    """One ClientFightUnit for an owned hero row, standing at position."""
    client_hero = hero.build_client_hero(registry, cfg, hero_row)
    unit = registry.message_class("ClientFightUnit")(
        type=UNIT_TYPE_HERO,
        refer=client_hero.entry,
        position=position,
        star=client_hero.star,
        quality=client_hero.quality,
        level=client_hero.level,
        max_level=client_hero.max_level,
        ability=client_hero.ability,
        model=client_hero.model,
    )
    unit.spells.extend(client_hero.spells)
    unit.unit.CopyFrom(client_hero.unit)
    fill_required(unit)
    return unit


def build_self_team_res(
    registry: Registry,
    cfg: Config,
    conn: sqlite3.Connection,
    row: sqlite3.Row | None,
    req,
    rng: random.Random | None = None,
):
    res = registry.message_class("QuerySelfTeamRes")(refer=int(req.refer))
    # Present even when there is nothing to put in it: a nil team_base is the
    # LineTeam.lua:34 crash, an empty unit list is only a trace in
    # getServerAttackerInfo and the client still fights with its own layout.
    base = res.team_base
    base.SetInParent()
    for value in level.roll_urandom(rng):
        res.urandom.append(value)
    if row is None:
        fill_required(res)
        return res

    player_id = int(row["id"])
    # One row per entry, the lowest id, the same choice db.add_hero_xp makes.
    owned: dict[int, sqlite3.Row] = {}
    for hero_row in db.heroes_of(conn, player_id):
        owned.setdefault(int(hero_row["entry"]), hero_row)

    ability = 0
    for slot, entry in enumerate(req.units):
        entry = int(entry)
        if entry == 0:
            continue
        if slot == ANGEL_SLOT:
            log.warning(
                "5_2327 asks for angel %d in the angel slot; angels are not in "
                "Plan B1, the fight runs without it", entry,
            )
            continue
        hero_row = owned.get(entry)
        if hero_row is None:
            log.warning(
                "5_2327 asks for hero %d in slot %d, which player %d does not "
                "own; the slot is left out", entry, slot, player_id,
            )
            continue
        unit = build_fight_unit(registry, cfg, hero_row, slot)
        ability += int(unit.ability)
        res.team_base.units.add().CopyFrom(unit)

    if any(int(value) for value in req.renter_units) or int(req.renter):
        log.warning(
            "5_2327 asks for hired units (renter %d, renter_units %s); hiring is "
            "not in Plan B1 and they are left out",
            int(req.renter), [int(v) for v in req.renter_units],
        )

    base.id = player_id
    base.source = 0
    base.level = int(row["level"])
    base.fightAbility = ability
    base.name = row["nickname"]
    base.avatar = int(row["avatar"])
    # BattleFactoryBase:getAttackerTeamInfo uses "" and 0 for its own local
    # copy of these three (BattleFactoryBase.lua:386-391).
    base.origin = ""
    base.district = 0
    base.avatar_type = 0
    fill_required(res)
    return res


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def query_self_team(session: Session, req):
        row = _player(session)
        if row is None:
            log.warning(
                "5_2327 before any character exists, answering an empty team "
                "(a missing team_base would kill the client)"
            )
            return build_self_team_res(registry, cfg, conn, None, req, rng=rng)
        session.player_id = int(row["id"])
        res = build_self_team_res(registry, cfg, conn, row, req, rng=rng)
        log.info(
            "5_2327 fight_type %d for player %d: team of %d unit(s) %s",
            int(req.fight_type), int(row["id"]), len(res.team_base.units),
            [(u.position, u.refer) for u in res.team_base.units],
        )
        return res

    return {(5, 2327): query_self_team}
