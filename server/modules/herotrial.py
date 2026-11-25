"""Hero trials: 5_2331 HerotrialsInfoReq, 5_2333 HerotrialsBattleReq,
5_2335 HerotrialsBattleResultReq (plan B2 Wave 2, task B5).

What the client reads (the spec):

- 5_2332 (FunctionType.lua:499-518): maxTrialTimes is the total for every
  vocation (setHeroTryTotalTime, ClientDailyStats.lua:125-134),
  zs/fs/ss_trialTimes the runs used today, zs/fs/ss_cd the epoch at which the
  vocation's cooldown ends (HeroTryDetailUI.lua:478-486 shows cd - now).
  zs/fs/ss are vocations 1/2/3 (the proto comments 战士/法师/射手 and
  setHeroTryTime(1..3)).
- The trial a player picks is a herotrials_stage_info row. HeroTryTypeUI
  groups them by the row's own `vocation` and `weekday`
  (HeroTryTypeUI.lua:50-66) and shows today's set, today being
  g_timeManager:getDay(-5*3600) (HeroTryTypeUI.lua:70): the weekday with
  0 = Sunday (ServerTimeManager.lua:102-108) of the local time minus 5 hours,
  "服务器半夜5点更新" (HeroTryDetailUI.lua:99). A stage opens at the stage's
  own `level` (HeroTryTypeLevelItem.lua:159); the feature at function 10091
  英雄试炼 (FunctionType.lua:100).
- herotrials_grade_info is read only by the legacy HeroTryUI.lua, which no UI
  opens (UI_HERO_TRAIN is HeroTryTypeUI, SystemEventManager.lua:99). Its
  `vocation` column is not the trial's vocation. A stage's `icon` names its
  grade row, and only icons 1000-4000 have one; that row's `cd` is the
  cooldown, and a stage without a grade row falls back to the variable
  HERO_TRIALS_COOLDOWN.
- 5_2334 (HeroTryLine.lua:67-112) starts the fight on any answer: its
  `msg.status` is the native header's 0, and an unknown trialEntry falls back
  to the stage the player clicked. A refusal therefore cannot be delivered on
  5_2334. It is logged with its language.db code, no battle is recorded as
  pending, and the 5_2335 that follows pays nothing and answers the true
  counters, which the client copies (BattleFactoryHeroTry.lua:120-130,
  HeroTryLine.lua:142-150).
- 5_2336: success, the counters, prizes (BattleFactoryHeroTry.lua:128,
  HeroTryAutoResult.lua:26). owner/heroes/angel xp are not shown for this
  fight type (FightType.showServerPveExpInfo excludes HERO_TRY), and no grade
  row pays xp. `energy` has no reader; it carries the current energy.
- The fight's team comes from 5_2327 with fight_type 8 (FightType.HERO_TRY,
  FightType.lua:106-109); team.py answers it without the campaign's support
  hero.

Runs reset with the 05:00 day above (db.day_key(5)). A loss uses no run.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import datetime
from typing import Callable

from server import db
from server.config import Config
from server.modules import drops, item, level, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.herotrial")

STATUS_NO_TIMES = 333313    # language.db 英雄试炼次数不足
STATUS_COOLDOWN = 333314    # language.db 英雄试炼处于冷却中
STATUS_LEVEL = 327957       # language.db 未满足此玩法的等级

FUNCTION_HERO_TRY = 10091   # FunctionType.HERO_TRY, 英雄试炼
DAY_START_HOUR = 5          # getDay(-5*3600)
VOCATIONS = {1: "zs", 2: "fs", 3: "ss"}
STAR_DROPS = {1: "one_star_drops", 2: "two_star_drops", 3: "three_star_drops"}

PENDING_KEY = "herotrial_pending"


def weekday(now: float) -> int:
    """The client's getDay(-5*3600): 0 = Sunday, the day starting at 05:00."""
    return (datetime.fromtimestamp(float(now) - DAY_START_HOUR * 3600).weekday() + 1) % 7


def _limit(cfg: Config) -> int:
    raw = cfg.variable("HEROTRIALS_LIMIT")
    if raw in (None, ""):
        raise KeyError("variables.HEROTRIALS_LIMIT is missing")
    return int(float(raw))


def _cooldown(cfg: Config, stage: sqlite3.Row) -> int:
    grade = cfg.herotrials_grade(int(stage["icon"]))
    if grade is not None:
        return int(grade["cd"] or 0)
    return cfg.variable_int("HERO_TRIALS_COOLDOWN", 0)


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], float] | None = None,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _today(pid: int, now: float):
        """The player row with the runs zeroed when they belong to an earlier
        day. Cooldowns are epochs and simply run out."""
        today = db.day_key(DAY_START_HOUR, now)
        conn.execute(
            "UPDATE players SET herotrials_zs = 0, herotrials_fs = 0,"
            " herotrials_ss = 0, herotrials_day = ?"
            " WHERE id = ? AND herotrials_day != ?",
            (today, pid, today),
        )
        conn.commit()
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def _counters(res, row) -> None:
        for name in VOCATIONS.values():
            if row is None:
                setattr(res, f"{name}_trialTimes", 0)
                setattr(res, f"{name}_cd", 0)
            else:
                setattr(res, f"{name}_trialTimes", int(row[f"herotrials_{name}"]))
                setattr(res, f"{name}_cd", int(row[f"herotrials_{name}_cd"]))

    def info(session: Session, req):
        res = registry.message_class("HerotrialsInfoRes")(maxTrialTimes=_limit(cfg))
        row = _player(session)
        if row is not None:
            session.player_id = int(row["id"])
            row = _today(int(row["id"]), now_of())
        _counters(res, row)
        fill_required(res)
        return res

    def _refusal(pid: int, entry: int, now: float) -> str | None:
        """Why this trial cannot be fought now, or None."""
        stage = cfg.herotrials_stage(entry)
        if stage is None:
            return f"no herotrials_stage_info row {entry}"
        row = _today(pid, now)
        need = max(cfg.function_unlock(FUNCTION_HERO_TRY), int(stage["level"] or 0))
        if int(row["level"]) < need:
            return f"player level {int(row['level'])} < {need} ({STATUS_LEVEL})"
        today = weekday(now)
        if int(stage["weekday"]) != today:
            return (
                f"stage weekday {int(stage['weekday'])} is not today's weekday "
                f"{today} (no language.db code; the client floats x03033 itself)"
            )
        vocation = VOCATIONS.get(int(stage["vocation"]))
        if vocation is None:
            return f"stage vocation {stage['vocation']} is not 1-3"
        used, limit = int(row[f"herotrials_{vocation}"]), _limit(cfg)
        if used >= limit:
            return f"{vocation} runs {used} of {limit} used ({STATUS_NO_TIMES})"
        ends = int(row[f"herotrials_{vocation}_cd"])
        if ends > now:
            return f"{vocation} cooldown ends at {ends}, now {int(now)} ({STATUS_COOLDOWN})"
        return None

    def battle(session: Session, req):
        entry = int(req.trialEntry)
        res = registry.message_class("HerotrialsBattleRes")(trialEntry=entry)
        res.Urandom.extend(level.roll_urandom(rng))
        row = _player(session)
        pending = session.data.setdefault(PENDING_KEY, set())
        pending.discard(entry)
        if row is None:
            log.warning("5_2333 trial %d before any character exists", entry)
        else:
            pid = int(row["id"])
            session.player_id = pid
            why = _refusal(pid, entry, now_of())
            if why is None:
                pending.add(entry)
                log.info("5_2333 trial %d entered by player %d", entry, pid)
            else:
                log.warning(
                    "5_2333 trial %d refused for player %d: %s; HerotrialsBattleRes "
                    "has no status, the client fights and 5_2335 pays nothing",
                    entry, pid, why,
                )
        fill_required(res)
        return res

    def result(session: Session, req):
        entry = int(req.trialEntry)
        now = now_of()
        res = registry.message_class("HerotrialsBattleResultRes")(
            trialEntry=entry, success=False
        )
        row = _player(session)
        if row is None:
            log.warning("5_2335 trial %d before any character exists", entry)
            _counters(res, None)
            fill_required(res)
            return res
        pid = int(row["id"])
        session.player_id = pid
        pending = session.data.setdefault(PENDING_KEY, set())
        star = max(0, min(3, int(req.star)))
        stage = cfg.herotrials_stage(entry)

        if entry not in pending or stage is None:
            log.warning(
                "5_2335 trial %d for player %d with no accepted 5_2333 on this "
                "session, paying nothing", entry, pid,
            )
        elif star == 0:
            pending.discard(entry)
            log.info("5_2335 trial %d lost by player %d, no run used", entry, pid)
        else:
            # Popped before anything is granted, as level_out does.
            pending.discard(entry)
            vocation = VOCATIONS[int(stage["vocation"])]
            rolled = drops.roll(cfg, int(stage[STAR_DROPS[star]] or 0), rng=rng)
            try:
                granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
            except Exception:
                # grant_prizes vets before it writes: nothing is paid, so the
                # client's retry may replay.
                pending.add(entry)
                raise
            _today(pid, now)
            conn.execute(
                f"UPDATE players SET herotrials_{vocation} = herotrials_{vocation} + 1,"
                f" herotrials_{vocation}_cd = ? WHERE id = ?",
                (int(now) + _cooldown(cfg, stage), pid),
            )
            conn.commit()
            res.success = True
            for prize in drops.to_prize_entries(registry, rolled):
                res.prizes.add().CopyFrom(prize)
            item.mark_converted(res.prizes, granted)
            item.announce(registry, session, granted)
            notify.items_changed(registry, session, granted["items"])
            notify.player_changed(registry, session, {
                "gold": granted["gold"], "diamond": granted["diamond"],
            })
            log.info(
                "5_2335 trial %d won by player %d with %d star(s)%s, prizes %s",
                entry, pid, star, " (auto)" if req.auto else "",
                drops.as_triples(rolled),
            )

        row = db.refresh_energy(conn, cfg, _today(pid, now), now=int(now))
        _counters(res, row)
        res.energy = int(row["energy"])
        fill_required(res)
        return res

    return {(5, 2331): info, (5, 2333): battle, (5, 2335): result}
