"""Divine ruins (神之遗迹, function 50000, level 57), plan B2 Wave 3, task B8.

What the client reads (the spec):

- The tower is every chapter_info type 8 chapter in idx order, each a run of
  stage_info floors in idx order (NpcTowerUI.lua:41-51, LevelManager.lua:
  86-101). players.last_god_level is the floor being fought, 0 = the first
  floor (getLevelData(0, 8) answers stageList[1]).
- A floor has one enemy team per non-zero stage_info.group0..group2
  (NpcTowerUI.lua:702-704, 852-856). fight_status bit k = team k beaten
  (ClientPlayer.lua:541-548). The floor is cleared when every team is
  beaten; the client then moves last_god_level to the next floor with
  fight_status 0, or stays on the last floor of the tower
  (FunctionType.lua:321-336, ClientPlayer.lua:509, 527).
- x07044 (the rules text): beat all teams to go on, then three cards; floors
  3, 6 and 10 hold an extra chest; the units that beat a team rest until the
  floor is reset; resets and sweeps refresh at 05:00; only a fully cleared
  chapter can be swept.
- The chest of a floor is chest_info by stage_info.flags: the client shows
  the box when flags > 0 (NpcTowerUI.lua:100, 300, 316) and sets
  last_god_chest from it on a clear (BattleFactoryGodPve.lua:66-71,
  FunctionType.lua:335). Every type-8 chapter has flags 0,0,c,0,0,c+1,0,0,0,
  c+2 on idx 1..10, all inside chest_info 1..42. 5_2547 is sent only while
  last_god_chest > 0 (NpcTowerUI.lua:460-464, 660-662); the box pays the
  chest's drop and clears it (:368-375).
- 5_2551 GodFightIntoReq {chapter = the floor's stage entry, group = team
  index from 0} (NpcTowerLine.lua:152, 318). The client enters the fight on
  any header-status-0 answer: it never reads `flag` (NpcTowerLine.lua:
  215-222). So flag 1 here only marks the refusal; what stops the payout is
  that 5_2531 pays only a fight 5_2551 accepted on this session.
- 5_2531 GodFightReq {chapter, group, heroes, angel, result, autofight}
  (BattleFactoryGodPve.lua:76-118, NpcTowerLine.lua:227-237). The win is
  GodFightRes.result > 0 (forceResult :121-123); the end screen shows
  `drop` and the xp (FightType.showServerPveExpInfo includes GOD_PVE).
  GodFightRes.is_draw replaces ClientPlayer.is_draw on every fight
  (FunctionType.lua:323): bit i = card i still to turn (NpcTowerCardUI.lua:
  297), bit 0 the free bronze card (ClientPlayer:needShowDraw).
- 5_2517 GodChallengeReq {} -> {cd, cd_time, balance, max, chapter,
  fight_status, heros, angel} (NpcTowerUI.lua:378-412, 938-1001): cd 1 =
  locked, cd_time = the soft cooldown left, counting down per second;
  balance/max = resets left/total (x07006); heros/angel = resting units
  (excludeHeros/excludeAngels, :913-914, NpcTowerLine.lua:28-38).
- 5_2563 GodCdResetReq {level} clears the cooldown for GOD_CD_RESET_COST
  diamonds (x07051, NpcTowerUI.lua:917-927, :359-366).
- Cooldown (GOD_EVERY_FIGHT_CD 300 "单次战斗CD", GOD_NOT_FIGHT_CD 1200
  "战斗进入CD的总时间"): every fight adds 300 s to players.god_cd_until; the
  tower is locked while the time left is >= 1200 (the ruling for B8).

Resets and sweeps (commit 2):

- 5_2519 GodLevelResetReq {} replays the current floor: fight_status 0,
  nobody resting, cooldown 0, one reset used (NpcTowerUI.lua:347-357). The
  button needs fight_status != 0 (:877, 947; 336011) and a reset left
  (336002). Resets a day: vip_info 20120 神器PVE关卡免费重置VIP次数, plus
  the ones bought; max = both, balance = max - used.
- 5_2521/5_2523 {} -> {max, used, diamond}: buys allowed per day = vip_info
  20150 神器PVE关卡购买VIP次数 (336003), `used` = bought today, `diamond` =
  the next buy's GOD_LEVEL_RESET_COST tier ("price|count,..."), x07011.
- 5_2525 GodChapterCleanReq {chapter, times, silver_card, gold_card}
  (NpcTowerSweepDetailUI.lua:280-285): only a chapter whose every floor is
  cleared (ClientPlayer:isCanSweepNpcTower, 336007); `times` from the sweeps
  left (336004 none left, 336006 too few); energy = times x the chapter's
  floor energy (:34-36, 262); the cards cost times x floors x
  GOD_SILVER_CARD_COST / GOD_GOLD_CARD_COST diamonds (:294-300). The Res
  holds one GodCleanLevelEntry per floor in idx order (NpcTowerSweepList.lua:
  136-158 pairs drops[i] with stageList[i]) and `times` = sweeps left after
  it (:128). Each floor pays per sweep what clearing it and turning the
  bronze card pay (invisible_drops + visible_drops, as the campaign sweep
  pays both), the silver card stage_info.silver_card, the gold card
  gold_card, and the floor's player_xp.
- 5_2527/5_2529 {} -> {max, used, clean_num, clean_max, diamond}: free sweeps
  a day = vip_info 20130 神器PVE扫荡免费VIP次数, buys = 20140
  神器PVE扫荡购买VIP次数 (336005) at GOD_CHAPTER_CLEAN_COST tiers; clean_max
  = free + bought, clean_num = used (:58-66). No discount is sent (the
  optional discount fields stay unset, which the client reads as none).
- Every counter rolls at 05:00 (players.god_day, db.day_key(5)).

The card draw (commit 3): 5_2543 GodDrawReq {idx 0..2} -> {drops, diamond}
(NpcTowerCardUI.lua:265-267). Card idx is bit idx of is_draw; a turned card
clears it (:64-67, 336010 when already turned). Bronze (0) is free, silver
(1) costs GOD_SILVER_CARD_COST, gold (2) GOD_GOLD_CARD_COST diamonds
(:232-253). The cards belong to the floor just cleared: the current floor
when fight_status != 0 (the tower's last floor, no next one), else the one
before it (:29-35). Bronze pays that floor's visible_drops (the ruling),
silver its stage_info.silver_card, gold its gold_card. `diamond` carries
the price paid: no Lua reads it.

No God*Res has a `status` field (allProtos.proto:7853-8071), so a refusal
changes nothing, logs a WARNING with its language.db code and answers the
current state.

Ruling Board f-3af5e5: the fight that clears a floor pays the floor's
invisible_drops; the bronze card pays visible_drops. The floor's energy
(stage_info.energy, 6) and player_xp are paid once, on that clear: the
client gates every fight on one floor's energy (NpcTowerUI.lua:762) and a
sweep costs one floor's energy per floor (NpcTowerSweepDetailUI.lua:34-36).
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from typing import Callable

from server import db
from server.config import Config
from server.modules import drops, hero, item, mystery, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.godtower")

STATUS_NO_DIAMOND = 327938      # language.db 钻石不足
STATUS_NO_ENERGY = 327939       # language.db 体力不足
STATUS_LEVEL = 327957           # language.db 未满足此玩法的等级
STATUS_NOT_ENTERED = 328196     # language.db 没有进入关卡
STATUS_ENTER = 336001           # language.db 您不满足进入条件
STATUS_RESET_USED = 336002      # language.db 关卡重置次数已经用完
STATUS_RESET_BUY_MAX = 336003   # language.db 关卡重置购买次数已达上限
STATUS_CLEAN_USED = 336004      # language.db 章节扫荡次数已经用完
STATUS_CLEAN_BUY_MAX = 336005   # language.db 章节扫荡购买次数已达上限
STATUS_CLEAN_SHORT = 336006     # language.db 章节扫荡次数不足
STATUS_CLEAN_LOCKED = 336007    # language.db 不能扫荡该章节
STATUS_CHEST_TAKEN = 336008     # language.db 宝箱已经领过了
STATUS_RESTING = 336009         # language.db 这位英雄/女神正在休息中，不可出战
STATUS_DRAWN = 336010           # language.db 已翻牌
STATUS_NO_RESET_NEEDED = 336011 # language.db 当前未击败任何对手，无需重置
STATUS_IN_CD = 336012           # language.db 战斗cd中
STATUS_BAD_DATA = 336013        # language.db 数据异常,

FUNCTION_GOD = 50000            # FunctionType NPC_TOWER, function.unlock_level 57
CHAPTER_GOD = 8                 # chapter_info.type of 5000000-5190000
DAY_START_HOUR = 5              # x07044, O-W3-9
GROUP_COLUMNS = ("group0", "group1", "group2")
ALL_CARDS = 0b111               # bronze, silver, gold (NpcTowerCardUI.lua:140-146)
CARD_DROPS = ("visible_drops", "silver_card", "gold_card")
CARD_COSTS = (None, "GOD_SILVER_CARD_COST", "GOD_GOLD_CARD_COST")

VIP_FREE_RESETS = 20120         # vip_info 神器PVE关卡免费重置VIP次数
VIP_FREE_CLEANS = 20130         # vip_info 神器PVE扫荡免费VIP次数
VIP_BUY_CLEANS = 20140          # vip_info 神器PVE扫荡购买VIP次数
VIP_BUY_RESETS = 20150          # vip_info 神器PVE关卡购买VIP次数

FLAG_OK = 0
FLAG_REFUSED = 1

PENDING_KEY = "god_pending"


def var_int(cfg: Config, key: str) -> int:
    raw = cfg.variable(key)
    if raw in (None, ""):
        raise KeyError(f"variables.{key} is missing")
    return int(float(raw))


def vip_int(cfg: Config, entry: int, vip: int) -> int:
    raw = cfg.vip_value(entry, vip)
    if raw in (None, ""):
        raise KeyError(f"vip_info has no value for {entry} at VIP {vip}")
    return int(float(raw))


def tier_price(cost: str, n: int) -> int:
    """The price of purchase number n (1-based) on a "price|count,..." ladder
    (GOD_LEVEL_RESET_COST, GOD_CHAPTER_CLEAN_COST); past the end, the last."""
    price, running = 0, 0
    for part in (p for p in str(cost).split(",") if p):
        tier, count = part.split("|")
        price = int(tier)
        running += int(count)
        if running >= n:
            break
    return price


def floors(cfg: Config) -> list[int]:
    """Every divine-ruins stage entry in climbing order."""
    return [
        int(stage["entry"])
        for chapter in cfg.chapters_of_type(CHAPTER_GOD)
        for stage in cfg.stages_in_chapter(int(chapter["entry"]))
    ]


def current_floor(cfg: Config, row) -> int:
    return int(row["last_god_level"]) or floors(cfg)[0]


def full_mask(stage) -> int:
    """The fight_status of a floor with every team beaten."""
    return sum(1 << k for k, col in enumerate(GROUP_COLUMNS) if int(stage[col] or 0))


def cd_left(row, now: float) -> int:
    return max(0, int(row["god_cd_until"]) - int(now))


def chapter_cleared(conn: sqlite3.Connection, cfg: Config, pid: int, chapter: int) -> bool:
    """Every floor of the chapter cleared: its last floor has a `levels` row,
    which only a clear writes, and floors are climbed in order."""
    stages = cfg.stages_in_chapter(chapter)
    if not stages:
        return False
    progress = db.level_progress(conn, pid, int(stages[-1]["entry"]))
    return progress is not None and int(progress["star"]) > 0


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Callable[[], float] | None = None,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    now_of = clock or time.time

    def _player(session: Session):
        if session.player_id is not None:
            row = conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        else:
            row = db.find_player(conn, settings.username)
        if row is not None:
            session.player_id = int(row["id"])
        return row

    def _row(pid: int):
        return conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()

    def _res(name: str, **fields):
        res = registry.message_class(name)(**fields)
        fill_required(res)
        return res

    def _locked(row, now: float) -> bool:
        return cd_left(row, now) >= var_int(cfg, "GOD_NOT_FIGHT_CD")

    def _today(pid: int, now: float):
        """The player row with the four daily counters zeroed when they
        belong to an earlier 05:00 day."""
        today = db.day_key(DAY_START_HOUR, now)
        conn.execute(
            "UPDATE players SET god_reset_used = 0, god_reset_bought = 0,"
            " god_clean_used = 0, god_clean_bought = 0, god_day = ?"
            " WHERE id = ? AND god_day != ?",
            (today, pid, today),
        )
        conn.commit()
        return _row(pid)

    def _resets(row) -> tuple[int, int]:
        """(balance, max) of today's floor resets."""
        total = vip_int(cfg, VIP_FREE_RESETS, int(row["vip"])) + int(row["god_reset_bought"])
        return max(0, total - int(row["god_reset_used"])), total

    def _sweeps_left(row) -> int:
        total = vip_int(cfg, VIP_FREE_CLEANS, int(row["vip"])) + int(row["god_clean_bought"])
        return max(0, total - int(row["god_clean_used"]))

    # 5_2517 GodChallengeReq {} -> GodChallengeRes
    def state(session: Session, req):
        res = registry.message_class("GodChallengeRes")(
            cd=0, cd_time=0, balance=0, max=0, chapter=0, fight_status=0
        )
        row = _player(session)
        if row is None:
            log.warning("5_2517 before any character exists")
            fill_required(res)
            return res
        now = now_of()
        row = _today(int(row["id"]), now)
        need = cfg.function_unlock(FUNCTION_GOD)
        if int(row["level"]) < need:
            log.warning(
                "5_2517 player %d level %d < %d (%d); GodChallengeRes has no "
                "status, answering the current state",
                int(row["id"]), int(row["level"]), need, STATUS_LEVEL,
            )
        floor = cfg.stage(current_floor(cfg, row))
        res.cd = 1 if _locked(row, now) else 0
        res.cd_time = cd_left(row, now)
        res.balance, res.max = _resets(row)
        res.chapter = int(floor["chapter"])
        res.fight_status = int(row["god_fight_status"])
        res.heros.extend(int(e) for e in json.loads(row["god_rest_heroes"] or "[]"))
        res.angel.extend(int(e) for e in json.loads(row["god_rest_angels"] or "[]"))
        fill_required(res)
        return res

    def _enter_refusal(row, lvl: int, group: int, now: float) -> str | None:
        level, need = int(row["level"]), cfg.function_unlock(FUNCTION_GOD)
        if level < need:
            return f"player level {level} < {need} ({STATUS_LEVEL})"
        floor = current_floor(cfg, row)
        if lvl != floor:
            return f"stage {lvl} is not the current floor {floor} ({STATUS_ENTER})"
        stage = cfg.stage(lvl)
        if not 0 <= group < len(GROUP_COLUMNS) or not int(stage[GROUP_COLUMNS[group]] or 0):
            return f"floor {lvl} has no team {group} ({STATUS_BAD_DATA})"
        if int(row["god_fight_status"]) & (1 << group):
            return f"team {group} of floor {lvl} is already beaten ({STATUS_BAD_DATA})"
        if _locked(row, now):
            return f"cooldown {cd_left(row, now)} s left ({STATUS_IN_CD})"
        energy, cost = int(row["energy"]), int(stage["energy"] or 0)
        if energy < cost:
            return f"needs {cost} energy, has {energy} ({STATUS_NO_ENERGY})"
        return None

    # 5_2551 GodFightIntoReq {chapter, group} -> GodFightIntoRes {flag}
    def enter(session: Session, req):
        lvl, group = int(req.chapter), int(req.group)
        session.data.pop(PENDING_KEY, None)
        row = _player(session)
        if row is None:
            log.warning("5_2551 floor %d before any character exists", lvl)
            return _res("GodFightIntoRes", flag=FLAG_REFUSED)
        row = db.refresh_energy(conn, cfg, row)
        why = _enter_refusal(row, lvl, group, now_of())
        if why is not None:
            log.warning(
                "5_2551 floor %d team %d refused for player %d: %s; answering flag %d",
                lvl, group, int(row["id"]), why, FLAG_REFUSED,
            )
            return _res("GodFightIntoRes", flag=FLAG_REFUSED)
        session.data[PENDING_KEY] = (lvl, group)
        log.info("5_2551 floor %d team %d entered by player %d", lvl, group, int(row["id"]))
        return _res("GodFightIntoRes", flag=FLAG_OK)

    def _answer_fight(res, pid: int):
        row = _row(pid)
        res.owner.refer = pid
        res.owner.level = int(row["level"])
        res.owner.xp = int(row["xp"])
        res.is_draw = int(row["god_is_draw"])
        fill_required(res)
        return res

    # 5_2531 GodFightReq -> GodFightRes
    def fight(session: Session, req):
        lvl, group = int(req.chapter), int(req.group)
        res = registry.message_class("GodFightRes")(result=0)
        row = _player(session)
        if row is None:
            log.warning("5_2531 floor %d before any character exists", lvl)
            fill_required(res)
            return res
        pid = int(row["id"])
        if session.data.get(PENDING_KEY) != (lvl, group):
            log.warning(
                "5_2531 floor %d team %d for player %d with no accepted 5_2551 on "
                "this session (%d), paying nothing", lvl, group, pid, STATUS_NOT_ENTERED,
            )
            return _answer_fight(res, pid)
        session.data.pop(PENDING_KEY)
        heroes = [int(e) for e in req.heroes if int(e)]
        angel = int(req.angel)
        rest_heroes = json.loads(row["god_rest_heroes"] or "[]")
        rest_angels = json.loads(row["god_rest_angels"] or "[]")
        resting = [e for e in heroes if e in rest_heroes]
        if angel and angel in rest_angels:
            resting.append(angel)
        if resting:
            log.warning(
                "5_2531 floor %d team %d for player %d fielded resting unit(s) %s "
                "(%d), paying nothing", lvl, group, pid, resting, STATUS_RESTING,
            )
            return _answer_fight(res, pid)

        now = now_of()
        stage = cfg.stage(lvl)
        cd_until = int(now) + cd_left(row, now) + var_int(cfg, "GOD_EVERY_FIGHT_CD")
        if int(req.result) <= 0:
            conn.execute(
                "UPDATE players SET god_cd_until = ?, god_is_draw = 0 WHERE id = ?",
                (cd_until, pid),
            )
            conn.commit()
            log.info("5_2531 floor %d team %d lost by player %d", lvl, group, pid)
            return _answer_fight(res, pid)

        status = int(row["god_fight_status"]) | (1 << group)
        rest_heroes += [e for e in heroes if e not in rest_heroes]
        if angel and angel not in rest_angels:
            rest_angels.append(angel)
        cleared = status == full_mask(stage)
        floor, is_draw, chest = lvl, 0, int(row["last_god_chest"])
        rolled: list = []
        granted = None
        if cleared:
            chest_entry = int(stage["flags"] or 0)
            if chest_entry:
                cfg.chest(chest_entry)      # a missing chest row is a config error
            rolled = drops.roll(cfg, int(stage["invisible_drops"] or 0), rng=rng)
            try:
                granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
            except Exception:
                # grant_prizes vets before it writes: nothing is paid, so the
                # client's retry may replay.
                session.data[PENDING_KEY] = (lvl, group)
                raise
            order = floors(cfg)
            at = order.index(lvl)
            if at + 1 < len(order):
                floor, status = order[at + 1], 0
            rest_heroes, rest_angels = [], []
            is_draw, chest = ALL_CARDS, chest_entry
        try:
            conn.execute(
                "UPDATE players SET last_god_level = ?, god_fight_status = ?,"
                " god_rest_heroes = ?, god_rest_angels = ?, god_cd_until = ?,"
                " god_is_draw = ?, last_god_chest = ? WHERE id = ?",
                (floor, status, json.dumps(rest_heroes), json.dumps(rest_angels),
                 cd_until, is_draw, chest, pid),
            )
            conn.commit()
            xp_change = None
            if cleared:
                cost = int(stage["energy"] or 0)
                db.spend_energy(conn, pid, cost)
                mystery.on_energy_spent(conn, cfg, registry, session, pid, cost,
                                        rng=rng, now=now)
                db.upsert_level(conn, pid, lvl, star=1, count_delta=1)
                xp_change = db.add_player_xp(conn, cfg, pid, int(stage["player_xp"] or 0))
            hero_xp = db.add_hero_xp(
                conn, cfg, pid, heroes, int(stage["unit_xp"] or 0) if cleared else 0
            )
            angel_xp = db.add_angel_xp(
                conn, cfg, pid, angel, int(stage["angel_xp"] or 0) if cleared else 0
            )
        except Exception:
            log.error(
                "5_2531 floor %d: drops %s granted to player %d but a later write "
                "failed", lvl, drops.as_triples(rolled), pid, exc_info=True,
            )
            raise

        res.result = 1
        for entry, hlevel, hxp in hero_xp:
            client_xp = res.heroes.add()
            client_xp.refer, client_xp.level, client_xp.xp = entry, hlevel, hxp
        if angel_xp is not None:
            res.angel.refer = angel
            res.angel.level, res.angel.xp = angel_xp
        if cleared:
            for prize in drops.to_prize_entries(registry, rolled):
                res.drop.add().CopyFrom(prize)
            item.mark_converted(res.drop, granted)
            item.announce(registry, session, granted)
            notify.items_changed(registry, session, granted["items"])
            fresh = _row(pid)
            notify.player_changed(registry, session, {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "xp": int(fresh["xp"]), "level": int(fresh["level"]),
                "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
            })
            if xp_change["levelled"]:
                before, after = xp_change["before"], xp_change["after"]
                notify.level_up(
                    registry, session,
                    (before[0], before[2], before[3]), (after[0], after[2], after[3]),
                )
            if int(stage["unit_xp"] or 0) > 0:
                for entry, _hlevel, _hxp in hero_xp:
                    hero_row = conn.execute(
                        "SELECT * FROM heroes WHERE player_id = ? AND entry = ?"
                        " ORDER BY id", (pid, entry),
                    ).fetchone()
                    notify.hero_changed(
                        registry, session, entry,
                        hero.hero_notify_fields_with_runes(
                            registry, cfg, hero_row, hero.runes_of(conn, hero_row)
                        ),
                    )
            if angel_xp is not None and int(stage["angel_xp"] or 0) > 0:
                notify.angel_changed(registry, session, angel, {
                    "level": angel_xp[0], "exp": angel_xp[1],
                })
        log.info(
            "5_2531 floor %d team %d won by player %d%s",
            lvl, group, pid,
            f": floor cleared, next {floor}, chest {chest}, prizes "
            f"{drops.as_triples(rolled)}" if cleared else "",
        )
        return _answer_fight(res, pid)

    # 5_2563 GodCdResetReq {level} -> GodCdResetRes {}
    def cd_reset(session: Session, req):
        row = _player(session)
        if row is None:
            log.warning("5_2563 before any character exists")
            return _res("GodCdResetRes")
        pid, now = int(row["id"]), now_of()
        left = cd_left(row, now)
        cost = var_int(cfg, "GOD_CD_RESET_COST")
        if left <= 0:
            log.warning("5_2563 player %d has no cooldown to clear (%d)", pid, STATUS_BAD_DATA)
        elif int(row["diamond"]) < cost:
            log.warning(
                "5_2563 player %d needs %d diamonds, has %d (%d)",
                pid, cost, int(row["diamond"]), STATUS_NO_DIAMOND,
            )
        else:
            db.spend(conn, pid, diamond=cost)
            conn.execute("UPDATE players SET god_cd_until = 0 WHERE id = ?", (pid,))
            conn.commit()
            notify.player_changed(registry, session, {"diamond": int(_row(pid)["diamond"])})
            log.info("5_2563 player %d cleared %d s of cooldown for %d diamonds",
                     pid, left, cost)
        return _res("GodCdResetRes")

    # 5_2547 GodGetChestReq {} -> GodGetChestRes {drops}
    def chest(session: Session, req):
        res = registry.message_class("GodGetChestRes")()
        row = _player(session)
        if row is None:
            log.warning("5_2547 before any character exists")
            fill_required(res)
            return res
        pid, entry = int(row["id"]), int(row["last_god_chest"])
        if entry <= 0:
            log.warning("5_2547 player %d has no chest to open (%d)", pid, STATUS_CHEST_TAKEN)
            fill_required(res)
            return res
        rolled = drops.roll(cfg, int(cfg.chest(entry)["drops"]), rng=rng)
        granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
        conn.execute("UPDATE players SET last_god_chest = 0 WHERE id = ?", (pid,))
        conn.commit()
        for prize in drops.to_prize_entries(registry, rolled):
            res.drops.add().CopyFrom(prize)
        item.mark_converted(res.drops, granted)
        item.announce(registry, session, granted)
        notify.items_changed(registry, session, granted["items"])
        notify.player_changed(registry, session, {
            "gold": granted["gold"], "diamond": granted["diamond"],
        })
        log.info("5_2547 player %d opened chest %d: %s", pid, entry,
                 drops.as_triples(rolled))
        fill_required(res)
        return res

    def _warn(name: str, code: int, why: str) -> None:
        log.warning("%s refused (%d): %s; no status field, answering the current state",
                    name, code, why)

    # 5_2519 GodLevelResetReq {} -> GodLevelResetRes {}
    def reset(session: Session, req):
        row = _player(session)
        if row is None:
            log.warning("5_2519 before any character exists")
            return _res("GodLevelResetRes")
        pid = int(row["id"])
        row = _today(pid, now_of())
        balance, _total = _resets(row)
        if balance <= 0:
            _warn("5_2519", STATUS_RESET_USED, f"player {pid} has no reset left")
        elif int(row["god_fight_status"]) == 0:
            _warn("5_2519", STATUS_NO_RESET_NEEDED, f"player {pid} beat no team yet")
        else:
            conn.execute(
                "UPDATE players SET god_reset_used = god_reset_used + 1,"
                " god_fight_status = 0, god_rest_heroes = '[]', god_rest_angels = '[]',"
                " god_cd_until = 0 WHERE id = ?", (pid,),
            )
            conn.commit()
            log.info("5_2519 player %d reset floor %d (%d reset(s) left)",
                     pid, current_floor(cfg, row), balance - 1)
        return _res("GodLevelResetRes")

    def _buy_reset_res(name: str, row):
        bought = int(row["god_reset_bought"])
        return _res(
            name, max=vip_int(cfg, VIP_BUY_RESETS, int(row["vip"])), used=bought,
            diamond=tier_price(cfg.variable("GOD_LEVEL_RESET_COST") or "", bought + 1),
        )

    # 5_2521 GodQueryBuyLevelResetReq {} -> {max, used, diamond}
    def query_buy_reset(session: Session, req):
        row = _player(session)
        if row is None:
            return _res("GodQueryBuyLevelResetRes", max=0, used=0, diamond=0)
        return _buy_reset_res("GodQueryBuyLevelResetRes", _today(int(row["id"]), now_of()))

    # 5_2523 GodBuyLevelResetReq {} -> {max, used, diamond}
    def buy_reset(session: Session, req):
        row = _player(session)
        if row is None:
            return _res("GodBuyLevelResetRes", max=0, used=0, diamond=0)
        pid = int(row["id"])
        row = _today(pid, now_of())
        bought, limit = int(row["god_reset_bought"]), vip_int(cfg, VIP_BUY_RESETS, int(row["vip"]))
        price = tier_price(cfg.variable("GOD_LEVEL_RESET_COST") or "", bought + 1)
        if bought >= limit:
            _warn("5_2523", STATUS_RESET_BUY_MAX, f"{bought} of {limit} bought at VIP {row['vip']}")
        elif int(row["diamond"]) < price:
            _warn("5_2523", STATUS_NO_DIAMOND, f"needs {price} diamonds, has {row['diamond']}")
        else:
            db.spend(conn, pid, diamond=price)
            conn.execute(
                "UPDATE players SET god_reset_bought = god_reset_bought + 1 WHERE id = ?",
                (pid,),
            )
            conn.commit()
            row = _row(pid)
            notify.player_changed(registry, session, {"diamond": int(row["diamond"])})
            log.info("5_2523 player %d bought reset %d for %d diamonds", pid, bought + 1, price)
        return _buy_reset_res("GodBuyLevelResetRes", row)

    def _buy_clean_fields(row) -> dict:
        bought = int(row["god_clean_bought"])
        return {
            "max": vip_int(cfg, VIP_BUY_CLEANS, int(row["vip"])), "used": bought,
            "diamond": tier_price(cfg.variable("GOD_CHAPTER_CLEAN_COST") or "", bought + 1),
        }

    # 5_2527 GodQueryBuyChapterCleanReq {} -> {max, used, clean_num, clean_max, diamond}
    def query_buy_clean(session: Session, req):
        row = _player(session)
        if row is None:
            return _res("GodQueryBuyChapterCleanRes", max=0, used=0, clean_num=0,
                        clean_max=0, diamond=0)
        row = _today(int(row["id"]), now_of())
        used = int(row["god_clean_used"])
        return _res(
            "GodQueryBuyChapterCleanRes", clean_num=used,
            clean_max=used + _sweeps_left(row), **_buy_clean_fields(row),
        )

    # 5_2529 GodBuyChapterCleanReq {} -> {max, used, diamond}
    def buy_clean(session: Session, req):
        row = _player(session)
        if row is None:
            return _res("GodBuyChapterCleanRes", max=0, used=0, diamond=0)
        pid = int(row["id"])
        row = _today(pid, now_of())
        fields = _buy_clean_fields(row)
        bought, limit, price = fields["used"], fields["max"], fields["diamond"]
        if bought >= limit:
            _warn("5_2529", STATUS_CLEAN_BUY_MAX, f"{bought} of {limit} bought at VIP {row['vip']}")
        elif int(row["diamond"]) < price:
            _warn("5_2529", STATUS_NO_DIAMOND, f"needs {price} diamonds, has {row['diamond']}")
        else:
            db.spend(conn, pid, diamond=price)
            conn.execute(
                "UPDATE players SET god_clean_bought = god_clean_bought + 1 WHERE id = ?",
                (pid,),
            )
            conn.commit()
            row = _row(pid)
            notify.player_changed(registry, session, {"diamond": int(row["diamond"])})
            log.info("5_2529 player %d bought sweep %d for %d diamonds", pid, bought + 1, price)
        return _res("GodBuyChapterCleanRes", **_buy_clean_fields(row))

    # 5_2525 GodChapterCleanReq {chapter, times, silver_card, gold_card}
    def sweep(session: Session, req):
        chapter, times = int(req.chapter), int(req.times)
        silver, gold = bool(req.silver_card), bool(req.gold_card)
        res = registry.message_class("GodChapterCleanRes")(times=0)
        row = _player(session)
        if row is None:
            log.warning("5_2525 before any character exists")
            fill_required(res)
            return res
        pid, now = int(row["id"]), now_of()
        row = db.refresh_energy(conn, cfg, _today(pid, now))
        left = _sweeps_left(row)
        res.times = left
        info = cfg.chapter(chapter)
        stages = cfg.stages_in_chapter(chapter) if info is not None else []
        energy = times * sum(int(s["energy"] or 0) for s in stages)
        card_cost = (var_int(cfg, "GOD_SILVER_CARD_COST") if silver else 0) + (
            var_int(cfg, "GOD_GOLD_CARD_COST") if gold else 0)
        diamond = times * len(stages) * card_cost
        need = cfg.function_unlock(FUNCTION_GOD)
        why = None
        if int(row["level"]) < need:
            why = STATUS_LEVEL, f"player level {row['level']} < {need}"
        elif info is None or int(info["type"]) != CHAPTER_GOD:
            why = STATUS_CLEAN_LOCKED, f"chapter {chapter} is not a divine-ruins chapter"
        elif not chapter_cleared(conn, cfg, pid, chapter):
            why = STATUS_CLEAN_LOCKED, f"chapter {chapter} is not fully cleared"
        elif left <= 0:
            why = STATUS_CLEAN_USED, "no sweep left today"
        elif times < 1 or times > left:
            why = STATUS_CLEAN_SHORT, f"times {times}, {left} left"
        elif int(row["energy"]) < energy:
            why = STATUS_NO_ENERGY, f"needs {energy} energy, has {row['energy']}"
        elif int(row["diamond"]) < diamond:
            why = STATUS_NO_DIAMOND, f"needs {diamond} diamonds, has {row['diamond']}"
        if why is not None:
            _warn(f"5_2525 chapter {chapter} x{times}", *why)
            fill_required(res)
            return res

        # Per floor, every sweep's rolls in order: base, then silver, then gold.
        base = [[] for _ in stages]
        cards: dict[str, list[list]] = {"silver_card": [[] for _ in stages],
                                       "gold_card": [[] for _ in stages]}
        picked = [c for c, on in (("silver_card", silver), ("gold_card", gold)) if on]
        for _ in range(times):
            for i, stage in enumerate(stages):
                base[i] += drops.roll(cfg, int(stage["invisible_drops"] or 0), rng=rng)
                base[i] += drops.roll(cfg, int(stage["visible_drops"] or 0), rng=rng)
                for column in picked:
                    cards[column][i] += drops.roll(cfg, int(stage[column] or 0), rng=rng)
        lists = [base] + [cards[c] for c in picked]
        flat = [d for per_floor in lists for rolled in per_floor for d in rolled]
        granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(flat))
        try:
            if diamond:
                db.spend(conn, pid, diamond=diamond)
            db.spend_energy(conn, pid, energy)
            mystery.on_energy_spent(conn, cfg, registry, session, pid, energy, rng=rng, now=now)
            conn.execute(
                "UPDATE players SET god_clean_used = god_clean_used + ? WHERE id = ?",
                (times, pid),
            )
            conn.commit()
            xp_change = db.add_player_xp(
                conn, cfg, pid, times * sum(int(s["player_xp"] or 0) for s in stages)
            )
        except Exception:
            log.error("5_2525 chapter %d x%d: prizes %s granted to player %d but a later "
                      "write failed", chapter, times, drops.as_triples(flat), pid,
                      exc_info=True)
            raise

        targets = [res.drops] + [
            res.silver_drops if c == "silver_card" else res.gold_drops for c in picked
        ]
        for target, per_floor in zip(targets, lists):
            for rolled in per_floor:
                level_entry = target.add()
                for prize in drops.to_prize_entries(registry, rolled):
                    level_entry.drop.add().CopyFrom(prize)
        # The same order as `flat`, which is what grant_prizes indexed.
        item.mark_converted([d for t in targets for e in t for d in e.drop], granted)
        res.times = _sweeps_left(_row(pid))
        item.announce(registry, session, granted)
        notify.items_changed(registry, session, granted["items"])
        fresh = _row(pid)
        notify.player_changed(registry, session, {
            "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
            "xp": int(fresh["xp"]), "level": int(fresh["level"]),
            "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
        })
        if xp_change["levelled"]:
            before, after = xp_change["before"], xp_change["after"]
            notify.level_up(registry, session, (before[0], before[2], before[3]),
                            (after[0], after[2], after[3]))
        log.info("5_2525 player %d swept chapter %d x%d (cards %s): %d energy, %d "
                 "diamonds, prizes %s", pid, chapter, times, picked, energy, diamond,
                 drops.as_triples(flat))
        fill_required(res)
        return res

    # 5_2543 GodDrawReq {idx} -> GodDrawRes {drops, diamond}
    def draw(session: Session, req):
        idx = int(req.idx)
        res = registry.message_class("GodDrawRes")()
        row = _player(session)
        if row is None:
            log.warning("5_2543 before any character exists")
            fill_required(res)
            return res
        pid = int(row["id"])
        cards = int(row["god_is_draw"])
        order = floors(cfg)
        at = order.index(current_floor(cfg, row))
        if int(row["god_fight_status"]) == 0:
            at -= 1         # moved on: the cards are the previous floor's
        why = None
        if not 0 <= idx < len(CARD_DROPS):
            why = STATUS_BAD_DATA, f"card {idx}"
        elif not cards & (1 << idx):
            why = STATUS_DRAWN, f"card {idx} is not on offer (is_draw {cards})"
        elif at < 0:
            why = STATUS_BAD_DATA, "no floor cleared yet"
        if why is not None:
            _warn(f"5_2543 player {pid}", *why)
            fill_required(res)
            return res
        cost = var_int(cfg, CARD_COSTS[idx]) if CARD_COSTS[idx] else 0
        if int(row["diamond"]) < cost:
            _warn(f"5_2543 player {pid}", STATUS_NO_DIAMOND,
                  f"card {idx} needs {cost} diamonds, has {row['diamond']}")
            fill_required(res)
            return res
        stage = cfg.stage(order[at])
        rolled = drops.roll(cfg, int(stage[CARD_DROPS[idx]] or 0), rng=rng)
        granted = item.grant_prizes(conn, cfg, pid, drops.as_triples(rolled))
        if cost:
            db.spend(conn, pid, diamond=cost)
        conn.execute("UPDATE players SET god_is_draw = ? WHERE id = ?",
                     (cards & ~(1 << idx), pid))
        conn.commit()
        for prize in drops.to_prize_entries(registry, rolled):
            res.drops.add().CopyFrom(prize)
        item.mark_converted(res.drops, granted)
        res.diamond = cost
        item.announce(registry, session, granted)
        notify.items_changed(registry, session, granted["items"])
        fresh = _row(pid)
        notify.player_changed(registry, session, {
            "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
        })
        log.info("5_2543 player %d turned card %d of floor %d for %d diamonds: %s",
                 pid, idx, order[at], cost, drops.as_triples(rolled))
        fill_required(res)
        return res

    return {
        (5, 2517): state,
        (5, 2519): reset,
        (5, 2521): query_buy_reset,
        (5, 2523): buy_reset,
        (5, 2525): sweep,
        (5, 2527): query_buy_clean,
        (5, 2529): buy_clean,
        (5, 2531): fight,
        (5, 2543): draw,
        (5, 2547): chest,
        (5, 2551): enter,
        (5, 2563): cd_reset,
    }
