"""Bag: 5_2137 SellItemReq, 5_2149 SellAllGoldStockReq, 5_2131 UseItemReq,
5_2933 ItemBuyReq, and an empty 5_2139 QueryTrainInfoReq answer.

Selling (BagCtr.lua:41-47,64-68): the client offers "sell" only when
item_info.price > 0 (BagLeftPanel.lua:278-292) and reads `status` alone;
SellItemRes has no `prizes` field, so the gold arrives as an ident-1 notify.

Selling junk (BargainPanel.lua:127-147): on opening a shop the client walks
its inventory and offers to sell the items it counts as junk
(AllShopUI.lua:1099-1112, NormalShop.lua:197-210): item_info.class 90, or an
expire_time > 0 with auto_sell 1 and not yet expired or auto_sell 2 and
expired. It sends 5_2149 with no fields and reads `status` alone: 0 floats
"获得N金币" from its own sum and closes the panel. The server sells every junk
row at item_info.price, also past the five the panel lists. With no junk it
answers 0 and changes nothing (the panel closes, nothing was lost).

Using. The bag shows a "use" button per item_info.class (BagLeftPanel.lua:
135-191) and the button does one of two things (BagLeftPanel.lua:581-612):

- It opens another screen and sends nothing here: 44 exp potions (training),
  100 gacha tickets (gacha), 50 rune energy (rune screen), 60 sweep tickets
  (sweep screen).
- It opens BagUsePanel, which sends 5_2131 {item, amount, box_idx}
  (BagUsePanel.lua:335-349, BagCtr.lua:80-89):
  - 45 联盟经验合剂: arg0 player xp per item ("在背包中使用，可获得100联盟经验");
    arg1 is a level ceiling only stated in the text ("45级内可用").
  - 99 food and chests: arg0 is a drop id (美味吐司 "+6 体力", 猎人宝箱 "one of").
  - 98 VIP cards: arg0 is the VIP level granted.
  - 97 recharge vouchers: arg0 is recharge credit for payment activities.
  - 103 avatar unlocks: arg0 is the avatar id.
  - 104 titles: arg0 is a duration in seconds, arg1 the title text.
  - 199 goddess lottery box: arg0 0, prizes are real-world goods.
  - 102 gingerbread: arg0 drop id, arg1 a gacha cooldown cut in seconds.

  Only class 45 has its whole effect fixed by item_info columns, so it is the
  one implemented. Every other class is refused with 327948 未知的道具类型 and
  nothing is written. The arg1 ceiling of 1150/1160 is not enforced: no
  status code says "level too high" for an item.

Item purchase (ItemBuyPanel.lua:89-112,158-171): the client prices an item at
item_buy_info.rate diamonds per unit, matched on (category, refer). ItemBuyRes
has no fields, so this handler cannot refuse: a short balance, an unknown
(category, refer) or a category other than 20 (item) changes nothing and is
logged at WARNING.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.bag")

STATUS_OK = 0
STATUS_NOT_ENOUGH_ITEMS = 327942   # language.db 没有足够道具
STATUS_UNKNOWN_ITEM_TYPE = 327948  # language.db 未知的道具类型

CLASS_PLAYER_XP = 45
CLASS_JUNK = 90          # AllShopUI.lua:1108 "class==90"
CATEGORY_PLAYER_XP = 11  # ClientPlayer.PLAYER_EXP_TYPE
CATEGORY_ITEM = 20       # ClientPlayer.ITEM_TYPE


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _have(pid: int, entry: int) -> int:
        row = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
        ).fetchone()
        return int(row["amount"]) if row else 0

    def _fresh(pid: int):
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def _res(name: str, **fields):
        res = registry.message_class(name)(**fields)
        fill_required(res)
        return res

    def sell(session: Session, req):
        name = "SellItemRes"
        pid = int(_player(session)["id"])
        entry, amount = int(req.item), int(req.amount)
        if amount <= 0 or _have(pid, entry) < amount:
            log.info("sell %dx %d by player %d refused %d", amount, entry, pid,
                     STATUS_NOT_ENOUGH_ITEMS)
            return _res(name, status=STATUS_NOT_ENOUGH_ITEMS, item=entry, amount=amount)
        info = cfg.item(entry)
        price = int(info["price"] or 0) if info is not None else 0
        if price <= 0:
            log.info("sell %dx %d by player %d refused %d: no price", amount, entry,
                     pid, STATUS_UNKNOWN_ITEM_TYPE)
            return _res(name, status=STATUS_UNKNOWN_ITEM_TYPE, item=entry, amount=amount)
        left = db.take_item(conn, pid, entry, amount)
        conn.execute("UPDATE players SET gold = gold + ? WHERE id = ?",
                     (price * amount, pid))
        conn.commit()
        notify.items_changed(registry, session, [(entry, left)])
        notify.player_changed(registry, session, {"gold": int(_fresh(pid)["gold"])})
        log.info("player %d sold %dx %d for %d gold", pid, amount, entry, price * amount)
        return _res(name, status=STATUS_OK, item=entry, amount=amount)

    def _is_junk(info, now: int) -> bool:
        expire, auto_sell = int(info["expire_time"] or 0), int(info["auto_sell"] or 0)
        return int(info["class"] or 0) == CLASS_JUNK or (expire > 0 and (
            (auto_sell == 1 and expire > now) or (auto_sell == 2 and expire <= now)))

    def sell_all(session: Session, req):
        name = "SellAllGoldStockRes"
        pid = int(_player(session)["id"])
        now = int(time.time())
        junk = []
        for row in db.items_of(conn, pid):
            info = cfg.item(int(row["entry"]))
            if info is not None and int(row["amount"]) > 0 and _is_junk(info, now):
                junk.append((int(row["entry"]), int(row["amount"]),
                             int(info["price"] or 0)))
        if not junk:
            log.info("sell all by player %d: no junk, nothing changed", pid)
            return _res(name, status=STATUS_OK)
        for entry, amount, _price in junk:
            db.take_item(conn, pid, entry, amount)
        gold = sum(amount * price for _entry, amount, price in junk)
        conn.execute("UPDATE players SET gold = gold + ? WHERE id = ?", (gold, pid))
        conn.commit()
        notify.items_changed(registry, session, [(entry, 0) for entry, _a, _p in junk])
        notify.player_changed(registry, session, {"gold": int(_fresh(pid)["gold"])})
        log.info("player %d sold all junk %s for %d gold", pid,
                 [(e, a) for e, a, _p in junk], gold)
        return _res(name, status=STATUS_OK)

    def use(session: Session, req):
        name = "UseItemRes"
        pid = int(_player(session)["id"])
        entry, amount = int(req.item), int(req.amount)
        info = cfg.item(entry)
        item_class = int(info["class"] or 0) if info is not None else 0
        if item_class != CLASS_PLAYER_XP:
            log.info("use %dx %d (class %d) by player %d refused %d: class not"
                     " implemented", amount, entry, item_class, pid,
                     STATUS_UNKNOWN_ITEM_TYPE)
            return _res(name, status=STATUS_UNKNOWN_ITEM_TYPE, amount=amount)
        if amount <= 0 or _have(pid, entry) < amount:
            log.info("use %dx %d by player %d refused %d", amount, entry, pid,
                     STATUS_NOT_ENOUGH_ITEMS)
            return _res(name, status=STATUS_NOT_ENOUGH_ITEMS, amount=amount)
        xp = int(info["arg0"] or 0) * amount
        left = db.take_item(conn, pid, entry, amount)
        change = db.add_player_xp(conn, cfg, pid, xp)
        fresh = _fresh(pid)
        notify.items_changed(registry, session, [(entry, left)])
        notify.player_changed(registry, session, {
            "xp": int(fresh["xp"]), "level": int(fresh["level"]),
            "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
        })
        if change["levelled"]:
            before, after = change["before"], change["after"]
            notify.level_up(registry, session, (before[0], before[2], before[3]),
                            (after[0], after[2], after[3]))
        res = _res(name, status=STATUS_OK, amount=amount)
        prize = res.prizes.add()
        prize.category, prize.refer, prize.amount = CATEGORY_PLAYER_XP, 0, xp
        fill_required(res)
        log.info("player %d used %dx %d for %d player xp", pid, amount, entry, xp)
        return res

    def item_buy(session: Session, req):
        name = "ItemBuyRes"
        pid = int(_player(session)["id"])
        category, refer = int(req.prize.category), int(req.prize.refer)
        amount = int(req.prize.amount)
        row = cfg.item_buy(refer)
        if row is None or int(row["category"]) != category:
            log.warning("item purchase by player %d of category %d refer %d: not in"
                        " item_buy_info, nothing changed", pid, category, refer)
            return _res(name)
        if category != CATEGORY_ITEM or cfg.item(refer) is None or amount <= 0:
            log.warning("item purchase by player %d of category %d refer %d x%d:"
                        " not supported, nothing changed", pid, category, refer, amount)
            return _res(name)
        cost = int(row["rate"]) * amount
        if int(_fresh(pid)["diamond"]) < cost:
            log.warning("item purchase by player %d of %dx %d needs %d diamonds"
                        " (327938 钻石不足, ItemBuyRes cannot carry it), nothing"
                        " changed", pid, amount, refer, cost)
            return _res(name)
        db.spend(conn, pid, diamond=cost)
        new_amount = db.grant_item(conn, pid, refer, amount)
        notify.items_changed(registry, session, [(refer, new_amount)])
        notify.player_changed(registry, session, {"diamond": int(_fresh(pid)["diamond"])})
        log.info("player %d bought %dx %d for %d diamonds", pid, amount, refer, cost)
        return _res(name)

    def train_info(session: Session, req):
        # Training unlocks at level 5 (Wave 2); RoleData.lua:1137-1139 asks at
        # login anyway, so it gets a valid answer with nothing in it.
        return _res("QueryTrainInfoRes", status=STATUS_OK)

    return {
        (5, 2137): sell,
        (5, 2149): sell_all,
        (5, 2131): use,
        (5, 2933): item_buy,
        (5, 2139): train_info,
    }
