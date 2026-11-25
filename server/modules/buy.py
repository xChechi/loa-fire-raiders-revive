"""Energy sync and the two daily purchases: 5_2013 SyncEnergyReq,
5_2145 QueryBuyEnergyReq, 5_2141 BuyEnergyReq, 5_2147 QueryBuyGoldReq,
5_2143 BuyGoldReq.

Energy sync: GameEnergryTipPanel re-asks 5_2013 at last_recover_time +
PLAYER_ENERGY_RECOVER_CYCLE and reads it as epoch seconds
(GameEnergryTipPanel.lua:45-48,61-63,186-189), which is players.energy_at
after db.refresh_energy.

Energy purchase: the daily allowance is vip_info 10000 at the player's VIP
level, the gain is ENERGY_BUY_GAIN, and the price of the n-th purchase comes
from ENERGY_BUY_COST "price|count,..." tiers the way MMTools:getCost reads
them (MMTools.lua:33-54): the first tier whose running count reaches n, else
the last tier. BuyEnergyRes follows the client's own field comments
(StrengthUI.lua:184-223): `energy` is what this purchase gave (floated as
"获得 N 体力"), `nextEnergy` and `diamond` describe the next purchase.

Gold purchase ("点金"): the allowance is vip_info 10010, the n-th purchase
costs buy_gold_cost(n) diamonds and pays DigUI:getAddGoldNum
(DigUI.lua:566-584): (GOLD_BUY_BASE + GOLD_BUY_LEVEL_BASE * level) *
n ^ GOLD_BUY_TIMES_RATIO, rounded up as DigUI.lua:550 displays it, times a
crit multiplier 1..5 rolled over vip_info 10020..10060.

At VIP 0 both allowances are 0, so every purchase is refused with 327952
购买次数不足 (plan settled point 16).
"""

from __future__ import annotations

import logging
import math
import random
import sqlite3
from datetime import date

from server import db
from server.config import Config
from server.modules import events, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.buy")

STATUS_OK = 0
STATUS_NOT_ENOUGH_DIAMONDS = 327938  # language.db 钻石不足
STATUS_NO_PURCHASES_LEFT = 327952    # language.db 购买次数不足

VIP_ENERGY_BUYS = 10000   # vip_info 体力购买次数
VIP_GOLD_BUYS = 10010     # vip_info 点金次数
VIP_GOLD_CRIT = (10020, 10030, 10040, 10050, 10060)  # 点金1..5倍爆率


def _today() -> str:
    """The ISO day the daily counters belong to; tests replace it."""
    return date.today().isoformat()


def _roll() -> float:
    """One uniform draw in [0, 1) for a gold crit; tests replace it."""
    return random.random()


def _tier_price(cost_str: str, n: int) -> int:
    """MMTools:getCost for a single purchase number n (1-based)."""
    price, running = 0, 0
    for part in (p for p in cost_str.split(",") if p):
        tier_price, count = part.split("|")
        price = int(tier_price)
        running += int(count)
        if running >= n:
            break
    return price


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            pid = session.player_id
        else:
            pid = int(db.find_player(conn, settings.username)["id"])
        db.ensure_today(conn, pid, _today())
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def _vip_int(entry: int, vip: int) -> int:
        raw = cfg.vip_value(entry, vip)
        return 0 if raw in (None, "") else int(float(raw))

    def _energy_price(n: int) -> int:
        return _tier_price(cfg.variable("ENERGY_BUY_COST") or "", n)

    def _gold_gain(level: int, n: int) -> int:
        base = cfg.variable_int("GOLD_BUY_BASE", 0)
        per_level = cfg.variable_int("GOLD_BUY_LEVEL_BASE", 0)
        ratio = float(cfg.variable("GOLD_BUY_TIMES_RATIO") or 0)
        return math.ceil((base + per_level * level) * n ** ratio)

    def _crit(vip: int) -> int:
        draw, edge = _roll(), 0.0
        for multiplier, entry in enumerate(VIP_GOLD_CRIT, start=1):
            raw = cfg.vip_value(entry, vip)
            edge += 0.0 if raw in (None, "") else float(raw)
            if draw < edge:
                return multiplier
        return 1

    def _res(name: str, **fields):
        res = registry.message_class(name)(**fields)
        fill_required(res)
        return res

    def sync_energy(session: Session, req):
        row = _player(session)
        fresh = db.refresh_energy(conn, cfg, row)
        if int(fresh["energy"]) != int(row["energy"]):
            notify.player_changed(registry, session, {"energy": int(fresh["energy"])})
        return _res("SyncEnergyRes", status=STATUS_OK,
                    last_recover_time=int(fresh["energy_at"]))

    def query_buy_energy(session: Session, req):
        row = _player(session)
        used = int(row["buy_energy_used"])
        return _res(
            "QueryBuyEnergyRes", status=STATUS_OK, used=used,
            max=_vip_int(VIP_ENERGY_BUYS, int(row["vip"])),
            energy=cfg.variable_int("ENERGY_BUY_GAIN", 0),
            diamond=_energy_price(used + 1),
        )

    def buy_energy(session: Session, req):
        name = "BuyEnergyRes"
        row = _player(session)
        pid, used = int(row["id"]), int(row["buy_energy_used"])
        most = _vip_int(VIP_ENERGY_BUYS, int(row["vip"]))
        gain = cfg.variable_int("ENERGY_BUY_GAIN", 0)
        if used >= most:
            log.info("energy purchase by player %d refused %d: %d/%d used",
                     pid, STATUS_NO_PURCHASES_LEFT, used, most)
            return _res(name, status=STATUS_NO_PURCHASES_LEFT, used=used, max=most)
        price = _energy_price(used + 1)
        if int(row["diamond"]) < price:
            log.info("energy purchase by player %d refused %d: %d diamonds needed",
                     pid, STATUS_NOT_ENOUGH_DIAMONDS, price)
            return _res(name, status=STATUS_NOT_ENOUGH_DIAMONDS, used=used, max=most)
        db.spend(conn, pid, diamond=price)
        # Uncapped: the client refuses to ask above 2400 (StrengthUI.lua:292-297).
        conn.execute(
            "UPDATE players SET energy = energy + ?, buy_energy_used = buy_energy_used + 1"
            " WHERE id = ?", (gain, pid),
        )
        conn.commit()
        fresh = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
        notify.player_changed(registry, session, {
            "energy": int(fresh["energy"]), "diamond": int(fresh["diamond"]),
        })
        used += 1
        log.info("player %d bought %d energy for %d diamonds (%d/%d today)",
                 pid, gain, price, used, most)
        return _res(name, status=STATUS_OK, energy=gain, nextEnergy=gain,
                    diamond=_energy_price(used + 1), used=used, max=most)

    def query_buy_gold(session: Session, req):
        row = _player(session)
        used = int(row["buy_gold_used"])
        return _res(
            "QueryBuyGoldRes", status=STATUS_OK, used=used,
            max=_vip_int(VIP_GOLD_BUYS, int(row["vip"])),
            gold=_gold_gain(int(row["level"]), used + 1),
        )

    def buy_gold(session: Session, req):
        name = "BuyGoldRes"
        row = _player(session)
        pid, used, vip = int(row["id"]), int(row["buy_gold_used"]), int(row["vip"])
        most = _vip_int(VIP_GOLD_BUYS, vip)
        times = int(req.use_times)
        costs = [cfg.buy_gold_cost(n) for n in range(used + 1, used + times + 1)]
        # Validate the whole run before a single write.
        if used + times > most or None in costs:
            log.info("gold purchase x%d by player %d refused %d: %d/%d used",
                     times, pid, STATUS_NO_PURCHASES_LEFT, used, most)
            return _res(name, status=STATUS_NO_PURCHASES_LEFT, used=used, max=most)
        price = sum(costs)
        if int(row["diamond"]) < price:
            log.info("gold purchase x%d by player %d refused %d: %d diamonds needed",
                     times, pid, STATUS_NOT_ENOUGH_DIAMONDS, price)
            return _res(name, status=STATUS_NOT_ENOUGH_DIAMONDS, used=used, max=most)
        res = _res(name, status=STATUS_OK, used=used + times, max=most)
        for n in range(used + 1, used + times + 1):
            crit = _crit(vip)
            res.gold.append(_gold_gain(int(row["level"]), n) * crit)
            res.crit.append(crit)
        db.spend(conn, pid, diamond=price)
        conn.execute(
            "UPDATE players SET gold = gold + ?, buy_gold_used = buy_gold_used + ?"
            " WHERE id = ?", (sum(res.gold), times, pid),
        )
        conn.commit()
        fresh = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
        notify.player_changed(registry, session, {
            "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
        })
        events.bump(conn, cfg, registry, session, pid, events.KIND_BUY_GOLD, n=times)
        log.info("player %d bought gold x%d for %d diamonds: %s crit %s (%d/%d today)",
                 pid, times, price, list(res.gold), list(res.crit), used + times, most)
        return res

    return {
        (5, 2013): sync_energy,
        (5, 2145): query_buy_energy,
        (5, 2141): buy_energy,
        (5, 2147): query_buy_gold,
        (5, 2143): buy_gold,
    }
