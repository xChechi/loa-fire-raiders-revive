"""Campaign stages: 5_2201 LevelIntoReq, 5_2203 LevelOutReq, the chapter star
chest 5_2209, 5_2205 sweep and 5_2207 reset.

Daily counts: a levels row whose deadline has passed starts the day at count 0
and reset_count 0 (roll_daily_counts), before any handler here reads it.

Wire shape per spec section 4: the server validates the unlock, spends the
energy, rolls 64 randoms and pre-rolls the drops, and the client fights.
LevelIntoRes has no status field (fields: drop, urandom, flag, star), so a
refusal is flag: 1 makes the client float z00224 and reopen the campaign UI,
2 floats z00225 (LevelLine.lua:37-60). The real language.db code goes to the
log, which is the only place it can be said.

Master dungeon (王者副本, chapter_info type 13, Wave 3 B5): its frontier is
last_signet (LevelManager.lua:444-457), the tab opens at function 80020
(LevelTab.lua:43-47,84-87). An entry costs one signet fight instead of energy
(stage energy is 0) and a sweep of n costs n (DesSweepPanel.lua:449-453,
576-579). The client advances its own frontier on a win (LevelManager.lua:
641-655) and last_signet is not a ClientPlayer notify field, so only
signet_fight_cnt is pushed. Drops are category-21 signets: each one gets
5_2742; a full bag mails them (101200) and pushes 5_2744.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import drops, events, hero, item, mystery, notify, signet
from server.modules.player import _end_of_today
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.level")

# BattleAlthm.MAX_URANDOM_SIZE and SCALE (BattleAlthm.lua:14, 27). Any other
# length makes NewAlgorithm return nil and the battle never starts.
URANDOM_SIZE = 64
URANDOM_SCALE = 10000

FLAG_OK = 0
FLAG_STAGE_CHANGED = 1     # z00224, client reopens the campaign UI
FLAG_MAX_TIMES = 2         # z00225

STATUS_NOT_ENOUGH_ENERGY = 327939   # language.db 体力不足, cannot be delivered on 5_2202
STATUS_STAGE_LOCKED = 328193        # language.db 关卡未开启
STATUS_NOT_ENTERED = 328196         # language.db 没有进入关卡
STATUS_ALREADY_CLAIMED = 328194     # language.db 关卡不可重复刷
STATUS_NOT_ENOUGH_STARS = 328197    # language.db 星级不够
STATUS_RESET_LIMIT = 328202         # language.db 达到关卡重置限制
STATUS_NOT_ENOUGH_DIAMOND = 327938  # language.db 钻石不足
STATUS_MAX_TIMES = 328195           # language.db 已经达到最大次数
STATUS_NOT_ENOUGH_ITEM = 327942     # language.db 没有足够道具
STATUS_LEVEL = 327957               # language.db 未满足此玩法的等级

# item_info 1300 精英扫荡券: 10 of them sweep an elite stage once
# (CLEAN_ELITE_ITEM_NUM_EVERYTIME), up to CLEAN_ELITE_TIMES_LIMIT a day.
CLEAN_ELITE_ITEM = 1300

# vip_info 10100 (重置精英关卡次数): resets allowed per stage per day.
VIP_RESET_ENTRY = 10100

PENDING_KEY = "level_pending"

_default_rng = random.SystemRandom()


def roll_urandom(rng: random.Random | None = None) -> list[int]:
    rng = _default_rng if rng is None else rng
    return [rng.randrange(URANDOM_SCALE) for _ in range(URANDOM_SIZE)]


CHAPTER_ELITE = 2   # chapter_info.type of the elite chapters 110000-127000
CHAPTER_SIGNET = 13  # the master dungeon, chapters 9001000-9010000
FUNCTION_MASTER_DUNGEON = 80020     # 王者副本 (LevelTab.lua:43)


def chapter_type(cfg: Config, lvl: int) -> int:
    """chapter_info.type of a stage's chapter; 1 when the chapter is unknown."""
    stage = cfg.stage(lvl)
    chapter = None if stage is None else cfg.chapter(int(stage["chapter"]))
    return 1 if chapter is None else int(chapter["type"])


def frontier(cfg: Config, row: sqlite3.Row, type_: int = 1) -> int:
    """The one stage the player may newly clear. Elite chapters follow
    last_elite, the master dungeon last_signet, the rest last_level
    (LevelManager.lua:409-457)."""
    column = "last_elite" if type_ == CHAPTER_ELITE else "last_level"
    if type_ == CHAPTER_SIGNET:
        column = "last_signet"
    last = int(row[column])
    return cfg.next_stage(last) if last else cfg.first_stage(type_)


def is_unlocked(
    cfg: Config, conn: sqlite3.Connection, row: sqlite3.Row, lvl: int
) -> bool:
    type_ = chapter_type(cfg, lvl)
    progress = db.level_progress(conn, int(row["id"]), lvl)
    if type_ == CHAPTER_ELITE and (progress is None or int(progress["star"]) <= 0):
        # An unstarred elite stage opens only once its relation_level normal
        # stage has a star; a starred one is status 1 and stays open
        # (LevelManager.lua:858-879, LevelBuildTouch.lua:163-185).
        relation = db.level_progress(
            conn, int(row["id"]), int(cfg.stage(lvl)["relation_level"] or 0)
        )
        if relation is None or int(relation["star"]) <= 0:
            return False
    if lvl == frontier(cfg, row, type_):
        return True
    return progress is not None


def chapter_stars(
    cfg: Config, conn: sqlite3.Connection, player_id: int, chapter: int
) -> int:
    """The stars the player holds across one chapter's stages."""
    entries = {int(r["entry"]) for r in cfg.stages_in_chapter(chapter)}
    return sum(
        int(r["star"]) for r in db.levels_of(conn, player_id)
        if int(r["level"]) in entries
    )


def roll_daily_counts(
    conn: sqlite3.Connection, player_id: int, now: int | None = None
) -> None:
    """Every levels row whose deadline has passed gets count 0, reset_count 0,
    clean_elite_count 0 and the end of today as its new deadline."""
    now = int(time.time()) if now is None else int(now)
    conn.execute(
        "UPDATE levels SET count = 0, reset_count = 0, clean_elite_count = 0,"
        " deadline = ?"
        " WHERE player_id = ? AND deadline < ?",
        (_end_of_today(), int(player_id), now),
    )
    conn.commit()


def _ensure_row(conn: sqlite3.Connection, player_id: int, lvl: int) -> None:
    """A stage's first row carries today's deadline, so the next
    roll_daily_counts does not zero the play it was created for."""
    conn.execute(
        "INSERT INTO levels (player_id, level, deadline) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, level) DO NOTHING",
        (int(player_id), int(lvl), _end_of_today()),
    )


def _required(stage: sqlite3.Row, column: str, lvl: int) -> int:
    """A stage_info value the handler cannot work without. A stage the client
    invented is a refusal; a stage the config knows but cannot describe is a
    config gap, and those fail loud naming the entry (Task 11 rule)."""
    value = stage[column]
    if value is None or value == "":
        raise KeyError(f"stage_info row {lvl} has no {column}")
    return int(value)


def _grant_stage_prizes(
    conn: sqlite3.Connection, cfg: Config, player_id: int, prizes
) -> tuple[dict, bool]:
    """item.grant_prizes, except that signets a full bag cannot take go to
    mail 101200 (fu00073 "印记已满，请到邮件中领取！"). True when they did."""
    try:
        return item.grant_prizes(conn, cfg, player_id, prizes), False
    except item.SignetBagFull:
        keep = [i for i, p in enumerate(prizes) if int(p[0]) != item.CATEGORY_SIGNET]
        granted = item.grant_prizes(conn, cfg, player_id, [prizes[i] for i in keep])
        granted["converted"] = [keep[i] for i in granted["converted"]]
        mailed = [p for p in prizes if int(p[0]) == item.CATEGORY_SIGNET]
        granted["mails"].append(
            signet.mail_signets(conn, cfg, player_id, mailed, int(time.time()))
        )
        log.warning("player %d: signet bag full (%d), %d signet(s) mailed",
                    player_id, signet.STATUS_BAG_FULL, len(mailed))
        return granted, True


def _mark_signets(entries, granted: dict) -> None:
    """ClientPrizeExtra.signet_id of each category-21 entry, in grant order:
    TipDrop.lua:65-73 finds the dropped signet by it."""
    ids = iter(granted["signets"])
    for entry in entries:
        signet_id = next(ids, 0) if entry.category == item.CATEGORY_SIGNET else 0
        if signet_id:
            # extra.type is required; 0 is "not converted" (mark_converted).
            entry.extra.type = entry.extra.type
            entry.extra.signet_id = signet_id


def handlers(
    registry: Registry,
    settings: Settings,
    conn: sqlite3.Connection,
    cfg: Config,
    rng: random.Random | None = None,
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _refused(flag: int, star: int = 0):
        res = registry.message_class("LevelIntoRes")(flag=flag, star=star)
        fill_required(res)
        return res

    def level_into(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        if row is None or stage is None:
            log.warning(
                "5_2201 for stage %d: no such stage (%d)", lvl, STATUS_STAGE_LOCKED
            )
            return _refused(FLAG_STAGE_CHANGED)
        session.player_id = int(row["id"])
        row = db.refresh_energy(conn, cfg, row)
        roll_daily_counts(conn, int(row["id"]))
        progress = db.level_progress(conn, int(row["id"]), lvl)

        if not is_unlocked(cfg, conn, row, lvl):
            log.warning("5_2201 stage %d is locked (%d)", lvl, STATUS_STAGE_LOCKED)
            return _refused(FLAG_STAGE_CHANGED)
        if progress is not None and int(stage["once"] or 0) == 1 and int(
            progress["star"]
        ) > 0:
            log.info("5_2201 stage %d is a once-only stage already cleared", lvl)
            return _refused(FLAG_STAGE_CHANGED, star=int(progress["star"]))
        maxcount = int(stage["maxcount"] or 0)
        if maxcount and progress is not None and int(progress["count"]) >= maxcount:
            return _refused(FLAG_MAX_TIMES, star=int(progress["star"]))
        master = chapter_type(cfg, lvl) == CHAPTER_SIGNET
        if master:
            need = cfg.function_unlock(FUNCTION_MASTER_DUNGEON)
            if int(row["level"]) < need:
                log.warning("5_2201 stage %d needs level %d, player is %d (%d)",
                            lvl, need, int(row["level"]), STATUS_LEVEL)
                return _refused(FLAG_STAGE_CHANGED)
            if signet.settle_fights(conn, cfg, int(row["id"])) < 1:
                log.warning("5_2201 stage %d: no signet fight left (%d)",
                            lvl, signet.STATUS_NO_FIGHTS)
                return _refused(
                    FLAG_MAX_TIMES, star=0 if progress is None else int(progress["star"])
                )

        cost = _required(stage, "energy", lvl)
        if int(row["energy"]) < cost:
            log.warning(
                "5_2201 stage %d needs %d energy, player has %d; the client cannot be "
                "told status %d on 5_2202 (no status field), answering flag 1",
                lvl, cost, int(row["energy"]), STATUS_NOT_ENOUGH_ENERGY,
            )
            return _refused(
                FLAG_STAGE_CHANGED, star=0 if progress is None else int(progress["star"])
            )

        # Past here nothing can refuse, so the writes are safe to make.
        if cost:
            db.spend_energy(conn, int(row["id"]), cost)
            mystery.on_energy_spent(conn, cfg, registry, session, int(row["id"]), cost)
        fights_left = signet.spend_fights(conn, cfg, int(row["id"]), 1) if master else None
        visible = drops.roll(cfg, _required(stage, "visible_drops", lvl), rng=rng)
        invisible = drops.roll(cfg, _required(stage, "invisible_drops", lvl), rng=rng)
        # One flat list for the whole entry: level_out grants it all at once.
        rolled = visible + invisible
        session.data.setdefault(PENDING_KEY, {})[lvl] = rolled

        res = registry.message_class("LevelIntoRes")(flag=FLAG_OK, star=0)
        for value in roll_urandom(rng):
            res.urandom.append(value)
        # Only the visible roll goes out on entry: FightData.drops (FightData.lua:33)
        # are the items that visibly fall during the fight. The full list, visible
        # plus invisible, reaches the end screen from LevelOutRes.drop
        # (BattleFactoryLevel:forceResult).
        for entry in drops.to_prize_entries(registry, visible):
            res.drop.add().CopyFrom(entry)
        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        changed = {"energy": int(fresh["energy"])}
        if fights_left is not None:
            changed["signet_fight_cnt"] = fights_left
        notify.player_changed(registry, session, changed)
        log.info(
            "stage %d entered by player %d, %d energy spent, visible drops %s,"
            " invisible %s",
            lvl, int(row["id"]), cost, drops.as_triples(visible),
            drops.as_triples(invisible),
        )
        fill_required(res)
        return res

    def level_out(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        pending = session.data.get(PENDING_KEY, {})
        if row is None or stage is None:
            res = registry.message_class("LevelOutRes")(status=STATUS_STAGE_LOCKED)
            fill_required(res)
            return res
        if lvl not in pending:
            log.warning(
                "5_2203 for stage %d with no matching 5_2201 on this session, "
                "answering %d", lvl, STATUS_NOT_ENTERED,
            )
            res = registry.message_class("LevelOutRes")(status=STATUS_NOT_ENTERED)
            fill_required(res)
            return res

        # Popped before anything is granted: the client retries 5_2203 twice
        # more after a 6 s timeout (BattleFactoryBase.lua:871-930).
        rolled = pending.pop(lvl)
        player_id = int(row["id"])
        elite = chapter_type(cfg, lvl) == CHAPTER_ELITE
        master = chapter_type(cfg, lvl) == CHAPTER_SIGNET
        star = max(0, min(3, int(req.star)))
        won = star > 0

        granted = {"gold": int(row["gold"]), "diamond": int(row["diamond"]), "items": []}
        mailed = False
        hero_xp: list[tuple[int, int, int]] = []
        levels_before: dict[int, int] = {}
        angel_xp: tuple[int, int] | None = None
        xp_change = {"before": None, "after": None, "levelled": False}
        prizes: list[tuple[int, int, int]] = []
        if won:
            prizes = drops.as_triples(rolled)
            prizes.append((item.CATEGORY_GOLD, 0, int(stage["gold"] or 0)))
            # grant_prizes vets the whole list before it writes anything, so it
            # runs before this handler's own irreversible writes (Task 11). If
            # it raises, the pending entry goes back and the retry can replay.
            try:
                granted, mailed = _grant_stage_prizes(conn, cfg, player_id, prizes)
            except Exception:
                pending[lvl] = rolled
                raise

        # Past this line the drops are paid and the pending entry is already
        # popped. Putting it back would re-pay them on the client's retry, and a
        # transaction across these four writes is Plan B2, so the only honest
        # answer to a failure here is an ERROR carrying every fact needed to
        # repair the row by hand, and the exception going up.
        try:
            _ensure_row(conn, player_id, lvl)
            db.upsert_level(conn, player_id, lvl, star=star, count_delta=1)
            if won:
                xp_change = db.add_player_xp(
                    conn, cfg, player_id, int(stage["player_xp"] or 0)
                )
                levels_before = {  # reversed: the lowest id wins, as in add_hero_xp
                    int(h["entry"]): int(h["level"])
                    for h in reversed(db.heroes_of(conn, player_id))
                }
                hero_xp = db.add_hero_xp(
                    conn, cfg, player_id, list(req.heroes), int(stage["unit_xp"] or 0)
                )
                angel_xp = db.add_angel_xp(
                    conn, cfg, player_id, int(req.angel), int(stage["angel_xp"] or 0)
                )
                if elite and lvl == frontier(cfg, row, CHAPTER_ELITE):
                    # db.py has no setter and is not this task's file.
                    conn.execute(
                        "UPDATE players SET last_elite = ? WHERE id = ?",
                        (lvl, player_id),
                    )
                    conn.commit()
                elif master and lvl == frontier(cfg, row, CHAPTER_SIGNET):
                    conn.execute(
                        "UPDATE players SET last_signet = ? WHERE id = ?",
                        (lvl, player_id),
                    )
                    conn.commit()
                elif not elite and not master and lvl == frontier(cfg, row):
                    db.set_last_level(conn, player_id, lvl)
        except Exception:
            log.error(
                "stage %d: payout granted to player %d (star %d, prizes %s) but a"
                " later write failed; the stage is paid and NOT recorded",
                lvl, player_id, star, prizes, exc_info=True,
            )
            raise

        res = registry.message_class("LevelOutRes")(status=0, star=star)

        if won:
            for entry in drops.to_prize_entries(registry, rolled):
                res.drop.add().CopyFrom(entry)
            gold_entry = res.drop.add()
            gold_entry.category = item.CATEGORY_GOLD
            gold_entry.refer = 0
            gold_entry.amount = int(stage["gold"] or 0)
            item.mark_converted(res.drop, granted)
            _mark_signets(res.drop, granted)
            if mailed:
                res.if_mail = True

        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        # BattleEndLayer reads owner.xp and owner.level; refer is unused there.
        res.owner.refer = player_id
        res.owner.level = int(fresh["level"])
        res.owner.xp = int(fresh["xp"])
        for entry, hlevel, hxp in hero_xp:
            # refer is the hero entry: toExpInfo keys heroes by v.refer and
            # BattleEndLayer looks them up by the unit entry.
            client_xp = res.heroes.add()
            client_xp.refer = entry
            client_xp.level = hlevel
            client_xp.xp = hxp
        if angel_xp is not None:
            # BattleFactoryLevel:toExpInfo keys the angel by refer = its
            # angel_entry and BattleEndLayer looks it up by that entry.
            res.angel.refer = int(req.angel)
            res.angel.level, res.angel.xp = angel_xp

        if won:
            # First, so the absolute player values below are the last word.
            item.announce(registry, session, granted)
            notify.items_changed(registry, session, granted["items"])
            signet.obtained(registry, conn, cfg, session, granted["signets"], rng)
            if mailed:
                signet.bag_full(registry, session)
            changed = {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "xp": int(fresh["xp"]), "level": int(fresh["level"]),
                "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
                "last_level": int(fresh["last_level"]),
            }
            if elite:
                changed["last_elite"] = int(fresh["last_elite"])
            notify.player_changed(registry, session, changed)
            if xp_change["levelled"]:
                before = xp_change["before"]
                after = xp_change["after"]
                notify.level_up(
                    registry, session,
                    (before[0], before[2], before[3]), (after[0], after[2], after[3]),
                )
            # BattleFactoryLevel:toExpInfo only feeds the end screen, so the
            # client's ClientHero keeps its old level until one ident-2 notify
            # per hero that gained xp says otherwise (plan B2 settled point 2a).
            if int(stage["unit_xp"] or 0) > 0:
                for entry, _hlevel, _hxp in hero_xp:
                    hero_row = conn.execute(
                        "SELECT * FROM heroes WHERE player_id = ? AND entry = ?"
                        " ORDER BY id", (player_id, entry),
                    ).fetchone()
                    notify.hero_changed(
                        registry, session, entry,
                        hero.hero_notify_fields_with_runes(
                            registry, cfg, hero_row, hero.runes_of(conn, hero_row), conn=conn
                        ),
                    )
            if angel_xp is not None:
                notify.angel_changed(registry, session, int(req.angel), {
                    "level": angel_xp[0], "exp": angel_xp[1],
                })
        log.info(
            "stage %d finished by player %d with %d star(s), won=%s", lvl, player_id,
            star, won,
        )
        if won:
            events.refresh(conn, cfg, registry, session, player_id)
            events.bump(conn, cfg, registry, session, player_id, events.KIND_FIGHT,
                        events.FIGHT_ELITE if elite else events.FIGHT_NORMAL)
            levelled = sum(1 for e, lv, _ in hero_xp if lv > levels_before.get(e, lv))
            if levelled:
                events.bump(conn, cfg, registry, session, player_id,
                            events.KIND_HERO_LEVEL, n=levelled)
        fill_required(res)
        return res

    def chapter_prize(session: Session, req):
        chapter = int(req.chapter)
        row = _player(session)
        info = cfg.chapter(chapter)
        if row is None or info is None:
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_STAGE_LOCKED, chapter=chapter
            )
            fill_required(res)
            return res
        player_id = int(row["id"])
        claimed = {
            int(c["chapter"]): int(c["award"]) for c in db.chapters_of(conn, player_id)
        }
        if claimed.get(chapter):
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_ALREADY_CLAIMED, chapter=chapter
            )
            fill_required(res)
            return res
        # The threshold is chapter_info.star_req0, never a literal: chapter 1
        # has 5 stages, so 15 stars are on offer and the chest asks for 9.
        need = int(info["star_req0"] or 0)
        have = chapter_stars(cfg, conn, player_id, chapter)
        if have < need:
            log.info(
                "chapter %d chest needs %d stars, player has %d", chapter, need, have
            )
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_NOT_ENOUGH_STARS, chapter=chapter
            )
            fill_required(res)
            return res

        # grant_prizes vets the whole list before it writes, so it runs before
        # the irreversible set_chapter_award (Task 11 lesson): an award that
        # cannot be paid leaves the chest claimable.
        rolled = drops.roll(cfg, int(info["award0"] or 0), rng=rng)
        granted = item.grant_prizes(conn, cfg, player_id, drops.as_triples(rolled))
        db.set_chapter_award(conn, player_id, chapter, 1)
        item.announce(registry, session, granted)
        notify.items_changed(registry, session, granted["items"])
        notify.player_changed(registry, session, {
            "gold": granted["gold"], "diamond": granted["diamond"],
        })
        log.info(
            "chapter %d chest paid to player %d: %s", chapter, player_id,
            drops.as_triples(rolled),
        )
        # The client renders the reward panel itself from chapter_info.award0;
        # it only needs status 0 and the chapter back (LevelBoxStarPanel.lua:78).
        res = registry.message_class("LevelChapterPrizeRes")(status=0, chapter=chapter)
        fill_required(res)
        return res

    def level_clean(session: Session, req):
        # LevelCleanRes field 1 is flag, not status (B1 settled point 13), so a
        # refusal cannot float a language text. DesSweepPanel:onReceiveSweepData
        # knows one refusal, flag 1: it resyncs the stage count from `times` and
        # floats z00225 (DesSweepPanel.lua:713-727). Every refusal therefore
        # answers flag 1 with the server's count, and the real code goes to the
        # log.
        lvl, times = int(req.level), int(req.times)
        row = _player(session)
        stage = cfg.stage(lvl)

        def _refused(code: int, why: str, count: int = 0):
            log.warning("5_2205 sweep of stage %d x%d refused (%d): %s",
                        lvl, times, code, why)
            res = registry.message_class("LevelCleanRes")(
                flag=FLAG_STAGE_CHANGED, times=count
            )
            fill_required(res)
            return res

        if row is None or stage is None:
            return _refused(STATUS_STAGE_LOCKED, "no such stage")
        player_id = int(row["id"])
        session.player_id = player_id
        row = db.refresh_energy(conn, cfg, row)
        roll_daily_counts(conn, player_id)
        progress = db.level_progress(conn, player_id, lvl)
        count = 0 if progress is None else int(progress["count"])
        if times < 1:
            return _refused(STATUS_STAGE_LOCKED, "times < 1", count)
        if progress is None or int(progress["star"]) < 3:
            return _refused(STATUS_NOT_ENOUGH_STARS, "not 3-starred", count)
        if int(stage["once"] or 0) == 1:
            # level_into refuses a cleared once-only stage; a sweep must not
            # replay it either.
            return _refused(STATUS_STAGE_LOCKED, "once-only stage", count)
        cost = times * _required(stage, "energy", lvl)
        if int(row["energy"]) < cost:
            return _refused(
                STATUS_NOT_ENOUGH_ENERGY,
                f"needs {cost} energy, has {int(row['energy'])}", count,
            )
        maxcount = int(stage["maxcount"] or 0)
        if maxcount and count + times > maxcount:
            return _refused(
                STATUS_MAX_TIMES, f"count {count} + {times} > maxcount {maxcount}",
                count,
            )
        master = chapter_type(cfg, lvl) == CHAPTER_SIGNET
        if master:
            left = signet.settle_fights(conn, cfg, player_id)
            if left < times:
                return _refused(
                    signet.STATUS_NO_FIGHTS, f"{left} signet fights < {times}", count
                )

        visible_id = _required(stage, "visible_drops", lvl)
        invisible_id = _required(stage, "invisible_drops", lvl)
        per_time = [
            drops.roll(cfg, visible_id, rng=rng) + drops.roll(cfg, invisible_id, rng=rng)
            for _ in range(times)
        ]
        gold = times * int(stage["gold"] or 0)
        prizes = [t for rolled in per_time for t in drops.as_triples(rolled)]
        prizes.append((item.CATEGORY_GOLD, 0, gold))
        # grant_prizes vets the whole list before it writes, so it runs first.
        granted, mailed = _grant_stage_prizes(conn, cfg, player_id, prizes)
        db.spend_energy(conn, player_id, cost)
        mystery.on_energy_spent(conn, cfg, registry, session, player_id, cost)
        if master:
            fights_left = signet.spend_fights(conn, cfg, player_id, times)
        _ensure_row(conn, player_id, lvl)
        new_count = int(
            db.upsert_level(conn, player_id, lvl, count_delta=times)["count"]
        )
        # LevelCleanRes has no field for hero xp, so a sweep pays none.
        xp_change = db.add_player_xp(
            conn, cfg, player_id, times * int(stage["player_xp"] or 0)
        )

        res = registry.message_class("LevelCleanRes")(flag=FLAG_OK, times=new_count)
        for rolled in per_time:
            entry = res.drops.add()
            for prize in drops.to_prize_entries(registry, rolled):
                entry.drop.add().CopyFrom(prize)
        # prizes is every time's drops in order, then the gold.
        item.mark_converted([d for e in res.drops for d in e.drop], granted)
        _mark_signets([d for e in res.drops for d in e.drop], granted)
        if mailed:
            res.if_mail = True

        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        item.announce(registry, session, granted)
        notify.items_changed(registry, session, granted["items"])
        signet.obtained(registry, conn, cfg, session, granted["signets"], rng)
        if mailed:
            signet.bag_full(registry, session)
        changed = {
            "gold": int(fresh["gold"]), "xp": int(fresh["xp"]),
            "level": int(fresh["level"]), "energy": int(fresh["energy"]),
            "max_energy": int(fresh["max_energy"]),
        }
        if master:
            changed["signet_fight_cnt"] = fights_left
        notify.player_changed(registry, session, changed)
        if xp_change["levelled"]:
            before, after = xp_change["before"], xp_change["after"]
            notify.level_up(
                registry, session,
                (before[0], before[2], before[3]), (after[0], after[2], after[3]),
            )
        log.info(
            "stage %d swept x%d by player %d: %d energy, %d gold, drops %s",
            lvl, times, player_id, cost, gold, prizes[:-1],
        )
        # A sweep of n is n plays of the stage (DesSweepPanel.lua:715-720).
        elite = chapter_type(cfg, lvl) == CHAPTER_ELITE
        events.bump(conn, cfg, registry, session, player_id, events.KIND_FIGHT,
                    events.FIGHT_ELITE if elite else events.FIGHT_NORMAL, n=times)
        fill_required(res)
        return res

    def level_reset(session: Session, req):
        # DesBuyPanel:onReset reads status and reset_count (DesBuyPanel.lua:
        # 246-257); a non-zero status floats its language text.
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)

        def _answer(status: int, reset_count: int = 0):
            res = registry.message_class("LevelResetRes")(
                status=status, reset_count=reset_count
            )
            fill_required(res)
            return res

        if row is None or stage is None:
            log.warning("5_2207 for stage %d: no such stage (%d)", lvl,
                        STATUS_STAGE_LOCKED)
            return _answer(STATUS_STAGE_LOCKED)
        player_id = int(row["id"])
        session.player_id = player_id
        roll_daily_counts(conn, player_id)
        progress = db.level_progress(conn, player_id, lvl)
        used = 0 if progress is None else int(progress["reset_count"])
        allowed = int(cfg.vip_value(VIP_RESET_ENTRY, int(row["vip"])) or 0)
        if used >= allowed:
            log.info("5_2207 stage %d: reset %d of %d at VIP %d (%d)", lvl, used,
                     allowed, int(row["vip"]), STATUS_RESET_LIMIT)
            return _answer(STATUS_RESET_LIMIT, used)
        # MMTools:getCostNum(LEVEL_RESET_COST, reset_count) (DesBuyPanel.lua:
        # 203-204): "price|count,..." tiers, the price of the tier that holds
        # reset number used + 1; past the last tier the client says 0.
        raw = cfg.variable("LEVEL_RESET_COST")
        if not raw:
            raise KeyError("variables.LEVEL_RESET_COST is missing")
        price, total = 0, 0
        for part in raw.split(","):
            tier_price, tier_count = part.split("|")
            total += int(tier_count)
            if used + 1 <= total:
                price = int(tier_price)
                break
        if int(row["diamond"]) < price:
            log.info("5_2207 stage %d: reset costs %d diamonds, player has %d (%d)",
                     lvl, price, int(row["diamond"]), STATUS_NOT_ENOUGH_DIAMOND)
            return _answer(STATUS_NOT_ENOUGH_DIAMOND, used)

        db.spend(conn, player_id, diamond=price)
        _ensure_row(conn, player_id, lvl)
        conn.execute(
            "UPDATE levels SET count = 0, reset_count = ? WHERE player_id = ?"
            " AND level = ?", (used + 1, player_id, lvl),
        )
        conn.commit()
        diamond = conn.execute(
            "SELECT diamond FROM players WHERE id = ?", (player_id,)
        ).fetchone()["diamond"]
        notify.player_changed(registry, session, {"diamond": int(diamond)})
        log.info("stage %d reset by player %d (reset %d today) for %d diamonds",
                 lvl, player_id, used + 1, price)
        return _answer(0, used + 1)

    def clean_elite(session: Session, req):
        # UseCleanEliteItemRes has no status (LevelItemSweep.lua:79-139), so a
        # refusal changes nothing, logs the language.db code it would have
        # used and answers the unchanged count. O-W2-12: no energy, no
        # maxcount; drops, gold and player xp as a 5_2205 sweep.
        lvl, amount = int(req.level_entry), int(req.amount)
        row = _player(session)
        stage = cfg.stage(lvl)
        per = cfg.variable_int("CLEAN_ELITE_ITEM_NUM_EVERYTIME", 10)
        limit = cfg.variable_int("CLEAN_ELITE_TIMES_LIMIT", 9)
        times = amount // per if per > 0 else 0

        def _answer(count: int, done: int = 0):
            return registry.message_class("UseCleanEliteItemRes")(
                times=done, level_entry=lvl, level_clean_elite_count=count
            )

        def _refused(code: int, why: str, count: int = 0):
            log.warning("5_2337 item sweep of stage %d with %d tickets refused"
                        " (%d): %s", lvl, amount, code, why)
            res = _answer(count)
            fill_required(res)
            return res

        if row is None or stage is None:
            return _refused(STATUS_STAGE_LOCKED, "no such stage")
        player_id = int(row["id"])
        session.player_id = player_id
        roll_daily_counts(conn, player_id)
        progress = db.level_progress(conn, player_id, lvl)
        count = 0 if progress is None else int(progress["clean_elite_count"])
        if times < 1:
            return _refused(STATUS_STAGE_LOCKED, f"amount {amount} < {per}", count)
        if progress is None or int(progress["star"]) < 3:
            return _refused(STATUS_NOT_ENOUGH_STARS, "not 3-starred", count)
        if count + times > limit:
            return _refused(
                STATUS_MAX_TIMES, f"count {count} + {times} > limit {limit}", count
            )
        cost = times * per
        owned = conn.execute(
            "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
            (player_id, CLEAN_ELITE_ITEM),
        ).fetchone()
        have = 0 if owned is None else int(owned["amount"])
        if have < cost:
            return _refused(
                STATUS_NOT_ENOUGH_ITEM,
                f"needs {cost} of item {CLEAN_ELITE_ITEM}, has {have}", count,
            )

        visible_id = _required(stage, "visible_drops", lvl)
        invisible_id = _required(stage, "invisible_drops", lvl)
        per_time = [
            drops.roll(cfg, visible_id, rng=rng) + drops.roll(cfg, invisible_id, rng=rng)
            for _ in range(times)
        ]
        gold = times * int(stage["gold"] or 0)
        prizes = [t for rolled in per_time for t in drops.as_triples(rolled)]
        prizes.append((item.CATEGORY_GOLD, 0, gold))
        # grant_prizes vets the whole list before it writes, so it runs first.
        granted = item.grant_prizes(conn, cfg, player_id, prizes)
        tickets_left = db.take_item(conn, player_id, CLEAN_ELITE_ITEM, cost)
        _ensure_row(conn, player_id, lvl)
        conn.execute(
            "UPDATE levels SET clean_elite_count = clean_elite_count + ?"
            " WHERE player_id = ? AND level = ?", (times, player_id, lvl),
        )
        conn.commit()
        new_count = count + times
        xp_change = db.add_player_xp(
            conn, cfg, player_id, times * int(stage["player_xp"] or 0)
        )

        res = _answer(new_count, times)
        for rolled in per_time:
            entry = res.drops.add()
            for prize in drops.to_prize_entries(registry, rolled):
                entry.drop.add().CopyFrom(prize)
        item.mark_converted([d for e in res.drops for d in e.drop], granted)

        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        item.announce(registry, session, granted)
        notify.items_changed(
            registry, session, granted["items"] + [(CLEAN_ELITE_ITEM, tickets_left)]
        )
        notify.player_changed(registry, session, {
            "gold": int(fresh["gold"]), "xp": int(fresh["xp"]),
            "level": int(fresh["level"]), "energy": int(fresh["energy"]),
            "max_energy": int(fresh["max_energy"]),
        })
        if xp_change["levelled"]:
            before, after = xp_change["before"], xp_change["after"]
            notify.level_up(
                registry, session,
                (before[0], before[2], before[3]), (after[0], after[2], after[3]),
            )
        log.info(
            "stage %d item-swept x%d by player %d: %d tickets, %d gold, drops %s",
            lvl, times, player_id, cost, gold, prizes[:-1],
        )
        elite = chapter_type(cfg, lvl) == CHAPTER_ELITE
        events.bump(conn, cfg, registry, session, player_id, events.KIND_FIGHT,
                    events.FIGHT_ELITE if elite else events.FIGHT_NORMAL, n=times)
        fill_required(res)
        return res

    return {
        (5, 2201): level_into,
        (5, 2203): level_out,
        (5, 2205): level_clean,
        (5, 2207): level_reset,
        (5, 2209): chapter_prize,
        (5, 2337): clean_elite,
    }
