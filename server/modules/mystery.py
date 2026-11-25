"""The mystery merchant (神秘商人): store 2, pushed on energy spent (O-W2-11).

store_info(2): merchandise_amount 12, appeared_type 2, min/max_appeared_cost
120/600, appeared_rate 0.05, stay_time 3600, vip_buy_level 14.
MAX_SHOW_STORE_TIMES is 1 per day; function(10350).unlock_level is 16
(FunctionType.MYSTERYSTORE_TYPE, FunctionType.lua:73).

- Energy spent since the last appearance accumulates in players.mystery_energy.
  From min_appeared_cost on every spend rolls appeared_rate; at
  max_appeared_cost the merchant appears for sure.
- energy_use (ClientDailyStats field 9) and mystery_shown (show_store_times,
  field 8) belong to players.mystery_day and start again at midnight; this
  module writes mystery_day = today whenever it updates them.
- An appearance pushes 5_2020 ShowStoreNotify {store, onEnergyCost = true}
  (RPGGame.lua:846-885). The client keeps store.lastappear/stay_time and
  opens the shop only while lastappear + stay_time - now > 0, or always when
  stay_time is 0 (FunctionType.lua:598-620). VIP >= vip_buy_level has the
  store permanently: stay_time 0.
- When the stay runs out the client sends 5_2129 {type 2, op 1}
  ("到了要给后端发查询消息才会触发离开消息", GameSceneOtherPanel.lua:75-92); the
  shop answers it with 5_2022 DisapperStoreNotify {store 2} (RPGGame.lua:937)
  through `expire`.

The celestial merchant (神界商人), store 7, is store 2's twin with its own
numbers and counters (plan B2 Wave 3 A3, O-W3-3): store_info(7)
merchandise_amount 6, min/max_appeared_cost 200/400, appeared_rate 0.005,
stay_time 3600; function(10370).unlock_level is 19 (FunctionType.LEGENDS_TYPE,
opened with 5_2129 {type 7, op 1}, FunctionType.lua:1401-1404). It keeps
players.legends_*, has its own MAX_SHOW_STORE_TIMES per day and is never
permanent (the VIP rule of FunctionType.lua:1184-1193 names store 2 only).
Its appearance is the same 5_2020 push with store 7 (RPGGame.lua:884-911); the
client opens UI_LEGENDS only while legendsAppearTime + legendsStayTime > now
(FunctionType.lua:619-627), re-asks 5_2129 {type 7} when the time runs out
(GameSceneOtherPanel.lua:95-105) and leaves on 5_2022 {store 7}
(RPGGame.lua:955-962). "Send away" is 5_2589 ExitSoulStoreReq {}
(LegendsUI.lua:156-162), which ends the stay at once (`send_away`).
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from typing import NamedTuple

from server import db
from server.config import Config
from server.modules import shop
from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.mystery")

STORE = 2
FUNCTION = 10350          # FunctionType.MYSTERYSTORE_TYPE
DAY_HOUR = 0              # the counters reset at midnight (A6)
LEGENDS_STORE = 7
LEGENDS_FUNCTION = 10370  # FunctionType.LEGENDS_TYPE, 神界商人


class _Columns(NamedTuple):
    """The players columns and unlock function of one merchant."""
    energy: str
    appear: str
    stay: str
    shown: str
    function: int


COLUMNS = {
    STORE: _Columns("mystery_energy", "mystery_appear", "mystery_stay",
                    "mystery_shown", FUNCTION),
    LEGENDS_STORE: _Columns("legends_energy", "legends_appear", "legends_stay",
                            "legends_shown", LEGENDS_FUNCTION),
}

_default_rng = random.SystemRandom()


def is_permanent(store_row, player: sqlite3.Row) -> bool:
    """VIP >= vip_buy_level keeps store 2 open (FunctionType.lua:1184-1193)."""
    return int(player["vip"]) >= int(store_row["vip_buy_level"])


def present(player: sqlite3.Row, now: float, store: int = STORE) -> bool:
    col = COLUMNS[store]
    appear, stay = int(player[col.appear]), int(player[col.stay])
    return appear > 0 and (stay == 0 or now < appear + stay)


def expire(registry: Registry, session: Session, player: sqlite3.Row, now: float,
           stores: tuple[int, ...] = (STORE, LEGENDS_STORE)) -> bool:
    """Queue 5_2022 {store} for each of `stores` whose stay has run out."""
    left = False
    for store in stores:
        col = COLUMNS[store]
        appear, stay = int(player[col.appear]), int(player[col.stay])
        if appear <= 0 or stay <= 0 or now < appear + stay:
            continue
        msg = registry.message_class("DisapperStoreNotify")(store=store)
        fill_required(msg)
        session.queue(5, 2022, msg)
        log.info("merchant of store %d left player %d (appeared %d, stay %d)",
                 store, int(player["id"]), appear, stay)
        left = True
    return left


def send_away(conn: sqlite3.Connection, pid: int, now: float) -> None:
    """5_2589: end store 7's stay now, so that appear + stay <= now. A stay of
    0 would mean "permanent", so a stay sent away in its first second moves
    the appearance one second back instead."""
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    appear = int(player["legends_appear"])
    if appear <= 0:
        log.info("5_2589 for player %d with no celestial merchant", pid)
        return
    stay = int(now) - appear
    if stay <= 0:
        appear, stay = int(now) - 1, 1
    conn.execute(
        "UPDATE players SET legends_appear = ?, legends_stay = ? WHERE id = ?",
        (appear, stay, pid),
    )
    conn.commit()
    log.info("celestial merchant sent away by player %d", pid)


def on_energy_spent(
    conn: sqlite3.Connection,
    cfg: Config,
    registry: Registry,
    session: Session,
    pid: int,
    amount: int,
    rng=None,
    now: float | None = None,
) -> bool:
    """Count `amount` energy spent and maybe bring store 2, then store 7. True
    when either appeared (one 5_2020 queued per appearance)."""
    rng = _default_rng if rng is None else rng
    now = time.time() if now is None else float(now)
    today = db.day_key(DAY_HOUR, now)
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    if player["mystery_day"] != today:
        conn.execute(
            "UPDATE players SET energy_use = 0, mystery_shown = 0, mystery_day = ?"
            " WHERE id = ?", (today, pid),
        )
    if player["legends_day"] != today:
        conn.execute(
            "UPDATE players SET legends_shown = 0, legends_day = ? WHERE id = ?",
            (today, pid),
        )
    conn.execute(
        "UPDATE players SET energy_use = energy_use + ?,"
        " mystery_energy = mystery_energy + ?, legends_energy = legends_energy + ?"
        " WHERE id = ?",
        (int(amount), int(amount), int(amount), pid),
    )
    conn.commit()
    appeared = False
    for store in (STORE, LEGENDS_STORE):
        if _roll(conn, cfg, registry, session, pid, store, rng, now, today):
            appeared = True
    return appeared


def _roll(conn: sqlite3.Connection, cfg: Config, registry: Registry, session: Session,
          pid: int, store: int, rng, now: float, today: str) -> bool:
    """One merchant's appearance roll on its own counters (O-W2-11, O-W3-3)."""
    col = COLUMNS[store]
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    store_row = cfg.store(store)
    spent = int(player[col.energy])
    if (
        int(player["level"]) < cfg.function_unlock(col.function)
        or int(player[col.shown]) >= cfg.variable_int("MAX_SHOW_STORE_TIMES", 1)
        or spent < int(store_row["min_appeared_cost"])
    ):
        return False
    if spent < int(store_row["max_appeared_cost"]) and not (
        rng.random() < float(store_row["appeared_rate"])
    ):
        return False

    at = int(now)
    permanent = store == STORE and is_permanent(store_row, player)
    stay = 0 if permanent else int(store_row["stay_time"])
    slots = json.dumps(shop.generate_slots(conn, cfg, player, store_row, rng))
    conn.execute(
        "INSERT INTO stores (player_id, store, lastupdate, slots, refresh_used, refresh_day)"
        " VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT(player_id, store) DO UPDATE SET"
        " lastupdate = excluded.lastupdate, slots = excluded.slots,"
        " refresh_used = 0, refresh_day = excluded.refresh_day",
        (pid, store, at, slots, today),
    )
    conn.execute(
        f"UPDATE players SET {col.energy} = 0, {col.appear} = ?, {col.stay} = ?,"
        f" {col.shown} = {col.shown} + 1 WHERE id = ?",
        (at, stay, pid),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM stores WHERE player_id = ? AND store = ?", (pid, store)
    ).fetchone()
    msg = registry.message_class("ShowStoreNotify")(onEnergyCost=True)
    msg.store.CopyFrom(shop.client_store(registry, store_row, row, at, stay))
    fill_required(msg)
    session.queue(5, 2020, msg)
    log.info("merchant of store %d appeared for player %d after %d energy (stay %d)",
             store, pid, spent, stay)
    return True
