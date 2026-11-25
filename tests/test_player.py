"""QueryMyselfRes for a fresh player and the five main-city stubs.

Every server here binds 127.0.0.1 explicitly through bind_host (settings.host
stays the client-side address) and takes port 0, so assertions use server.port.
"""

import asyncio
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, grant_hero, grant_item
from server.modules import player
from server.net.registry import Registry
from server.net.server import Server, fill_required
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg():
    conf = Config.load(STOCK)
    yield conf
    conf.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", "127.0.0.1", bind=BIND,
                    port=0, username="stefan", guide_id=0)


@pytest.fixture
def row(settings: Settings):
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)
    return conn, find_player(conn, "stefan")


def test_query_myself_res_serializes(reg, cfg, row) -> None:
    """Review Focus 1. The fixture is a bare create_player with no starting kit,
    so this character owns nothing yet; the kit is covered by test_login.py."""
    conn, r = row
    res = player.build_query_myself_res(reg, cfg, conn, r)
    raw = res.SerializeToString()
    assert raw  # non-empty
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(raw)
    assert parsed.status == 0
    assert parsed.player.username == "stefan"
    assert parsed.player.nickname == "stefan"
    assert parsed.player.level == 1
    assert parsed.HasField("stats")
    assert parsed.HasField("gold_trails")
    assert len(parsed.heroes) == 0
    assert len(parsed.inventory) == 0
    assert len(parsed.levels) == 0
    assert len(parsed.angels) == 0


def test_query_myself_res_carries_a_granted_hero(reg, cfg, row) -> None:
    """A character that owns a hero sends it inside QueryMyselfRes, and the
    whole message still serializes with its proto2 required fields set."""
    conn, r = row
    grant_hero(conn, int(r["id"]), 100000, 10, star=1, level=1)
    res = player.build_query_myself_res(reg, cfg, conn, r)
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(res.SerializeToString())
    assert len(parsed.heroes) == 1
    assert parsed.heroes[0].entry == 100000
    assert parsed.heroes[0].prototype == 100000
    assert parsed.heroes[0].unit.max_hp == 100


def test_query_myself_res_carries_the_bag_merged_per_entry(reg, cfg, row) -> None:
    """The bag travels in QueryMyselfRes.inventory as one ClientStock per item
    entry: a repeat grant of an entry the player already owns raises its amount
    instead of adding a second stock, and the whole message still encodes with
    its proto2 required fields filled."""
    conn, r = row
    grant_item(conn, int(r["id"]), 10000, 3)
    grant_item(conn, int(r["id"]), 1100, 2)
    grant_item(conn, int(r["id"]), 10000, 1)
    res = player.build_query_myself_res(reg, cfg, conn, r)
    fill_required(res)
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(res.SerializeToString())
    assert [(s.entry, s.amount) for s in parsed.inventory] == [(10000, 4), (1100, 2)]
    assert [s.index for s in parsed.inventory] == [0, 1]


def test_player_sets_every_field_lua_concatenates(reg, row) -> None:
    """Review Focus 2: ClientPlayer:updateData concatenates nobility_level."""
    _, r = row
    p = player.build_client_player(reg, r)
    assert p.HasField("nobility_level")
    assert p.HasField("nobility_exp")
    assert p.HasField("guild_id")


def test_every_required_client_player_field_is_set(reg, row) -> None:
    _, r = row
    p = player.build_client_player(reg, r)
    missing = [
        fd.name for fd in p.DESCRIPTOR.fields if fd.is_required and not p.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in p.DESCRIPTOR.fields if fd.is_required]) == 30


def test_every_required_daily_stats_field_is_set(reg) -> None:
    s = player.build_daily_stats(reg)
    missing = [
        fd.name for fd in s.DESCRIPTOR.fields if fd.is_required and not s.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in s.DESCRIPTOR.fields if fd.is_required]) == 19


def test_arena_and_goddess_trial_coins_come_from_the_stored_row(reg, settings) -> None:
    """ClientPlayer.lua:360-363 reads both off the login ClientPlayer."""
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET arena_point = 1000, angel_money = 52")
    conn.commit()
    p = player.build_client_player(reg, find_player(conn, "stefan"))
    assert (p.arena_point, p.angel_money) == (1000, 52)


def test_guide_id_comes_from_the_stored_row(reg, settings) -> None:
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=14302)
    p = player.build_client_player(reg, find_player(conn, "stefan"))
    assert p.guide_id == 14302


def test_the_five_main_city_stubs_serialize(reg, settings, cfg) -> None:
    """Every explicit main-city Res must survive proto2 required-field encoding."""
    conn = connect(settings.db_path)
    handlers = player.handlers(reg, settings, conn, cfg)
    expected = {
        (5, 2317): "GameReadyRes",
        (5, 2801): "QueryMyPushMessageRes",
        (5, 2943): "QueryBtCardRecordRes",
        (153, 2001): "MagicStateRes",
        (151, 2041): "TounamentQuerySeasonStateRes",
    }
    for key, name in expected.items():
        res = handlers[key](None, None)
        assert res.DESCRIPTOR.name == name
        fill_required(res)
        res.SerializeToString()
    assert handlers[(153, 2001)](None, None).match_state == 99


def test_query_myself_over_a_socket(reg, settings, row, cfg) -> None:
    conn, _ = row

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(5, 2005)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.player.username == "stefan"
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_query_myself_without_any_character_answers_status_one(reg, settings, cfg) -> None:
    """No login and no row: a status 1 stub, never a crash."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(5, 2005)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.status == 1
        assert not res.HasField("player")
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_the_five_main_city_messages_are_answered(reg, settings, row, cfg) -> None:
    conn, _ = row
    expected = {(5, 2317): 2318, (5, 2801): 2802, (5, 2943): 2944,
                (153, 2001): 2002, (151, 2041): 2042}

    async def scenario() -> None:
        server = Server(
            reg, settings, player.handlers(reg, settings, conn, cfg), bind_host=BIND
        )
        task, port = await _run_server(server)
        c = await Client.connect(port)
        for (service, cmd), res_cmd in expected.items():
            await c.send(service, cmd)
            frame = await c.recv()
            assert (frame.service, frame.cmd) == (service, res_cmd)
        assert server.sent_unknown == set()
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_bt_cards_carries_both_privilege_cards(reg) -> None:
    """Review Focus 5: RoleData:updateRechangeCardsList does for i = 1,#data
    over btCards, and RechangeCardPanel builds its boxes from the same
    variables.db key, so the entries must be 100000 and 100100 in that order."""
    from server.config import Config
    from server.modules.player import build_bt_cards

    cfg = Config.load(STOCK)
    res = build_bt_cards(reg, cfg)
    assert [c.entry for c in res.btCards] == [100000, 100100]
    assert [c.isActivation for c in res.btCards] == [False, False]
    assert [c.isAward for c in res.btCards] == [False, False]
    res.SerializeToString()
    cfg.close()


def test_bt_cards_fails_loud_when_the_award_key_is_missing(reg, monkeypatch) -> None:
    """An empty btCards is the Plan A crash shape: RoleData:updateRechangeCardsList
    measures the repeated field with #, so a silently empty list is worse than a
    refusal. A missing config value raises (Task 6 rule)."""
    from server.config import Config
    from server.modules.player import build_bt_cards

    cfg = Config.load(STOCK)
    monkeypatch.setattr(cfg, "variable", lambda key: None)
    with pytest.raises(KeyError, match="variables.BT_CARD_AWARD"):
        build_bt_cards(reg, cfg)
    cfg.close()


def test_query_myself_reports_the_regenerated_energy(reg, settings, cfg) -> None:
    """5_2005 answers with the lazily regenerated energy, not the stored one."""
    from server.net.server import Session

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET energy = 10, energy_at = 0 WHERE id = ?", (pid,)
    )
    conn.commit()
    handlers = player.handlers(reg, settings, conn, cfg)
    # Session(writer=None) is safe: query_myself only returns a message.
    res = handlers[(5, 2005)](
        Session(writer=None, peer="t", bound_port=0),
        reg.message_class("QueryMyselfReq")(),
    )
    assert res.player.energy == 60
    assert res.player.max_energy == 60


def test_levels_and_last_level_reach_the_client(reg, settings, cfg) -> None:
    """LevelManager:readLastLevelInfo takes the unlock frontier from
    player.last_level, and readServerLevelInfo takes the stars from levels."""
    from server.db import set_last_level, upsert_level

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    set_last_level(conn, pid, 10000)
    res = player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert [(l.level, l.star, l.count) for l in res.levels] == [(10000, 3, 1)]
    assert res.player.last_level == 10000
    assert res.player.last_elite == 0
    res.SerializeToString()


def test_chapters_only_contains_real_chapter_entries(reg, settings, cfg) -> None:
    """Review Focus 3: LevelManager:readBoxInfo indexes chapterEntryTable by the
    entry we send, with no nil check, so an entry chapter_info does not know
    crashes the client."""
    from server.db import set_chapter_award

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_chapter_award(conn, pid, 10000, 1)
    set_chapter_award(conn, pid, 424242, 1)        # not a chapter_info entry
    res = player.build_query_myself_res(reg, cfg, conn, find_player(conn, "stefan"))
    assert [c.chapter for c in res.chapters] == [10000]
    assert res.chapters[0].award == 1
    res.SerializeToString()


# --- Plan B2 T6: angels, mail flag, events, login-award bits, daily counters --

def _query(reg, cfg, conn, today=None):
    res = player.build_query_myself_res(
        reg, cfg, conn, find_player(conn, "stefan"), today=today
    )
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(res.SerializeToString())
    return parsed


def test_query_myself_carries_owned_angels(reg, cfg, row) -> None:
    """AngelManager:parseAngel overlays QueryMyselfRes.angels on its roster,
    and above level 10 an empty list forces a logout (AngelManager.lua:60-68)."""
    from server.db import grant_angel

    conn, r = row
    grant_angel(conn, int(r["id"]), 500000, level=1, star=1)
    parsed = _query(reg, cfg, conn)
    assert [(a.angel_entry, a.star, a.level) for a in parsed.angels] == [(500000, 1, 1)]
    assert list(parsed.angels[0].spells) == [5000000, 5010000]
    assert len(parsed.angels[0].auras) == 6


def test_query_myself_mail_new_only_for_unchecked_unexpired(reg, cfg, row) -> None:
    import time

    conn, r = row
    pid, now = int(r["id"]), int(time.time())
    assert _query(reg, cfg, conn).mail_new == 0
    conn.execute(
        "INSERT INTO mails (player_id, entry, created, expires, checked)"
        " VALUES (?, 99999, ?, ?, 1)", (pid, now, now + 86400),
    )
    conn.execute(
        "INSERT INTO mails (player_id, entry, created, expires, checked)"
        " VALUES (?, 99999, ?, ?, 0)", (pid, now - 90000, now - 10),
    )
    conn.commit()
    assert _query(reg, cfg, conn).mail_new == 0
    conn.execute(
        "INSERT INTO mails (player_id, entry, created, expires, checked)"
        " VALUES (?, 99999, ?, ?, 0)", (pid, now, now + 86400),
    )
    conn.commit()
    assert _query(reg, cfg, conn).mail_new == 1


def test_query_myself_events_exclude_claimed(reg, cfg, row) -> None:
    conn, r = row
    pid = int(r["id"])
    conn.executemany(
        "INSERT INTO events (player_id, entry, progress, done, claimed)"
        " VALUES (?, ?, ?, ?, ?)",
        [(pid, 10270, 3, 0, 0), (pid, 10280, 1, 1, 0), (pid, 10290, 1, 1, 1)],
    )
    conn.commit()
    parsed = _query(reg, cfg, conn)
    assert [(e.entry, e.cur_progress, e.done) for e in parsed.events] == [
        (10270, 3, 0), (10280, 1, 1)
    ]


def test_client_player_login_award_from_column(reg, cfg, row) -> None:
    conn, r = row
    conn.execute(
        "UPDATE players SET login_award = ? WHERE id = ?", (0b1_0000_0001, int(r["id"]))
    )
    conn.commit()
    assert _query(reg, cfg, conn).player.login_award == 0b1_0000_0001


def test_daily_stats_counters_reset_on_a_new_day(reg, cfg, row) -> None:
    conn, r = row
    pid = int(r["id"])
    conn.execute(
        "UPDATE players SET buy_energy_used = 2, buy_gold_used = 5,"
        " daily_day = '2026-11-24' WHERE id = ?", (pid,),
    )
    conn.commit()
    same_day = _query(reg, cfg, conn, today="2026-11-24")
    assert (same_day.stats.buy_energy, same_day.stats.buy_gold) == (2, 5)
    next_day = _query(reg, cfg, conn, today="2026-11-25")
    assert (next_day.stats.buy_energy, next_day.stats.buy_gold) == (0, 0)
    stored = find_player(conn, "stefan")
    assert (stored["buy_energy_used"], stored["daily_day"]) == (0, "2026-11-25")


def test_daily_stats_carry_paid_store_refreshes(reg, cfg, row) -> None:
    """The client counts only paid refreshes in store_refresh_times_<store>
    (AllShopUI.lua:736-739): refresh_used - free_refresh, never below 0, and 0
    for a row whose counter belongs to an older day. Store 1 has 4 free
    refreshes, store 2 none, store 3 one."""
    from datetime import date

    conn, r = row
    pid = int(r["id"])
    today = date.today().isoformat()
    for store, used, day in ((1, 6, today), (2, 3, today), (3, 1, today), (4, 5, "2000-01-01")):
        conn.execute(
            "INSERT INTO stores (player_id, store, lastupdate, slots, refresh_used,"
            " refresh_day) VALUES (?, ?, 0, '[]', ?, ?)", (pid, store, used, day),
        )
    conn.commit()
    stats = player.build_query_myself_res(reg, cfg, conn, r).stats
    assert stats.store_refresh_times_1 == 2
    assert stats.store_refresh_times_2 == 3
    assert stats.store_refresh_times_3 == 0
    assert stats.store_refresh_times_4 == 0


# --- Wave 2 A6: last_elite and the Phase B daily counters -------------------

def test_query_myself_sends_last_elite(reg, cfg, row) -> None:
    """LevelManager.lua:427-444: 0 = elite just opened, else the last elite
    stage cleared."""
    conn, r = row
    assert _query(reg, cfg, conn).player.last_elite == 0
    conn.execute("UPDATE players SET last_elite = 110010 WHERE id = ?", (int(r["id"]),))
    conn.commit()
    assert _query(reg, cfg, conn).player.last_elite == 110010


def test_daily_stats_mystery_and_gold_trail_counters_reset_on_a_new_day(
    reg, cfg, row
) -> None:
    """show_store_times and energy_use belong to mystery_day, gold_trails_times
    and the QueryMyselfRes.gold_trails ladder ("今日累计伤害", x02003) to
    gold_trails_day. A counter from another day reads 0; nothing is written."""
    conn, r = row
    pid = int(r["id"])
    conn.execute(
        "UPDATE players SET mystery_shown = 1, energy_use = 84,"
        " mystery_day = '2026-11-24', gold_trails_times = 2,"
        " gold_trails_best = 50000, gold_trails_prize = 3,"
        " gold_trails_day = '2026-11-24' WHERE id = ?", (pid,),
    )
    conn.commit()
    same = _query(reg, cfg, conn, today="2026-11-24")
    assert (same.stats.show_store_times, same.stats.energy_use) == (1, 84)
    assert same.stats.gold_trails_times == 2
    assert (same.gold_trails.damage, same.gold_trails.prize) == (50000, 3)
    nxt = _query(reg, cfg, conn, today="2026-11-25")
    assert (nxt.stats.show_store_times, nxt.stats.energy_use) == (0, 0)
    assert nxt.stats.gold_trails_times == 0
    assert nxt.gold_trails.HasField("prize")
    assert (nxt.gold_trails.damage, nxt.gold_trails.prize) == (0, 0)
    stored = find_player(conn, "stefan")
    assert (stored["mystery_shown"], stored["gold_trails_times"]) == (1, 2)


def test_level_reporter_query_answers_empty(reg, settings, cfg) -> None:
    # DesFlagPanel.lua:62-75 sends 5_2623 when a stage's flag panel opens and
    # draws cells only `if firstReporter`: an empty answer is harmless.
    conn = connect(settings.db_path)
    handlers = player.handlers(reg, settings, conn, cfg)
    req = reg.message_class("LevelReporterQueryReq")(level=10012)
    res = handlers[(5, 2623)](None, req)
    assert res.DESCRIPTOR.name == "LevelReporterQueryRes"
    assert not res.HasField("first_reporter")
    assert len(res.reporters) == 0
    assert res.IsInitialized()
    res.SerializeToString()


def test_sync_red_point_sends_nothing_and_is_registered(
    reg, settings, cfg, caplog, monkeypatch
) -> None:
    # 5_2039 SyncRedPointReq has no Res (GameToolsBtnPanel.lua:102-120 sends
    # it every 60 s): the handler returns None, so the server sends nothing.
    import logging

    monkeypatch.setattr(player, "_red_point_logged", False)
    conn = connect(settings.db_path)
    handlers = player.handlers(reg, settings, conn, cfg)
    assert (5, 2039) in handlers
    req = reg.message_class("SyncRedPointReq")(angel_count=0)
    with caplog.at_level(logging.DEBUG, logger="loa.player"):
        assert handlers[(5, 2039)](None, req) is None
        assert handlers[(5, 2039)](None, req) is None
    lines = [r for r in caplog.records if "5_2039 SyncRedPointReq has no Res" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.DEBUG
    assert lines[0].getMessage() == "5_2039 SyncRedPointReq has no Res; nothing to send"
