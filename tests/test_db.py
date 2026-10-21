from pathlib import Path

from server.db import connect, create_player, find_player


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
