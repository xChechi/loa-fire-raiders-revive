"""Training: 5_2139 QueryTrainInfoReq, 5_2119 TrainUseReq, 5_2117
TrainQualityUpReq.

Slots (TrainList.lua:116-127,183-199, TrainCell.lua:127-173). A slot is a
train_info.entry and the client matches ClientTrain.train to it. A slot the
answer leaves out is locked; refer_id 0 is open and empty; anything else is
training; at the hero cap exp + 1 == maxexp is "full" (type 5).

Opening and upgrading both send 5_2117 {train} (TrainCtr.lua:253-272,342-351):
opening costs train_quality(train, 1).diamond, gated by train_info.vip_need;
upgrading costs train_quality(train, quality + 1).diamond. Placing sends
TrainUseReq {train, op 1 place | 2 remove, refer_id, refer_type 1 hero |
2 angel} (TrainCtr.lua:101-112). refer_id is the hero entry or the angel
entry (TrainCtr.lua:21-24 keys godTable by it).

The client polls 5_2139 {op 1} every TRAIN_MIN_DURATION and after fights,
sends op 2 on opening the screen ("是否需要消除经验增量",
TrainCache.lua:104-111, TrainUI.lua:464-477), and floats info.addxp
(TrainCell.lua:117-124).

Passive xp (O-W2-8) is settled in whole TRAIN_MIN_DURATION ticks since
cal_time on every train request: per tick exp_up x (1 + rate) + base x D/3600,
the client's own per-hour display formula divided by 3600/D
(TrainUI.lua:636-662), with train_level_xp keyed by player level and slot
quality. A hero stops at xp_for_level(player level).hero_max_level with
need - 1 xp, an angel at the lower of angel_info.max_level and that
hero_max_level with need - 1 (O-W2-9; train/LevelHelp.lua:38-52).
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from collections.abc import Callable

from server import db
from server.config import Config
from server.modules import events, hero, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.train")

STATUS_OK = 0
STATUS_INTERNAL_ERROR = 327681       # 系统内部错误
STATUS_NOT_ENOUGH_DIAMOND = 327938   # 钻石不足
STATUS_NO_HERO = 327941              # 英雄不存在
STATUS_NOT_ENOUGH_ITEMS = 327942     # 没有足够道具
STATUS_UNIT_FULL = 327945            # 英雄经验值已经满了
STATUS_UNKNOWN_ITEM = 327948         # 未知的道具类型
STATUS_VIP_TOO_LOW = 327951          # VIP等级不足
STATUS_FUNCTION_LOCKED = 327957      # 未满足此玩法的等级
STATUS_NO_ANGEL = 328457             # 女神不存在
STATUS_TOP_QUALITY = 329217          # 训练位已经是最高等级
STATUS_SLOT_LOCKED = 329218          # 训练位还未开启
STATUS_SLOT_TAKEN = 329219           # 训练位上已经有英雄
STATUS_SLOT_EMPTY = 329220           # 训练位上没有英雄
STATUS_HERO_TRAINING = 329221        # 此英雄已经训练位上
STATUS_ANGEL_TRAINING = 329222       # 此女神已经训练位上

TRAIN_FUNCTION = 10040               # function 训练 (TrainCache.lua:110)
STORE_XP_ITEMS = 999                 # merchandise_info store of the potions
REFER_HERO = 1
REFER_ANGEL = 2
OP_PLACE = 1
OP_REMOVE = 2
OP_QUERY_AND_CLEAR = 2               # QueryTrainInfoReq.op 2 zeroes addxp
TRAIN_TYPE_NORMAL = 1                # train_type 2 slots are nobility (TrainCell.lua:138-140)
POTION_CLASS = 44                    # item_info.class of the xp potions
PRICE_GOLD = 1                       # merchandise_info.price_type
PRICE_DIAMOND = 9

XP_COLUMN = {REFER_HERO: "hero_xp_for_next_level", REFER_ANGEL: "angel_xp_for_next_level"}


def _need(cfg: Config, kind: int, level: int) -> int:
    row = cfg.xp_for_level(int(level))
    return int(row[XP_COLUMN[kind]] or 0) if row else 0


def room(cfg: Config, kind: int, level: int, xp: int, cap: int) -> int:
    """The xp a unit at (level, xp) can still take before it sits at `cap`
    with need - 1 xp, the client's "full" state."""
    if level > cap:
        return 0
    total = sum(_need(cfg, kind, lv) for lv in range(int(level), int(cap)))
    total += max(0, _need(cfg, kind, cap) - 1)
    return max(0, total - int(xp))


def _hero_cap(cfg: Config, player: sqlite3.Row) -> int:
    caps = cfg.xp_for_level(int(player["level"]))
    return int(caps["hero_max_level"]) if caps else 1


def _angel_cap(cfg: Config, player: sqlite3.Row, angel_row: sqlite3.Row) -> int:
    """angel_info.max_level, and never past the heroes' cap for the player
    level (train/LevelHelp.lua:38-52)."""
    info = cfg.angel_by_star(int(angel_row["angel_entry"]), int(angel_row["star"]))
    if info is None:
        raise KeyError(
            f"angel_info has no row for angel {angel_row['angel_entry']}"
            f" star {angel_row['star']}"
        )
    return min(int(info["max_level"]), _hero_cap(cfg, player))


def _unit(conn: sqlite3.Connection, pid: int, kind: int, entry: int):
    if kind == REFER_HERO:
        return conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (pid, int(entry)),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM angels WHERE player_id = ? AND angel_entry = ?",
        (pid, int(entry)),
    ).fetchone()


def unit_state(cfg: Config, conn: sqlite3.Connection, player, kind: int, entry: int):
    """(level, exp, maxexp, cap, room) of the unit on a slot. exp is held at
    maxexp - 1 at the cap (O-W2-9)."""
    row = _unit(conn, int(player["id"]), kind, entry)
    if row is None:
        return None
    if kind == REFER_HERO:
        level, xp, cap = int(row["level"]), int(row["xp"]), _hero_cap(cfg, player)
    else:
        level, xp, cap = int(row["level"]), int(row["exp"]), _angel_cap(cfg, player, row)
    need = _need(cfg, kind, level)
    exp = min(xp, need - 1) if level >= cap and need > 0 else xp
    return level, exp, need, cap, room(cfg, kind, level, xp, cap)


def build_client_train(registry: Registry, cfg: Config, conn, player, row):
    """All ten required ClientTrain fields; id is the slot entry."""
    msg = registry.message_class("ClientTrain")(
        id=int(row["train"]), train=int(row["train"]), quality=int(row["quality"]),
        refer_type=int(row["refer_type"]), refer_id=int(row["refer_id"]),
        cal_time=int(row["cal_time"]), exp=0, maxexp=0, level=0,
        addxp=int(row["addxp"]),
    )
    if int(row["refer_id"]):
        state = unit_state(cfg, conn, player, int(row["refer_type"]), int(row["refer_id"]))
        if state is not None:
            msg.level, msg.exp, msg.maxexp = state[0], state[1], state[2]
    fill_required(msg)
    return msg


def ensure_free_slots(conn: sqlite3.Connection, cfg: Config, player) -> None:
    """O-W2-7: the free normal slots open at quality 1 once Train is open."""
    for slot in cfg.train_slots():
        if not int(slot["is_free"] or 0) or int(slot["train_type"] or 0) != TRAIN_TYPE_NORMAL:
            continue
        if int(slot["vip_need"] or 0) > int(player["vip"]):
            continue
        if int(slot["level_need"] or 0) > int(player["level"]):
            continue
        conn.execute(
            "INSERT INTO trains (player_id, train, quality) VALUES (?, ?, 1)"
            " ON CONFLICT(player_id, train) DO NOTHING",
            (int(player["id"]), int(slot["entry"])),
        )
    conn.commit()


def per_tick(cfg: Config, player, quality: int, train: int) -> float:
    duration = cfg.variable_int("TRAIN_MIN_DURATION", 60)
    q = cfg.train_quality(train, quality)
    if q is None:
        raise KeyError(f"train_quality has no row for train {train} quality {quality}")
    scale = cfg.train_level_xp(int(player["level"]), quality)
    rate = float(scale["rate"] or 0) if scale else 0.0
    base = float(scale["base"] or 0) if scale else 0.0
    return float(q["exp_up"] or 0) * (1 + rate) + base * duration / 3600


def apply_xp(
    registry: Registry, cfg: Config, conn: sqlite3.Connection, session: Session,
    player, kind: int, entry: int, amount: int, always: bool = False,
) -> int:
    """Give up to `amount` xp, clipped at the cap's need - 1; push the hero or
    angel notify when a level changed (or on any gain when `always`, as for a
    potion). Returns the xp actually given."""
    pid = int(player["id"])
    state = unit_state(cfg, conn, player, kind, entry)
    if state is None:
        return 0
    before_level, gain = state[0], min(int(amount), state[4])
    if gain <= 0:
        return 0
    if kind == REFER_HERO:
        db.add_hero_xp(conn, cfg, pid, [entry], gain)
        row = _unit(conn, pid, kind, entry)
        if always or int(row["level"]) != before_level:
            notify.hero_changed(
                registry, session, int(entry),
                hero.hero_notify_fields_with_runes(registry, cfg, row, hero.runes_of(conn, row)),
            )
        if int(row["level"]) != before_level:
            events.bump(conn, cfg, registry, session, pid, events.KIND_HERO_LEVEL)
    else:
        level, exp = db.add_angel_xp(conn, cfg, pid, entry, gain)
        if always or level != before_level:
            notify.angel_changed(registry, session, int(entry), {"level": level, "exp": exp})
    return gain


def settle(
    registry: Registry, cfg: Config, conn: sqlite3.Connection, session: Session,
    player, now: float,
) -> None:
    """O-W2-8/9/10 over every occupied slot of the player."""
    duration = cfg.variable_int("TRAIN_MIN_DURATION", 60)
    pid = int(player["id"])
    rows = conn.execute(
        "SELECT * FROM trains WHERE player_id = ? AND refer_id != 0 ORDER BY train",
        (pid,),
    ).fetchall()
    for row in rows:
        ticks = max(0, (int(now) - int(row["cal_time"])) // duration)
        if not ticks:
            continue
        rolled = math.floor(
            round(ticks * per_tick(cfg, player, int(row["quality"]), int(row["train"])), 6)
        )
        given = apply_xp(
            registry, cfg, conn, session, player,
            int(row["refer_type"]), int(row["refer_id"]), rolled,
        )
        conn.execute(
            "UPDATE trains SET cal_time = cal_time + ?, addxp = addxp + ?"
            " WHERE player_id = ? AND train = ?",
            (ticks * duration, given, pid, int(row["train"])),
        )
        conn.commit()
        if given:
            log.info("train slot %d of player %d: %d ticks, %d xp to %s %d",
                     row["train"], pid, ticks, given,
                     "hero" if int(row["refer_type"]) == REFER_HERO else "angel",
                     row["refer_id"])


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], float] | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _fresh(pid: int):
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def _slot(pid: int, train: int):
        return conn.execute(
            "SELECT * FROM trains WHERE player_id = ? AND train = ?", (pid, int(train))
        ).fetchone()

    def _res(name: str, status: int, pid: int | None = None, train: int | None = None):
        res = registry.message_class(name)(status=status)
        if pid is not None and train is not None:
            res.train.CopyFrom(
                build_client_train(registry, cfg, conn, _fresh(pid), _slot(pid, train))
            )
        fill_required(res)
        return res

    def _refused(name: str, status: int, why: str):
        log.info("%s refused %d: %s", name, status, why)
        return _res(name, status)

    def query(session: Session, req):
        name = "QueryTrainInfoRes"
        player = _player(session)
        pid = int(player["id"])
        unlock = cfg.function_unlock(TRAIN_FUNCTION)
        if int(player["level"]) < unlock:
            return _refused(name, STATUS_FUNCTION_LOCKED,
                            f"player level {player['level']} < {unlock}")
        ensure_free_slots(conn, cfg, player)
        settle(registry, cfg, conn, session, player, now_of())
        player = _fresh(pid)
        res = registry.message_class(name)(status=STATUS_OK)
        for row in conn.execute(
            "SELECT * FROM trains WHERE player_id = ? ORDER BY train", (pid,)
        ).fetchall():
            res.trains.add().CopyFrom(build_client_train(registry, cfg, conn, player, row))
        res.items.extend(int(m["item"]) for m in cfg.merchandise(STORE_XP_ITEMS))
        if int(req.op) == OP_QUERY_AND_CLEAR:
            conn.execute("UPDATE trains SET addxp = 0 WHERE player_id = ?", (pid,))
            conn.commit()
        fill_required(res)
        return res

    def use(session: Session, req):
        name = "TrainUseRes"
        player = _player(session)
        pid = int(player["id"])
        train, op = int(req.train), int(req.op)
        kind, entry = int(req.refer_type), int(req.refer_id)
        slot = _slot(pid, train)
        if slot is None:
            return _refused(name, STATUS_SLOT_LOCKED, f"slot {train}")
        settle(registry, cfg, conn, session, player, now_of())
        slot = _slot(pid, train)
        if op == OP_PLACE:
            if kind not in (REFER_HERO, REFER_ANGEL):
                return _refused(name, STATUS_INTERNAL_ERROR, f"refer_type {kind}")
            if _unit(conn, pid, kind, entry) is None:
                return _refused(
                    name, STATUS_NO_HERO if kind == REFER_HERO else STATUS_NO_ANGEL,
                    f"refer {kind}/{entry} not owned",
                )
            busy = conn.execute(
                "SELECT train FROM trains WHERE player_id = ? AND refer_type = ?"
                " AND refer_id = ?", (pid, kind, entry),
            ).fetchone()
            if busy is not None:
                return _refused(
                    name,
                    STATUS_HERO_TRAINING if kind == REFER_HERO else STATUS_ANGEL_TRAINING,
                    f"refer {kind}/{entry} already on slot {busy['train']}",
                )
            if int(slot["refer_id"]):
                return _refused(name, STATUS_SLOT_TAKEN, f"slot {train} occupied")
            conn.execute(
                "UPDATE trains SET refer_type = ?, refer_id = ?, cal_time = ?, addxp = 0"
                " WHERE player_id = ? AND train = ?",
                (kind, entry, int(now_of()), pid, train),
            )
            conn.commit()
            log.info("player %d places %s %d on train slot %d", pid,
                     "hero" if kind == REFER_HERO else "angel", entry, train)
            return _res(name, STATUS_OK, pid, train)
        if op == OP_REMOVE:
            if not int(slot["refer_id"]):
                return _refused(name, STATUS_SLOT_EMPTY, f"slot {train} empty")
            conn.execute(
                "UPDATE trains SET refer_type = 0, refer_id = 0, cal_time = 0, addxp = 0"
                " WHERE player_id = ? AND train = ?", (pid, train),
            )
            conn.commit()
            log.info("player %d clears train slot %d", pid, train)
            return _res(name, STATUS_OK, pid, train)
        return _refused(name, STATUS_INTERNAL_ERROR, f"op {op}")

    def quality_up(session: Session, req):
        name = "TrainQualityUpRes"
        player = _player(session)
        pid = int(player["id"])
        train = int(req.train)
        slot = _slot(pid, train)
        if slot is None:
            info = next((s for s in cfg.train_slots() if int(s["entry"]) == train), None)
            first = cfg.train_quality(train, 1)
            if info is None or first is None:
                return _refused(name, STATUS_INTERNAL_ERROR, f"slot {train} not configured")
            if int(player["vip"]) < int(info["vip_need"] or 0):
                return _refused(name, STATUS_VIP_TOO_LOW,
                                f"slot {train} needs vip {info['vip_need']}")
            cost = int(first["diamond"] or 0)
            if int(player["diamond"]) < cost:
                return _refused(name, STATUS_NOT_ENOUGH_DIAMOND, f"{cost} diamonds")
            db.spend(conn, pid, diamond=cost)
            conn.execute(
                "INSERT INTO trains (player_id, train, quality) VALUES (?, ?, 1)",
                (pid, train),
            )
            conn.commit()
            log.info("player %d opens train slot %d for %d diamonds", pid, train, cost)
        else:
            nxt = cfg.train_quality(train, int(slot["quality"]) + 1)
            if nxt is None:
                return _refused(name, STATUS_TOP_QUALITY,
                                f"slot {train} at quality {slot['quality']}")
            cost = int(nxt["diamond"] or 0)
            if int(player["diamond"]) < cost:
                return _refused(name, STATUS_NOT_ENOUGH_DIAMOND, f"{cost} diamonds")
            # Ticks before the upgrade are paid at the old quality.
            settle(registry, cfg, conn, session, player, now_of())
            db.spend(conn, pid, diamond=cost)
            conn.execute(
                "UPDATE trains SET quality = quality + 1 WHERE player_id = ? AND train = ?",
                (pid, train),
            )
            conn.commit()
            log.info("player %d raises train slot %d to quality %d for %d diamonds",
                     pid, train, int(slot["quality"]) + 1, cost)
        notify.player_changed(registry, session, {"diamond": int(_fresh(pid)["diamond"])})
        return _res(name, STATUS_OK, pid, train)

    def speed_up(session: Session, req):
        """5_2125 {item, train, amount}: each potion gives item_info.arg0 x
        train_quality.effect (TrainCtr.lua:316-333,445-464). A long press
        sends big amounts (TrainCtr.lua:396-451), so only the potions the cap
        leaves room for are consumed (Risk 4)."""
        name = "TrainSpeedUpRes"
        player = _player(session)
        pid = int(player["id"])
        entry, train, amount = int(req.item), int(req.train), int(req.amount)
        item_row = cfg.item(entry)
        if item_row is None or int(item_row["class"] or 0) != POTION_CLASS:
            return _refused(name, STATUS_UNKNOWN_ITEM, f"item {entry} is not a potion")
        slot = _slot(pid, train)
        if slot is None or not int(slot["refer_id"]):
            return _refused(name, STATUS_SLOT_EMPTY, f"slot {train} empty")
        if amount <= 0:
            return _refused(name, STATUS_INTERNAL_ERROR, f"amount {amount}")
        owned = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?", (pid, entry)
        ).fetchone()
        if owned is None or int(owned["amount"]) < amount:
            return _refused(name, STATUS_NOT_ENOUGH_ITEMS, f"{amount}x {entry}")
        kind, refer = int(slot["refer_type"]), int(slot["refer_id"])
        # The passive ticks are paid first, so the cap is judged on them too.
        settle(registry, cfg, conn, session, player, now_of())
        player = _fresh(pid)
        state = unit_state(cfg, conn, player, kind, refer)
        if state is None or state[4] <= 0:
            return _refused(name, STATUS_UNIT_FULL, f"slot {train} unit is full")
        quality = cfg.train_quality(train, int(slot["quality"]))
        if quality is None:
            raise KeyError(f"train_quality has no row for train {train} quality {slot['quality']}")
        per = int(item_row["arg0"] or 0) * int(quality["effect"] or 0)
        if per <= 0:
            raise ValueError(f"potion {entry} on slot {train} gives {per} xp")
        used = min(amount, -(-state[4] // per))
        left = db.take_item(conn, pid, entry, used)
        notify.items_changed(registry, session, [(entry, left)])
        given = apply_xp(registry, cfg, conn, session, player, kind, refer, used * per,
                         always=True)
        events.bump(conn, cfg, registry, session, pid, events.KIND_XP_POTION, now=now_of())
        log.info("player %d uses %dx %d (of %d asked) on train slot %d: %d xp",
                 pid, used, entry, amount, train, given)
        return _res(name, STATUS_OK, pid, train)

    def buy_xp_item(session: Session, req):
        """5_2165 {merchandise, amount = groups} (TrainBuyItemPanel.lua:255-268).
        BuyXpItemRes has no status, so a shortfall changes nothing and logs
        the code it would have sent (TrainCtr.lua:90-97)."""
        name = "BuyXpItemRes"
        player = _player(session)
        pid = int(player["id"])
        groups = int(req.amount)
        row = next(
            (m for m in cfg.merchandise(STORE_XP_ITEMS) if int(m["entry"]) == int(req.merchandise)),
            None,
        )
        empty = registry.message_class(name)()
        fill_required(empty)
        if row is None or groups <= 0:
            log.warning("5_2165 for merchandise %s x%d, not in store %d; nothing changed",
                        req.merchandise, groups, STORE_XP_ITEMS)
            return empty
        if int(row["min_level"] or 0) > int(player["level"]):
            log.warning("5_2165 merchandise %d needs level %d, player %d is %d"
                        " (327943 玩家等级不够); nothing changed",
                        row["entry"], row["min_level"], pid, player["level"])
            return empty
        cost = int(row["price"] or 0) * groups
        price_type = int(row["price_type"] or 0)
        if price_type == PRICE_GOLD:
            short, spend, code = int(player["gold"]) < cost, {"gold": cost}, 327937
        elif price_type == PRICE_DIAMOND:
            short, spend, code = int(player["diamond"]) < cost, {"diamond": cost}, 327938
        else:
            raise ValueError(f"merchandise {row['entry']} has price_type {price_type}")
        if short:
            log.warning("5_2165 merchandise %d x%d costs %d (%d); nothing changed",
                        row["entry"], groups, cost, code)
            return empty
        db.spend(conn, pid, **spend)
        item_entry = int(row["item"])
        total = int(row["amount"] or 0) * groups
        new_amount = db.grant_item(conn, pid, item_entry, total)
        fresh = _fresh(pid)
        notify.items_changed(registry, session, [(item_entry, new_amount)])
        notify.player_changed(registry, session, {k: int(fresh[k]) for k in spend})
        log.info("player %d buys %dx %d for %d %s", pid, total, item_entry, cost,
                 next(iter(spend)))
        return empty

    return {
        (5, 2139): query,
        (5, 2119): use,
        (5, 2117): quality_up,
        (5, 2125): speed_up,
        (5, 2165): buy_xp_item,
    }
