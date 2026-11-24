import subprocess
import sys
from pathlib import Path

import pytest

from client.build_assets import PATCHES, PatchNotFound, apply_patches, main

STOCK_SCRIPTS = Path(".stock/assets/scripts")
BATTLE_FACTORY = "scripts/app/game/view/scenes/battleScene/type/BattleFactoryBase.lua"
TOUCHED = (
    "scripts/main.lua",
    "scripts/app/MyApp.lua",
    "scripts/app/game/view/scenes/GameLoginScene.lua",
    "scripts/sdk/LuaSuperSDKManager.lua",
    "scripts/upgrade/upgrade.lua",
    BATTLE_FACTORY,
    "scripts/app/game/utils/MMGUICreator.lua",
    "scripts/app/game/view/ui/roleUI/RoleUIInfoPanel.lua",
    "scripts/app/game/view/ui/bag/BagLeftPanel.lua",
    "scripts/app/game/view/ui/LevelDes.lua",
    "scripts/app/game/framework/MMPlayerUpgradePanel.lua",
    "scripts/app/game/view/ui/RoleUI.lua",
)


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A fixture copy of only the Lua files the patches touch."""
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


def test_apply_patches_rewrites_every_touched_file(assets: Path) -> None:
    changed = apply_patches(assets, server_ip="192.168.1.50", username="stefan", port=8112)
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

    assert '        lfs.mkdir(wrireUrl .. "/upgrade");\n' in app

    upgrade = (assets / "scripts/upgrade/upgrade.lua").read_text(encoding="utf-8")
    assert "\tg_sdkManager:checkVersion();\n" in upgrade


def test_upgrade_calls_checkversion_after_the_listener_is_registered(
    assets: Path,
) -> None:
    """Nothing in the stock Lua ever calls checkVersion on Android.

    The channel SDK's Java side fires the init/version callbacks through the
    handler registered by lua_setCallBack; our stub never does. upgrade:init
    therefore has to kick checkVersion itself, and the kick has to come after
    its own comSdk_checkVersionCallback_event listener exists, or the event
    patch 7 dispatches has nobody to deliver to.
    """
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    upgrade = (assets / "scripts/upgrade/upgrade.lua").read_text(encoding="utf-8")

    listener = upgrade.index('addEventListener("comSdk_checkVersionCallback_event"')
    kick = upgrade.index("g_sdkManager:checkVersion();")
    assert listener < kick

    # And the event that kick produces is the local dispatch, not a Java call.
    sdk = (assets / "scripts/sdk/LuaSuperSDKManager.lua").read_text(encoding="utf-8")
    assert 'luaj.callStaticMethod(self.javaSDKClass, "checkVersion", {}, "()V");' not in sdk
    assert 'dispatchEvent("comSdk_checkVersionCallback_event"' in sdk


def test_the_db_copy_creates_its_target_directory(assets: Path) -> None:
    """files/upgrade/ is made by MMUpdater:setVersion, which patch 2 skips.

    MyApp:updateDB io.opens files/upgrade/<name>.db for writing and never
    checks the handle, so a missing directory is a nil-index Lua error that
    kills the boot one frame before the login scene. Make the directory.
    """
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    app = (assets / "scripts/app/MyApp.lua").read_text(encoding="utf-8")

    mkdir = app.index('lfs.mkdir(wrireUrl .. "/upgrade")')
    write = app.index('pfp = io.open(wrireUrl  .."/upgrade/" .. key ..".db", "wb")')
    assert mkdir < write


def test_no_placeholder_survives(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan", port=8112)
    for rel in TOUCHED:
        text = (assets / rel).read_text(encoding="utf-8")
        assert "__LOA_SERVER_IP__" not in text
        assert "__LOA_USERNAME__" not in text
        assert "__LOA_SERVER_PORT__" not in text


def test_applying_twice_raises_instead_of_double_patching(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan", port=8112)
    with pytest.raises(PatchNotFound):
        apply_patches(assets, server_ip="10.0.0.1", username="stefan", port=8112)


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_apply_patches_keeps_each_file_line_ending(tmp_path: Path, eol: str) -> None:
    """A CRLF file stays CRLF, an LF file stays LF: only the patched lines differ."""
    root = tmp_path / "assets"
    for rel in TOUCHED:
        src = STOCK_SCRIPTS / rel[len("scripts/") :]
        text = src.read_text(encoding="utf-8")  # universal newlines -> "\n"
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(text.replace("\n", eol).encode("utf-8"))

    apply_patches(root, server_ip="10.0.0.1", username="stefan", port=8112)

    for rel in TOUCHED:
        raw = (root / rel).read_bytes()
        assert raw.count(b"\n") > 0, rel
        if eol == "\r\n":
            assert raw.count(b"\r\n") == raw.count(b"\n"), rel + " lost CRLF"
        else:
            assert b"\r" not in raw, rel + " gained CR"

    scene = (root / "scripts/app/game/view/scenes/GameLoginScene.lua").read_bytes()
    assert b'socket_domain = "10.0.0.1"' in scene
    main_lua = (root / "scripts/main.lua").read_bytes()
    assert b"CONFIG_DEVELOP = 1;" in main_lua


def test_the_settings_port_lands_in_the_generated_lua(tmp_path: Path) -> None:
    """The server list's socket_port comes from settings.toml, not from a literal.

    main() prints `{s.host}:{s.port}`, so a port that is only true in the banner
    and not in the Lua would send the client to the wrong socket.
    """
    stock = tmp_path / "stock"
    for rel in TOUCHED:
        src = STOCK_SCRIPTS / rel[len("scripts/") :]
        dst = stock / "assets" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    (stock / "assets/res").mkdir(parents=True)
    (stock / "assets/fonts").mkdir(parents=True)
    (stock / "lib/armeabi").mkdir(parents=True)
    (stock / "lib/armeabi/libgame.so").write_bytes(b"\x7fELF fake")

    settings = tmp_path / "settings.toml"
    settings.write_text(
        "[paths]\n"
        f'stock_dir = "{stock.as_posix()}"\n'
        'db_path = "data/player.db"\n'
        "[net]\n"
        'host = "10.0.0.7"\n'
        "port = 8113\n"
        "[account]\n"
        'username = "stefan"\n'
        "[player]\n"
        "guide_id = 0\n",
        encoding="utf-8",
    )
    dest_assets = tmp_path / "out/assets"

    assert main([
        "--settings", str(settings),
        "--assets", str(dest_assets),
        "--jnilibs", str(tmp_path / "out/jniLibs"),
    ]) == 0

    scene = (dest_assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(
        encoding="utf-8"
    )
    assert "socket_port   = 8113," in scene
    # the patched block's own spacing; the stock sample list writes
    # "socket_port =   8112," and those four entries are untouched
    assert "socket_port   = 8112," not in scene
    assert 'socket_domain = "10.0.0.7"' in scene


def test_documented_entry_point_builds_a_miniature_tree(tmp_path: Path) -> None:
    """`py -3.14 -m client.build_assets` is the documented invocation; drive it."""
    stock = tmp_path / "stock"
    (stock / "assets/res").mkdir(parents=True)
    (stock / "assets/fonts").mkdir(parents=True)
    (stock / "assets/res/marker.txt").write_text("res", encoding="utf-8")
    (stock / "assets/fonts/marker.txt").write_text("font", encoding="utf-8")
    (stock / "assets/debug.txt").write_text("debug", encoding="utf-8")
    for rel in TOUCHED:
        src = STOCK_SCRIPTS / rel[len("scripts/") :]
        dst = stock / "assets" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    (stock / "lib/armeabi").mkdir(parents=True)
    (stock / "lib/armeabi/libgame.so").write_bytes(b"\x7fELF fake")

    settings = tmp_path / "settings.toml"
    settings.write_text(
        "[paths]\n"
        f'stock_dir = "{stock.as_posix()}"\n'
        'db_path = "data/player.db"\n'
        "[net]\n"
        'host = "10.0.0.7"\n'
        "port = 8112\n"
        "[account]\n"
        'username = "stefan"\n'
        "[player]\n"
        "guide_id = 0\n",
        encoding="utf-8",
    )
    dest_assets = tmp_path / "out/assets"
    dest_jnilibs = tmp_path / "out/jniLibs"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "client.build_assets",
            "--settings", str(settings),
            "--assets", str(dest_assets),
            "--jnilibs", str(dest_jnilibs),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("patched ") == len(PATCHES)
    assert "copied libgame.so" in proc.stdout

    scene = (dest_assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(
        encoding="utf-8"
    )
    assert 'socket_domain = "10.0.0.7"' in scene
    assert (dest_assets / "res/marker.txt").exists()
    assert (dest_assets / "fonts/marker.txt").exists()
    assert (dest_assets / "debug.txt").exists()
    assert (dest_jnilibs / "armeabi-v7a/libgame.so").read_bytes() == b"\x7fELF fake"


def test_patch_11_builds_the_servers_support_unit_in_the_attacker_team(
    assets: Path,
) -> None:
    """getAttackers creates a unit per entry of the local line-up only.

    The support hero of the newbie fights (variables.NEW_FIGHT_HELP_HERO, Task
    19) exists in team_base.units and nowhere on the client, so without this
    patch it is never built and never fights. The inserted block mirrors the
    UNIT_SERVER_FIGHT branch of initUnitData for info.type 3 and has to run
    before the stock line that freezes the team into self.attackers.
    """
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    lua = (assets / BATTLE_FACTORY).read_text(encoding="utf-8")

    assert lua.count("roleData:initByServerFightHero(serverInfo,false)") == 1
    built = lua.index("roleData:initByServerFightHero(serverInfo,false)")
    # The stock loop over self.data.attacker still runs first, and the stock
    # line that publishes the team still runs last.
    assert lua.index("for k,v in pairs(self.data.attacker) do") < built
    assert built < lua.index("        self.attackers=attackers;")
    # Only a server unit with no local counterpart is added.
    assert "attackers.units[place]==nil" in lua


def test_english_overlay_replaces_the_chinese_language_files_and_dbs(tmp_path: Path) -> None:
    from client.build_assets import overlay_english

    assets = tmp_path / "assets"
    (assets / "res/language").mkdir(parents=True)
    (assets / "res/data/split").mkdir(parents=True)
    (assets / "res/language/Language_cn.lua").write_text("cn", encoding="utf-8")
    (assets / "res/language/Language_start_cn.lua").write_text("cn start", encoding="utf-8")
    (assets / "res/data/split/item_info.db").write_bytes(b"cn db")
    (assets / "res/data/split/only_stock.db").write_bytes(b"stock")
    en = tmp_path / "en"
    (en / "assets/res/language").mkdir(parents=True)
    (en / "assets/res/data/split").mkdir(parents=True)
    (en / "assets/res/language/Language_en.lua").write_text("en", encoding="utf-8")
    (en / "assets/res/language/Language_start_en.lua").write_text("en start", encoding="utf-8")
    (en / "assets/res/data/split/item_info.db").write_bytes(b"en db")
    (assets / "scripts/app").mkdir(parents=True)
    (assets / "scripts/app/Scene.lua").write_text("cn lua", encoding="utf-8")
    (assets / "scripts/app/Other.lua").write_text("untouched", encoding="utf-8")
    (en / "assets/scripts/app").mkdir(parents=True)
    (en / "assets/scripts/app/Scene.lua").write_text("en lua", encoding="utf-8")

    assert overlay_english(en, assets) == 4
    assert (assets / "scripts/app/Scene.lua").read_text(encoding="utf-8") == "en lua"
    assert (assets / "scripts/app/Other.lua").read_text(encoding="utf-8") == "untouched"

    assert (assets / "res/language/Language_cn.lua").read_text(encoding="utf-8") == "en"
    assert (assets / "res/language/Language_start_cn.lua").read_text(encoding="utf-8") == "en start"
    assert (assets / "res/data/split/item_info.db").read_bytes() == b"en db"
    assert (assets / "res/data/split/only_stock.db").read_bytes() == b"stock"
    assert not (assets / "res/language/Language_en.lua").exists()


def test_english_overlay_ships_the_redrawn_images_over_the_stock_ones(tmp_path: Path) -> None:
    from client.build_assets import overlay_english

    assets = tmp_path / "assets"
    (assets / "res/language").mkdir(parents=True)
    (assets / "res/data/split").mkdir(parents=True)
    (assets / "res/assets/ui/mainSceneImg").mkdir(parents=True)
    (assets / "res/assets/ui/mainSceneImg/mainBtnRank.png").write_bytes(b"cn png")
    (assets / "res/assets/ui/other.png").write_bytes(b"stock png")
    en = tmp_path / "en"
    (en / "assets/res/language").mkdir(parents=True)
    (en / "assets/res/data/split").mkdir(parents=True)
    (en / "assets/res/language/Language_en.lua").write_text("en", encoding="utf-8")
    (en / "assets/res/language/Language_start_en.lua").write_text("en", encoding="utf-8")
    (en / "assets/res/assets/ui/mainSceneImg").mkdir(parents=True)
    (en / "assets/res/assets/ui/mainSceneImg/mainBtnRank.png").write_bytes(b"en png")

    assert overlay_english(en, assets) == 3
    assert (assets / "res/assets/ui/mainSceneImg/mainBtnRank.png").read_bytes() == b"en png"
    assert (assets / "res/assets/ui/other.png").read_bytes() == b"stock png"


def test_english_overlay_without_writer_output_fails_loudly(tmp_path: Path) -> None:
    from client.build_assets import overlay_english

    with pytest.raises(FileNotFoundError, match="localise.write"):
        overlay_english(tmp_path / "missing", tmp_path / "assets")


def test_patch_13_places_hero_values_after_their_labels(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    panel = (assets / "scripts/app/game/view/ui/roleUI/RoleUIInfoPanel.lua").read_text(
        encoding="utf-8"
    )
    for x, y, i in ((420, 480, 4), (420, 440, 3), (475, 400, 2), (475, 360, 1)):
        assert f"math.max({x}, 364 + self.descLabel[{i}]:getContentSize().width)" in panel
    # the labels exist before the values that measure them
    assert panel.index("self.descLabel[i] = stcTfd") < panel.index("math.max(420")


def test_patch_14_right_anchors_the_bag_owned_label(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    bag = (assets / "scripts/app/game/view/ui/bag/BagLeftPanel.lua").read_text(encoding="utf-8")
    assert "self.stc1:setAnchorPoint(ccp(1, 0.5)); self.stc1:setPositionX(206);" in bag


def test_patch_15_keeps_the_stage_story_above_the_drops_panel(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    des = (assets / "scripts/app/game/view/ui/LevelDes.lua").read_text(encoding="utf-8")
    assert "self.levelInfo.description, 163 - 15, 265, self.widgetBg, cc.size(500, 170)," in des


def test_patch_16_right_aligns_the_consent_line(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    scene = (assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(encoding="utf-8")
    assert "txt1:setAnchorPoint(ccp(1, 0.5)); txt1:setPositionX(50);" in scene


def test_patch_17_keeps_the_rebirth_requirement_after_its_label(assets: Path) -> None:
    # updateReBirthInfo moves the "Lv.55" value back to x 475 on every
    # refresh, over the wider English label; patch 13 alone is undone there.
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    panel = (assets / "scripts/app/game/view/ui/roleUI/RoleUIInfoPanel.lua").read_text(
        encoding="utf-8"
    )
    assert "self.nextReBirthLvTfd:setPosition(ccp(475,360))" not in panel
    assert ("self.nextReBirthLvTfd:setPosition(ccp(math.max(475, 364 + "
            "self.descLabel[1]:getContentSize().width),360))") in panel


def test_patch_16_moves_the_consent_checkbox_left_of_the_longer_line(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    scene = (assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(encoding="utf-8")
    moved = "self.privacyCheckBtn:setPositionX(50 - txt1:getContentSize().width - 22);"
    assert moved in scene
    # after both the checkbox and the consent line exist
    assert scene.index("self.privacyCheckBtn:setPosition(ccp(-200,110))") < scene.index(moved)
    assert scene.index('createLabel("我已详细阅读并同意"') < scene.index(moved)


def test_patch_18_shrinks_long_level_up_labels_to_end_before_the_value(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    panel = (assets / "scripts/app/game/framework/MMPlayerUpgradePanel.lua").read_text(
        encoding="utf-8"
    )
    fit = ("local w = txt1:getContentSize().width; "
           "if w > 170 then txt1:setScale(170 / w) end")
    assert fit in panel
    assert panel.index("box:addNode(txt1);") < panel.index(fit) < panel.index("local txt2")


def test_patch_19_gives_the_hero_side_tabs_a_longer_trimmed_label(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.2.2", username="stefan", port=8112)
    ui = (assets / "scripts/app/game/view/ui/RoleUI.lua").read_text(encoding="utf-8")
    assert "CCSize(33, 80)" not in ui
    assert ('createMMLabel((tempTabTxtAry[k]:gsub("%s+$", "")), 24, ccp(-19, -3), '
            "CCSize(33, 96), ui.TEXT_ALIGN_LEFT, true);") in ui
