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

# variables.NEW_FIGHT_HELP_HERO, memo 新手战斗中（关卡1-2）支援的英雄的NPC Id:
# the npc the stock server puts in the attacker team of the newbie fights.
SUPPORT_HERO_KEY = "NEW_FIGHT_HELP_HERO"

# The idx values of the first chapter the memo calls the newbie fights.
NEWBIE_IDX = (1, 2)

# Places 1..6 hold heroes; 0 is the angel (ANGEL_SLOT / BattleDefine.ANGEL_PLACE).
HERO_PLACES = range(1, 7)


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


def pending_stage(session: Session) -> int | None:
    """The stage this fight is for, or None outside a stage.

    5_2201 leaves the entered stage on the session (level.PENDING_KEY) until
    5_2203 pops it, and 5_2327 arrives between the two. The line-up screen
    sends 5_2327 as well, with nothing pending.
    """
    pending = session.data.get(level.PENDING_KEY, {})
    if not pending:
        return None
    # One entry in practice; a client retry can leave the newest one last.
    return int(list(pending)[-1])


def support_hero_for(
    cfg: Config,
    conn: sqlite3.Connection,
    session: Session,
    player_id: int,
) -> int | None:
    """The npc entry of the support hero for this fight, or None.

    The stock server carries variables.NEW_FIGHT_HELP_HERO for exactly this:
    the first two stages of the first chapter are unwinnable with the starting
    heroes (runs 4 and 5 of Task 17), and the real server answered them with an
    npc of its own. It joins only while the stage has not been cleared yet, so
    a replay of a finished stage is fought by the player's own team.
    """
    stage = pending_stage(session)
    if stage is None:
        log.debug("5_2327 outside a stage, no support hero")
        return None
    info = cfg.stage(stage)
    if info is None:
        return None
    first = cfg.stage(cfg.first_stage())
    # The first chapter is read from the config, never written as 10000 here.
    if int(info["chapter"]) != int(first["chapter"]):
        return None
    if int(info["idx"]) not in NEWBIE_IDX:
        return None
    cleared = any(
        int(r["level"]) == stage and int(r["star"]) > 0
        for r in db.levels_of(conn, player_id)
    )
    if cleared:
        return None
    raw = cfg.variable(SUPPORT_HERO_KEY)
    if raw is None or raw == "":
        raise KeyError(f"variables.{SUPPORT_HERO_KEY} is missing")
    return int(float(raw))


def build_self_team_res(
    registry: Registry,
    cfg: Config,
    conn: sqlite3.Connection,
    row: sqlite3.Row | None,
    session: Session,
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

    support = support_hero_for(cfg, conn, session, player_id)
    if support is not None:
        taken = {int(unit.position) for unit in res.team_base.units}
        free = next((place for place in HERO_PLACES if place not in taken), None)
        if free is None:
            log.warning(
                "stage %s is a newbie fight but places 1-6 are all taken, so "
                "support hero %d is left out", pending_stage(session), support,
            )
        else:
            res.team_base.units.add().CopyFrom(
                hero.build_npc_fight_unit(registry, cfg, support, free)
            )
            log.info(
                "stage %d is a newbie fight, support hero %d joins at position %d",
                pending_stage(session), support, free,
            )

    if any(int(value) for value in req.renter_units) or int(req.renter):
        log.warning(
            "5_2327 asks for hired units (renter %d, renter_units %s); hiring is "
            "not in Plan B1 and they are left out",
            int(req.renter), [int(v) for v in req.renter_units],
        )

    base.id = player_id
    base.source = 0
    base.level = int(row["level"])
    # The sum over the player's own heroes only: the support hero of a newbie
    # fight is the server's npc, not the player's power, and this number is what
    # the end screen shows as his.
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
            return build_self_team_res(
                registry, cfg, conn, None, session, req, rng=rng
            )
        session.player_id = int(row["id"])
        res = build_self_team_res(registry, cfg, conn, row, session, req, rng=rng)
        log.info(
            "5_2327 fight_type %d for player %d: team of %d unit(s) %s",
            int(req.fight_type), int(row["id"]), len(res.team_base.units),
            [(u.position, u.refer) for u in res.team_base.units],
        )
        return res

    return {(5, 2327): query_self_team}
