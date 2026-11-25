"""Gold trial: 5_2213 GoldTrailsInfo, 5_2215 GoldTrailsResult and 5_2217
GoldTrailsPrize (plan B2 wave 2, task B4).

What the client reads (paths under .stock/assets/scripts/app/game/):

- GoldTrailsInfoRes (5_2214), CoinLine:getEnterFightResult:
  `status` (non-zero: return, CoinLine.lua:61), `level` (the fight's stage,
  :63,69), `urandom` (fightData:setRandoms, :64,70), `drop` (FightData, :69),
  `fight_tick` (fightData.max_tick, :71). The request is sent by name with
  `{level = stage}` (:168,218); the stage is the weekday's entry of
  GoldTryUI.lua:286-287 (1000000, 1000010, ...).
  `times` (field 6, a double) is read by no Lua file; it is left unset.
- GoldTrailsResultRes (5_2216), through BattleFactoryBase:requestServerInfo
  (status 0 -> showResult, else back to the main scene,
  view/scenes/battleScene/type/BattleFactoryBase.lua:871-900):
  `damage` (BattleEndLayer.lua:537; the base gold on the end panel is the
  client's own getCoinByDamage(damage), :563), `addition_gold`
  (BattleEndLayer.lua:589; GoldTryUI.lua:31), `all_damage` (GoldTryUI.lua:35
  stores it as g_roleData.goldTryDamage, which GoldTryAwardUI.lua:129 labels
  x02003 "今日累计伤害", today's total). `times` and `cooldown` are not read:
  GoldTryUI.lua:26-28 adds 1 to stats.gold_trails_times and sets
  player.gold_trails_cooldown to now itself. The auto fight (CoinLine.lua:
  75-103,106-148) sends damage 0 and hands the Res to GoldTryAutoResult.
- GoldTrailsPrizeRes (5_2218), no status field: `prize` (the new flags,
  GoldTryUI.lua:104), `prizeEntries` (the get-all reward panel,
  GoldTryAwardUI.lua:75-76); a single claim shows the row's own gold
  (GoldTryAwardUI.lua:61-64). The request is `{index}` for one row
  (goldTry/GoldTryAwardItem.lua:103) or `{index = 0, get_all = true}`
  (GoldTryAwardUI.lua:170).
- `prize` is a bitmask: bit k is row k of gold_trails_prize_info sorted by
  damage, 0-based (RoleData.lua:820-848). A row is claimable when today's
  total damage >= its damage and its bit is clear (RoleData.lua:840).
- Today's total ADDS each run's damage (AssistantData.lua:658), so
  players.gold_trails_best holds that sum and the ladder compares against it.
  QueryMyselfRes.gold_trails sends it with the flags (RoleData.lua:885-887).
- Gold per run: getCoinByDamage over gold_trails_exchange_info (gold per 100
  damage, band by band), capped by gold_trails_gold_limit(player level).gold
  (BattleFactoryCoinTry.lua:33,136-160). The star bonus is shown as
  rightLineStar x GOLD_TRAILS_STAR_GOLD_RATE, and rightLineStar is the line's
  hero stars plus its angel's star (CoinLine.lua:37-41, line/LineRight.lua:
  106-110).
- The fight asks for its team with 5_2327 fight_type 3 (FightType.GOLD_TRY,
  type/FightType.lua:16,105-107; type/FunctionType.lua:1102-1133). team.py
  answers every fight type with the player's own heroes and adds the support
  npc only for the campaign, so nothing changes there.

Counters are today's (O-W2-14, midnight): a players row whose gold_trails_day
is not today reads as zero runs, zero damage and no claimed rows, and every
write stamps today.
"""

from __future__ import annotations

import logging
import math
import random
import sqlite3
from collections.abc import Callable
from datetime import date

from server import db
from server.config import Config
from server.modules import item, level, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.goldtrial")

STATUS_OK = 0
STATUS_FUNCTION_LOCKED = 327957      # language.db 未满足此玩法的等级
STATUS_NO_TRIES = 331014             # language.db 挑战次数不够
STATUS_NOT_MET = 330245              # language.db 未满足领取该奖励的条件 (logged only)

FUNCTION_GOLD_TRIAL = 10070
TIMES_KEY = "GOLD_TRAILS_TIMES"
FIGHT_TICK_KEY = "GOLD_TRAILS_FIGHT_TICK"
STAR_RATE_KEY = "GOLD_TRAILS_STAR_GOLD_RATE"


def coin_by_damage(bands, damage: int) -> int:
    """BattleFactoryCoinTry:getCoinByDamage before its cap, the same float
    steps: `bands` is (damage, gold) sorted by damage."""
    coin, dam, last_dam, last_rate = 0, int(damage), 0, 0
    for band_dam, gold in bands:
        last_rate = gold
        if dam >= band_dam:
            coin += math.floor((band_dam - last_dam) * 0.01 * gold)
            last_dam = band_dam
        else:
            coin += math.floor((dam - last_dam) * 0.01 * last_rate)
            break
    return coin


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], date] | None = None,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    today_of = clock or date.today

    def _variable(key: str) -> str:
        raw = cfg.variable(key)
        if raw is None or raw == "":
            raise KeyError(f"variables.{key} is missing")
        return raw

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _today_state(row, today: str) -> tuple[int, int, int]:
        """(runs, total damage, claimed flags) of today; another day's are 0."""
        if row["gold_trails_day"] != today:
            return 0, 0, 0
        return (int(row["gold_trails_times"]), int(row["gold_trails_best"]),
                int(row["gold_trails_prize"]))

    def _out_of_tries(row, today: str) -> bool:
        return _today_state(row, today)[0] >= int(float(_variable(TIMES_KEY)))

    def _line_stars(pid: int, heroes, angel: int) -> int:
        owned: dict[int, int] = {}
        for hero_row in db.heroes_of(conn, pid):
            owned.setdefault(int(hero_row["entry"]), int(hero_row["star"]))
        stars = 0
        for entry in heroes:
            entry = int(entry)
            if entry == 0:
                continue
            if entry not in owned:
                log.warning("5_2215 names hero %d, which player %d does not own", entry, pid)
                continue
            stars += owned[entry]
        if int(angel):
            angel_row = conn.execute(
                "SELECT star FROM angels WHERE player_id = ? AND angel_entry = ?",
                (pid, int(angel)),
            ).fetchone()
            if angel_row is None:
                log.warning("5_2215 names angel %d, which player %d does not own", angel, pid)
            else:
                stars += int(angel_row["star"])
        return stars

    def _pay_gold(session: Session, pid: int, gold: int) -> None:
        # grant_prizes commits, so the caller's counter UPDATE lands with it.
        changed = item.grant_prizes(conn, cfg, pid, [(item.CATEGORY_GOLD, 0, gold)])
        notify.player_changed(registry, session, {"gold": changed["gold"]})

    def info(session: Session, req):
        name = "GoldTrailsInfoRes"
        row = _player(session)
        pid, today = int(row["id"]), today_of().isoformat()
        unlock = cfg.function_unlock(FUNCTION_GOLD_TRIAL)
        if int(row["level"]) < unlock:
            status, why = STATUS_FUNCTION_LOCKED, f"level {row['level']} < {unlock}"
        elif _out_of_tries(row, today):
            status, why = STATUS_NO_TRIES, "no runs left today"
        else:
            status = STATUS_OK
        if status != STATUS_OK:
            log.info("5_2213 for player %d refused %d: %s", pid, status, why)
            res = registry.message_class(name)(status=status)
            fill_required(res)
            return res
        res = registry.message_class(name)(
            status=STATUS_OK, level=int(req.level),
            fight_tick=int(float(_variable(FIGHT_TICK_KEY))),
        )
        res.urandom.extend(level.roll_urandom(rng))
        fill_required(res)
        log.info("5_2213 player %d enters gold trial stage %d", pid, int(req.level))
        return res

    def result(session: Session, req):
        name = "GoldTrailsResultRes"
        row = _player(session)
        pid, today = int(row["id"]), today_of().isoformat()
        if _out_of_tries(row, today):
            log.info("5_2215 for player %d refused %d: no runs left today", pid, STATUS_NO_TRIES)
            res = registry.message_class(name)(status=STATUS_NO_TRIES)
            fill_required(res)
            return res
        damage = max(0, int(req.damage))
        if req.auto:
            log.warning(
                "5_2215 auto fight for player %d sends damage %d; the server "
                "does not simulate fights, so it pays on that", pid, damage,
            )
        bands = [(int(r["damage"]), int(r["gold"])) for r in cfg.gold_trails_exchange()]
        gold = coin_by_damage(bands, damage)
        limit = cfg.gold_trails_limit(int(row["level"]))
        if limit is not None:
            gold = min(gold, int(limit["gold"]))
        stars = _line_stars(pid, req.heroes, int(req.angel))
        addition = math.floor(gold * float(_variable(STAR_RATE_KEY)) * stars)
        times, total, flags = _today_state(row, today)
        times, total = times + 1, total + damage
        conn.execute(
            "UPDATE players SET gold_trails_times = ?, gold_trails_best = ?,"
            " gold_trails_prize = ?, gold_trails_day = ? WHERE id = ?",
            (times, total, flags, today, pid),
        )
        if gold + addition > 0:
            _pay_gold(session, pid, gold + addition)
        else:
            conn.commit()
        log.info(
            "5_2215 player %d run %d: damage %d (today %d), gold %d + %d for %d stars",
            pid, times, damage, total, gold, addition, stars,
        )
        res = registry.message_class(name)(
            status=STATUS_OK, gold=gold, addition_gold=addition, damage=damage,
            all_damage=total, times=times, cooldown=0, star=max(0, int(req.star)),
        )
        fill_required(res)
        return res

    def prize(session: Session, req):
        name = "GoldTrailsPrizeRes"
        row = _player(session)
        pid, today = int(row["id"]), today_of().isoformat()
        times, total, flags = _today_state(row, today)
        rows = cfg.gold_trails_prizes()
        reached = [
            k for k, r in enumerate(rows)
            if total >= int(r["damage"]) and not flags & (1 << k)
        ]
        picked = reached if req.get_all else [k for k in reached if k == int(req.index)]
        res = registry.message_class(name)(index=int(req.index))
        if not picked:
            # No status on this Res (the header's 0 is all the client sees):
            # answer the current flags and pay nothing.
            log.warning(
                "5_2217 player %d index %d get_all %s: nothing to claim at %d "
                "damage, flags %#x (%d)", pid, int(req.index), bool(req.get_all),
                total, flags, STATUS_NOT_MET,
            )
            res.prize = flags
            fill_required(res)
            return res
        gold = 0
        for k in picked:
            flags |= 1 << k
            gold += int(rows[k]["gold"])
            res.prizeEntries.add(category=item.CATEGORY_GOLD, refer=0, amount=int(rows[k]["gold"]))
        conn.execute(
            "UPDATE players SET gold_trails_times = ?, gold_trails_best = ?,"
            " gold_trails_prize = ?, gold_trails_day = ? WHERE id = ?",
            (times, total, flags, today, pid),
        )
        _pay_gold(session, pid, gold)
        log.info("5_2217 player %d claimed rows %s for %d gold, flags %#x", pid, picked, gold, flags)
        res.prize = flags
        fill_required(res)
        return res

    return {
        (5, 2213): info,
        (5, 2215): result,
        (5, 2217): prize,
    }
