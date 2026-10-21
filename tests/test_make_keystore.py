from pathlib import Path

import pytest

from client import make_keystore
from client.make_keystore import ensure, keytool_argv


def test_keytool_argv_has_the_required_switches(tmp_path: Path) -> None:
    argv = keytool_argv(tmp_path / "loa.jks", "s3cret")
    assert argv[0].endswith("keytool.exe")
    joined = " ".join(argv)
    assert "-genkeypair" in joined
    assert "-keyalg RSA" in joined
    assert "-keysize 2048" in joined
    assert "-validity 10000" in joined
    assert "-alias loa" in joined
    assert "-storetype PKCS12" in joined
    assert "CN=LOA Private" in joined
    assert "s3cret" in joined


def test_ensure_is_a_noop_when_both_files_exist(tmp_path: Path) -> None:
    (tmp_path / "loa.jks").write_bytes(b"not-a-real-keystore")
    (tmp_path / "password.txt").write_text("already", encoding="utf-8")

    keystore, password = ensure(tmp_path)

    assert keystore == tmp_path / "loa.jks"
    assert password == "already"
    assert (tmp_path / "loa.jks").read_bytes() == b"not-a-real-keystore"


def test_ensure_refuses_a_keystore_without_its_password_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "loa.jks").write_bytes(b"the-only-copy")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        make_keystore.subprocess, "run", lambda argv, **kw: calls.append(argv)
    )

    with pytest.raises(RuntimeError, match="keystore present without its password file"):
        ensure(tmp_path)

    assert calls == []
    assert not (tmp_path / "password.txt").exists()
    assert (tmp_path / "loa.jks").read_bytes() == b"the-only-copy"


def test_ensure_regenerates_and_says_so_when_only_the_password_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "password.txt").write_text("stale\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kw: object) -> None:
        calls.append(argv)
        Path(argv[argv.index("-keystore") + 1]).write_bytes(b"freshly-generated")

    monkeypatch.setattr(make_keystore.subprocess, "run", fake_run)

    keystore, password = ensure(tmp_path)

    assert len(calls) == 1
    assert keystore.read_bytes() == b"freshly-generated"
    assert password != "stale"
    assert (tmp_path / "password.txt").read_text(encoding="utf-8").strip() == password
    assert "replacing" in capsys.readouterr().out
