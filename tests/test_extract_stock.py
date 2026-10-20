import zipfile
from pathlib import Path

import pytest

from tools.extract_stock import extract


def test_extract_writes_every_member(tmp_path: Path) -> None:
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/scripts/main.lua", "GAME_VERSION\n")
        z.writestr("lib/armeabi/libgame.so", b"\x7fELF-not-really")
    dest = tmp_path / ".stock"

    count = extract(apk, dest)

    assert count == 2
    assert (dest / "assets/scripts/main.lua").read_text() == "GAME_VERSION\n"
    assert (dest / "lib/armeabi/libgame.so").read_bytes() == b"\x7fELF-not-really"


def test_extract_refuses_path_traversal(tmp_path: Path) -> None:
    apk = tmp_path / "evil.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("../escaped.txt", "nope")
    dest = tmp_path / ".stock"

    with pytest.raises(ValueError, match="escapes dest"):
        extract(apk, dest)
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_is_idempotent(tmp_path: Path) -> None:
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/a.txt", "one")
    dest = tmp_path / ".stock"

    assert extract(apk, dest) == 1
    assert extract(apk, dest) == 1
    assert (dest / "assets/a.txt").read_text() == "one"
