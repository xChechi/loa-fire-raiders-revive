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
