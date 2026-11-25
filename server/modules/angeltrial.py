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
from server.modules import drops, item, notify
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
            # The fights land in the second angel-trials commit.
            return _refused(name, STATUS_NO_ENEMY, pid, f"floor {level} is a fight")
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

    return {
        (8, 2501): query,
        (8, 2503): start,
        (8, 2505): trigger,
        (8, 2507): query_buffs,
        (8, 2517): rank,
        (8, 2519): self_rank,
    }
