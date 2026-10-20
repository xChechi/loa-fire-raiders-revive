"""Extract the stock LOA APK into .stock/ with the standard library only."""

from __future__ import annotations

import argparse
import sys
import tomllib
import zipfile
from pathlib import Path


def extract(apk_path: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    written = 0
    with zipfile.ZipFile(apk_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"zip member escapes dest: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--apk", type=Path, default=None)
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = tomllib.loads(args.settings.read_text(encoding="utf-8"))
    apk = args.apk or Path(cfg["paths"]["apk"])
    dest = args.dest or Path(cfg["paths"]["stock_dir"])

    count = extract(apk, dest)
    print(f"extracted {count} members from {apk} into {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
