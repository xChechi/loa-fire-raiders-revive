import json
from pathlib import Path

import pytest

from client.fetch_cocos_java import (
    FindClassError,
    PatchError,
    apply_patches,
    fetch,
    verify_natives,
)

# Origin 1: the cocos2d-x 2.2.2 directory listing.
FAKE_LISTING = [
    {"name": "Cocos2dxRenderer.java", "type": "file",
     "download_url": "https://example.invalid/Cocos2dxRenderer.java"},
    {"name": "README.md", "type": "file",
     "download_url": "https://example.invalid/README.md"},
]
# Origin 2: single files pinned by commit SHA, here quick-cocos2d-x.
FAKE_EXTRA = {
    "Cocos2dxLuaJavaBridge.java": "https://example.invalid/Cocos2dxLuaJavaBridge.java",
}

FLOATMATH_SOURCE = (
    "package org.cocos2dx.lib;\n"
    "import android.util.FloatMath;\n"
    "class Cocos2dxBitmap {\n"
    "  int a = (int) FloatMath.ceil(1.0f);\n"
    "  int b = (int) FloatMath.ceil(2.0f);\n"
    "  int c = (int) FloatMath.ceil(3.0f);\n"
    "  private static native void nativeInitBitmapDC(int w, int h, byte[] pixels);\n}\n"
)


def test_fetch_writes_only_java_files_from_both_origins(tmp_path: Path, monkeypatch) -> None:
    def fake_get(url: str) -> bytes:
        return b"package org.cocos2dx.lib;\nclass Cocos2dxRenderer {}\n"

    monkeypatch.setattr("client.fetch_cocos_java._get", fake_get)
    written = fetch(tmp_path, listing=FAKE_LISTING, extra=FAKE_EXTRA)

    assert written == ["Cocos2dxLuaJavaBridge.java", "Cocos2dxRenderer.java"]
    assert (tmp_path / "Cocos2dxRenderer.java").read_text().startswith(
        "package org.cocos2dx.lib;"
    )
    assert (tmp_path / "Cocos2dxLuaJavaBridge.java").exists()
    assert not (tmp_path / "README.md").exists()


def test_fetch_patches_floatmath_out_of_the_bitmap_source(tmp_path: Path, monkeypatch) -> None:
    listing = [{"name": "Cocos2dxBitmap.java", "type": "file",
                "download_url": "https://example.invalid/Cocos2dxBitmap.java"}]

    def fake_get(url: str) -> bytes:
        return FLOATMATH_SOURCE.encode("utf-8")

    monkeypatch.setattr("client.fetch_cocos_java._get", fake_get)
    fetch(tmp_path, listing=listing, extra={})

    patched = (tmp_path / "Cocos2dxBitmap.java").read_text(encoding="utf-8")
    assert "FloatMath" not in patched
    assert patched.count("(int) Math.ceil(") == 3


def test_apply_patches_raises_when_the_expected_text_is_gone(tmp_path: Path) -> None:
    (tmp_path / "Cocos2dxBitmap.java").write_text(
        "package org.cocos2dx.lib;\nclass Cocos2dxBitmap {}\n", encoding="utf-8"
    )
    with pytest.raises(PatchError):
        apply_patches(tmp_path, ["Cocos2dxBitmap.java"])


def test_verify_natives_flags_a_missing_declaration(tmp_path: Path) -> None:
    (tmp_path / "Cocos2dxRenderer.java").write_text(
        "package org.cocos2dx.lib;\nclass Cocos2dxRenderer {\n"
        "  private static native void nativeInit(int w, int h);\n}\n",
        encoding="utf-8",
    )
    missing = verify_natives(tmp_path, {"Cocos2dxRenderer": ["nativeInit", "nativeRender"]})
    assert missing == {"Cocos2dxRenderer": ["nativeRender"]}


def test_real_tree_declares_every_native_libgame_exports() -> None:
    root = Path("client/android/app/src/main/java/org/cocos2dx/lib")
    missing = verify_natives(root, json.loads(Path("client/cocos_natives.json").read_text()))
    assert missing == {}


def test_real_tree_is_the_patched_tree() -> None:
    """The committed sources must be what fetch() produces, not the raw download."""
    bitmap = Path(
        "client/android/app/src/main/java/org/cocos2dx/lib/Cocos2dxBitmap.java"
    ).read_text(encoding="utf-8")
    assert "FloatMath" not in bitmap
