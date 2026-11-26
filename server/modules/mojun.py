"""Demon onslaught (魔君来袭, function 10092): 5_2727 MagicArmyQueryReq,
5_2729 MagicArmyBattleStartReq, 5_2731 MagicArmyBattleEndReq (plan B2 Wave 3,
task B3).

What the client reads (the spec):

- The monster of the day is the chapter_info type 12 row whose idx is the
  client's day: g_timeManager:getDay() with 0 = Sunday read as 7, and hours
  0-4 counted as the day before ("魔王是当天五点来，次日五点走",
  MojunDataHelp.lua:24-42, 92-107). That is herotrial.weekday (local time
  minus 5 h, 0 = Sunday) with 0 mapped to 7 (O-W3-9).
- A difficulty is the stage_info row of that chapter with that idx
  (MojunDataHelp.lua:55-56, 66-67, 109-110). Only 1-9 exist for the client:
  mojunMaxNum = 9 (MojunDataHelp.lua:13), and SelectRender.lua:30-35, 79-81
  blocks 10 and above ("V4.6 先屏蔽10级及其以上难度"), although stage_info
  has 15 per chapter.
- 5_2728 `state` is the highest difficulty of this monster already passed,
  0 = never fought (MojunDataHelp.lua:16-17, MojunDetailInfoUI.lua:29-30,
  capped at 9 there; MojunSelectPanel.lua:10). The req carries the chapter
  entry (MojunStruckUI.lua:25, 137). Difficulty d is selectable when
  d <= state, or d == state + 1 and the player level reaches the stage's
  unlock_level (SelectRender.lua:92-112, MojunDataHelp.lua:53-62).
- 5_2728 `battle_times` is the runs used today against MAGIC_ARMY_DAY_TIMES
  (MojunDetailInfoUI.lua:33, 66, 300). The client refuses only when the runs
  are spent AND the chosen difficulty is not above `state`
  (MojunDetailInfoUI.lua:165, 302): a first clear uses no run, f00465
  "首次通关不消耗次数" (:141-142, 257-262). The first-clear reward the
  screen shows is the stage's invisible_drops, a repeat shows visible_drops
  (:266, 278); pet money (category 86) sits in visible_drops.
- 5_2730 (MojunLine.lua:60-81): `if msg.status~=0 then return end; if
  msg.flag==1 then floatMsg(x13001 "该据点已通过") return end`, then the
  fight (FightType.MOJUN 27). So flag 1 is the refusal and flag 0 enters
  the fight; MagicArmyBattleStartRes has no status and msg.status is the
  frame header's 0.
- 5_2731 (BattleFactoryMojun.lua:102-134, 152-163): {level, group 1, heroes,
  angel (angel_entry), result 1|0, ops}. 5_2732 needs header status 0, then
  the win is resData.result > 0 (forceResult, :152-154) and the end screen
  shows resData.drop (:156-159). FightType.showServerPveExpInfo excludes
  MOJUN (FightType.lua:115-119), so owner/heroes/angel xp are not shown;
  they are filled as level_out fills them. Nothing in the Lua reads
  `state`/`battle_times` of 5_2732: the city re-sends 5_2727 after the fight
  (isBattleLaterOpenMojun, FunctionType.lua:373-376, MojunStruckUI.lua:22-28).
  They carry the true values anyway.

No Res in this module has a `status` field (allProtos.proto:1069-1133), so a
refusal is a WARNING with its language.db code and the current state.
language.db codes: 327957 未满足此玩法的等级, 328193 关卡未开启, 328195
已经达到最大次数, 328196 没有进入关卡.

Storage: runs are players.mojun_times for players.mojun_day, the db.day_key(5)
day (O-W3-9). A passed difficulty is a `levels` row of its stage with star 1,
the table the client's own g_levelManager:levelPlayed(dstLevel) reads for the
mojun stage (MojunLine.lua:77). A loss uses no run (as the hero trial).
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from typing import Callable

from server import db
from server.config import Config
from server.modules import drops, hero, herotrial, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.mojun")

STATUS_LEVEL = 327957          # language.db 未满足此玩法的等级
STATUS_STAGE_LOCKED = 328193   # language.db 关卡未开启
STATUS_MAX_TIMES = 328195      # language.db 已经达到最大次数
STATUS_NOT_ENTERED = 328196    # language.db 没有进入关卡

FUNCTION_MOJUN = 10092         # FunctionType.MOJUN_STRUCK_TYPE
CHAPTER_MOJUN = 12             # chapter_info.type of 8010000-8070000
MAX_DIFFICULTY = 9             # MojunDataHelp.lua:13, SelectRender.lua:30-35
DAY_START_HOUR = 5

FLAG_OK = 0
FLAG_REFUSED = 1               # MojunLine.lua:62-65, x13001

PENDING_KEY = "mojun_pending"


def client_day(now: float) -> int:
    """MojunDataHelp's curDay: 1 = Monday .. 7 = Sunday, the day from 05:00."""
    return herotrial.weekday(now) or 7


def today_chapter(cfg: Config, now: float) -> int:
    """The chapter entry of today's monster, 0 when the config has none."""
    day = client_day(now)
    for chapter in cfg.chapters_of_type(CHAPTER_MOJUN):
        if int(chapter["idx"]) == day:
            return int(chapter["entry"])
    return 0


def state_of(conn: sqlite3.Connection, cfg: Config, pid: int, chapter: int) -> int:
    """The highest difficulty of this chapter passed, 0 for none."""
    best = 0
    for stage in cfg.stages_in_chapter(chapter):
        idx = int(stage["idx"])
        if idx > MAX_DIFFICULTY:
            continue
        progress = db.level_progress(conn, pid, int(stage["entry"]))
        if progress is not None and int(progress["star"]) > 0:
            best = max(best, idx)
    return best


def _day_times(cfg: Config) -> int:
    raw = cfg.variable("MAGIC_ARMY_DAY_TIMES")
    if raw in (None, ""):
        raise KeyError("variables.MAGIC_ARMY_DAY_TIMES is missing")
    return int(float(raw))


def _mojun_chapter(cfg: Config, stage) -> int:
    """The stage's chapter when it is a type-12 chapter, else 0."""
    if stage is None:
        return 0
    chapter = cfg.chapter(int(stage["chapter"]))
    if chapter is None or int(chapter["type"]) != CHAPTER_MOJUN:
        return 0
    return int(chapter["entry"])


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
        """The player row with mojun_times zeroed when it belongs to an
        earlier 05:00 day."""
        today = db.day_key(DAY_START_HOUR, now)
        conn.execute(
            "UPDATE players SET mojun_times = 0, mojun_day = ?"
            " WHERE id = ? AND mojun_day != ?",
            (today, pid, today),
        )
        conn.commit()
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def query(session: Session, req):
        entry = int(req.entry)
        res = registry.message_class("MagicArmyQueryRes")(state=0, battle_times=0)
        row = _player(session)
        if row is None:
            log.warning("5_2727 chapter %d before any character exists", entry)
            fill_required(res)
            return res
        pid = int(row["id"])
        session.player_id = pid
        row = _today(pid, now_of())
        need = cfg.function_unlock(FUNCTION_MOJUN)
        if int(row["level"]) < need:
            log.warning(
                "5_2727 player %d level %d < %d (%d); MagicArmyQueryRes has no "
                "status, answering the current state",
                pid, int(row["level"]), need, STATUS_LEVEL,
            )
        chapter = cfg.chapter(entry)
        if chapter is None or int(chapter["type"]) != CHAPTER_MOJUN:
            log.warning(
                "5_2727 chapter %d is not a chapter_info type %d row (%d)",
                entry, CHAPTER_MOJUN, STATUS_STAGE_LOCKED,
            )
        else:
            res.state = state_of(conn, cfg, pid, entry)
        res.battle_times = int(row["mojun_times"])
        fill_required(res)
        return res

    def _refusal(pid: int, lvl: int, now: float) -> str | None:
        """Why this difficulty cannot be fought now, or None."""
        stage = cfg.stage(lvl)
        chapter = _mojun_chapter(cfg, stage)
        if not chapter:
            return f"stage {lvl} is not a demon-onslaught stage ({STATUS_STAGE_LOCKED})"
        row = _today(pid, now)
        level, need = int(row["level"]), cfg.function_unlock(FUNCTION_MOJUN)
        if level < need:
            return f"player level {level} < {need} ({STATUS_LEVEL})"
        today = today_chapter(cfg, now)
        if chapter != today:
            return (
                f"chapter {chapter} is not today's monster {today} "
                f"({STATUS_STAGE_LOCKED})"
            )
        idx = int(stage["idx"])
        if idx > MAX_DIFFICULTY:
            return (
                f"difficulty {idx} is above the client's {MAX_DIFFICULTY} "
                f"({STATUS_STAGE_LOCKED})"
            )
        state = state_of(conn, cfg, pid, chapter)
        if idx > state + 1:
            return (
                f"difficulty {idx} needs {idx - 1} passed, passed {state} "
                f"({STATUS_STAGE_LOCKED})"
            )
        unlock = int(stage["unlock_level"] or 0)
        if idx == state + 1 and level < unlock:
            return f"difficulty {idx} opens at level {unlock}, player {level} ({STATUS_LEVEL})"
        used, limit = int(row["mojun_times"]), _day_times(cfg)
        if idx <= state and used >= limit:
            return f"runs {used} of {limit} used ({STATUS_MAX_TIMES})"
        return None

    def start(session: Session, req):
        lvl = int(req.level)
        res = registry.message_class("MagicArmyBattleStartRes")(flag=FLAG_REFUSED)
        pending = session.data.setdefault(PENDING_KEY, set())
        pending.discard(lvl)
        row = _player(session)
        if row is None:
            log.warning("5_2729 stage %d before any character exists", lvl)
        else:
            pid = int(row["id"])
            session.player_id = pid
            why = _refusal(pid, lvl, now_of())
            if why is None:
                pending.add(lvl)
                res.flag = FLAG_OK
                log.info("5_2729 stage %d entered by player %d", lvl, pid)
            else:
                log.warning(
                    "5_2729 stage %d refused for player %d: %s; answering flag %d",
                    lvl, pid, why, FLAG_REFUSED,
                )
        fill_required(res)
        return res

    def end(session: Session, req):
        lvl = int(req.level)
        now = now_of()
        res = registry.message_class("MagicArmyBattleEndRes")(result=0)
        row = _player(session)
        if row is None:
            log.warning("5_2731 stage %d before any character exists", lvl)
            fill_required(res)
            return res
        pid = int(row["id"])
        session.player_id = pid
        pending = session.data.setdefault(PENDING_KEY, set())
        stage = cfg.stage(lvl)
        chapter = _mojun_chapter(cfg, stage)
        hero_xp: list[tuple[int, int, int]] = []
        angel_xp: tuple[int, int] | None = None

        if lvl not in pending or not chapter:
            log.warning(
                "5_2731 stage %d for player %d with no accepted 5_2729 on this "
                "session (%d), paying nothing", lvl, pid, STATUS_NOT_ENTERED,
            )
        elif int(req.result) <= 0:
            pending.discard(lvl)
            log.info("5_2731 stage %d lost by player %d, no run used", lvl, pid)
        else:
            # Popped before anything is granted, as level_out does.
            pending.discard(lvl)
            first = int(stage["idx"]) > state_of(conn, cfg, pid, chapter)
            rolled = drops.roll(cfg, int(stage["visible_drops"] or 0), rng=rng)
            if first:
                rolled += drops.roll(cfg, int(stage["invisible_drops"] or 0), rng=rng)
            try:
                granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
            except Exception:
                # grant_prizes vets before it writes: nothing is paid, so the
                # client's retry may replay.
                pending.add(lvl)
                raise
            try:
                db.upsert_level(conn, pid, lvl, star=1, count_delta=1)
                if not first:
                    _today(pid, now)
                    conn.execute(
                        "UPDATE players SET mojun_times = mojun_times + 1 WHERE id = ?",
                        (pid,),
                    )
                    conn.commit()
                xp_change = db.add_player_xp(conn, cfg, pid, int(stage["player_xp"] or 0))
                hero_xp = db.add_hero_xp(
                    conn, cfg, pid, list(req.heroes), int(stage["unit_xp"] or 0)
                )
                angel_xp = db.add_angel_xp(
                    conn, cfg, pid, int(req.angel), int(stage["angel_xp"] or 0)
                )
            except Exception:
                log.error(
                    "5_2731 stage %d: drops %s granted to player %d but a later "
                    "write failed; the clear and the run are NOT recorded",
                    lvl, drops.as_triples(rolled), pid, exc_info=True,
                )
                raise
            res.result = 1
            for prize in drops.to_prize_entries(registry, rolled):
                res.drop.add().CopyFrom(prize)
            item.mark_converted(res.drop, granted)
            item.announce(registry, session, granted)
            notify.items_changed(registry, session, granted["items"])
            fresh = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
            notify.player_changed(registry, session, {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "xp": int(fresh["xp"]), "level": int(fresh["level"]),
            })
            if xp_change["levelled"]:
                before, after = xp_change["before"], xp_change["after"]
                notify.level_up(
                    registry, session,
                    (before[0], before[2], before[3]), (after[0], after[2], after[3]),
                )
            if int(stage["unit_xp"] or 0) > 0:
                for entry, _hlevel, _hxp in hero_xp:
                    hero_row = conn.execute(
                        "SELECT * FROM heroes WHERE player_id = ? AND entry = ?"
                        " ORDER BY id", (pid, entry),
                    ).fetchone()
                    notify.hero_changed(
                        registry, session, entry,
                        hero.hero_notify_fields_with_runes(
                            registry, cfg, hero_row, hero.runes_of(conn, hero_row), conn=conn
                        ),
                    )
            if angel_xp is not None:
                notify.angel_changed(registry, session, int(req.angel), {
                    "level": angel_xp[0], "exp": angel_xp[1],
                })
            log.info(
                "5_2731 stage %d won by player %d (%s), prizes %s",
                lvl, pid, "first clear, no run used" if first else "one run used",
                drops.as_triples(rolled),
            )

        row = _today(pid, now)
        res.owner.refer = pid
        res.owner.level = int(row["level"])
        res.owner.xp = int(row["xp"])
        for entry, hlevel, hxp in hero_xp:
            client_xp = res.heroes.add()
            client_xp.refer = entry
            client_xp.level = hlevel
            client_xp.xp = hxp
        if angel_xp is not None:
            res.angel.refer = int(req.angel)
            res.angel.level, res.angel.xp = angel_xp
        res.state = state_of(conn, cfg, pid, chapter) if chapter else 0
        res.battle_times = int(row["mojun_times"])
        fill_required(res)
        return res

    return {(5, 2727): query, (5, 2729): start, (5, 2731): end}
