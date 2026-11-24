"""Shops: 5_2129 QueryOrRefreshStoreInfoReq, 5_2135 BuyMerchandiseReq.

The client sends op 1 to open a shop and op 2 to refresh it ("1 查询 2 花代币刷新",
NormalShop.lua:178; AllShopUI.lua:621,1169). A refresh is free while
remain_free_refresh > 0 (AllShopUI.lua:1158-1169), then costs
MMTools:getCostNum(store_info.refresh_cost, paid refreshes so far) in
refresh_cost_type (MMTools.lua:1433-1451). The client counts the paid ones in
ClientDailyStats.store_refresh_times_<store> (AllShopUI.lua:736-739), so the
server's paid index is refresh_used - free_refresh.

A slot is generated from merchandise_info(store) rows that fit the player's
level, VIP and cleared chapters, `merchandise_amount` of them picked by weight
without replacement. BuyMerchandiseReq.index is the 0-based slot
(ShopBuyPanel.lua:486, buyIndex - 1).

`discount` is always 100. The client multiplies the price by discount/100
whenever the field is present (AllShopUI.lua:831-833) and shows no badge at 100
("不打折和10折不显示", NormalShopRender.lua:245-246), so 100 is the one value
that keeps the displayed price right however the decoder treats an unset field.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from datetime import date

from server import db
from server.config import Config
from server.modules import item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.shop")

STATUS_OK = 0
STATUS_INTERNAL = 327681             # language.db 系统内部错误
STATUS_NOT_ENOUGH_GOLD = 327937      # language.db 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938   # language.db 钻石不足
STATUS_NO_REFRESH_LEFT = 329985      # language.db 今日刷新次数已用完
STATUS_SOLD_OUT = 329988             # language.db 此商品已经卖完

OP_REFRESH = 2
NO_DISCOUNT = 100

# Only these two currencies are tracked in Wave 1 (players.gold/diamond).
CURRENCY_GOLD = item.CATEGORY_GOLD
CURRENCY_DIAMOND = item.CATEGORY_DIAMOND
SHORT_STATUS = {
    CURRENCY_GOLD: STATUS_NOT_ENOUGH_GOLD,
    CURRENCY_DIAMOND: STATUS_NOT_ENOUGH_DIAMOND,
}

_default_rng = random.SystemRandom()


def refresh_cost(cost: str, paid_before: int) -> int:
    """MMTools:getCostNum: "price|count" tiers; 0 once every tier is used."""
    seen = 0
    for tier in str(cost).split(","):
        parts = tier.split("|")
        if len(parts) < 2:
            continue
        seen += int(parts[1])
        if paid_before + 1 <= seen:
            return int(parts[0])
    return 0


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    rng = _default_rng if rng is None else rng

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _highest_cleared_chapter(pid: int) -> int:
        best = 0
        for row in db.levels_of(conn, pid):
            if int(row["star"]) <= 0:
                continue
            stage = cfg.stage(int(row["level"]))
            if stage is not None:
                best = max(best, int(stage["chapter"]))
        return best

    def _generate(player: sqlite3.Row, store_row) -> list[dict]:
        level, vip = int(player["level"]), int(player["vip"])
        chapter = _highest_cleared_chapter(int(player["id"]))
        pool = [
            r for r in cfg.merchandise(int(store_row["entry"]))
            if int(r["min_level"]) <= level <= int(r["max_level"])
            and int(r["min_vip"]) <= vip <= int(r["max_vip"])
            and int(r["unlock_chapter"] or 0) <= chapter
            and int(r["weight"] or 0) > 0
        ]
        slots: list[dict] = []
        for _ in range(min(int(store_row["merchandise_amount"]), len(pool))):
            pick = rng.randrange(sum(int(r["weight"]) for r in pool))
            for at, row in enumerate(pool):
                pick -= int(row["weight"])
                if pick < 0:
                    slots.append({"merchandise": int(row["entry"]), "buy": 0})
                    del pool[at]
                    break
        return slots

    def _load(player: sqlite3.Row, store_row) -> sqlite3.Row:
        """The saved store, created on first sight; the refresh counter starts
        again on a new ISO day."""
        pid, store = int(player["id"]), int(store_row["entry"])
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT * FROM stores WHERE player_id = ? AND store = ?", (pid, store)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO stores (player_id, store, lastupdate, slots,"
                " refresh_used, refresh_day) VALUES (?, ?, ?, ?, 0, ?)",
                (pid, store, int(time.time()),
                 json.dumps(_generate(player, store_row)), today),
            )
        elif row["refresh_day"] != today:
            conn.execute(
                "UPDATE stores SET refresh_used = 0, refresh_day = ?"
                " WHERE player_id = ? AND store = ?",
                (today, pid, store),
            )
        conn.commit()
        return conn.execute(
            "SELECT * FROM stores WHERE player_id = ? AND store = ?", (pid, store)
        ).fetchone()

    def _client_store(store_row, row: sqlite3.Row):
        free_left = max(0, int(store_row["free_refresh"]) - int(row["refresh_used"]))
        msg = registry.message_class("ClientStore")(
            store=int(store_row["entry"]),
            lastupdate=int(row["lastupdate"]),
            remain_free_refresh=free_left,
        )
        for index, slot in enumerate(json.loads(row["slots"])):
            msg.merchandise.add(
                index=index,
                merchandise=int(slot["merchandise"]),
                buy=int(slot["buy"]),
                discount=NO_DISCOUNT,
            )
        fill_required(msg)
        return msg

    def _refused(name: str, status: int, why: str):
        log.info("%s refused %d: %s", name, status, why)
        res = registry.message_class(name)(status=status)
        fill_required(res)
        return res

    def _charge(session: Session, pid: int, currency: int, amount: int) -> None:
        """The caller checked the balance, so db.spend does not raise."""
        if currency == CURRENCY_GOLD:
            db.spend(conn, pid, gold=amount)
            field = "gold"
        else:
            db.spend(conn, pid, diamond=amount)
            field = "diamond"
        value = conn.execute(
            f"SELECT {field} FROM players WHERE id = ?", (pid,)
        ).fetchone()[0]
        notify.player_changed(registry, session, {field: int(value)})

    def _balance(player: sqlite3.Row, currency: int) -> int:
        return int(player["gold" if currency == CURRENCY_GOLD else "diamond"])

    def query_or_refresh(session: Session, req):
        name = "QueryOrRefreshStoreInfoRes"
        store, op = int(req.type), int(req.op)
        store_row = cfg.store(store)
        if store_row is None:
            return _refused(name, STATUS_INTERNAL, f"store {store} not in store_info")
        player = _player(session)
        pid = int(player["id"])
        row = _load(player, store_row)
        if op == OP_REFRESH:
            used, free = int(row["refresh_used"]), int(store_row["free_refresh"])
            if used >= free:
                currency = int(store_row["refresh_cost_type"])
                cost = refresh_cost(store_row["refresh_cost"], used - free)
                if cost <= 0:
                    return _refused(name, STATUS_NO_REFRESH_LEFT, f"store {store}: tiers used")
                if currency not in SHORT_STATUS:
                    log.warning(
                        "store %d refresh in currency %d is not tracked in Wave 1",
                        store, currency,
                    )
                    return _refused(name, STATUS_INTERNAL, f"currency {currency}")
                if _balance(player, currency) < cost:
                    return _refused(name, SHORT_STATUS[currency], f"store {store}: {cost}")
                _charge(session, pid, currency, cost)
            conn.execute(
                "UPDATE stores SET slots = ?, lastupdate = ?, refresh_used = refresh_used + 1"
                " WHERE player_id = ? AND store = ?",
                (json.dumps(_generate(player, store_row)), int(time.time()), pid, store),
            )
            conn.commit()
            row = _load(player, store_row)
            log.info("store %d refreshed for player %d (refresh %d today)",
                     store, pid, int(row["refresh_used"]))
        res = registry.message_class(name)(status=STATUS_OK)
        res.store.CopyFrom(_client_store(store_row, row))
        fill_required(res)
        return res

    def buy(session: Session, req):
        name = "BuyMerchandiseRes"
        store, index = int(req.type), int(req.index)
        store_row = cfg.store(store)
        if store_row is None:
            return _refused(name, STATUS_INTERNAL, f"store {store} not in store_info")
        player = _player(session)
        pid = int(player["id"])
        row = _load(player, store_row)
        slots = json.loads(row["slots"])
        if not 0 <= index < len(slots):
            return _refused(name, STATUS_INTERNAL, f"store {store} has no slot {index}")
        if int(slots[index]["buy"]):
            return _refused(name, STATUS_SOLD_OUT, f"store {store} slot {index} bought")
        merch = next(
            (r for r in cfg.merchandise(store)
             if int(r["entry"]) == int(slots[index]["merchandise"])),
            None,
        )
        if merch is None or cfg.item(int(merch["item"])) is None:
            return _refused(name, STATUS_INTERNAL, f"merchandise {slots[index]} unknown")
        currency, price = int(merch["price_type"]), int(merch["price"])
        if currency not in SHORT_STATUS:
            log.warning(
                "merchandise %d price_type %d is not tracked in Wave 1; refused",
                int(merch["entry"]), currency,
            )
            return _refused(name, STATUS_INTERNAL, f"price_type {currency}")
        if _balance(player, currency) < price:
            return _refused(name, SHORT_STATUS[currency], f"{price} in {currency}")
        _charge(session, pid, currency, price)
        granted = item.grant_prizes(
            conn, cfg, pid,
            [(item.CATEGORY_ITEM, int(merch["item"]), int(merch["amount"]))],
        )
        notify.items_changed(registry, session, granted["items"])
        item.announce(registry, session, granted)
        slots[index]["buy"] = 1
        conn.execute(
            "UPDATE stores SET slots = ? WHERE player_id = ? AND store = ?",
            (json.dumps(slots), pid, store),
        )
        conn.commit()
        log.info("player %d bought merchandise %d (store %d slot %d) for %d in %d",
                 pid, int(merch["entry"]), store, index, price, currency)
        res = registry.message_class(name)(status=STATUS_OK)
        fill_required(res)
        return res

    return {(5, 2129): query_or_refresh, (5, 2135): buy}
