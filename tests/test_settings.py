from pathlib import Path

from server.settings import load

SAMPLE = """
[paths]
stock_dir = ".stock"
db_path = "data/player.db"
apk = "C:/x.apk"

[net]
host = "192.168.1.50"
port = 8112

[account]
username = "stefan"

[player]
guide_id = 0
"""


def test_load_reads_every_field(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE, encoding="utf-8")

    s = load(cfg)

    assert s.stock_dir == Path(".stock")
    assert s.db_path == Path("data/player.db")
    assert s.host == "192.168.1.50"
    assert s.port == 8112
    assert s.username == "stefan"
    assert s.guide_id == 0


def test_load_reads_the_bind_address(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE.replace("port = 8112", "bind = \"0.0.0.0\"\nport = 8112"),
                   encoding="utf-8")
    assert load(cfg).bind == "0.0.0.0"


def test_bind_defaults_to_all_interfaces_when_absent(tmp_path: Path) -> None:
    """An older settings.toml must keep working: Plan A had no [net] bind key."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    assert load(cfg).bind == "0.0.0.0"
