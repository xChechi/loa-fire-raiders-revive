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

GUI_CREATOR = "scripts/app/game/utils/MMGUICreator.lua"
ROLE_INFO = "scripts/app/game/view/ui/roleUI/RoleUIInfoPanel.lua"
BAG_LEFT = "scripts/app/game/view/ui/bag/BagLeftPanel.lua"
LEVEL_DES = "scripts/app/game/view/ui/LevelDes.lua"

# Patch 12, English text layout. The engine draws every label with its own
# FreeType code (FTLabelManager in libgame.so), which may break a line after
# any character: right for Chinese, wrong for English ("summ|on"). For text
# without CJK this breaks lines on spaces before the text reaches the engine,
# and shrinks the font when the longest word or the lines do not fit the
# label's area (the narrow side tabs, "Angel Obtained"). Text with CJK goes
# through untouched. MMGUICreator is required by GameGlobal before any UI is
# built, so the overrides are in place for every label.
ENGLISH_TEXT_HOOK = r'''-- LOA private server (patch 12): English text layout, see client/build_assets.py.
do
    local CJK = "[\227-\233]"
    local MIN_SIZE = 12
    -- enableStrokeEx draws a 2 px outline round every glyph, which a bare
    -- measuring label does not have.
    local STROKE_PAD = LOA_TEXT_STROKE_PAD or 2
    local rawCreate = CCLabelTTF.create
    local widthCache, heightCache = {}, {}

    local function probe(s, font, size)
        return rawCreate(CCLabelTTF, s, font, size):getContentSize()
    end
    local function width(s, font, size)
        if s == "" then return 0 end
        local key = font .. "\1" .. size .. "\1" .. s
        local w = widthCache[key]
        if w == nil then w = probe(s, font, size).width + STROKE_PAD * #s; widthCache[key] = w end
        return w
    end
    local function lineHeight(font, size)
        local key = font .. "\1" .. size
        local h = heightCache[key]
        if h == nil then h = probe("Ag", font, size).height; heightCache[key] = h end
        return h
    end

    local function wrap(text, font, size, maxw)
        local out, n = {}, 0
        local space = width("a a", font, size) - width("aa", font, size)
        for line in (text .. "\n"):gmatch("(.-)\n") do
            local indent = line:match("^ *")
            local cur, curw = nil, 0
            for word in line:gmatch("%S+") do
                local ww = width(word, font, size)
                if cur == nil then
                    cur, curw = indent .. word, width(indent, font, size) + ww
                elseif curw + space + ww <= maxw then
                    cur, curw = cur .. " " .. word, curw + space + ww
                else
                    n = n + 1; out[n] = cur
                    cur, curw = word, ww
                end
            end
            n = n + 1; out[n] = cur or indent
        end
        return table.concat(out, "\n"), n
    end

    -- (text, size) that fit maxw x maxh, or nil to leave the text alone.
    local function fit(text, font, size, maxw, maxh)
        if type(text) ~= "string" or text == "" or text:find(CJK) or not maxw or maxw <= 0 then
            return nil
        end
        text = text:gsub("\\n", "\n")
        font = (font and font ~= "") and font or DEFAULT_TEXT_FONT
        size = math.floor(tonumber(size) or DEFAULT_TEXT_SIZE or 20)
        -- The engine's own line breaking kicks in a little before our
        -- measurement says the line is full (stroke, kerning): on the AVD a
        -- line measured at 95% was broken again inside "her|oes".
        local limit = maxw * 0.86
        local s = size
        -- A box only one line tall: shrink the whole text onto one line.
        if maxh and maxh > 0 and maxh < 1.8 * lineHeight(font, s) and not text:find("\n") then
            local w = width(text, font, s)
            if w > limit then s = math.max(MIN_SIZE, math.floor(s * limit / w)) end
            return text, s
        end
        local longest = 0
        for word in text:gmatch("%S+") do
            local ww = width(word, font, s)
            if ww > longest then longest = ww end
        end
        if longest > limit then s = math.max(MIN_SIZE, math.floor(s * limit / longest)) end
        local out, lines = wrap(text, font, s, limit)
        if maxh and maxh > 0 then
            while s > MIN_SIZE and lines * lineHeight(font, s) > maxh do
                s = s - 1
                out, lines = wrap(text, font, s, limit)
            end
        end
        return out, s
    end

    local baseSize = setmetatable({}, {__mode = "k"})
    local rotated = setmetatable({}, {__mode = "k"})

    -- A tall narrow area (the side tabs, "装\n备" style) whose English word
    -- does not fit across at 4/5 of the size: lay the text along the long
    -- side and turn the label 90 degrees clockwise.
    local function turnSideways(text, font, size, w, h)
        if type(text) ~= "string" or text:find(CJK) or not w or w <= 0 or h < 2 * w then
            return false
        end
        font = (font and font ~= "") and font or DEFAULT_TEXT_FONT
        local s = math.floor((tonumber(size) or 20) * 0.8)
        for word in text:gmatch("%S+") do
            if width(word, font, s) > w * 0.95 then return true end
        end
        return false
    end

    CCLabelTTF.create = function(cls, ...)
        local n = select("#", ...)
        local a = {...}
        local base = a[3]
        local turn = false
        if n >= 4 and type(a[1]) == "string" and a[4] ~= nil then
            local w, h = a[4].width, a[4].height
            local ok, t = pcall(turnSideways, a[1], a[2], a[3], w, h)
            if ok and t then
                turn = true
                a[4] = CCSize(h, w)
                w, h = h, w
            end
            local ok2, t2, s2 = pcall(fit, a[1], a[2], a[3], w, h)
            if ok2 and t2 then a[1], a[3] = t2, s2 end
        end
        local label = rawCreate(cls, unpack(a, 1, n))
        if label and n >= 4 and base then baseSize[label] = base end
        if label and turn then
            rotated[label] = true
            label:setRotation(90)
        end
        return label
    end

    -- For a turned label the caller's anchor refers to the upright box;
    -- (ax, ay) there is (1 - ay, ax) on the turned one.
    local rawAnchor = CCLabelTTF.setAnchorPoint
    if rawAnchor then
        CCLabelTTF.setAnchorPoint = function(self, p, ...)
            if rotated[self] and p then
                return rawAnchor(self, ccp(1 - p.y, p.x))
            end
            return rawAnchor(self, p, ...)
        end
    end

    local rawSetString = CCLabelTTF.setString
    CCLabelTTF.setString = function(self, text, ...)
        if type(text) == "string" and text ~= "" then
            local ok, t, s = pcall(function()
                local d = self:getDimensions()
                if not d or d.width <= 0 then return nil end
                local base = baseSize[self] or self:getFontSize()
                baseSize[self] = base
                local t2, s2 = fit(text, self:getFontName(), base, d.width, d.height)
                if t2 == nil then return nil, base end
                return t2, s2
            end)
            if ok then
                if s and s ~= self:getFontSize() then self:setFontSize(s) end
                if t then text = t end
            end
        end
        return rawSetString(self, text, ...)
    end

    if Label and Label.setText and Label.setTextAreaSize and Label.setFontSize then
        local info = setmetatable({}, {__mode = "k"})
        local rawSetText, rawSetArea, rawSetFS = Label.setText, Label.setTextAreaSize, Label.setFontSize
        local function get(self)
            local i = info[self]
            if i == nil then i = {}; info[self] = i end
            return i
        end
        local function apply(self)
            local i = get(self)
            local t, s
            if i.w and i.w > 0 then
                local ok
                ok, t, s = pcall(fit, i.text, DEFAULT_TEXT_FONT, i.size or 20, i.w, i.h)
                if not ok then t, s = nil, nil end
            end
            local size = s or i.size
            if size and size ~= i.cur then rawSetFS(self, size); i.cur = size end
            return rawSetText(self, t or i.text)
        end
        Label.setText = function(self, text)
            local i = get(self)
            i.text = text
            if type(text) ~= "string" then return rawSetText(self, text) end
            return apply(self)
        end
        Label.setTextAreaSize = function(self, size)
            rawSetArea(self, size)
            local i = get(self)
            i.w, i.h = size.width, size.height
            if type(i.text) == "string" then apply(self) end
        end
        Label.setFontSize = function(self, size)
            local i = get(self)
            i.size, i.cur = size, size
            rawSetFS(self, size)
            if type(i.text) == "string" and i.w then apply(self) end
        end
    end
end
'''

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
    # 12. English text layout: wrap on spaces, shrink to fit (ENGLISH_TEXT_HOOK).
    Patch(GUI_CREATOR,
          'local MMGUICreator = class("MMGUICreator");\n',
          ENGLISH_TEXT_HOOK + 'local MMGUICreator = class("MMGUICreator");\n'),
    # 13. RoleUIInfoPanel: the level, EXP and rebirth values sit at fixed x
    #     (420 / 475) that fit the Chinese labels; English labels are wider
    #     ("Rebirth L0Spin"), so each value starts after its label, never left
    #     of where it was. descLabel[1..4] are the rebirth requirement, rebirth
    #     level, EXP and level labels, at y 360, 400, 440, 480.
    *[Patch(ROLE_INFO, f"createMMLabel({txt}, {size}, ccp({x}, {y}), nil, nil, true)",
            f"createMMLabel({txt}, {size}, ccp(math.max({x}, 364 + "
            f"self.descLabel[{i}]:getContentSize().width), {y}), nil, nil, true)")
      for txt, size, x, y, i in (('"0"', 22, 420, 480, 4), ('"0"', 20, 420, 440, 3))],
    *[Patch(ROLE_INFO, f'createMMLabel(" ", 22, ccp({x},{y}), nil, nil, true)',
            f'createMMLabel(" ", 22, ccp(math.max({x}, 364 + '
            f'self.descLabel[{i}]:getContentSize().width),{y}), nil, nil, true)')
      for x, y, i in ((475, 400, 2), (475, 360, 1))],
    # 14. BagLeftPanel: "Owned" is centred on x 180 and the count starts at a
    #     fixed 213; anchor the label's right edge at 206, where the centred
    #     Chinese 拥有 ends, so a wider word grows to the left.
    Patch(BAG_LEFT,
          "    self.stc1:setColor(g_colorManager.C3_WHITE);\n",
          "    self.stc1:setColor(g_colorManager.C3_WHITE);\n"
          "    self.stc1:setAnchorPoint(ccp(1, 0.5)); self.stc1:setPositionX(206);\n"),
    # 15. LevelDes: the stage story is centred in a 500 x 300 box that reaches
    #     down behind the stamina / drops panel; three Chinese lines never got
    #     there, six English ones do. Same top edge (y 350), 170 high, so the
    #     text shrinks to stay above the panel.
    Patch(LEVEL_DES,
          "self.levelInfo.description, 163 - 15, 200, self.widgetBg, cc.size(500, 300),",
          "self.levelInfo.description, 163 - 15, 265, self.widgetBg, cc.size(500, 170),"),
    # 16. GameLoginScene: the consent line is centred on x -15 and the green
    #     "Privacy Policy" button starts at x 55, where the Chinese line ends;
    #     right-align the line to end at x 50 so a longer English one grows left.
    Patch(SCENE,
          "    txt1:setColor(g_colorManager.C3_WHITE);\n",
          "    txt1:setColor(g_colorManager.C3_WHITE);\n"
          "    txt1:setTextHorizontalAlignment(kCCTextAlignmentRight);"
          " txt1:setAnchorPoint(ccp(1, 0.5)); txt1:setPositionX(50);\n"),
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


def overlay_english(english: Path, dest_assets: Path) -> int:
    """Put the localise.write output over the copied assets; returns files copied.

    The English Lua goes in under the Chinese file names. The client loads
    `language.Language_` .. CONFIG_LANAGUE, and CONFIG_LANAGUE = "cn" in
    main.lua also selects the SDK branch, IS_FACEBOOK and the opid table, so
    renaming the language would change behaviour; substituting the files
    changes only the text.
    """
    src = Path(english) / "assets/res"
    if not (src / "language/Language_en.lua").is_file():
        raise FileNotFoundError(
            f"{src / 'language/Language_en.lua'} missing; run `py -3.14 -m localise.write`"
        )
    n = 0
    for en_name in ("Language_en.lua", "Language_start_en.lua"):
        shutil.copy2(src / "language" / en_name,
                     dest_assets / "res/language" / en_name.replace("_en.lua", "_cn.lua"))
        n += 1
    for db in sorted((src / "data/split").glob("*.db")):
        shutil.copy2(db, dest_assets / "res/data/split" / db.name)
        n += 1
    # Lua files whose hard-coded Chinese UI text was translated
    # (localise.scripts); the PATCHES apply on top of these copies.
    scripts = Path(english) / "assets/scripts"
    for lua in sorted(scripts.rglob("*.lua")) if scripts.is_dir() else []:
        dst = dest_assets / "scripts" / lua.relative_to(scripts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lua, dst)
        n += 1
    return n


def build(
    stock: Path,
    dest_assets: Path,
    dest_jnilibs: Path,
    server_ip: str,
    username: str,
    port: int,
    english: Path | None = None,
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

    if english is not None:
        n = overlay_english(english, dest_assets)
        print(f"English text: {n} files from {english}")

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
    build(s.stock_dir, args.assets, args.jnilibs, s.host, s.username, s.port,
          s.english_dir)
    print(f"assets ready, server list points at {s.host}:{s.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
