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
"""

from __future__ import annotations

import logging
import random
import sqlite3

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


def refresh(
    conn: sqlite3.Connection, cfg: Config, registry: Registry,
    session: Session | None, pid: int,
) -> None:
    """Bring every active achievement's row up to date; push one task notify
    per row that changed (a new row is a change). With no session (inside
    query_myself) the rows ride in QueryMyselfRes.events instead."""
    pid = int(pid)
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
    conn.commit()


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    def _pid(session: Session) -> int:
        if session.player_id is not None:
            return int(session.player_id)
        return int(db.find_player(conn, settings.username)["id"])

    def _pay(session: Session, pid: int, triples) -> dict:
        """grant_prizes vets the whole list before it writes, so a raise
        leaves every event unclaimed."""
        changed = item.grant_prizes(conn, cfg, pid, triples)
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
        refresh(conn, cfg, registry, session, pid)
        ev = cfg.event(entry)
        row = conn.execute(
            "SELECT * FROM events WHERE player_id = ? AND entry = ?", (pid, entry)
        ).fetchone()
        status = STATUS_OK
        if ev is None or int(ev["catalog"]) != CATALOG_ACHIEVEMENTS or row is None \
                or int(row["claimed"]):
            status = STATUS_UNKNOWN
        elif not int(row["done"]):
            status = STATUS_NOT_DONE
        if status:
            log.info("5_2241 event %d of player %d refused %d", entry, pid, status)
            res = registry.message_class(name)(status=status, entry=entry)
            fill_required(res)
            return res
        rolled = drops.roll(cfg, int(ev["drops"] or 0), rng=rng)
        _pay(session, pid, drops.as_triples(rolled))
        _claim(pid, [entry])
        refresh(conn, cfg, registry, session, pid)  # activates the children
        log.info("player %d claimed event %d: %s", pid, entry, drops.as_triples(rolled))
        res = registry.message_class(name)(status=STATUS_OK, entry=entry)
        fill_required(res)
        return res

    def award_all(session: Session, req):
        catalog, pid = int(req.type), _pid(session)
        refresh(conn, cfg, registry, session, pid)
        entries, rolled = [], []
        for row in conn.execute(
            "SELECT entry FROM events WHERE player_id = ? AND done = 1 AND claimed = 0"
            " ORDER BY entry", (pid,),
        ).fetchall():
            ev = cfg.event(int(row["entry"]))
            if ev is None or int(ev["catalog"]) != catalog:
                continue
            entries.append(int(row["entry"]))
            rolled.extend(drops.roll(cfg, int(ev["drops"] or 0), rng=rng))
        res = registry.message_class("AllEventAwardRes")(
            eventNum=len(entries), type=catalog
        )
        if entries:
            changed = _pay(session, pid, drops.as_triples(rolled))
            _claim(pid, entries)
            refresh(conn, cfg, registry, session, pid)
            for entry in drops.to_prize_entries(registry, rolled):
                res.drops.add().CopyFrom(entry)
            item.mark_converted(res.drops, changed)
            res.entrys.extend(entries)
            log.info("player %d claimed events %s of catalog %d", pid, entries, catalog)
        fill_required(res)
        return res

    return {(5, 2241): award, (5, 2243): award_all}
