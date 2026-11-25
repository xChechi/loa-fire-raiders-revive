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
GUIDE_TALK = "scripts/app/game/manager/guide/NewGuideTalkPanel.lua"
EMAIL_ROW = "scripts/app/game/view/ui/email/EmailRenderBox.lua"

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
    #     there, six English ones do. Centred on y 280 - 13 and fitted to 110
    #     high, then drawn in a 140-high box. Patch 12 measures a line at
    #     about 0.88 of the advance the engine draws, and the label clips to
    #     its box: fitted to 170 or 140, five lines at size 26 passed and
    #     Death Mine ran into the drops panel on the AVD; fitted and drawn at
    #     85 the fourth line was cut off.
    Patch(LEVEL_DES,
          "  g_cocoGUI_creator:add_txt_mm(26, self.levelInfo.description, 163 - 15, 200, "
          "self.widgetBg, cc.size(500, 300), kCCTextAlignmentLeft, kCCVerticalTextAlignmentCenter)\n",
          "  local desc = g_cocoGUI_creator:add_txt_mm(26, self.levelInfo.description, 163 - 15, 280, "
          "self.widgetBg, cc.size(500, 110), kCCTextAlignmentLeft, kCCVerticalTextAlignmentCenter)\n"
          "  desc:setDimensions(cc.size(500, 140))\n"),
    # 16. GameLoginScene: the consent line is centred on x -15 and the green
    #     "Privacy Policy" button starts at x 55, where the Chinese line ends;
    #     right-align the line to end at x 50 so a longer English one grows left.
    #     The checkbox (x -200) then sits under the start of the English
    #     line, so it moves to just left of wherever the line starts.
    #     On the AVD (24-11-2026) the drawn line still ran about one glyph
    #     past x 50 into "Privacy Policy"; it ends at x 30.
    Patch(SCENE,
          "    txt1:setColor(g_colorManager.C3_WHITE);\n",
          "    txt1:setColor(g_colorManager.C3_WHITE);\n"
          "    txt1:setTextHorizontalAlignment(kCCTextAlignmentRight);"
          " txt1:setAnchorPoint(ccp(1, 0.5)); txt1:setPositionX(30);\n"
          "    self.privacyCheckBtn:setPositionX(30 - txt1:getContentSize().width - 22);\n"),
    # 17. RoleUIInfoPanel:updateReBirthInfo puts the rebirth requirement
    #     ("Lv.55") back at x 475 on every refresh, which undoes patch 13 and
    #     covers "Rebirth Req:"; same rule as patch 13 there.
    Patch(ROLE_INFO,
          "self.nextReBirthLvTfd:setPosition(ccp(475,360))",
          "self.nextReBirthLvTfd:setPosition(ccp(math.max(475, 364 + "
          "self.descLabel[1]:getContentSize().width),360))"),
    # 18. MMPlayerUpgradePanel: each row's label starts at x 120 and its old
    #     value sits at a fixed x 320 (300 without a new value); "Alliance
    #     Level:" and "Max Stamina:" at size 36 run past it. Scale a label
    #     wider than 170 down so it ends by x 290.
    Patch("scripts/app/game/framework/MMPlayerUpgradePanel.lua",
          "\tbox:addNode(txt1);\n",
          "\tbox:addNode(txt1);\n"
          "\tlocal w = txt1:getContentSize().width; if w > 170 then txt1:setScale(170 / w) end\n"),
    # 19. RoleUI side tabs: the label box is 33 x 80, which patch 12 turns
    #     sideways; "Breakthrough" does not fit 80 even at the minimum size,
    #     so the engine breaks it ("Breakthro|ugh"), and f00380 "Awakening "
    #     carries a trailing space that wraps too. 96 long (the tabs are 110
    #     apart) and trimmed. On the AVD the engine still broke "Breakthrou|gh"
    #     (the stroke makes the line wider than measured) and the left-aligned
    #     "Skills" sat at the box end, under the selected Equip tab. Once the
    #     fit has picked the size, the box is dropped: one line, never wrapped,
    #     centred on the tab by its anchor, 12 lower than the stock centre so
    #     the selected tab above does not cover its first letter.
    Patch("scripts/app/game/view/ui/RoleUI.lua",
          "createMMLabel(tempTabTxtAry[k], 24, ccp(-19, -3), CCSize(33, 80), ui.TEXT_ALIGN_LEFT, true);",
          'createMMLabel((tempTabTxtAry[k]:gsub("%s+$", "")), 24, ccp(-19, -15), '
          "CCSize(33, 96), ui.TEXT_ALIGN_LEFT, true); "
          "tabTfd1:setDimensions(CCSize(0, 0));"),
    # 20. NewGuideTalkPanel: the princess's line is fitted to a 300 x 120 box,
    #     but the engine's own wrap adds a line, and the vertically centred
    #     text then runs below the bubble. Fit to 100 high instead, centred on
    #     the same line (bottom 10 higher in both facing directions).
    Patch(GUIDE_TALK,
          'createMMLabel("", 28, ccp(-50,-107), CCSizeMake(300, 120),nil,false);',
          'createMMLabel("", 28, ccp(-50,-107), CCSizeMake(300, 100),nil,false);'),
    Patch(GUIDE_TALK, "self.tf:setPosition(ccp(-50,-92));", "self.tf:setPosition(ccp(-50,-82));"),
    Patch(GUIDE_TALK, "self.tf:setPosition(ccp(-245,-92));", "self.tf:setPosition(ccp(-245,-82));"),
    # 21. RoleUIInfoPanel: the rebirth count ("0 Rebirths") starts after
    #     "Rebirth Lv:" (patch 13) and runs under the side-tab column, which
    #     begins near x 618 in the panel (measured on the AVD: one panel unit
    #     is about 1.5 px of the 2280 px screen, "Level:" at x 364 is 131 px
    #     wide); scale it down to end by x 610.
    Patch(ROLE_INFO,
          '    self.reBirthLvTfd:setString(tostring(rebirthLv) .. g_lan:getTxt("h07008"))\n',
          '    self.reBirthLvTfd:setString(tostring(rebirthLv) .. g_lan:getTxt("h07008"))\n'
          "    local room = 610 - self.reBirthLvTfd:getPositionX(); "
          "local w = self.reBirthLvTfd:getContentSize().width; "
          "self.reBirthLvTfd:setScale(w > room and room / w or 1)\n"),
    # 22. DesSweepPanel:addUnlockTxt: the five-part "Alliance Level Reached 8
    #     Lv. or VIP 1 Unlock Sweep" line starts at x -278 of btnBg and the
    #     Challenge button's left edge is at x 169 there (405 - 80 - 156);
    #     scale the line down to 430 wide so it ends before the button.
    Patch("scripts/app/game/view/ui/des/DesSweepPanel.lua",
          "  local txt_node = g_gameUI_Tools:createContentNode(txtTable)\n"
          "  txt_node:setPosition(ccp(-228 - 50, 0))\n",
          "  local txt_node, txt_w = g_gameUI_Tools:createContentNode(txtTable)\n"
          "  txt_node:setPosition(ccp(-228 - 50, 0))\n"
          "  if txt_w and txt_w > 430 then txt_node:setScale(430 / txt_w) end\n"),
    # 23. RoleListRoleRender: the hero name is centred 35 right of the centre
    #     of the 248-wide class strip, whose badge ends 38 left of it;
    #     "Earthshaker Colossus" ran over the badge. Scale a name wider than
    #     142 down, so it stays clear of the badge on the left.
    Patch("scripts/app/game/view/ui/roleListUI/RoleListRoleRender.lua",
          "    self.nameTfd:setString(tempHeroName);\n",
          "    self.nameTfd:setString(tempHeroName);\n"
          "    local w = self.nameTfd:getContentSize().width; "
          "self.nameTfd:setScale(w > 142 and 142 / w or 1)\n"),
    # 24. AngelPreviewDes: the name is right-aligned to end at x 178 and the
    #     "Locked" / "Lv.N" label on the same line is right-aligned to end at
    #     250; the English label is wider than 未召唤 and ran into the name
    #     ("Idol Angel" + "Locked"). The name box moves 24 left.
    Patch("scripts/app/game/view/ui/angel/AngelPreviewDes.lua",
          "self.angelInfo.name, 12 - 34, 60 + 30, self.bgImg",
          "self.angelInfo.name, 12 - 34 - 24, 60 + 30, self.bgImg"),
    # 25. EmailRenderBox: every text of a mailbox row is a Label centred in a
    #     fixed box (320 wide unless given), placed for the short Chinese:
    #     "Subject:" from x 100 with the subject from x 180, so the subject
    #     ran over the label ("ThemItem"), and "Remaining" / the day count /
    #     "Days" from x 540 / 610 / 640 ("Rema7niDays"). The labels drop
    #     their box so they measure their own text: the subject starts 8
    #     after "Subject:" and is fitted (patch 12) to end by x 530; the
    #     date and "Remaining N Days" end at x 705, the right end of the
    #     Chinese date, each part placed left of the one after it. A boxed
    #     Label draws its text at the top of its 56-high box, so every label
    #     here hangs from that top edge (y + 28) and the row stays in line.
    Patch(EMAIL_ROW,
          "tf_title1:setColor(g_colorManager.C3_GREEN);\n",
          "tf_title1:setColor(g_colorManager.C3_GREEN);\n"
          "    tf_title:setTextAreaSize(CCSize(0, 0)); tf_title:setAnchorPoint(ccp(0, 1)); "
          "tf_title:setPosition(ccp(100, 80 + 28))\n"
          "    local sx = 100 + tf_title:getContentSize().width + 8; "
          "tf_title1:setAnchorPoint(ccp(0, 1)); tf_title1:setPosition(ccp(sx, 80 + 28)); "
          "tf_title1:setTextAreaSize(CCSize(530 - sx, 56))\n"),
    Patch(EMAIL_ROW,
          "tf_2:setColor(g_colorManager.C3_WHITE);\n",
          "tf_2:setColor(g_colorManager.C3_WHITE);\n"
          "    tf_2:setTextAreaSize(CCSize(0, 0)); "
          "tf_2:setAnchorPoint(ccp(1, 1)); tf_2:setPosition(ccp(705, 80 + 28))\n"),
    Patch(EMAIL_ROW,
          "tf_5:setColor(g_colorManager.C3_WHITE)",
          "tf_5:setColor(g_colorManager.C3_WHITE)\n"
          "        local x = 705\n"
          "        for _, t in ipairs({tf_5, tf_4, tf_3}) do\n"
          "            t:setTextAreaSize(CCSize(0, 0)); t:setAnchorPoint(ccp(1, 1)); "
          "t:setPosition(ccp(x, 20 + 28))\n"
          "            x = x - t:getContentSize().width - (t == tf_4 and 8 or 0)\n"
          "        end"),
    Patch(EMAIL_ROW, "tf_2:setPosition(ccp(700, 20))", "tf_2:setPositionY(20 + 28)"),
    # 26. MMTools:getDateStr (the mail date, the friend chat time) wrote
    #     year-month-day unpadded ("2026-5-3"); the owner's rule is dd-mm-yyyy.
    Patch("scripts/app/game/utils/MMTools.lua",
          'timeStr = timeTab.year .. "-" .. timeTab.month .. "-"..timeTab.day;',
          'timeStr = string.format("%02d-%02d-%04d", timeTab.day, timeTab.month, '
          "timeTab.year);"),
    # 27. NormalShopRender: the item name under a 210-wide shop slot is one
    #     unbounded line; "Soul Stone (Lunar Priestess)" ran into the next
    #     slot's name. A 216 x 56 box, centred both ways: patch 12 wraps it
    #     onto two lines (size 16-20) no wider than 186 (its 0.86 of 216).
    #     The store's clip edge sits about 88 left of the first column's
    #     slot centre (it cut "ul Stone" in stock), so the widest drawn line,
    #     measured with a plain probe label plus the 2 per glyph of its
    #     stroke (as patch 12 counts it), is scaled to at most 168; a 200
    #     box instead put long names on three tiny lines. Patch 12 squeezes a
    #     box under 1.8 line heights onto one line, and msyh.ttf at 22 is 30
    #     high: a 46-high box ran the name onto one line at the minimum size
    #     and the engine broke it mid-word ("Knig|ht") on the AVD. Two lines
    #     at 20 (about 27 each, 1.37 of the size) did not fit under the slot:
    #     measured on the AVD
    #     the price plate ends near y -79, the next row's slot starts near
    #     -131 and the scroll view clips the bottom row near -122. The name
    #     moves up to -100 and is scaled so its lines take at most 40.
    Patch("scripts/app/game/view/ui/normalShop/NormalShopRender.lua",
          'self.nameTfd = g_cocoGUI_creator:createMMLabel("", 22, ccp(102, -105));',
          'self.nameTfd = g_cocoGUI_creator:createMMLabel("", 22, ccp(102, -100), '
          "CCSize(216, 56), ui.TEXT_ALIGN_CENTER); "
          "self.nameTfd:setVerticalAlignment(kCCVerticalTextAlignmentCenter);"),
    Patch("scripts/app/game/view/ui/normalShop/NormalShopRender.lua",
          "    self.nameTfd:setString(itemData.itemVo.name);\n",
          "    self.nameTfd:setString(itemData.itemVo.name);\n"
          '    local lines, widest = 0, 0; '
          'for line in (self.nameTfd:getString() .. "\\n"):gmatch("(.-)\\n") do '
          "lines = lines + 1; widest = math.max(widest, CCLabelTTF:create(line, "
          "self.nameTfd:getFontName(), self.nameTfd:getFontSize()):getContentSize().width + 2 * #line) end; "
          "local h = lines * self.nameTfd:getFontSize() * 1.37; "
          "self.nameTfd:setScale(math.min(1, 40 / h, 168 / math.max(widest, 1)))\n"),
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
    """Put the localise.write and localise.images output over the copied assets;
    returns files copied.

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
    # Images whose baked-in Chinese text was re-drawn (localise.images) and
    # the story scripts with English dialogue (localise.story), same relative
    # path as the stock file they replace.
    images = Path(english) / "assets/res/assets"
    for pattern in ("*.png", "*.lua"):
        for f in sorted(images.rglob(pattern)) if images.is_dir() else []:
            dst = dest_assets / "res/assets" / f.relative_to(images)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
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
