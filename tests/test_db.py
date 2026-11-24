from pathlib import Path

from server.db import connect, create_player, find_player

STOCK = Path(".stock")


def test_connect_creates_the_file_and_the_tables(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "player.db"
    conn = connect(db)
    assert db.exists()
    names = {
        row["name"]
        for row in conn.execute("select name from sqlite_master where type='table'")
    }
    assert {"players", "heroes", "angels", "items"} <= names


def test_create_and_find_player(tmp_path: Path) -> None:
    conn = connect(tmp_path / "player.db")
    assert find_player(conn, "stefan") is None

    pid = create_player(conn, "stefan", "Stefan", guide_id=0)

    row = find_player(conn, "stefan")
    assert row is not None
    assert row["id"] == pid
    assert row["username"] == "stefan"
    assert row["nickname"] == "Stefan"
    assert row["level"] == 1
    assert row["guide_id"] == 0
    assert row["created_at"] is not None


def test_create_player_is_rejected_twice(tmp_path: Path) -> None:
    import sqlite3

    conn = connect(tmp_path / "player.db")
    create_player(conn, "stefan", "Stefan", guide_id=0)
    try:
        create_player(conn, "stefan", "Stefan", guide_id=0)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("username must be unique")


def test_energy_at_column_is_added_to_an_old_database(tmp_path: Path) -> None:
    """Additive migration only: a Plan A player.db must open and keep its row."""
    import sqlite3

    from server.db import PLAN_A_SCHEMA_PROBE

    path = tmp_path / "player.db"
    raw = sqlite3.connect(path)
    raw.executescript(PLAN_A_SCHEMA_PROBE)
    raw.execute(
        "INSERT INTO players (username, nickname, level, xp, gold, diamond, vip,"
        " energy, max_energy, avatar, guide_id, created_at)"
        " VALUES ('stefan', 'Stefan', 7, 310, 1234, 55, 1, 48, 72, 3, 10041,"
        " '2026-10-21T12:31:00+00:00')"
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    row = find_player(conn, "stefan")
    assert row is not None
    # Every Plan A column survives untouched.
    assert (row["nickname"], row["level"], row["xp"], row["gold"]) == (
        "Stefan", 7, 310, 1234
    )
    assert (row["diamond"], row["vip"], row["energy"], row["max_energy"]) == (
        55, 1, 48, 72
    )
    assert int(row["avatar"]) == 3
    assert int(row["guide_id"]) == 10041
    assert row["created_at"] == "2026-10-21T12:31:00+00:00"
    # The columns added after Plan A carry their defaults.
    assert int(row["energy_at"]) == 0
    assert int(row["last_level"]) == 0
    assert int(row["gold_single_draws"]) == 0
    assert int(row["diamond_single_draws"]) == 0


def test_refresh_energy_regenerates_one_per_360_seconds(tmp_path: Path) -> None:
    from server.config import Config
    from server.db import refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET energy = 40, energy_at = 1000 WHERE id = ?", (pid,)
    )
    conn.commit()

    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=1000 + 3 * 360)
    assert int(row["energy"]) == 43
    assert int(row["energy_at"]) == 1000 + 3 * 360
    # No regeneration before a whole cycle has elapsed, and the remainder of a
    # partial cycle is not thrown away.
    row = refresh_energy(conn, cfg, row, now=1000 + 3 * 360 + 359)
    assert int(row["energy"]) == 43
    assert int(row["energy_at"]) == 1000 + 3 * 360
    row = refresh_energy(conn, cfg, row, now=1000 + 3 * 360 + 360)
    assert int(row["energy"]) == 44
    cfg.close()


def test_refresh_energy_clamps_at_the_level_cap(tmp_path: Path) -> None:
    from server.config import Config
    from server.db import refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET energy = 59, energy_at = 0 WHERE id = ?", (pid,))
    conn.commit()
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=100_000)
    assert int(row["energy"]) == 60          # xp_for_level lvl 1 max_energy
    assert int(row["max_energy"]) == 60
    # At the cap the clock moves with the player: no credit accumulates.
    assert int(row["energy_at"]) == 100_000
    cfg.close()


def test_max_energy_follows_the_player_level(tmp_path: Path) -> None:
    from server.config import Config
    from server.db import refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET level = 3 WHERE id = ?", (pid,))
    conn.commit()
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=0)
    assert int(row["max_energy"]) == 64      # xp_for_level lvl 3
    cfg.close()


def test_refresh_energy_keeps_the_stored_cap_for_a_level_config_does_not_know(
    tmp_path: Path,
) -> None:
    """xp_for_level stops at 105; a lookup past it returns None (Config rule),
    and then the stored max_energy is the cap instead of a crash."""
    from server.config import Config
    from server.db import refresh_energy

    cfg = Config.load(STOCK)
    assert cfg.xp_for_level(9999) is None
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET level = 9999, energy = 40, max_energy = 70,"
        " energy_at = 1000 WHERE id = ?", (pid,)
    )
    conn.commit()
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=1000 + 360)
    assert int(row["max_energy"]) == 70
    assert int(row["energy"]) == 41
    cfg.close()


def test_spend_energy_never_goes_below_zero(tmp_path: Path) -> None:
    from server.db import spend_energy

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    spend_energy(conn, pid, 12)
    assert int(find_player(conn, "stefan")["energy"]) == 48
    spend_energy(conn, pid, 500)
    assert int(find_player(conn, "stefan")["energy"]) == 0


def test_add_energy_stops_at_the_level_cap(tmp_path: Path) -> None:
    from server.config import Config
    from server.db import add_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET energy = 50 WHERE id = ?", (pid,))
    conn.commit()
    add_energy(conn, cfg, pid, 4)
    assert int(find_player(conn, "stefan")["energy"]) == 54
    add_energy(conn, cfg, pid, 100)
    assert int(find_player(conn, "stefan")["energy"]) == 60
    cfg.close()


def test_grant_item_adds_to_the_same_entry(tmp_path) -> None:
    from server.db import connect, create_player, grant_item, items_of

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    assert grant_item(conn, pid, 1100, 3) == 3
    assert grant_item(conn, pid, 1100, 2) == 5
    assert grant_item(conn, pid, 10000, 2) == 2
    assert {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)} == {
        1100: 5, 10000: 2
    }


def test_upsert_level_keeps_the_best_star_and_counts_plays(tmp_path) -> None:
    from server.db import connect, create_player, level_progress, upsert_level

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    upsert_level(conn, pid, 10000, star=2, count_delta=1)
    row = level_progress(conn, pid, 10000)
    assert (int(row["star"]), int(row["count"])) == (2, 1)
    upsert_level(conn, pid, 10000, star=1, count_delta=1)
    row = level_progress(conn, pid, 10000)
    assert (int(row["star"]), int(row["count"])) == (2, 2)   # 1 does not beat 2
    upsert_level(conn, pid, 10000, star=3, count_delta=0)
    assert int(level_progress(conn, pid, 10000)["star"]) == 3


def test_chapter_award_is_remembered(tmp_path) -> None:
    from server.db import chapters_of, connect, create_player, set_chapter_award

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_chapter_award(conn, pid, 10000, 1)
    set_chapter_award(conn, pid, 10000, 1)
    assert [(int(r["chapter"]), int(r["award"])) for r in chapters_of(conn, pid)] == [
        (10000, 1)
    ]


def test_wave1_tables_exist(tmp_path) -> None:
    conn = connect(tmp_path / "player.db")
    names = {
        row["name"]
        for row in conn.execute("select name from sqlite_master where type='table'")
    }
    assert {"mails", "checkins", "events", "stores"} <= names
    indexes = {
        row["name"]
        for row in conn.execute("select name from sqlite_master where type='index'")
    }
    assert "angels_player_entry" in indexes
    players = {r["name"] for r in conn.execute("PRAGMA table_info(players)")}
    assert {
        "login_award", "login_days", "last_login_day", "daily_day",
        "buy_energy_used", "buy_gold_used",
    } <= players


def test_hero_items_default_to_six_zeros(tmp_path) -> None:
    from server.db import grant_hero, heroes_of, set_hero_items

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    hid = grant_hero(conn, pid, 100000, quality=10)
    row = heroes_of(conn, pid)[0]
    assert [int(row[f"item{i}"]) for i in range(6)] == [0] * 6
    set_hero_items(conn, hid, [10000, 0, 0, 0, 0, 11170])
    row = heroes_of(conn, pid)[0]
    assert [int(row[f"item{i}"]) for i in range(6)] == [10000, 0, 0, 0, 0, 11170]


def test_b1_world_migrates_without_loss(tmp_path) -> None:
    """A B1 player.db (Plan A players + a heroes row with quality) opens, keeps
    its rows, and the Wave 1 columns read their defaults."""
    import sqlite3

    from server.db import PLAN_A_SCHEMA_PROBE, heroes_of

    path = tmp_path / "player.db"
    raw = sqlite3.connect(path)
    raw.executescript(PLAN_A_SCHEMA_PROBE)
    raw.executescript(
        "CREATE TABLE heroes (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " player_id INTEGER NOT NULL REFERENCES players(id), entry INTEGER NOT NULL,"
        " star INTEGER NOT NULL DEFAULT 1, level INTEGER NOT NULL DEFAULT 1,"
        " xp INTEGER NOT NULL DEFAULT 0, quality INTEGER NOT NULL DEFAULT 0);"
    )
    raw.execute(
        "INSERT INTO players (username, nickname, level, xp, gold, diamond, vip,"
        " energy, max_energy, avatar, guide_id, created_at)"
        " VALUES ('stefan', 'Stefan', 2, 15, 900, 30, 0, 50, 62, 1, 10180,"
        " '2026-11-24T08:00:00+00:00')"
    )
    raw.execute(
        "INSERT INTO heroes (player_id, entry, star, level, xp, quality)"
        " VALUES (1, 100000, 2, 3, 40, 10)"
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    row = find_player(conn, "stefan")
    assert (row["nickname"], row["level"], row["xp"], row["gold"]) == (
        "Stefan", 2, 15, 900
    )
    assert int(row["guide_id"]) == 10180
    for column in ("login_award", "login_days", "buy_energy_used", "buy_gold_used"):
        assert int(row[column]) == 0
    assert row["last_login_day"] == ""
    assert row["daily_day"] == ""
    hero = heroes_of(conn, int(row["id"]))[0]
    assert (hero["entry"], hero["star"], hero["level"], hero["xp"], hero["quality"]) == (
        100000, 2, 3, 40, 10
    )
    assert [int(hero[f"item{i}"]) for i in range(6)] == [0] * 6


def test_stage3_fresh_char_world_opens(tmp_path) -> None:
    """Every kept world must still load. A COPY is opened, never the original."""
    import shutil

    import pytest

    src = Path("data") / "player.db.stage3-fresh-char"
    if not src.exists():
        pytest.skip("data/player.db.stage3-fresh-char is not in this tree")
    copy = tmp_path / "player.db"
    shutil.copy2(src, copy)
    conn = connect(copy)
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] >= 1
    conn.close()


def test_take_item_refuses_more_than_owned_and_writes_nothing(tmp_path) -> None:
    import pytest

    from server.db import grant_item, items_of, take_item

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 500000, 10)
    with pytest.raises(ValueError):
        take_item(conn, pid, 500000, 11)
    with pytest.raises(ValueError):
        take_item(conn, pid, 10000, 1)          # never owned
    assert {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)} == {
        500000: 10
    }
    assert take_item(conn, pid, 500000, 4) == 6
    assert take_item(conn, pid, 500000, 6) == 0


def test_spend_refuses_and_writes_nothing(tmp_path) -> None:
    import pytest

    from server.db import spend

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=1000, diamond=20)
    with pytest.raises(ValueError):
        spend(conn, pid, gold=500, diamond=21)   # diamond short: gold not taken
    with pytest.raises(ValueError):
        spend(conn, pid, gold=1001)
    row = find_player(conn, "stefan")
    assert (int(row["gold"]), int(row["diamond"])) == (1000, 20)
    spend(conn, pid, gold=400, diamond=5)
    row = find_player(conn, "stefan")
    assert (int(row["gold"]), int(row["diamond"])) == (600, 15)


def test_ensure_today_resets_daily_counters_once(tmp_path) -> None:
    from server.db import ensure_today

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET buy_energy_used = 2, buy_gold_used = 3,"
        " daily_day = '2026-11-23' WHERE id = ?", (pid,)
    )
    conn.commit()
    ensure_today(conn, pid, "2026-11-24")
    row = find_player(conn, "stefan")
    assert (int(row["buy_energy_used"]), int(row["buy_gold_used"])) == (0, 0)
    assert row["daily_day"] == "2026-11-24"
    # A purchase later the same day is not wiped by a second call.
    conn.execute("UPDATE players SET buy_energy_used = 1 WHERE id = ?", (pid,))
    conn.commit()
    ensure_today(conn, pid, "2026-11-24")
    assert int(find_player(conn, "stefan")["buy_energy_used"]) == 1


def test_angels_unique_per_player_entry(tmp_path) -> None:
    import sqlite3

    import pytest

    from server.db import angels_of, grant_angel

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    aid = grant_angel(conn, pid, 500000, level=1, star=1)
    rows = angels_of(conn, pid)
    assert [(int(r["id"]), int(r["angel_entry"]), int(r["level"]), int(r["star"]))
            for r in rows] == [(aid, 500000, 1, 1)]
    with pytest.raises(sqlite3.IntegrityError):
        grant_angel(conn, pid, 500000, level=1, star=1)
    assert len(angels_of(conn, pid)) == 1
