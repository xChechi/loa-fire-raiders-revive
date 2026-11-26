"""Angel trials (女神试炼, 8_2501..8_2527): a 50-floor tower climbed once a day.

What the client reads, with file:line (scripts under .stock/assets/scripts/app/game):

- 8_2501 -> 8_2502 QueryAngeltrialsDataRes {status, opened, level, points,
  stars, crashLevel, treasure_cum_count, flag}: AngelTrainViewData:updateData
  (model/angelTry/AngelTrainViewData.lua:37-55). opened = false makes the
  client send 8_2503 (type/FunctionType.lua:484-497).
- 8_2503 -> 8_2504: the body is ignored; the client builds its own {opened,
  level 1, points 0, stars 0} (FunctionType.lua:466-482).
- 8_2505 {level, event} -> 8_2506 {status, level, event, eventResult}: sent
  for the client's current floor (AngelTrainTowerPanel.lua:358,372; the floor
  is AngelTrainViewData.level, :47). status 329729 is the "trial was reset,
  re-enter" alert and any other non-zero status floats and closes the UI
  (view/ui/angelTry/AngelTryCtr.lua:128-143). The result is read per event
  (AngelTrainSceneUIPanel.lua:189-224):
    1 treasure  treasureEvent {buyCount, prizes, treasure_cum_count, flag}; a
                non-empty prizes list is shown first, an empty one opens the
                treasure shop directly (AngelTrainSecretGemPanel).
    2 fight     fightEvent {enemies, enemyUnits, fightDifficulty}
                (AngelTrainBattleSelectPanel.lua:30-66).
    3 buff shop buffShopEvent.angeltrialsBuffs, three cards
                (AngelTrainSceneBuyBuffPanel.lua:27-45).
- 8_2507 -> 8_2508 {status, angeltrialsBuffs}: buff ids, looked up in
  angeltrials_buff_info (AngelTryCtr.lua:65-78,108-114).
- 8_2517 -> 8_2518 {status, leadings[], selfRank} (AngelTryCtr.lua:117-125);
  8_2519 -> 8_2520 {status, selfRank} (tryTypeSelect/TryTypeHelpPanel.lua:45-46).
  Multiplayer is out of scope, so the board holds the player alone.
- 8_2515 -> 8_2516 {status, units}: the player's live units, cached as
  myHeroLeftUnits and handed to the line-up (AngelTryCtr.lua:296-312). A hero
  with no live unit fights at full hp and 0 energy (AngelTryLine.lua:74-98).
- 8_2511 {difficulty 0-2, heros, angel} -> 8_2512 {status, selfUnits,
  enemyUnits, buffEffects, enemyBuffRate, urandom} (AngelTryLine.lua:120-188).
  enemyUnits are ClientFightUnit type 1 (hp > 0 only) or type 2; buffEffects
  is indexed by angeltrials_buff_info.effect from 0 and only 2, 3, 4 are read
  (Battle.lua:2286-2331); enemyBuffRate scales them for the enemy side. The
  fight itself then asks 5_2327 with fight_type 4 (FightType.ANGEL_TRY,
  FightType.lua:17,105-113), which team.py answers with the player's own
  heroes for any fight type.
- 8_2513 {success, units, enemyUnits, stars, heros, angel, op} -> 8_2514
  {warning, success, newLevel, points, stars, prizeEntries, units,
  angeltrialsBuffs}: the request is BattleFactoryAngelTry:getFightResultParam
  (BattleFactoryAngelTry.lua:122-175); warning == true is the cheat alert
  (:117-119); the rest goes to AngelTryUI:updateAngelViewData
  (AngelTryUI.lua:57-85).
- 8_2527 {heroIds, angelIds} -> 8_2528 {newLevel, points, stars,
  prizeEntries, units}: the fast clear (f00167 3星碾压) offered on a fight
  floor while crashLevel >= level, one floor per request
  (AngelTrainTowerPanel.lua:367-384, AngelTrainFastBattleDialog.lua:108-123,
  AngelTryCtr.lua:246-271).
- 8_2509 {index, unitType, unitEntry} -> 8_2510 {angeltrialsBuff, newStars,
  unit}: buy card `index` of the floor's buff shop for cost_star stars
  (AngelTryCtr.lua:366-377,200-234). Effects 2, 3, 4 are team-wide and kept in
  `buffs`; 0 (hp), 1 (energy) and 5 (revive) act on the chosen hero's live
  unit, which comes back in `unit` (AngelTrainBuffUseHeroPanel.lua:236-249
  picks hp < max, energy < max, dead). The Res has no status, so a refusal
  answers buff 0 and the unchanged stars.
- 8_2521 -> 8_2522 {newLevel} leaves the buff shop (AngelTryCtr.lua:237-243).
- 8_2523 {count} -> 8_2524 {buyCount, prizes, treasure_cum_count, flag}: open
  `count` treasures (1 when unset) for angeltrials_treasure_cost(buyCount + i)
  diamonds each (AngelTrainSecretGemPanel.lua:69-112,218-220,314-341;
  AngelTrainOpenMuliPanel.lua:81,149-156). Each open is one weighted row of
  angeltrials_treasure_drop with drop_group = the floor's arg5 (:53) inside
  its player-level and VIP ranges. No status either: a shortfall answers no
  prizes and the unchanged buyCount.
- 8_2525 -> 8_2526 {newLevel} leaves the treasure (:309-312).

Points are the client's own end-screen sum: floor(<difficulty>_battle_point x
ANGELTRIALS_POINTS_ADDITION_<n>_STAR x (1 + player level / 80))
(BattleEndLayer.lua:667-700; the 80 is the lvTop the client forces at
AngelTrainBattleSelectRender.lua:125-130). Stars gained are the fight's stars
x <difficulty>_battle_star, the "得星倍率" the card shows (:104-132).

The enemy (O-W2-14). The stock server matched a real player by arena rank
(arena_rank_percent0..4 with floor/ceiling_fa_fix0..4). There is no arena
here, so the enemy is the player's own strongest heroes, every stat and the
ability scaled by fa_fix_battle_<difficulty> x the middle of tier 4's
floor/ceiling_fa_fix (arena_rank_percent4 = 1, the tier that covers
everyone).

The state is one `angeltrials` row. It belongs to day_key(ANGELTRIALS_RANK_TIME)
(05:00, O-W2-1) and is reset on the first request of a new day. crash_level is
"yesterday's performance" (f00162 介于你昨日的表现，今日可以快速碾压): the floors
cleared on the day being reset. `pending` holds the event triggered on the
current floor, so a resend of 8_2505 answers the same event without paying
twice.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from collections.abc import Callable

from server import db
from server.config import Config
from server.modules import drops, events, hero, item, level as stage, notify, team
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.angeltrial")

# FunctionType.ANGEL_TRAIN_TYPE_1 (FunctionType.lua:58), function.unlock_level 20.
FUNCTION_ANGEL_TRIALS = 10090

RESET_HOUR_KEY = "ANGELTRIALS_RANK_TIME"

EVENT_TREASURE = 1
EVENT_FIGHT = 2
EVENT_BUFF_SHOP = 3

# Cards on one buff-shop floor (AngelTrainSceneBuyBuffPanel.lua:34).
BUFF_SHOP_CARDS = 3

# language.db.
STATUS_OK = 0
STATUS_LEVEL_LOW = 327957        # 未满足此玩法的等级
STATUS_NOT_OPENED = 329729       # 女神试炼未开启
STATUS_ALREADY_OPENED = 329730   # 女神试炼已开启
STATUS_WRONG_LEVEL = 329731      # 错误的女神试炼层数
STATUS_WRONG_EVENT = 329732      # 错误的女神试炼事件
STATUS_CLEARED = 329733          # 女神试炼已通关
STATUS_NO_ENEMY = 329734         # 女神试炼无法找到匹配的敌人,属于内部错误
STATUS_NO_EVENT = 329736         # 未触发女神试炼事件
STATUS_BAD_FIGHT = 329738        # 错误的战斗数据
STATUS_BUFF_FULL = 329735        # 女神试炼buff已满
STATUS_NO_STARS = 329737         # 女神试炼星数不足
STATUS_NO_DIAMOND = 327938       # 钻石不足

# angeltrials_buff_info.effect: the ones applied to all heroes for the rest of
# the day (AngelTryCtr.lua:210-212); the others act on one live unit.
TEAM_EFFECTS = (2, 3, 4)
EFFECT_HP, EFFECT_ENERGY, EFFECT_REVIVE = 0, 1, 5

# 试炼宝箱掉落VIP等级百分比加成, "7=0.5": from VIP 7 a treasure pays 50 % more.
VIP_BONUS_KEY = "ANGELTRIALS_VIP_TREASURE_BONUS"

# fightDifficulty 0, 1, 2 and their angeltrials_level_info column prefixes.
DIFFICULTIES = ("easy", "normal", "hard")
# f00167 3星碾压: the fast clear pays the top difficulty at 3 stars.
CRASH_DIFFICULTY = 2
CRASH_STARS = 3

POINTS_KEYS = {
    1: "ANGELTRIALS_POINTS_ADDITION_ONE_STAR",
    2: "ANGELTRIALS_POINTS_ADDITION_TWO_STAR",
    3: "ANGELTRIALS_POINTS_ADDITION_THREE_STAR",
}
RECOVER_HP_KEY = "ANGELTRIALS_RECOVER_HP_RATE"
CRASH_ENERGY_KEY = "ANGELTRIALS_CRASH_RECOVER_ENERGY_RATE"

# AngelTrainBattleSelectRender.lua:126 overrides PLAY_MAX_LEVEL with 80.
LV_TOP = 80

# The arena-rank tier whose floor/ceiling_fa_fix scale the mirror enemy.
ENEMY_TIER = 4

# Heroes in one line-up (LineFrame.lua:678 fills up to 5).
TEAM_SIZE = 5

# ClientFightLiveUnit.type.
UNIT_HERO = 1
UNIT_ANGEL = 2

# buffEffects has one slot per angeltrials_buff_info.effect 0..5.
BUFF_EFFECT_SLOTS = 6

# ClientHeroUnit fields the mirror enemy scales.
SCALED_FIELDS = ("power", "defence", "magic", "magic_defence")

_default_rng = random.SystemRandom()


def reset_hour(cfg: Config) -> int:
    raw = cfg.variable(RESET_HOUR_KEY)
    if raw is None or raw == "":
        raise KeyError(f"variables.{RESET_HOUR_KEY} is missing")
    return int(float(raw))


def top_level(cfg: Config) -> int:
    """The highest floor; a level above it means the tower is cleared."""
    level = 1
    while cfg.angeltrials_level(level + 1) is not None:
        level += 1
    return level


def load_state(conn: sqlite3.Connection, cfg: Config, pid: int, now: float) -> dict:
    """The player's tower for today, created or reset as needed."""
    today = db.day_key(reset_hour(cfg), now)
    row = conn.execute(
        "SELECT * FROM angeltrials WHERE player_id = ?", (int(pid),)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO angeltrials (player_id, day) VALUES (?, ?)", (int(pid), today)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM angeltrials WHERE player_id = ?", (int(pid),)
        ).fetchone()
    state = {
        key: int(row[key]) for key in (
            "opened", "level", "points", "stars", "crash_level",
            "treasure_cum_count", "flag",
        )
    }
    state["day"] = str(row["day"])
    state["buffs"] = json.loads(row["buffs"] or "[]")
    state["units"] = json.loads(row["units"] or "[]")
    state["pending"] = json.loads(row["pending"] or "{}")
    if state["day"] != today:
        cleared = max(0, state["level"] - 1) if state["opened"] else 0
        log.info(
            "angel trials for player %d reset for %s: yesterday cleared %d "
            "floor(s), crash level %d", int(pid), _dmy(today), cleared, cleared,
        )
        state.update(
            opened=0, level=0, points=0, stars=0, crash_level=cleared,
            treasure_cum_count=0, day=today, buffs=[], units=[], pending={},
        )
        save_state(conn, pid, state)
    return state


def save_state(conn: sqlite3.Connection, pid: int, state: dict) -> None:
    conn.execute(
        "UPDATE angeltrials SET opened = ?, level = ?, points = ?, stars = ?,"
        " crash_level = ?, treasure_cum_count = ?, flag = ?, day = ?, buffs = ?,"
        " units = ?, pending = ? WHERE player_id = ?",
        (
            state["opened"], state["level"], state["points"], state["stars"],
            state["crash_level"], state["treasure_cum_count"], state["flag"],
            state["day"], json.dumps(state["buffs"]), json.dumps(state["units"]),
            json.dumps(state["pending"]), int(pid),
        ),
    )
    conn.commit()


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def offer_buffs(cfg: Config, group: int, rng: random.Random) -> list[int]:
    """BUFF_SHOP_CARDS distinct buffs of one angeltrials_buff_info group, drawn
    by weight without replacement."""
    pool = [
        (int(b["id"]), max(0, int(b["weight"] or 0)))
        for b in cfg.angeltrials_buffs() if int(b["group"] or 0) == int(group)
    ]
    pool = [p for p in pool if p[1] > 0]
    if len(pool) < BUFF_SHOP_CARDS:
        raise ValueError(f"angeltrials_buff_info group {group} has fewer than "
                         f"{BUFF_SHOP_CARDS} buffs with a weight")
    out: list[int] = []
    while len(out) < BUFF_SHOP_CARDS:
        total = sum(w for _, w in pool)
        pick = rng.randrange(total)
        for index, (buff, weight) in enumerate(pool):
            pick -= weight
            if pick < 0:
                out.append(buff)
                pool.pop(index)
                break
    return out


def enemy_factor(info, difficulty: int) -> float:
    """How strong the mirror enemy is next to the player, per difficulty."""
    floor = float(info[f"floor_fa_fix{ENEMY_TIER}"] or 0)
    ceiling = float(info[f"ceiling_fa_fix{ENEMY_TIER}"] or 0)
    battle = float(info[f"fa_fix_battle_{DIFFICULTIES[difficulty]}"] or 0)
    return battle * (floor + ceiling) / 2


def _float_variable(cfg: Config, key: str) -> float:
    raw = cfg.variable(key)
    if raw is None or raw == "":
        raise KeyError(f"variables.{key} is missing")
    return float(raw)


def fight_award(cfg: Config, info, difficulty: int, stars: int, player_level: int):
    """(points, trial stars) for winning a floor at this difficulty."""
    prefix = DIFFICULTIES[difficulty]
    rate = _float_variable(cfg, POINTS_KEYS[stars])
    points = int(
        float(info[f"{prefix}_battle_point"] or 0) * rate
        * (1 + int(player_level) / LV_TOP)
    )
    return points, int(stars) * int(info[f"{prefix}_battle_star"] or 0)


def vip_bonus(cfg: Config, vip: int) -> float:
    """The extra share of a treasure from ANGELTRIALS_VIP_TREASURE_BONUS
    ("vip=rate" pairs, comma separated): the highest threshold at or below vip."""
    bonus = 0.0
    for pair in (cfg.variable(VIP_BONUS_KEY) or "").split(","):
        if "=" not in pair:
            continue
        threshold, rate = pair.split("=", 1)
        if int(vip) >= int(threshold):
            bonus = max(bonus, float(rate))
    return bonus


def roll_treasure(
    cfg: Config, group: int, player_level: int, vip: int, rng: random.Random
) -> tuple[int, int, int]:
    """One (category, refer, amount) from the floor's angeltrials_treasure_drop
    group, by weight, among the rows open to this player level and VIP."""
    rows = [
        r for r in cfg.angeltrials_treasure_drops()
        if int(r["drop_group"]) == int(group)
        and int(r["min_lvl"]) <= int(player_level) <= int(r["max_lvl"])
        and int(r["min_vip"]) <= int(vip) <= int(r["max_vip"])
        and int(r["weight"] or 0) > 0
    ]
    if not rows:
        raise ValueError(
            f"angeltrials_treasure_drop group {group} has no row for level "
            f"{player_level} VIP {vip}"
        )
    pick = rng.randrange(sum(int(r["weight"]) for r in rows))
    for row in rows:
        pick -= int(row["weight"])
        if pick < 0:
            amount = int(int(row["drop_amount"]) * (1 + vip_bonus(cfg, vip)))
            return int(row["drop_type"]), int(row["drop_entry"]), amount
    raise AssertionError("unreachable")


def live_dict(unit) -> dict:
    return {
        "type": int(unit.type), "refer": int(unit.refer), "hp": int(unit.hp),
        "energy": int(unit.energy), "max_hp": int(unit.max_hp),
        "max_energy": int(unit.max_energy),
    }


def find_live(units: list[dict], type_: int, refer: int) -> dict | None:
    return next(
        (u for u in units if u["type"] == int(type_) and u["refer"] == int(refer)), None
    )


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time
    rand = rng or _default_rng

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _res(name: str, status: int = STATUS_OK, **fields):
        res = registry.message_class(name)(status=status, **fields)
        fill_required(res)
        return res

    def _refused(name: str, status: int, pid: int, why: str):
        log.info("%s for player %d refused %d: %s", name, pid, status, why)
        return _res(name, status)

    def _locked(player) -> bool:
        return int(player["level"]) < cfg.function_unlock(FUNCTION_ANGEL_TRIALS)

    def query(session: Session, req):
        name = "QueryAngeltrialsDataRes"
        player = _player(session)
        pid = int(player["id"])
        if _locked(player):
            return _refused(name, STATUS_LEVEL_LOW, pid, f"player level {player['level']}")
        state = load_state(conn, cfg, pid, now_of())
        res = _res(
            name,
            opened=bool(state["opened"]), level=state["level"],
            points=state["points"], stars=state["stars"],
            crashLevel=state["crash_level"],
            treasure_cum_count=state["treasure_cum_count"], flag=state["flag"],
        )
        log.info(
            "8_2501 player %d: opened %d, level %d, points %d, stars %d, crash %d",
            pid, state["opened"], state["level"], state["points"], state["stars"],
            state["crash_level"],
        )
        return res

    def start(session: Session, req):
        name = "StartAngeltrialsRes"
        player = _player(session)
        pid = int(player["id"])
        if _locked(player):
            return _refused(name, STATUS_LEVEL_LOW, pid, f"player level {player['level']}")
        state = load_state(conn, cfg, pid, now_of())
        if state["opened"]:
            return _refused(name, STATUS_ALREADY_OPENED, pid, "already opened today")
        state.update(opened=1, level=1, points=0, stars=0, pending={})
        save_state(conn, pid, state)
        log.info("angel trials opened for player %d on %s", pid, _dmy(state["day"]))
        return _res(name)

    def _treasure_event(session: Session, pid: int, state: dict, info, res) -> None:
        treasure = res.eventResult.treasureEvent
        pending = state["pending"]
        if pending.get("level") == state["level"]:
            # A resend: the free prize was paid with the first answer.
            treasure.buyCount = int(pending.get("buy_count", 0))
        else:
            rolled = drops.roll(cfg, int(info["angel_advance_free_drop"] or 0), rand)
            changed = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
            notify.items_changed(registry, session, changed["items"])
            notify.player_changed(
                registry, session,
                {"gold": changed["gold"], "diamond": changed["diamond"],
                 "energy": changed["energy"]},
            )
            item.announce(registry, session, changed)
            for entry in drops.to_prize_entries(registry, rolled):
                treasure.prizes.add().CopyFrom(entry)
            state["treasure_cum_count"] += 1
            state["pending"] = {
                "level": state["level"], "event": EVENT_TREASURE, "buy_count": 0,
            }
            treasure.buyCount = 0
            log.info(
                "angel trials floor %d treasure for player %d: free prize %s",
                state["level"], pid,
                [(d.category, d.refer, d.amount) for d in rolled],
            )
        treasure.treasure_cum_count = state["treasure_cum_count"]
        treasure.flag = state["flag"]

    def _buff_shop_event(pid: int, state: dict, info, res) -> None:
        pending = state["pending"]
        if pending.get("level") != state["level"]:
            group = int(float(info["arg0"] or 0))
            pending = {
                "level": state["level"], "event": EVENT_BUFF_SHOP,
                "offers": offer_buffs(cfg, group, rand), "bought": [],
            }
            state["pending"] = pending
            log.info(
                "angel trials floor %d buff shop for player %d: group %d offers %s",
                state["level"], pid, group, pending["offers"],
            )
        res.eventResult.buffShopEvent.angeltrialsBuffs.extend(pending["offers"])

    def _owned_heroes(pid: int) -> dict[int, sqlite3.Row]:
        # One row per entry, the lowest id, as team.build_self_team_res does.
        owned: dict[int, sqlite3.Row] = {}
        for row in db.heroes_of(conn, pid):
            owned.setdefault(int(row["entry"]), row)
        return owned

    def _mirror_units(pid: int, entries: list[int], info, difficulty: int) -> list:
        """The enemy's ClientFightUnits: the player's own heroes, scaled."""
        owned = _owned_heroes(pid)
        factor = enemy_factor(info, difficulty)
        units = []
        for position, entry in enumerate(entries, start=1):
            if entry not in owned:
                continue
            unit = team.build_fight_unit(
                registry, cfg, owned[entry], position, hero.runes_of(conn, owned[entry]), conn=conn
            )
            unit.unit.max_hp = int(unit.unit.max_hp * factor)
            for field in SCALED_FIELDS:
                setattr(unit.unit, field, getattr(unit.unit, field) * factor)
            unit.ability = int(unit.ability * factor)
            unit.hp = unit.unit.max_hp
            unit.energy = int(info["enemy_hero_energy"] or 0)
            units.append(unit)
        return units

    def _fight_event(pid: int, player, state: dict, info, res) -> None:
        pending = state["pending"]
        if pending.get("level") != state["level"]:
            strongest = sorted(
                _owned_heroes(pid).values(),
                key=lambda r: -team.build_fight_unit(
                    registry, cfg, r, 0, hero.runes_of(conn, r), conn=conn
                ).ability,
            )
            pending = {
                "level": state["level"], "event": EVENT_FIGHT,
                "heroes": [int(r["entry"]) for r in strongest[:TEAM_SIZE]],
                "difficulty": -1, "left": {"difficulty": -1, "units": []},
            }
            state["pending"] = pending
            log.info(
                "angel trials floor %d fight for player %d: mirror of %s",
                state["level"], pid, pending["heroes"],
            )
        fight = res.eventResult.fightEvent
        for difficulty in range(len(DIFFICULTIES)):
            units = _mirror_units(pid, pending["heroes"], info, difficulty)
            enemy = fight.enemies.add(
                level=int(player["level"]), fightAbility=sum(u.ability for u in units),
                name=str(player["nickname"]), avatar=int(player["avatar"]),
            )
            for unit in units:
                hero_msg = enemy.heros.add(
                    entry=unit.refer, level=unit.level, star=unit.star,
                    quality=unit.quality, fightAbility=unit.ability,
                    position=unit.position, model=unit.model,
                )
                fill_required(hero_msg)
            fill_required(enemy)
            fight.fightDifficulty.append(difficulty)
        for left in pending["left"]["units"]:
            fight.enemyUnits.add(**left)

    def trigger(session: Session, req):
        name = "TriggerAngeltrialsEventRes"
        player = _player(session)
        pid = int(player["id"])
        if _locked(player):
            return _refused(name, STATUS_LEVEL_LOW, pid, f"player level {player['level']}")
        state = load_state(conn, cfg, pid, now_of())
        level, event = int(req.level), int(req.event)
        if not state["opened"]:
            return _refused(name, STATUS_NOT_OPENED, pid, "not opened today")
        if state["level"] > top_level(cfg):
            return _refused(name, STATUS_CLEARED, pid, f"level {state['level']}")
        if level != state["level"]:
            return _refused(name, STATUS_WRONG_LEVEL, pid,
                            f"asked {level}, current {state['level']}")
        info = cfg.angeltrials_level(level)
        if event != int(info["event"]):
            return _refused(name, STATUS_WRONG_EVENT, pid,
                            f"floor {level} is event {info['event']}, asked {event}")
        res = registry.message_class(name)(status=STATUS_OK, level=level, event=event)
        if event == EVENT_TREASURE:
            _treasure_event(session, pid, state, info, res)
        elif event == EVENT_BUFF_SHOP:
            _buff_shop_event(pid, state, info, res)
        else:
            if not _owned_heroes(pid):
                return _refused(name, STATUS_NO_ENEMY, pid, "no hero to mirror")
            _fight_event(pid, player, state, info, res)
        save_state(conn, pid, state)
        fill_required(res)
        log.info("8_2505 player %d floor %d event %d", pid, level, event)
        return res

    def query_buffs(session: Session, req):
        name = "QueryAngeltrialsBuffRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        res = _res(name)
        res.angeltrialsBuffs.extend(int(b) for b in state["buffs"])
        return res

    def rank(session: Session, req):
        name = "AngeltrialsRankRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        res = _res(name, selfRank=1)
        me = res.leadings.add(
            id=pid, name=str(player["nickname"]), avatar=int(player["avatar"]),
            avatarType=0, level=int(player["level"]), atRank=1,
            atPoints=state["points"], atLevel=state["level"],
        )
        fill_required(me)
        log.info("8_2517 player %d: the board is the player alone", pid)
        return res

    def self_rank(session: Session, req):
        return _res("AngeltrialsSelfRankRes", selfRank=1)

    def _fight_pending(state: dict) -> bool:
        pending = state["pending"]
        return bool(state["opened"]) and pending.get("event") == EVENT_FIGHT \
            and pending.get("level") == state["level"]

    def _buff_effects(state: dict) -> list[float]:
        by_id = {int(b["id"]): b for b in cfg.angeltrials_buffs()}
        effects = [0.0] * BUFF_EFFECT_SLOTS
        for buff in state["buffs"]:
            row = by_id[int(buff)]
            effects[int(row["effect"])] += float(row["effect_value"] or 0)
        return effects

    def fighting(session: Session, req):
        name = "AngeltrialsFightingRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        if not _fight_pending(state):
            return _refused(name, STATUS_NO_EVENT, pid, f"no fight on floor {state['level']}")
        difficulty = int(req.difficulty)
        heroes = [int(h) for h in req.heros if int(h)]
        angel = int(req.angel)
        owned = _owned_heroes(pid)
        why = None
        if difficulty not in range(len(DIFFICULTIES)):
            why = f"difficulty {difficulty}"
        elif not heroes:
            why = "no hero in the line-up"
        for entry in heroes:
            live = find_live(state["units"], UNIT_HERO, entry)
            if entry not in owned:
                why = f"hero {entry} is not owned"
            elif live is not None and live["hp"] <= 0:
                why = f"hero {entry} died earlier today"
        if angel and all(int(a["angel_entry"]) != angel for a in db.angels_of(conn, pid)):
            why = f"angel {angel} is not owned"
        if why:
            return _refused(name, STATUS_BAD_FIGHT, pid, why)
        pending = state["pending"]
        pending["difficulty"] = difficulty
        save_state(conn, pid, state)
        info = cfg.angeltrials_level(state["level"])
        res = registry.message_class(name)(
            status=STATUS_OK, enemyBuffRate=float(info["enemy_buff_fix"] or 0)
        )
        for live in state["units"]:
            if (live["type"] == UNIT_HERO and live["refer"] in heroes) or (
                live["type"] == UNIT_ANGEL and live["refer"] == angel
            ):
                res.selfUnits.add(**live)
        left = pending["left"]
        left_units = left["units"] if left["difficulty"] == difficulty else []
        for unit in _mirror_units(pid, pending["heroes"], info, difficulty):
            prior = find_live(left_units, UNIT_HERO, unit.refer)
            if prior is not None:
                unit.hp, unit.energy = prior["hp"], prior["energy"]
            res.enemyUnits.add().CopyFrom(unit)
        res.buffEffects.extend(_buff_effects(state))
        res.urandom.extend(stage.roll_urandom(rand))
        fill_required(res)
        log.info(
            "8_2511 player %d floor %d difficulty %d: heroes %s, angel %d vs %s",
            pid, state["level"], difficulty, heroes, angel,
            [(u.refer, u.hp) for u in res.enemyUnits],
        )
        return res

    def _hero_live(state: dict, hero_row) -> dict:
        """The hero's live unit, added at full hp and 0 energy when it has
        none yet: what the client assumes for it (AngelTryLine.lua:82-89)."""
        entry = int(hero_row["entry"])
        live = find_live(state["units"], UNIT_HERO, entry)
        if live is None:
            unit = team.build_fight_unit(
                registry, cfg, hero_row, 0, hero.runes_of(conn, hero_row), conn=conn
            ).unit
            live = {
                "type": UNIT_HERO, "refer": entry, "hp": int(unit.max_hp),
                "energy": 0, "max_hp": int(unit.max_hp),
                "max_energy": int(unit.max_energy),
            }
            state["units"].append(live)
        return live

    def _tower_answer(name: str, state: dict, **fields):
        res = registry.message_class(name)(
            newLevel=state["level"], points=state["points"], stars=state["stars"],
            **fields,
        )
        for live in state["units"]:
            res.units.add(**live)
        return res

    def end_fight(session: Session, req):
        name = "AngeltrialsEndFightRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        pending = state["pending"]
        if not _fight_pending(state) or int(pending.get("difficulty", -1)) < 0:
            # No status on this Res: the answer is the unchanged tower.
            log.warning(
                "8_2513 for player %d without a fight started on floor %d; "
                "would refuse %d", pid, state["level"], STATUS_NO_EVENT,
            )
            res = _tower_answer(name, state, warning=False, success=False)
            res.angeltrialsBuffs.extend(int(b) for b in state["buffs"])
            fill_required(res)
            return res
        difficulty = int(pending["difficulty"])
        fought = [live_dict(u) for u in req.units]
        fought_keys = {(u["type"], u["refer"]) for u in fought}
        recover = _float_variable(cfg, RECOVER_HP_KEY)
        for live in state["units"]:
            benched = (live["type"], live["refer"]) not in fought_keys
            if benched and live["type"] == UNIT_HERO and live["hp"] > 0:
                live["hp"] = min(live["max_hp"], live["hp"] + int(recover * live["max_hp"]))
        for unit in fought:
            live = find_live(state["units"], unit["type"], unit["refer"])
            if live is None:
                state["units"].append(unit)
            else:
                live.update(unit)
        stars = min(int(req.stars), CRASH_STARS)
        won = bool(req.success) and stars >= 1
        floor = state["level"]
        if won:
            info = cfg.angeltrials_level(floor)
            points, gained = fight_award(cfg, info, difficulty, stars, int(player["level"]))
            state["points"] += points
            state["stars"] += gained
            state["level"] += 1
            state["pending"] = {}
        else:
            pending["left"] = {
                "difficulty": difficulty,
                "units": [live_dict(u) for u in req.enemyUnits],
            }
            pending["difficulty"] = -1
        save_state(conn, pid, state)
        events.bump(conn, cfg, registry, session, pid, events.KIND_ANGEL_TRIAL, now=now_of())
        log.info(
            "8_2513 player %d floor %d difficulty %d: won %s with %d star(s); "
            "points %d, stars %d, floor now %d",
            pid, floor, difficulty, won, stars if won else 0,
            state["points"], state["stars"], state["level"],
        )
        res = _tower_answer(name, state, warning=False, success=won)
        res.angeltrialsBuffs.extend(int(b) for b in state["buffs"])
        fill_required(res)
        return res

    def fight_live(session: Session, req):
        name = "AngeltrialsFightLiveRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        if not state["opened"]:
            return _refused(name, STATUS_NOT_OPENED, pid, "not opened today")
        res = _res(name)
        for live in state["units"]:
            res.units.add(**live)
        return res

    def crash(session: Session, req):
        name = "AngeltrialsCrashLevelRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        floor = state["level"]
        info = cfg.angeltrials_level(floor) if floor >= 1 else None
        why = None
        if not state["opened"]:
            why = (STATUS_NOT_OPENED, "not opened today")
        elif info is None:
            why = (STATUS_CLEARED, f"floor {floor}")
        elif int(info["event"]) != EVENT_FIGHT:
            why = (STATUS_WRONG_EVENT, f"floor {floor} is event {info['event']}")
        elif floor > state["crash_level"]:
            why = (STATUS_WRONG_LEVEL, f"floor {floor} above crash level {state['crash_level']}")
        if why:
            # No status on this Res: the answer is the unchanged tower.
            log.warning("8_2527 for player %d would refuse %d: %s", pid, *why)
            res = _tower_answer(name, state)
            fill_required(res)
            return res
        points, gained = fight_award(
            cfg, info, CRASH_DIFFICULTY, CRASH_STARS, int(player["level"])
        )
        rate = _float_variable(cfg, CRASH_ENERGY_KEY)
        owned = _owned_heroes(pid)
        for entry in (int(h) for h in req.heroIds):
            if entry not in owned:
                continue
            live = _hero_live(state, owned[entry])
            if live["hp"] > 0:
                live["energy"] = min(
                    live["max_energy"], live["energy"] + int(rate * live["max_energy"])
                )
        # An angel has a live unit only once the client reported one from a
        # fight; its max energy is the client's own number.
        for entry in (int(a) for a in req.angelIds):
            live = find_live(state["units"], UNIT_ANGEL, entry)
            if live is not None:
                live["energy"] = min(
                    live["max_energy"], live["energy"] + int(rate * live["max_energy"])
                )
        state["points"] += points
        state["stars"] += gained
        state["level"] += 1
        state["pending"] = {}
        save_state(conn, pid, state)
        log.info(
            "8_2527 player %d crashed floor %d: +%d points, +%d stars", pid, floor,
            points, gained,
        )
        res = _tower_answer(name, state)
        fill_required(res)
        return res

    def _shop_pending(state: dict, event: int) -> bool:
        pending = state["pending"]
        return bool(state["opened"]) and pending.get("event") == event \
            and pending.get("level") == state["level"]

    def buy_buff(session: Session, req):
        name = "AngeltrialsBuyBuffRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        pending = state["pending"]

        def unchanged(status: int, why: str):
            # No status on this Res: buff 0 and the unchanged stars.
            log.warning("8_2509 for player %d would refuse %d: %s", pid, status, why)
            res = registry.message_class(name)(angeltrialsBuff=0, newStars=state["stars"])
            fill_required(res)
            return res

        if not _shop_pending(state, EVENT_BUFF_SHOP):
            return unchanged(STATUS_NO_EVENT, f"no buff shop on floor {state['level']}")
        index = int(req.index)
        if index not in range(len(pending["offers"])):
            return unchanged(STATUS_NO_EVENT, f"card {index}")
        if index in pending["bought"]:
            return unchanged(STATUS_BUFF_FULL, f"card {index} already bought")
        buff_id = int(pending["offers"][index])
        buff = next(b for b in cfg.angeltrials_buffs() if int(b["id"]) == buff_id)
        cost = int(buff["cost_star"] or 0)
        if state["stars"] < cost:
            return unchanged(STATUS_NO_STARS, f"buff {buff_id} costs {cost}, has {state['stars']}")
        effect, value = int(buff["effect"]), float(buff["effect_value"] or 0)
        live = None
        if effect not in TEAM_EFFECTS:
            hero_row = _owned_heroes(pid).get(int(req.unitEntry))
            if int(req.unitType) != UNIT_HERO or hero_row is None:
                return unchanged(STATUS_BAD_FIGHT, f"unit {req.unitType}/{req.unitEntry}")
            live = _hero_live(state, hero_row)
            dead = live["hp"] <= 0
            if dead != (effect == EFFECT_REVIVE):
                return unchanged(STATUS_BAD_FIGHT, f"buff {buff_id} on hp {live['hp']}")
            if effect == EFFECT_HP:
                live["hp"] = min(live["max_hp"], live["hp"] + int(value * live["max_hp"]))
            elif effect == EFFECT_ENERGY:
                live["energy"] = min(
                    live["max_energy"], live["energy"] + int(value * live["max_energy"])
                )
            elif effect == EFFECT_REVIVE:
                live["hp"] = min(live["max_hp"], int(value * live["max_hp"]))
        else:
            state["buffs"].append(buff_id)
        state["stars"] -= cost
        pending["bought"].append(index)
        save_state(conn, pid, state)
        log.info(
            "8_2509 player %d bought buff %d (effect %d) for %d star(s)%s",
            pid, buff_id, effect, cost, f" on hero {live['refer']}" if live else "",
        )
        res = registry.message_class(name)(angeltrialsBuff=buff_id, newStars=state["stars"])
        if live is not None:
            res.unit.CopyFrom(registry.message_class("ClientFightLiveUnit")(**live))
        fill_required(res)
        return res

    def _leave(name: str, event: int, session: Session):
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        if _shop_pending(state, event):
            state["level"] += 1
            state["pending"] = {}
            save_state(conn, pid, state)
            log.info("%s player %d moves on to floor %d", name, pid, state["level"])
        else:
            log.warning(
                "%s for player %d without event %d on floor %d; would refuse %d",
                name, pid, event, state["level"], STATUS_NO_EVENT,
            )
        res = registry.message_class(name)(newLevel=state["level"])
        fill_required(res)
        return res

    def end_buy_buff(session: Session, req):
        return _leave("AngeltrialsEndBuyBuffRes", EVENT_BUFF_SHOP, session)

    def end_buy_treasure(session: Session, req):
        return _leave("AngeltrialsEndBuyTreasureRes", EVENT_TREASURE, session)

    def buy_treasure(session: Session, req):
        name = "AngeltrialsBuyTreasureRes"
        player = _player(session)
        pid = int(player["id"])
        state = load_state(conn, cfg, pid, now_of())
        pending = state["pending"]

        def answer(prizes=()):
            res = registry.message_class(name)(
                buyCount=int(pending.get("buy_count", 0)),
                treasure_cum_count=state["treasure_cum_count"], flag=state["flag"],
            )
            for entry in prizes:
                res.prizes.add().CopyFrom(entry)
            fill_required(res)
            return res

        def unchanged(status: int, why: str):
            # No status on this Res: no prizes and the unchanged buyCount.
            log.warning("8_2523 for player %d would refuse %d: %s", pid, status, why)
            return answer()

        if not _shop_pending(state, EVENT_TREASURE):
            pending = {}
            return unchanged(STATUS_NO_EVENT, f"no treasure on floor {state['level']}")
        count = max(1, int(req.count))
        bought = int(pending["buy_count"])
        costs = [cfg.angeltrials_treasure_cost(bought + i) for i in range(1, count + 1)]
        if any(c is None for c in costs):
            return unchanged(STATUS_NO_EVENT, f"opens {bought}+{count} pass the cost table")
        cost = sum(costs)
        if int(player["diamond"]) < cost:
            return unchanged(STATUS_NO_DIAMOND, f"{count} open(s) cost {cost}")
        group = int(float(cfg.angeltrials_level(state["level"])["arg5"] or 0))
        triples = [
            roll_treasure(cfg, group, int(player["level"]), int(player["vip"]), rand)
            for _ in range(count)
        ]
        # grant_prizes vets the whole list before its first write; the
        # diamonds were checked above, so the spend after it cannot fail.
        changed = item.grant_prizes(conn, cfg, pid, triples)
        db.spend(conn, pid, diamond=cost)
        pending["buy_count"] = bought + count
        state["treasure_cum_count"] += count
        save_state(conn, pid, state)
        notify.items_changed(registry, session, changed["items"])
        diamond = int(conn.execute(
            "SELECT diamond FROM players WHERE id = ?", (pid,)
        ).fetchone()["diamond"])
        notify.player_changed(
            registry, session, {"gold": changed["gold"], "diamond": diamond}
        )
        item.announce(registry, session, changed)
        log.info(
            "8_2523 player %d opened %d treasure(s) on floor %d for %d diamonds: %s",
            pid, count, state["level"], cost, triples,
        )
        entries = [
            registry.message_class("ClientPrizeEntry")(category=c, refer=r, amount=a)
            for c, r, a in triples
        ]
        return answer(entries)

    return {
        (8, 2501): query,
        (8, 2503): start,
        (8, 2505): trigger,
        (8, 2507): query_buffs,
        (8, 2509): buy_buff,
        (8, 2511): fighting,
        (8, 2513): end_fight,
        (8, 2515): fight_live,
        (8, 2517): rank,
        (8, 2519): self_rank,
        (8, 2521): end_buy_buff,
        (8, 2523): buy_treasure,
        (8, 2525): end_buy_treasure,
        (8, 2527): crash,
    }
