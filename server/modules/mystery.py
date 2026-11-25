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
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import shop
from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.mystery")

STORE = 2
FUNCTION = 10350          # FunctionType.MYSTERYSTORE_TYPE
DAY_HOUR = 0              # the counters reset at midnight (A6)

_default_rng = random.SystemRandom()


def is_permanent(store_row, player: sqlite3.Row) -> bool:
    """VIP >= vip_buy_level keeps store 2 open (FunctionType.lua:1184-1193)."""
    return int(player["vip"]) >= int(store_row["vip_buy_level"])


def present(player: sqlite3.Row, now: float) -> bool:
    appear, stay = int(player["mystery_appear"]), int(player["mystery_stay"])
    return appear > 0 and (stay == 0 or now < appear + stay)


def expire(registry: Registry, session: Session, player: sqlite3.Row, now: float) -> bool:
    """Queue 5_2022 {store 2} once the stay of an appearance has run out."""
    appear, stay = int(player["mystery_appear"]), int(player["mystery_stay"])
    if appear <= 0 or stay <= 0 or now < appear + stay:
        return False
    msg = registry.message_class("DisapperStoreNotify")(store=STORE)
    fill_required(msg)
    session.queue(5, 2022, msg)
    log.info("mystery merchant left player %d (appeared %d, stay %d)",
             int(player["id"]), appear, stay)
    return True


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
    """Count `amount` energy spent and maybe bring the merchant. True when it
    appeared (5_2020 queued)."""
    rng = _default_rng if rng is None else rng
    now = time.time() if now is None else float(now)
    today = db.day_key(DAY_HOUR, now)
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    if player["mystery_day"] != today:
        conn.execute(
            "UPDATE players SET energy_use = 0, mystery_shown = 0, mystery_day = ?"
            " WHERE id = ?", (today, pid),
        )
    conn.execute(
        "UPDATE players SET energy_use = energy_use + ?,"
        " mystery_energy = mystery_energy + ? WHERE id = ?",
        (int(amount), int(amount), pid),
    )
    conn.commit()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    store_row = cfg.store(STORE)
    spent = int(player["mystery_energy"])
    if (
        int(player["level"]) < cfg.function_unlock(FUNCTION)
        or int(player["mystery_shown"]) >= cfg.variable_int("MAX_SHOW_STORE_TIMES", 1)
        or spent < int(store_row["min_appeared_cost"])
    ):
        return False
    if spent < int(store_row["max_appeared_cost"]) and not (
        rng.random() < float(store_row["appeared_rate"])
    ):
        return False

    at = int(now)
    stay = 0 if is_permanent(store_row, player) else int(store_row["stay_time"])
    slots = json.dumps(shop.generate_slots(conn, cfg, player, store_row, rng))
    conn.execute(
        "INSERT INTO stores (player_id, store, lastupdate, slots, refresh_used, refresh_day)"
        " VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT(player_id, store) DO UPDATE SET"
        " lastupdate = excluded.lastupdate, slots = excluded.slots,"
        " refresh_used = 0, refresh_day = excluded.refresh_day",
        (pid, STORE, at, slots, today),
    )
    conn.execute(
        "UPDATE players SET mystery_energy = 0, mystery_appear = ?, mystery_stay = ?,"
        " mystery_shown = mystery_shown + 1 WHERE id = ?",
        (at, stay, pid),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM stores WHERE player_id = ? AND store = ?", (pid, STORE)
    ).fetchone()
    msg = registry.message_class("ShowStoreNotify")(onEnergyCost=True)
    msg.store.CopyFrom(shop.client_store(registry, store_row, row, at, stay))
    fill_required(msg)
    session.queue(5, 2020, msg)
    log.info("mystery merchant appeared for player %d after %d energy (stay %d)",
             pid, spent, stay)
    return True
