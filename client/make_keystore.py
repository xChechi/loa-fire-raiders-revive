"""Create the release keystore once, outside the repository."""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

KEYSTORE_DIR = Path.home() / ".loa-keystore"
KEYTOOL = Path("C:/Program Files/Android/Android Studio/jbr/bin/keytool.exe")
ALIAS = "loa"
DNAME = "CN=LOA Private, OU=Home, O=Stefan, L=Sofia, C=BG"


def keytool_argv(keystore: Path, password: str, alias: str = ALIAS) -> list[str]:
    return [
        str(KEYTOOL),
        "-genkeypair",
        "-keystore", str(keystore),
        "-storetype", "PKCS12",
        "-storepass", password,
        "-keypass", password,
        "-alias", alias,
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-dname", DNAME,
    ]


def ensure(dir_: Path = KEYSTORE_DIR) -> tuple[Path, str]:
    dir_.mkdir(parents=True, exist_ok=True)
    keystore = dir_ / "loa.jks"
    pw_file = dir_ / "password.txt"
    if keystore.exists() and pw_file.exists():
        return keystore, pw_file.read_text(encoding="utf-8").strip()
    if keystore.exists():
        # Generating here would overwrite password.txt and lose the only copy of
        # the password that opens this keystore.
        raise RuntimeError(
            f"keystore present without its password file: {keystore} exists but "
            f"{pw_file} is missing; restore password.txt or move the keystore "
            "aside deliberately"
        )
    if pw_file.exists():
        print(f"{keystore} is missing: generating a new keystore and replacing {pw_file}")

    password = secrets.token_urlsafe(24)
    pw_file.write_text(password + "\n", encoding="utf-8")
    subprocess.run(keytool_argv(keystore, password), check=True)
    return keystore, password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=KEYSTORE_DIR)
    args = parser.parse_args(argv)
    keystore, _ = ensure(args.dir)
    print(f"keystore ready at {keystore}; password in {args.dir / 'password.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
