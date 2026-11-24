"""Monthly sign-in (5_2015, 5_2009, 5_2023, 5_2025, 5_2585) and the 7-day
login gift (5_2043).

Sign-in, as SignUI2 and SignData read it (SignData.lua:27-160, SignUI2.lua:
525-555):

- `normal_flags` bit (d-1) means "signed in on calendar day d".
- The award a sign-in pays is chosen by POSITION, not by date: the k-th
  sign-in of the month takes `awards[k]` (SignData:getTodayCheckPos is the
  number of set normal bits, plus 1 if today is not yet signed).
- `vip_flags` bit (k-1) means "the VIP extra of position k was paid"
  (SignData:isVIPCheckedAtPos). A row with `vip` < 1 has no VIP extra.
- 5_2023 is the VIP top-up of TODAY's position, sent only after today's normal
  sign-in when the player's VIP has reached the row's `vip` (SignUI2.lua:
  542-546). The diamond "append a missed day" request of the old SignUI is
  5_2021, and that UI is commented out (SystemEventManager.lua:226).
- `total_checkin_times` is a lifetime count: the `check_award` chain runs from
  5 to 2000 sign-ins. `checkins.total_award` is the cursor, the id of the next
  unclaimed `check_award` row (0 = the chain head).

The `checkin` table ends at month 202312, so a real month maps to the newest
table month with the same calendar month number (plan O3).

Login gift: `players.login_award` bits 0-6 mean "day 1-7 claimable" and bits
8-14 "day 1-7 claimed" (RoleData:getSevenStatus/hasSevenAward, RoleData.lua:
1699-1730). Day n pays drop id `variables.LOGIN_AWARD` [n-1]
(RoleData:getSevenDropTable). The client sets `login_award` from the Res
itself (SevenList.lua:32-43).
"""

from __future__ import annotations

import calendar
import logging
import sqlite3
from collections.abc import Callable
from datetime import date

from server import db
from server.config import Config
from server.modules import drops, hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.checkin")

STATUS_OK = 0
STATUS_ALREADY_SIGNED = 330241       # language.db 重复签到
STATUS_NOTHING_TO_APPEND = 330242    # language.db 没有需要补签的记录
STATUS_NO_VIP_AWARD = 330243         # language.db 此位置上没有vip物品
STATUS_NOT_MET = 330245              # language.db 未满足领取该奖励的条件

# The head of the check_award chain: the one id no row's `next` points at.
FIRST_CHECK_AWARD = 10001
# checkin_extreme_info has days 1..30; SignData:parse copies statusexterme
# one entry per day, and nothing in single-player ever fills one.
EXTREME_DAYS = 30
LOGIN_DAYS = 7
CLAIMED_SHIFT = 8


def table_month(cfg: Config, today: date) -> tuple[int, int]:
    """(checkin table month, total_days) for a real date, plan O3: the newest
    table month with the same month number; total_days is the real month's
    length truncated to the rows present."""
    candidates = [m for m in cfg.checkin_months() if m % 100 == today.month]
    if not candidates:
        raise KeyError(f"checkin has no month numbered {today.month}")
    month = max(candidates)
    real_days = calendar.monthrange(today.year, today.month)[1]
    return month, min(real_days, len(cfg.checkin_rows(month)))


def record_login(conn: sqlite3.Connection, cfg: Config, pid: int, today_iso: str) -> None:
    """Count a new login day for the 7-day gift (exported for the login wiring):
    on the first call of a day, login_days = min(7, +1) and its claimable bit
    is set. Also rolls the daily purchase counters (db.ensure_today)."""
    row = conn.execute(
        "SELECT login_award, login_days, last_login_day FROM players WHERE id = ?",
        (int(pid),),
    ).fetchone()
    if row["last_login_day"] != today_iso:
        days = min(LOGIN_DAYS, int(row["login_days"]) + 1)
        award = int(row["login_award"]) | (1 << (days - 1))
        conn.execute(
            "UPDATE players SET login_days = ?, login_award = ?, last_login_day = ?"
            " WHERE id = ?",
            (days, award, today_iso, int(pid)),
        )
        conn.commit()
        log.info("player %d login day %d of the 7-day gift (%s)", pid, days, today_iso)
    db.ensure_today(conn, pid, today_iso)


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], date] | None = None,
) -> dict[tuple[int, int], Handler]:
    today_of = clock or date.today

    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _state(pid: int, today: date) -> sqlite3.Row:
        """This player's checkins row; the month's flags start over when the
        real month (stored as YYYYMM) changes. The lifetime total stays."""
        real_month = today.year * 100 + today.month
        conn.execute(
            "INSERT OR IGNORE INTO checkins (player_id, month) VALUES (?, ?)",
            (pid, real_month),
        )
        conn.execute(
            "UPDATE checkins SET month = ?, normal_flags = 0, vip_flags = 0,"
            " append_used = 0 WHERE player_id = ? AND month != ?",
            (real_month, pid, real_month),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM checkins WHERE player_id = ?", (pid,)
        ).fetchone()

    def _prize(category: int, refer: int, amount: int):
        return registry.message_class("ClientPrizeEntry")(
            category=int(category), refer=int(refer), amount=int(amount)
        )

    def _total_awards(cursor: int):
        """ClientTotalCheckIn for the next unclaimed check_award row; past the
        end of the chain next_times is 0 and the list empty."""
        msg = registry.message_class("ClientTotalCheckIn")(next_times=0)
        row = cfg.check_award(cursor or FIRST_CHECK_AWARD)
        if row is not None:
            msg.next_times = int(row["times"])
            for n in (1, 2, 3):
                msg.next_awards.add().CopyFrom(
                    _prize(row[f"type{n}"], row[f"item{n}"], row[f"amount{n}"])
                )
        return msg

    def _pay(session: Session, pid: int, triples) -> dict:
        """grant_prizes vets the whole list before it writes, then the client
        gets the absolute balances, items and any new hero. The result goes
        back for item.mark_converted."""
        changed = item.grant_prizes(conn, cfg, pid, triples)
        for hero_row_id in changed["heroes"]:
            hero_row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (hero_row_id,)
            ).fetchone()
            notify.hero_added(
                registry, session, hero.build_client_hero(registry, cfg, hero_row)
            )
        notify.items_changed(registry, session, changed["items"])
        notify.player_changed(
            registry, session,
            {"gold": changed["gold"], "diamond": changed["diamond"],
             "energy": changed["energy"]},
        )
        item.announce(registry, session, changed)
        return changed

    def _refused(name: str, status: int, pid: int, why: str):
        log.info("%s for player %d refused %d: %s", name, pid, status, why)
        res = registry.message_class(name)(status=status)
        fill_required(res)
        return res

    def query(session: Session, req):
        today = today_of()
        pid = int(_player(session)["id"])
        state = _state(pid, today)
        month, total_days = table_month(cfg, today)
        res = registry.message_class("CheckInQueryRes")(
            status=STATUS_OK, month=month, day=today.day, total_days=total_days,
            normal_flags=int(state["normal_flags"]),
            vip_flags=int(state["vip_flags"]),
            total_checkin_times=int(state["total_times"]),
            append_times=0, append_cost=0,
            flag=min(today.day, EXTREME_DAYS),
        )
        for row in cfg.checkin_rows(month)[:total_days]:
            entry = res.awards.add(vip=int(row["vip"]), times=int(row["times"]))
            entry.award.CopyFrom(_prize(row["refer_type"], row["refer_id"], row["amount"]))
        res.total_checkin_awards.CopyFrom(_total_awards(int(state["total_award"])))
        res.statusexterme.extend([0] * EXTREME_DAYS)
        fill_required(res)
        return res

    def check_in(session: Session, req):
        name = "CheckInRes"
        today = today_of()
        player = _player(session)
        pid = int(player["id"])
        state = _state(pid, today)
        month, total_days = table_month(cfg, today)
        normal = int(state["normal_flags"])
        today_bit = 1 << (today.day - 1)
        if normal & today_bit:
            return _refused(name, STATUS_ALREADY_SIGNED, pid, f"day {today.day} signed")
        rows = cfg.checkin_rows(month)[:total_days]
        position = normal.bit_count() + 1
        if position > len(rows):
            return _refused(name, STATUS_NOT_MET, pid, f"no row for position {position}")
        row = rows[position - 1]
        amount, vip_flags = int(row["amount"]), int(state["vip_flags"])
        if int(row["vip"]) >= 1 and int(player["vip"]) >= int(row["vip"]):
            amount *= max(1, int(row["times"]))
            vip_flags |= 1 << (position - 1)
        prize = (int(row["refer_type"]), int(row["refer_id"]), amount)
        changed = _pay(session, pid, [prize])
        normal |= today_bit
        conn.execute(
            "UPDATE checkins SET normal_flags = ?, vip_flags = ?,"
            " total_times = total_times + 1 WHERE player_id = ?",
            (normal, vip_flags, pid),
        )
        conn.commit()
        log.info("player %d signed in day %d, position %d: %s", pid, today.day, position, prize)
        res = registry.message_class(name)(
            status=STATUS_OK, day=today.day, total_days=total_days,
            normal_flags=normal, vip_flags=vip_flags,
            total_checkin_times=int(state["total_times"]) + 1,
            append_times=0, append_cost=0,
        )
        res.awards.add().CopyFrom(_prize(*prize))
        item.mark_converted(res.awards, changed)
        fill_required(res)
        return res

    def vip_append(session: Session, req):
        name = "VipCheckInAppendRes"
        today = today_of()
        player = _player(session)
        pid = int(player["id"])
        state = _state(pid, today)
        month, total_days = table_month(cfg, today)
        normal, vip_flags = int(state["normal_flags"]), int(state["vip_flags"])
        if not normal & (1 << (today.day - 1)):
            return _refused(name, STATUS_NOTHING_TO_APPEND, pid, "today not signed in")
        position = normal.bit_count()
        rows = cfg.checkin_rows(month)[:total_days]
        row = rows[position - 1] if position <= len(rows) else None
        if row is None or int(row["vip"]) < 1:
            return _refused(name, STATUS_NO_VIP_AWARD, pid, f"position {position}")
        if vip_flags & (1 << (position - 1)):
            return _refused(name, STATUS_ALREADY_SIGNED, pid, f"position {position} VIP paid")
        if int(player["vip"]) < int(row["vip"]):
            return _refused(
                name, STATUS_NOT_MET, pid, f"vip {player['vip']} < {row['vip']}"
            )
        extra = int(row["amount"]) * (max(1, int(row["times"])) - 1)
        prize = (int(row["refer_type"]), int(row["refer_id"]), extra)
        changed = _pay(session, pid, [prize]) if extra > 0 else {"converted": []}
        vip_flags |= 1 << (position - 1)
        conn.execute(
            "UPDATE checkins SET vip_flags = ? WHERE player_id = ?", (vip_flags, pid)
        )
        conn.commit()
        log.info("player %d VIP top-up of position %d: %s", pid, position, prize)
        res = registry.message_class(name)(
            status=STATUS_OK, day=today.day, total_days=total_days,
            normal_flags=normal, vip_flags=vip_flags,
        )
        res.awards.add().CopyFrom(_prize(*prize))
        item.mark_converted(res.awards, changed)
        fill_required(res)
        return res

    def total_award(session: Session, req):
        name = "CheckInTotalAwardRes"
        today = today_of()
        pid = int(_player(session)["id"])
        state = _state(pid, today)
        cursor = int(state["total_award"]) or FIRST_CHECK_AWARD
        row = cfg.check_award(cursor)
        if row is None:
            return _refused(name, STATUS_NOT_MET, pid, f"check_award chain ended at {cursor}")
        if int(state["total_times"]) < int(row["times"]):
            return _refused(
                name, STATUS_NOT_MET, pid,
                f"{state['total_times']} sign-ins < {row['times']} for {cursor}",
            )
        triples = [
            (int(row[f"type{n}"]), int(row[f"item{n}"]), int(row[f"amount{n}"]))
            for n in (1, 2, 3)
        ]
        changed = _pay(session, pid, triples)
        following = int(row["next"])
        conn.execute(
            "UPDATE checkins SET total_award = ? WHERE player_id = ?", (following, pid)
        )
        conn.commit()
        log.info("player %d claimed check_award %d: %s", pid, cursor, triples)
        res = registry.message_class(name)(status=STATUS_OK)
        res.total_checkin_awards.CopyFrom(_total_awards(following))
        for triple in triples:
            res.awards.add().CopyFrom(_prize(*triple))
        item.mark_converted(res.awards, changed)
        fill_required(res)
        return res

    def extreme_reward(session: Session, req):
        # The 至尊 sign-in pays only after a recharge, which a single-player
        # world never has: torf 1 is the client's own failure answer
        # (SignUI2.lua:317-335).
        log.info("5_2585 extreme sign-in day %d answered torf 1 (no recharge)", req.today)
        res = registry.message_class("CheckinExtremeRewardRes")(torf=1)
        fill_required(res)
        return res

    def login_award(session: Session, req):
        name = "LoginAwardRes"
        player = _player(session)
        pid = int(player["id"])
        idx = int(req.award_index)
        bits = int(player["login_award"])
        claimed_bit = 1 << (CLAIMED_SHIFT + idx - 1) if 1 <= idx <= LOGIN_DAYS else 0
        if not (claimed_bit and bits & (1 << (idx - 1)) and not bits & claimed_bit):
            return _refused(name, STATUS_NOT_MET, pid, f"day {idx}, bits {bits:#x}")
        drop_ids = (cfg.variable("LOGIN_AWARD") or "").split("|")
        if len(drop_ids) < idx or not drop_ids[idx - 1]:
            raise KeyError(f"variables.LOGIN_AWARD has no drop id for day {idx}")
        rolled = drops.roll(cfg, int(drop_ids[idx - 1]))
        # Raises before any write on a category grant_prizes cannot apply, so
        # the day stays claimable.
        changed = _pay(session, pid, drops.as_triples(rolled))
        bits |= claimed_bit
        conn.execute("UPDATE players SET login_award = ? WHERE id = ?", (bits, pid))
        conn.commit()
        log.info(
            "player %d claimed 7-day gift day %d: %s", pid, idx,
            [(d.category, d.refer, d.amount) for d in rolled],
        )
        res = registry.message_class(name)(status=STATUS_OK, login_award=bits)
        for entry in drops.to_prize_entries(registry, rolled):
            res.awards.add().CopyFrom(entry)
        item.mark_converted(res.awards, changed)
        fill_required(res)
        return res

    return {
        (5, 2015): query,
        (5, 2009): check_in,
        (5, 2023): vip_append,
        (5, 2025): total_award,
        (5, 2585): extreme_reward,
        (5, 2043): login_award,
    }
