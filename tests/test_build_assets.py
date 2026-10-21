from pathlib import Path

import pytest

from client.build_assets import PATCHES, PatchNotFound, apply_patches

STOCK_SCRIPTS = Path(".stock/assets/scripts")
TOUCHED = (
    "scripts/main.lua",
    "scripts/app/MyApp.lua",
    "scripts/app/game/view/scenes/GameLoginScene.lua",
    "scripts/sdk/LuaSuperSDKManager.lua",
)


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A fixture copy of only the four Lua files the patches touch."""
    root = tmp_path / "assets"
    for rel in TOUCHED:
        src = STOCK_SCRIPTS / rel[len("scripts/") :]
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    return root


def test_every_old_string_occurs_exactly_once_in_the_stock_file(assets: Path) -> None:
    for patch in PATCHES:
        text = (assets / patch.relpath).read_text(encoding="utf-8")
        assert text.count(patch.old) == 1, patch.relpath + " :: " + patch.old[:60]


def test_apply_patches_rewrites_all_four_files(assets: Path) -> None:
    changed = apply_patches(assets, server_ip="192.168.1.50", username="stefan")
    assert sorted(set(changed)) == sorted(TOUCHED)

    main_lua = (assets / "scripts/main.lua").read_text(encoding="utf-8")
    assert "        CONFIG_DEVELOP = 1;\n" in main_lua
    assert "        CONFIG_UPGRADE_PROCESS = 0;\n" in main_lua

    scene = (assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(
        encoding="utf-8"
    )
    assert 'socket_domain = "192.168.1.50"' in scene
    assert "self:getRecommendServerIds();" not in scene
    assert "self:checkNotice();" not in scene
    assert "    self.privacyCheckBtnSelected = true\n" in scene

    sdk = (assets / "scripts/sdk/LuaSuperSDKManager.lua").read_text(encoding="utf-8")
    assert "comSdk_checkVersionCallback_event" in sdk
    assert 'uid = "stefan"' in sdk
    assert 'luaj.callStaticMethod(self.javaSDKClass, "login", {}, "()V");' not in sdk

    app = (assets / "scripts/app/MyApp.lua").read_text(encoding="utf-8")
    assert "scheduler.performWithDelayGlobal(function() self:initLogin(); end, 0.1);" in app


def test_no_placeholder_survives(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan")
    for rel in TOUCHED:
        text = (assets / rel).read_text(encoding="utf-8")
        assert "__LOA_SERVER_IP__" not in text
        assert "__LOA_USERNAME__" not in text


def test_applying_twice_raises_instead_of_double_patching(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan")
    with pytest.raises(PatchNotFound):
        apply_patches(assets, server_ip="10.0.0.1", username="stefan")
