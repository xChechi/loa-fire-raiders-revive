"""Achievements: event_info catalog 0, 5_2241 EventAwardReq, 5_2243 AllEventAwardReq.

The client shows every event the server sends (ClientEvent:updateData,
ClientEvent.lua:33-55) and adds one it has never seen from a task notify
(RoleData:onTaskInfoChange, RoleData.lua:741-786), so the server owns the
active set: catalog-0 rows with valid = 1, unlock_level <= the player level,
and parent 0 or a claimed parent. A claimed event is no longer sent
(TaskCtr:getTaskRewardReceiveHdr drops it, TaskCtr.lua:340-384).

Progress by kind, Wave 1:
- 1 with arg1 = 0: number of owned heroes ("拥有5个英雄").
- 2: 1 once stage arg1 has a star.
- 3: the player level.
Kind 1 with arg1 != 0 is "advance N heroes to quality arg2" (12378
"进阶1名英雄到绿色品质"), not a hero count, and stays at 0 like every other
kind; each is logged once.

5_2243 `type` is the catalog the tab claims: 1 daily, 0 achievements
(NewTaskUI.lua:147-156). AllEventAwardRes has no status field;
TaskCtr:getAllTaskRewardReceiveHdr acts only when both drops and entrys are
non-empty (TaskCtr.lua:387-402).

A single claim's notifies go out before its EventAwardRes (session.reply_last;
run 11, `MMTaskListView.lua:29: attempt to index local 'data'`). Paths under
.stock/assets/scripts/app/game/. The Res handler drops the entry from
g_roleData.events and starts a 1.1 s flash on the clicked row
(view/ui/newtask/NewTaskUICtr.lua:280-321, TaskBasePanel.lua:222-236,322-332),
whose end looks up the claimed row's next event in the list the panel built
(TaskBasePanel.lua:238-258,279-297). A task notify after the Res reloads that
list without the claimed row (NewTaskUICtr.lua:534-548 -> showBtnNum(true) ->
NewTaskUI.lua:45-58 while any reward is claimable -> TaskBasePanel.lua:98-127,
a framed reload), so the lookup finds nothing, removeCellByIndex shortens
mData under the running framed load (utils/MMTaskListView.lua:55-58), and
MMListView:createItemHdr hands nil to the cell callback for the old cellNum
(utils/MMListView.lua:177-179, the traceback's :179). Sent first, the notifies reload the list while
the claimed row and its child are still in it, which is the case
getNextEventByEntry is written for.

Daily tasks, Wave 2 (catalog 1): active once function 10430 is open, with
valid = 1 and unlock_level <= the player level. Each row belongs to the day
db.day_key(5) (O-W2-1, "次日5点" in 10580/10590); a row of another day starts
again at 0, not done, not claimed. The counted kinds (O-W2-13, read from each
row's desc) are raised by bump() at their call sites. Kind 4 (the lunch and
dinner energy) is done from arg1:00 until arg2:00 the next morning. Every
other daily kind (arena, guild, chat, nobility) stays at 0, logged once.

The kind-4 prize (80 energy, drops 150430 / 150440) is paid in full even
above the level's max_energy (owner's decision after run 11; the client
shows energy/max_energy unclamped, GameResourcePanel.lua:189). Every other
energy prize, the level-30+ achievements included, still stops at the cap.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime

from server import db
from server.config import Config
from server.modules import drops, hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.events")

STATUS_OK = 0
STATUS_UNKNOWN = 330753    # language.db 任务不存在
STATUS_NOT_DONE = 330754   # language.db 任务未完成

CATALOG_ACHIEVEMENTS = 0
KIND_HEROES = 1
KIND_STAGE = 2
KIND_LEVEL = 3

CATALOG_DAILY = 1
DAILY_FUNCTION = 10430     # the function row that opens the daily tab
DAILY_DAY_HOUR = 5         # O-W2-1
KIND_TIME_WINDOW = 4       # 10580 / 10590: done from arg1:00 to arg2:00 next day
# The counted daily kinds (O-W2-13; the row desc each one was read from).
KIND_XP_POTION = 4522006   # 使用经验药水1次, train 5_2125
KIND_BUY_GOLD = 3866635    # 点金1次, buy 5_2143
KIND_ANGEL_TRIAL = 3932173  # 进行女神试炼1次, angeltrial 8_2513
KIND_GACHA = 4063247       # 进行抽卡3次, gacha 5_2123
KIND_FIGHT = 3342342       # stage and trial fights, told apart by arg1 below
KIND_HERO_LEVEL = 4653080  # 提升英雄等级1次, any hero level-up
KIND_HERO_SKILL = 3407892  # 升级英雄技能1次, hero 5_2103
KIND_HERO_RUNE = 5701658   # 升级英雄符文1次, rune 5_2161
DAILY_COUNTED = {
    KIND_XP_POTION, KIND_BUY_GOLD, KIND_ANGEL_TRIAL, KIND_GACHA, KIND_FIGHT,
    KIND_HERO_LEVEL, KIND_HERO_SKILL, KIND_HERO_RUNE,
}
# KIND_FIGHT arg1: 10070 "完成任意普通或精英关卡" has arg1 1 / arg2 2, 10080
# "完成精英关卡" arg1 2, 10081 "进行金币试炼" arg1 3, 14020 "进行英雄试炼" arg1 4.
FIGHT_NORMAL = 1
FIGHT_ELITE = 2
FIGHT_GOLD_TRIAL = 3
FIGHT_HERO_TRIAL = 4

_logged_kinds: set = set()


def _claimed(conn: sqlite3.Connection, pid: int) -> set[int]:
    return {
        int(r["entry"]) for r in conn.execute(
            "SELECT entry FROM events WHERE player_id = ? AND claimed = 1", (pid,)
        )
    }


def _progress(conn: sqlite3.Connection, pid: int, level: int, ev) -> int | None:
    """The progress of one event, or None for a kind Wave 1 does not count."""
    kind = int(ev["kind"])
    if kind == KIND_HEROES and int(ev["arg1"] or 0) == 0:
        return int(conn.execute(
            "SELECT COUNT(*) FROM heroes WHERE player_id = ?", (pid,)
        ).fetchone()[0])
    if kind == KIND_STAGE:
        row = db.level_progress(conn, pid, int(ev["arg1"] or 0))
        return 1 if row is not None and int(row["star"]) > 0 else 0
    if kind == KIND_LEVEL:
        return level
    key = "1 (hero quality)" if kind == KIND_HEROES else str(kind)
    if key not in _logged_kinds:
        _logged_kinds.add(key)
        log.info("event kind %s is not counted in Wave 1; its events stay at 0", key)
    return None


def _in_window(ev, now: float) -> bool:
    """Kind 4: is the local hour of `now` inside [arg1:00, arg2:00 next day)?"""
    start, end = int(ev["arg1"] or 0), int(ev["arg2"] or 0)
    hour = datetime.fromtimestamp(now).hour
    return (hour - end) % 24 >= (start - end) % 24


def _refresh_daily(
    conn: sqlite3.Connection, cfg: Config, registry: Registry,
    session: Session | None, pid: int, level: int, stored: dict, now: float,
) -> None:
    """The daily rows of refresh(); the caller has checked function 10430."""
    today = db.day_key(DAILY_DAY_HOUR, now)
    for ev in cfg.events_catalog(CATALOG_DAILY):
        entry, kind = int(ev["entry"]), int(ev["kind"])
        if int(ev["valid"] or 0) != 1 or int(ev["unlock_level"] or 0) > level:
            continue
        row = stored.get(entry)
        fresh = row is None or row["day"] != today
        if not fresh and int(row["claimed"]):
            continue
        progress = 0 if fresh else int(row["progress"])
        if kind == KIND_TIME_WINDOW:
            done = int(_in_window(ev, now))
        elif kind in DAILY_COUNTED:
            done = int(progress >= int(ev["arg0"] or 0))
        else:
            key = f"daily {kind}"
            if key not in _logged_kinds:
                _logged_kinds.add(key)
                log.info("daily task kind %d is not counted; its tasks stay at 0", kind)
            progress, done = 0, 0
        if not fresh and (int(row["progress"]), int(row["done"])) == (progress, done):
            continue
        conn.execute(
            "INSERT INTO events (player_id, entry, progress, done, claimed, day)"
            " VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT (player_id, entry) DO UPDATE SET"
            " progress = excluded.progress, done = excluded.done, claimed = 0,"
            " day = excluded.day",
            (pid, entry, progress, done, today),
        )
        if session is not None:
            notify.task_changed(registry, session, entry, progress, bool(done))


def refresh(
    conn: sqlite3.Connection, cfg: Config, registry: Registry,
    session: Session | None, pid: int, now: float | None = None,
) -> None:
    """Bring every active achievement's and daily task's row up to date; push
    one task notify per row that changed (a new row is a change). With no
    session (inside query_myself) the rows ride in QueryMyselfRes.events
    instead."""
    pid = int(pid)
    now = time.time() if now is None else float(now)
    level = int(conn.execute(
        "SELECT level FROM players WHERE id = ?", (pid,)
    ).fetchone()[0])
    claimed = _claimed(conn, pid)
    stored = {
        int(r["entry"]): r for r in conn.execute(
            "SELECT * FROM events WHERE player_id = ?", (pid,)
        )
    }
    for ev in cfg.events_catalog(CATALOG_ACHIEVEMENTS):
        entry, parent = int(ev["entry"]), int(ev["parent"] or 0)
        if (
            int(ev["valid"] or 0) != 1
            or int(ev["unlock_level"] or 0) > level
            or entry in claimed
            or (parent != 0 and parent not in claimed)
        ):
            continue
        progress = _progress(conn, pid, level, ev)
        done = int(progress is not None and progress >= int(ev["arg0"] or 0))
        progress = progress or 0
        row = stored.get(entry)
        if row is not None:
            done = max(done, int(row["done"]))  # a finished achievement stays finished
            if (int(row["progress"]), int(row["done"])) == (progress, done):
                continue
        conn.execute(
            "INSERT INTO events (player_id, entry, progress, done) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (player_id, entry) DO UPDATE SET progress = excluded.progress,"
            " done = excluded.done",
            (pid, entry, progress, done),
        )
        if session is not None:
            notify.task_changed(registry, session, entry, progress, bool(done))
    if level >= cfg.function_unlock(DAILY_FUNCTION):
        _refresh_daily(conn, cfg, registry, session, pid, level, stored, now)
    conn.commit()


def bump(
    conn: sqlite3.Connection, cfg: Config, registry: Registry,
    session: Session | None, pid: int, kind: int, arg1: int = 0, n: int = 1,
    now: float | None = None,
) -> None:
    """Raise today's active daily tasks of `kind` by n, up to their arg0, and
    push the task notify of each one that changed. arg1 tells the KIND_FIGHT
    rows apart: it matches a row's arg1, or its arg2 when that is not 0.
    Only daily rows are touched, and nothing while the daily tab is locked."""
    pid, arg1 = int(pid), int(arg1)
    now = time.time() if now is None else float(now)
    level = int(conn.execute(
        "SELECT level FROM players WHERE id = ?", (pid,)
    ).fetchone()[0])
    if level < cfg.function_unlock(DAILY_FUNCTION):
        return
    stored = {
        int(r["entry"]): r for r in conn.execute(
            "SELECT * FROM events WHERE player_id = ?", (pid,)
        )
    }
    _refresh_daily(conn, cfg, registry, session, pid, level, stored, now)
    today = db.day_key(DAILY_DAY_HOUR, now)
    for ev in cfg.events_catalog(CATALOG_DAILY):
        if int(ev["kind"]) != int(kind) or not (
            arg1 == int(ev["arg1"] or 0) or (arg1 and arg1 == int(ev["arg2"] or 0))
        ):
            continue
        entry, goal = int(ev["entry"]), int(ev["arg0"] or 0)
        row = conn.execute(
            "SELECT * FROM events WHERE player_id = ? AND entry = ? AND day = ?"
            " AND claimed = 0", (pid, entry, today),
        ).fetchone()
        if row is None or int(row["progress"]) >= goal:
            continue
        progress = min(goal, int(row["progress"]) + int(n))
        done = int(progress >= goal)
        conn.execute(
            "UPDATE events SET progress = ?, done = ? WHERE player_id = ? AND entry = ?",
            (progress, done, pid, entry),
        )
        if session is not None:
            notify.task_changed(registry, session, entry, progress, bool(done))
        log.info("player %d daily task %d: %d/%d", pid, entry, progress, goal)
    conn.commit()


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _pid(session: Session) -> int:
        if session.player_id is not None:
            return int(session.player_id)
        return int(db.find_player(conn, settings.username)["id"])

    def _pay(session: Session, pid: int, triples, over_cap: bool = False) -> dict:
        """grant_prizes vets the whole list before it writes, so a raise
        leaves every event unclaimed."""
        changed = item.grant_prizes(conn, cfg, pid, triples, energy_over_cap=over_cap)
        for hero_row_id in changed["heroes"]:
            hero_row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (hero_row_id,)
            ).fetchone()
            notify.hero_added(
                registry, session, hero.build_client_hero(registry, cfg, hero_row)
            )
        item.announce(registry, session, changed)
        notify.items_changed(registry, session, changed["items"])
        notify.player_changed(registry, session, {
            "gold": changed["gold"], "diamond": changed["diamond"],
            "energy": changed["energy"],
        })
        return changed

    def _claim(pid: int, entries) -> None:
        conn.executemany(
            "UPDATE events SET claimed = 1 WHERE player_id = ? AND entry = ?",
            [(pid, int(e)) for e in entries],
        )
        conn.commit()

    def award(session: Session, req):
        name = "EventAwardRes"
        pid, entry = _pid(session), int(req.entry)
        refresh(conn, cfg, registry, session, pid, now_of())
        ev = cfg.event(entry)
        row = conn.execute(
            "SELECT * FROM events WHERE player_id = ? AND entry = ?", (pid, entry)
        ).fetchone()
        status = STATUS_OK
        if ev is None or int(ev["catalog"]) not in (CATALOG_ACHIEVEMENTS, CATALOG_DAILY) \
                or row is None or int(row["claimed"]):
            status = STATUS_UNKNOWN
        elif not int(row["done"]):
            status = STATUS_NOT_DONE
        if status:
            log.info("5_2241 event %d of player %d refused %d", entry, pid, status)
            res = registry.message_class(name)(status=status, entry=entry)
            fill_required(res)
            return res
        rolled = drops.roll(cfg, int(ev["drops"] or 0), rng=rng)
        _pay(session, pid, drops.as_triples(rolled),
             over_cap=int(ev["kind"]) == KIND_TIME_WINDOW)
        _claim(pid, [entry])
        refresh(conn, cfg, registry, session, pid, now_of())  # activates the children
        log.info("player %d claimed event %d: %s", pid, entry, drops.as_triples(rolled))
        session.reply_last = True  # the task notifies first; see the module docstring
        res = registry.message_class(name)(status=STATUS_OK, entry=entry)
        fill_required(res)
        return res

    def award_all(session: Session, req):
        catalog, pid = int(req.type), _pid(session)
        refresh(conn, cfg, registry, session, pid, now_of())
        entries, rolled, over_cap = [], [], False
        for row in conn.execute(
            "SELECT entry FROM events WHERE player_id = ? AND done = 1 AND claimed = 0"
            " ORDER BY entry", (pid,),
        ).fetchall():
            ev = cfg.event(int(row["entry"]))
            if ev is None or int(ev["catalog"]) != catalog:
                continue
            entries.append(int(row["entry"]))
            rolled.extend(drops.roll(cfg, int(ev["drops"] or 0), rng=rng))
            # Kind 4 is the only daily row whose drops pay energy, and no
            # achievement is kind 4, so the flag covers exactly its prize.
            over_cap = over_cap or int(ev["kind"]) == KIND_TIME_WINDOW
        res = registry.message_class("AllEventAwardRes")(
            eventNum=len(entries), type=catalog
        )
        if entries:
            changed = _pay(session, pid, drops.as_triples(rolled), over_cap=over_cap)
            _claim(pid, entries)
            refresh(conn, cfg, registry, session, pid, now_of())
            for entry in drops.to_prize_entries(registry, rolled):
                res.drops.add().CopyFrom(entry)
            item.mark_converted(res.drops, changed)
            res.entrys.extend(entries)
            log.info("player %d claimed events %s of catalog %d", pid, entries, catalog)
        fill_required(res)
        return res

    return {(5, 2241): award, (5, 2243): award_all}
