from pathlib import Path

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
