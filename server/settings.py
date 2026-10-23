"""settings.toml loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    stock_dir: Path
    db_path: Path
    host: str
    bind: str
    port: int
    username: str
    guide_id: int


def load(path: Path = Path("settings.toml")) -> Settings:
    cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return Settings(
        stock_dir=Path(cfg["paths"]["stock_dir"]),
        db_path=Path(cfg["paths"]["db_path"]),
        host=cfg["net"]["host"],
        # The listening address. settings.host is the client-side address baked
        # into the APK (10.0.2.2 for the emulator) and cannot be bound here.
        bind=cfg["net"].get("bind", "0.0.0.0"),
        port=int(cfg["net"]["port"]),
        username=cfg["account"]["username"],
        guide_id=int(cfg["player"]["guide_id"]),
    )
