"""Assemble client/android/app/src/main/assets from .stock, patching the Lua.

Run from the repo root:  py -3.14 -m client.build_assets
(the -m form is required: it puts the repo root on sys.path so
`from server.settings import load` resolves.)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from server.settings import load as load_settings

SCENE = "scripts/app/game/view/scenes/GameLoginScene.lua"
SDK = "scripts/sdk/LuaSuperSDKManager.lua"
BATTLE_FACTORY = "scripts/app/game/view/scenes/battleScene/type/BattleFactoryBase.lua"


class PatchNotFound(RuntimeError):
    def __init__(self, relpath: str, old: str, count: int) -> None:
        super().__init__(
            f"{relpath}: expected exactly one occurrence of {old[:70]!r}, found {count}"
        )
        self.relpath = relpath
        self.old = old
        self.count = count


@dataclass(frozen=True)
class Patch:
    relpath: str
    old: str
    new: str


_HOME_SERVER_LIST = (
    "    self:showServerList({\n"
    "        {\n"
    '            server        = "s1",\n'
    '            name          = "Home",\n'
    "            status        = 1,\n"
    '            server_id     = "1",\n'
    "            socket_port   = __LOA_SERVER_PORT__,\n"
    '            socket_domain = "__LOA_SERVER_IP__"\n'
    "        }\n"
    "    });\n"
)

# The two halves of the stock tail of BattleFactoryBase:getAttackers: the end
# of the loop that builds one unit per entry of the local line-up, and the
# line that publishes the finished team.
_ATTACKER_LOOP_END = (
    '            attackers.units[roleData:getIntValue(BattleDefine.place)]=roleData;\n'
    '            self.fullAttackers.units[roleData:getIntValue(BattleDefine.place)]=roleData;\n'
    '        end\n'
)

_ATTACKER_TEAM_PUBLISH = (
    '        -- end\n'
    '        self.attackers=attackers;\n'
)

_SUPPORT_UNIT_BLOCK = (
    '        -- LOA private server (patch 11): a team_base unit of type 3 (npc) with\n'
    "        -- no local counterpart is the server's support hero for the newbie\n"
    '        -- fights (variables.NEW_FIGHT_HELP_HERO). Stock creates units only for\n'
    '        -- the local lineup, so it is built here, mirroring the\n'
    '        -- UNIT_SERVER_FIGHT branch of initUnitData. initUnitData itself is not\n'
    '        -- used: it would call info:refreshFightData on the raw server table.\n'
    '        if self.attackerTeamInfo and self.attackerTeamInfo.units then\n'
    '            for _,serverInfo in pairs(self.attackerTeamInfo.units) do\n'
    '                local place=toint(serverInfo.position);\n'
    '                if toint(serverInfo.type)==3 and attackers.units[place]==nil then\n'
    '                    local roleData=BattleUnit.new(self.scene.battleEngine,nil)\n'
    '                    roleData:lock();\n'
    '                    roleData:setValue(BattleDefine.serverType,3)\n'
    '                    roleData:initByServerFightHero(serverInfo,false)\n'
    '                    roleData:setValue(BattleDefine.Type,BattleDefine.FIGHT_UNIT_TYPE_HERO)\n'
    '                    roleData:setValue(BattleDefine.place,place)\n'
    '                    self:setInitialEnergy(roleData,nil)\n'
    '                    roleData:setValue(BattleDefine.side,BattleDefine.SideAttacker);\n'
    '                    roleData:unlock();\n'
    '                    attackers.units[place]=roleData;\n'
    '                    self.fullAttackers.units[place]=roleData;\n'
    '                    trace("support unit from server at place",place,serverInfo.refer)\n'
    '                end\n'
    '            end\n'
    '        end\n'
)

PATCHES: tuple[Patch, ...] = (
    # 1. main.lua: development mode, so the client skips the version string
    #    match and the DB MD5 check in LoginSocketData:checkServerVersion.
    Patch("scripts/main.lua",
          "        CONFIG_DEVELOP = 0;\n",
          "        CONFIG_DEVELOP = 1;\n"),
    # 2. main.lua: UpgradeScene:onEnterScene returns straight to the game.
    Patch("scripts/main.lua",
          "        CONFIG_UPGRADE_PROCESS = 1;\n",
          "        CONFIG_UPGRADE_PROCESS = 0;\n"),
    # 3. MyApp:getGmActivity: do not wait on the dead patch CDN for the
    #    festival id; open the login scene on the next scheduler tick so the
    #    rest of initGame (initSocket) still runs first.
    Patch("scripts/app/MyApp.lua",
          "    callHttpRequestGet(url,function(event)\n",
          "    g_roleData.festivalId = 0;\n"
          "    scheduler.performWithDelayGlobal(function() self:initLogin(); end, 0.1);\n"
          "    do return end\n"
          "    callHttpRequestGet(url,function(event)\n"),
    # 4. GameLoginScene:showLogin: one static server, no recommend/serverList HTTP.
    Patch(SCENE,
          "    self:getRecommendServerIds();\n",
          _HOME_SERVER_LIST),
    # 5. GameLoginScene:showServerList: skip the login-notice HTTP.
    Patch(SCENE,
          "            self:checkNotice();\n",
          "            self:startLogin();\n"),
    # 6. GameLoginScene: privacy checkbox starts ticked. The two-line anchor is
    #    needed because the one-line form also appears in the toggle handler.
    Patch(SCENE,
          "    self.privacyCheckBtnSelected = false\n"
          '    self.privacyCheckBtn = g_cocoGUI_creator:createButton(g_load_ui.."btn/ui_checkBox_bg.png")\n',
          "    self.privacyCheckBtnSelected = true\n"
          '    self.privacyCheckBtn = g_cocoGUI_creator:createButton(g_load_ui.."btn/ui_checkBox_bg1.png")\n'),
    # 7. LuaSuperSDKManager:checkVersion: fire the event upgrade.lua waits for.
    Patch(SDK,
          '\t\tluaj.callStaticMethod(self.javaSDKClass, "checkVersion", {}, "()V");\n',
          '\t\tuf_eventManager:dispatchEvent("comSdk_checkVersionCallback_event",nil,true,self, {""} )\n'),
    # 8. LuaSuperSDKManager:showLogin: local account instead of the channel SDK.
    Patch(SDK,
          '\t\tluaj.callStaticMethod(self.javaSDKClass, "login", {}, "()V");\n',
          '\t\tuf_eventManager:dispatchEvent("comSdk_loginCallback_event",nil,false,self,'
          ' {{userinfo = {uid = "__LOA_USERNAME__"}, accessToken = "local"}} )\n'),
    # 9. upgrade:init: on Android nothing in the stock Lua ever calls
    #    checkVersion. The channel SDK's Java side fires the init / version
    #    callbacks through the handler lua_setCallBack registers, and our stub
    #    never calls back, so the boot stops right after lua_setCallBack. Kick
    #    checkVersion here, i.e. after the comSdk_checkVersionCallback_event
    #    listener three lines above exists, and patch 7 turns it into that
    #    event, which replaces the scene with UpgradeScene.
    Patch("scripts/upgrade/upgrade.lua",
          "\tg_sdkManager:onInitLogin();\n",
          "\tg_sdkManager:onInitLogin();\n"
          "\tg_sdkManager:checkVersion();\n"),
    # 10. MyApp:updateDB copies the split .db files into files/upgrade/ and
    #     never checks the io.open handle. That directory is created by
    #     MMUpdater:setVersion inside the hot-update path, which patch 2 skips,
    #     so the copy died with "attempt to index local 'pfp' (a nil value)".
    #     SqlManager:openDB reads the same directory, so make it, don't move
    #     the files elsewhere.
    Patch("scripts/app/MyApp.lua",
          "        local dbList = g_SqlManager.dbList;\n",
          "        local dbList = g_SqlManager.dbList;\n"
          '        lfs.mkdir(wrireUrl .. "/upgrade");\n'),
    # 11. BattleFactoryBase:getAttackers creates a unit for each entry of the
    #     local line-up (self.data.attacker) and nothing else, and initUnitData
    #     only refreshes such a unit from the matching team_base entry. The
    #     support hero of the newbie fights (variables.NEW_FIGHT_HELP_HERO) is a
    #     server-side unit with no local counterpart, so without this block it
    #     never reaches the field. BattleUnit and BattleDefine are already
    #     required at the top of the file (lines 14 and 20) and getAttackers
    #     itself uses both.
    Patch(BATTLE_FACTORY,
          _ATTACKER_LOOP_END + _ATTACKER_TEAM_PUBLISH,
          _ATTACKER_LOOP_END + _SUPPORT_UNIT_BLOCK + _ATTACKER_TEAM_PUBLISH),
)

COPY_DIRS = ("res", "scripts", "fonts")
COPY_FILES = ("debug.txt",)


def apply_patches(
    assets_root: Path, server_ip: str, username: str, port: int
) -> list[str]:
    changed: list[str] = []
    for patch in PATCHES:
        path = assets_root / patch.relpath
        raw = path.read_bytes()
        # The anchors are written with "\n", so match against normalised text;
        # three of the four stock files are CRLF, so write back with the
        # convention the file arrived with. Only the patched lines then differ
        # from .stock, and the diff stays readable.
        newline = "\r\n" if b"\r\n" in raw else ""
        text = raw.decode("utf-8").replace("\r\n", "\n")
        count = text.count(patch.old)
        if count != 1:
            raise PatchNotFound(patch.relpath, patch.old, count)
        new = patch.new.replace("__LOA_SERVER_IP__", server_ip)
        new = new.replace("__LOA_USERNAME__", username)
        new = new.replace("__LOA_SERVER_PORT__", str(port))
        path.write_text(text.replace(patch.old, new, 1), encoding="utf-8", newline=newline)
        changed.append(patch.relpath)
    return changed


def build(
    stock: Path,
    dest_assets: Path,
    dest_jnilibs: Path,
    server_ip: str,
    username: str,
    port: int,
) -> None:
    src_assets = stock / "assets"
    if dest_assets.exists():
        shutil.rmtree(dest_assets)
    dest_assets.mkdir(parents=True)
    for name in COPY_DIRS:
        print(f"copying {name} ...", flush=True)
        shutil.copytree(src_assets / name, dest_assets / name)
    for name in COPY_FILES:
        src = src_assets / name
        if src.exists():
            shutil.copy2(src, dest_assets / name)

    changed = apply_patches(dest_assets, server_ip, username, port)
    for rel in changed:
        print(f"patched {rel}")

    (dest_jnilibs / "armeabi-v7a").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        stock / "lib/armeabi/libgame.so",
        dest_jnilibs / "armeabi-v7a/libgame.so",
    )
    print("copied libgame.so")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path("client/android/app/src/main/assets"),
    )
    parser.add_argument(
        "--jnilibs",
        type=Path,
        default=Path("client/android/app/src/main/jniLibs"),
    )
    args = parser.parse_args(argv)

    s = load_settings(args.settings)
    build(s.stock_dir, args.assets, args.jnilibs, s.host, s.username, s.port)
    print(f"assets ready, server list points at {s.host}:{s.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
