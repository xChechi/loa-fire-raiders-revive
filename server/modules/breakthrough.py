"""Hero breakthrough: 5_2811 HeroBreakthroughReportQueryReq, 5_2813
HeroBreakthroughReq, 5_2815 HeroBreakthroughAutoReq (plan B2 Wave 3, task B6).

What the client reads (the spec):

- The tab is function 90070 英雄突破 (FunctionType.lua:196), checked with
  checkIsOpend before the tab opens (RoleUI.lua:382); unlock_level 54.
- The panel reads hero_breakthrough_info by hero_breakthrough_level, the
  current row and the next (RoleBreakthroughPanel.lua:45-46). The top level
  is the row count - 1 = 20 (:23-24); at the top the client floats h08021 and
  sends nothing (:651-656).
- The stone is item 2100 (g_roleData:getItemNum(2100), :233,247); a try costs
  the CURRENT row's breakthrough_stone (:228,246). The client sends only when
  it holds enough (isCanOffer, :241-256, isCanAdvance :646-678). No hero
  level, star or quality condition exists beyond the function gate.
- 5_2814/5_2816 {breakthrough_level, breakthrough_score, state, old_ability}
  (:696-735, :756-762): the client copies level and score; state 1 = success
  ("1,成功;0,失败", proto comment :702), which fills the ball to the old row's
  max_score and opens the success panel with old_ability (:719-729,258-260).
  The ball is score / max_score of the current row (:316-326).
- grow_add is "属性成长加成" (:467-468), the attribute GROWTH bonus, shown per
  growth attribute through rateToPercent (RoleBreakInfoItem.lua:38,52), i.e.
  0.1 = +10 % growth. bonus() applies it to the hero's hero_growth gain
  (level - 1 steps of the current star's row), see bonus().
- 5_2811 {level} opens the report panel (RoleBreakInfoPanel.lua:24-29); an
  empty `reports` shows h90009 "no player yet" (:95-112).
- None of the three Res has `status` (proto), so nothing here can refuse:
  a shortfall logs a WARNING with the code it would have used and answers the
  current state.

Weekly reset: h12024 "突破值每周一凌晨5点清空" (RoleBreakthroughPanel.lua:
635-637) clears the score every Monday 05:00, for every hero
(RoleData:clearAllHerosBreakScore, RoleData.lua:2509-2520, which has no
caller in the Lua). It runs lazily before every attempt: players.
breakthrough_week holds the week_key the scores belong to; on a new week
every hero's breakthrough_score goes to 0 and the level stays. A world from
before the stamp ('') is stamped, not cleared.

Success rule (O-W3-8, owner's default): each try pays the stones and adds
randint(breakthrough_min, breakthrough_max) to the score; it succeeds when
random() < p, p being the ladder rate of the highest bracket <= the new score,
and p = 1 from max_score on (from level 10 max_score sits below the ladder's
top bracket). Success raises the level and resets the score to 0. Auto
repeats until a success or a shortfall.

Status codes (language.db):
  327941 英雄不存在, 327942 没有足够道具, 327957 未满足此玩法的等级,
  339174 已达最大突破等级.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import date, timedelta

from server import db
from server.config import Config, parse_rate_ladder
from server.modules import hero as hero_mod
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.breakthrough")

FUNCTION = 90070                     # 英雄突破 (FunctionType.lua:196)
STONE_ITEM = 2100                    # RoleBreakthroughPanel.lua:233,247

STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_FUNCTION_LOCKED = 327957      # 未满足此玩法的等级
STATUS_TOP_LEVEL = 339174            # 已达最大突破等级

WEEK_START_HOUR = 5                  # h12024 每周一凌晨5点


def week_key(now: float) -> str:
    """The ISO date of the Monday that starts `now`'s week, the week turning
    at Monday 05:00 (the 05:00 day of db.day_key, back to its Monday)."""
    day = date.fromisoformat(db.day_key(WEEK_START_HOUR, now))
    return (day - timedelta(days=day.weekday())).isoformat()


def ensure_week(conn: sqlite3.Connection, pid: int, now: float) -> None:
    """Zero every hero's breakthrough_score when the stored week is an
    earlier one; '' (never stamped) is only stamped."""
    week = week_key(now)
    row = conn.execute(
        "SELECT breakthrough_week FROM players WHERE id = ?", (int(pid),)
    ).fetchone()
    stored = row["breakthrough_week"] if row is not None else week
    if stored == week:
        return
    if stored:
        conn.execute(
            "UPDATE heroes SET breakthrough_score = 0 WHERE player_id = ?", (int(pid),)
        )
        log.info("player %d: breakthrough scores cleared for the week of %s", pid, week)
    conn.execute(
        "UPDATE players SET breakthrough_week = ? WHERE id = ?", (week, int(pid))
    )
    conn.commit()


def success_rate(row, score: int) -> float:
    """O-W3-8: the ladder rate of the highest bracket <= score; 1 from
    max_score on."""
    max_score = int(row["max_score"] or 0)
    if max_score and score >= max_score:
        return 1.0
    rate = 0.0
    for bracket, value in parse_rate_ladder(row["rate"]):
        if bracket <= score:
            rate = value
    return rate


def bonus(conn: sqlite3.Connection, cfg: Config, hero_row) -> dict[str, float]:
    """grow_add of the hero's breakthrough level as a share of its growth
    gain: (level - 1) x hero_growth(hero, star)[field] x grow_add for every
    hero_growth column (the panel lists the growth attributes with
    grow_add as a percentage, RoleBreakthroughPanel.lua:51-104)."""
    level = int(hero_row["breakthrough_level"])
    steps = max(0, int(hero_row["level"]) - 1)
    if not level or not steps:
        return {}
    row = cfg.hero_breakthrough(level)
    if row is None:
        raise KeyError(f"hero_breakthrough_info has no row for level {level}")
    grow = float(row["grow_add"] or 0)
    growth = cfg.hero_growth(int(hero_row["entry"]), int(hero_row["star"]))
    if not grow or growth is None:
        return {}
    out: dict[str, float] = {}
    for field in hero_mod.GROWTH_FIELDS:
        value = steps * float(growth[field] or 0) * grow
        if value:
            out[field] = value
    return out


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
    clock=None,
) -> dict[tuple[int, int], Handler]:
    rand = rng or random.Random()
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _hero(pid: int, entry: int):
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (pid, int(entry)),
        ).fetchone()

    def _ability(row) -> int:
        built = hero_mod.build_client_hero_with_runes(
            registry, cfg, row, hero_mod.runes_of(conn, row)
        )
        return int(built.ability)

    def _stones(pid: int) -> int:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
            (pid, STONE_ITEM),
        ).fetchone()
        return int(row["amount"]) if row else 0

    def _res(name: str, row, state: int = 0, old_ability: int = 0):
        res = registry.message_class(name)(state=state, old_ability=old_ability)
        if row is not None:
            res.breakthrough_level = int(row["breakthrough_level"])
            res.breakthrough_score = int(row["breakthrough_score"])
        fill_required(res)
        return res

    def _warn(name: str, status: int, why: str) -> None:
        log.warning("%s would refuse %d (no status field): %s", name, status, why)

    def _attempt(pid: int, row) -> tuple[str, int]:
        """One try on a hero below the top: ('short'|'ok'|'success', stones
        paid). A shortfall writes nothing."""
        info = cfg.hero_breakthrough(int(row["breakthrough_level"]))
        cost = int(info["breakthrough_stone"] or 0)
        if _stones(pid) < cost:
            return "short", 0
        db.take_item(conn, pid, STONE_ITEM, cost)
        score = int(row["breakthrough_score"]) + rand.randint(
            int(info["breakthrough_min"]), int(info["breakthrough_max"])
        )
        level = int(row["breakthrough_level"])
        success = rand.random() < success_rate(info, score)
        if success:
            level, score = level + 1, 0
        conn.execute(
            "UPDATE heroes SET breakthrough_level = ?, breakthrough_score = ?"
            " WHERE id = ?", (level, score, int(row["id"])),
        )
        conn.commit()
        return ("success" if success else "ok"), cost

    def _run(session: Session, req, name: str, auto: bool):
        player = _player(session)
        pid = int(player["id"])
        ensure_week(conn, pid, now_of())
        row = _hero(pid, req.entry)
        if row is None:
            _warn(name, STATUS_NO_HERO, f"hero {req.entry}")
            return _res(name, None)
        unlock = cfg.function_unlock(FUNCTION)
        if int(player["level"]) < unlock:
            _warn(name, STATUS_FUNCTION_LOCKED, f"player level {player['level']} < {unlock}")
            return _res(name, row)
        old_ability = _ability(row)
        state, tries, spent = 0, 0, 0
        while True:
            level = int(row["breakthrough_level"])
            if cfg.hero_breakthrough(level + 1) is None:
                if not tries:
                    _warn(name, STATUS_TOP_LEVEL, f"hero {row['entry']} at level {level}")
                break
            outcome, cost = _attempt(pid, row)
            if outcome == "short":
                if not tries:
                    _warn(name, STATUS_NOT_ENOUGH_ITEMS, f"needs stones {STONE_ITEM}")
                break
            tries += 1
            spent += cost
            row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if outcome == "success":
                state = 1
                break
            if not auto:
                break
        if tries:
            notify.items_changed(registry, session, [(STONE_ITEM, _stones(pid))])
            notify.hero_changed(registry, session, int(row["entry"]), {
                "breakthrough_level": int(row["breakthrough_level"]),
                "breakthrough_score": int(row["breakthrough_score"]),
                "ability": _ability(row),
            })
            log.info(
                "hero %d of player %d: %d breakthrough tries, %dx %d, level %d score %d%s",
                row["entry"], pid, tries, spent, STONE_ITEM, row["breakthrough_level"],
                row["breakthrough_score"], " (success)" if state else "",
            )
        return _res(name, row, state, old_ability)

    def attempt(session: Session, req):
        return _run(session, req, "HeroBreakthroughRes", auto=False)

    def attempt_auto(session: Session, req):
        return _run(session, req, "HeroBreakthroughAutoRes", auto=True)

    def reports(session: Session, req):
        """Other players' breakthroughs; a single-player world has none."""
        res = registry.message_class("HeroBreakthroughReportQueryRes")()
        fill_required(res)
        return res

    return {
        (5, 2811): reports,
        (5, 2813): attempt,
        (5, 2815): attempt_auto,
    }
