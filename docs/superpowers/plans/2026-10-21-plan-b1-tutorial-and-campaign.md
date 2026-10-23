# Plan B1 — "Tutorial through to campaign chapter 1" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Plan A server so that Stefan, on the emulator `LOA_API30`, opens the game on a fresh `data/player.db`, plays the stock new-player guide once (intro movie, guide battle, the two summons the guide points at, the first campaign fight), force-stops the app and comes back to the main city with the guide resumed instead of replayed, then plays campaign chapter 1 stage by stage: energy is spent, stars, XP, drops and the next-stage unlock persist across a server restart, and the chapter-1 star chest pays out.

**Architecture:** Three new server pieces on top of Plan A's framing/registry/dispatch core. (1) `server/config/` opens the client's own `.db` tables read-only and hands out typed rows, so no handler ever writes SQL against the stock data. (2) New handler modules `guide`, `hero`, `item`, `gacha`, `level` follow the Plan A contract `handlers(registry, settings, conn) -> dict[(service, cmd), handler]`, widened to `handlers(registry, settings, conn, cfg)` for every module that reads game data, and are registered in `server/__main__.py:build_handlers`. (3) Player state grows additively in `data/player.db` (`levels`, `chapters`, a unique index on `items`, an `energy_at` column), and anything the client has to learn outside a request/response pair is pushed through the client's own notify ids (`5_2008 ClientNotification`, `5_2036 LevelUpNotify`, `5_2012 AddHeroNotify`) via a new one-frame-deep `Session.outbox`.

**Tech Stack:** Python 3.14.3 (`py -3.14`), `protobuf` 7.36.2, `pytest` 9.0.3, stdlib `asyncio`/`sqlite3`/`tomllib`; the stock client's SQLite config tables under `.stock/assets/res/data/split/`; Android SDK platform-tools + AVD `LOA_API30` for the acceptance run; Git Bash for shell steps.

**Spec:** `docs/superpowers/specs/2026-10-20-loa-private-server-design.md` (sections 3.1 `config` plus modules `level`/`item`/`hero`, 4 "Campaign stage", 5.3 milestone 2, and the 21-10-2026 amendment). Brief: `docs/superpowers/plans/BRIEF-plan-b1-tutorial-and-campaign.md`. Plan A plan: `docs/superpowers/plans/2026-10-20-plan-a-boot-to-main-city.md`. Plan A ledger with the rulings this plan inherits: `.superpowers/sdd/2026-10-20-plan-a-boot-to-main-city/progress.md`. Wire format: `docs/protocol.md`. Emulator loop: `docs/dev-loop.md`. Read the brief and this file before Task 1.

## Global Constraints

- Python is `py -3.14` on every command line. Never `python`, never `python3`. Tests: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa` from the repo root (forward slashes in basetemp — Plan A Task 1 ruling).
- Sockets in tests bind and connect to `127.0.0.1` explicitly through the `bind_host` parameter, never the name `localhost` (it resolves `::1` first, about 2 s per connect on this machine). `settings.host` stays the client-side address (`10.0.2.2`).
- **No `git push`, ever.** One local commit per task, conventional message (`feat(server): ...`, `chore(repo): ...`).
- `.stock/` is a read-only input. Every config connection is opened `mode=ro`. Nothing under `.stock/` is modified or committed.
- `data/player.db` migrations are additive only: `CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`, and `ALTER TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check. Never a rebuild: Stefan's Plan A character must survive.
- Every message the server emits goes through `fill_required` (`server/net/server.py`) before `SerializeToString()`. proto2 required fields are enforced at serialize time, and an `EncodeError` on the wire shows up as a white screen with no client-side error.
- Config reads go through `server/config/`. No handler contains SQL against the stock `.db` files.
- Status codes are the client's own, from `.stock/assets/res/data/split/language.db`, quoted by id in the task that uses them. Never invent a code.
- Python 3.14 rejects a literal `%` in an `argparse` help or description string (it is read as a format directive). Write "percent" in words in any new CLI help text.
- Any date that reaches a human (log banner, doc table) renders `dd-mm-yyyy`; stored and ISO values stay `YYYY-MM-DD`.
- No new abstraction for a single caller. `server/config/` is one class; the notification helper exists because `level` and `gacha` both need it.

## Assumptions and open questions

Answered by reading the code; each line says where. Then the ones that are genuinely unknown.

**Settled by the trace (not open):**

1. **The guide never asks the server for anything except `5_2041`.** `NewGuideManager` sends `5_2041 SaveGuideIdReq{guide_id}` at four sites (`NewGuideManager.lua:234, 331, 404, 725`) and nothing else. Every other step is a touch on a UI node registered with `setCheckPoint`, so what the guide needs from the server is whatever that UI needs.
2. **The guide battle sends no `LevelIntoReq` and no `LevelOutReq`.** `NewGuideManager:playFight` builds `fightData.test = true` with `levelEntry = "1000"` and a fixed NPC layout (`NewGuideManager.lua:466-486`); `BattleFactoryLevel:requestResultHandle` only sends `5_2203` when `self.data.test ~= true` (`BattleFactoryLevel.lua:385-392`), and `BattleFactoryGuide:requestResultHandle` overrides it to `self.scene:clearRoles(); self:openMainScene()` with no request at all (`BattleFactoryGuide.lua:274-278`). The guide battle is entirely client-side, including its hard-coded 64 random numbers (`BattleFactoryGuide.lua:73-76`).
3. **"Never replays" is `guide_id` persistence, not a one-shot flag.** `RPGGame:init` (`RPGGame.lua:78`) opens the main scene immediately when `toint(g_roleData.player.guide_id) ~= 0`; `LoadingManager:clear` (`LoadingManager.lua:195`) then calls `g_newGuideManager:check(0)`, which reads `g_roleData.player.guide_id`, follows that row's `jump_id` when it has one, and resumes from there (`NewGuideManager.lua:244-263`). A persisted non-zero `guide_id` is exactly "the intro does not run again, and the guide picks up where it stopped".
4. **An unimplemented guide step cannot lock the client.** `NewGuideManager:playGuide` clears the guide and drops its full-screen mask when `self.guideList[guideData.id]` is nil (`NewGuideManager.lua:429-440`), and `clear()` sets the node invisible, after which the touch layer returns false and clicks pass through (`onEnter`, `NewGuideManager.lua:113-122`). The guide self-terminates on any step whose node is not on screen.
5. **The campaign UI asks the server nothing when it opens.** `FunctionType:openUIByIdNotCheck` for `COPY_TYPE` (= 10230) just opens `UI_LEVEL_SELECT` (`FunctionType.lua:1205-1206`); the whole stage map comes from `stage_info`/`chapter_info` plus `QueryMyselfRes.levels`, `.chapters` and `player.last_level`.
6. **`last_level` is the unlock lever, not the `levels` array.** `LevelManager:readLastLevelInfo` sets `maxComLevel = levelTable[last_level].nextLevel`, and `last_level == 0` means "fresh account, start at the first stage" (`LevelManager.lua:409-424`). `nextLevel` is computed client-side as the next `idx` in the chapter, else the first stage of the next chapter of the same `type`, else itself (`LevelManager.lua:285-310`).
7. **Chapter 1 needs no angel.** `LevelLine:startFight` only demands an angel when `tonumber(self.levelInfo.entry) > 10022` (`LevelLine.lua:65-70`), and chapter 1's five stages are 10000, 10010, 10012, 10020, 10022. It does demand at least one hero on the field (`LineFrame:startFight`, text `z00303` 英雄不能为空), which is why the first hero is granted at character creation.
8. **A fresh character's starting values are in the config, not invented.** `variables.db`: `HERO_FIRST_ENTRY=100000`, `HERO_GOLD_INIT=1280000`, `HERO_DIAMOND_INIT=18888`, `PLAYER_ITEMS_INIT=1100|3,1200|2`, `ENERGY_INIT=60`, `ENERGY_MAX_INIT=60`.
9. **Energy regeneration comes from `variables.db`, not `xp_for_level`.** `PLAYER_ENERGY_RECOVER_CYCLE=360` (seconds) and `PLAYER_ENERGY_RECOVER=1`, which the client itself reads to schedule its "energy full" notification (`MyGroupInfoData.lua:131-146`). `xp_for_level.levelup_recovery_energy` (12 at level 1) is the energy granted **on level-up**; the brief reads it as the regen amount, the code does not. `xp_for_level.max_energy` is the cap per level (60 at level 1, +2 per level).
10. **`drop_group.drop_id` is the stage's drop id and `drop_group.drop_group_id` indexes `drop_base`.** `DataManager:getDropBaseAry` (`DataManager.lua:444-474`) does `SELECT drop_group_id FROM drop_group WHERE drop_id = ?`, then `SELECT * FROM drop_base WHERE drop_group_id IN (...)`, switching to the table `drop_base_2` for ids `>= DataManager.DROP_BASE_SPLIT = 10000000` (`DataManager.lua:14, 29-35`).
11. **`urandom` must be exactly 64 values below 10000.** `BattleAlthm.MAX_URANDOM_SIZE = 64`, `SCALE = 10000`, and `BattleAlthm.NewAlgorithm` returns `nil, "Invalid algorithm urandom size."` when `#urandom ~= 64` (`BattleAlthm.lua:175-190`), which kills the battle before its first frame. `Random()` divides by `SCALE` and must stay below 1.0.
12. **`LevelIntoRes` has no `status` field.** Its fields are `drop`, `urandom`, `flag`, `star`. The only refusal channel is `flag`: `flag == 1` floats `z00224` and reopens the campaign UI, `flag == 2` floats `z00225` (`LevelLine.lua:37-60`). `LevelOutRes` does have `status`, and `BattleFactoryBase:requestServerInfo` returns to the main scene on any non-zero (`BattleFactoryBase.lua:882-900`) while `MMMsgDispatcher:onNetMessage` floats the `language.db` text for it.
13. **`LevelCleanRes` field 1 is named `flag`, not `status`.** The Lua comment above the listener calls it `required uint32 status = 1`, but the compiled descriptor the client loads names it `flag`, and `MMMsgDispatcher` keys on the literal name `status`, so a non-zero value there floats nothing. That decides how Task 15 refuses a sweep.

**Open — do not guess, resolve as stated:**

- **A. `ClientNotification.flags` byte order.** The field is `fixed64` in the proto but Lua reads it as a string (`string.len(flags)`, `string.byte(flags, ...)` in `RoleData:onPlayerInfoChange`), so the mask is byte-indexed over the raw 8 bytes: bit `2^((i-1) mod 8)` of byte `floor((i-1)/8)+1`, for the 1-based index `i` into `ClientPlayer.PLAYER_FIELD_DIC` (48 entries: `vip` 1, `vip_expires` 2, `paycount` 3, `xp` 4, `level` 5, `energy` 6, `max_energy` 7, `gold` 8, `diamond` 9, ... `last_level` 13, `avatar` 15). Whether the native layer hands Lua those 8 bytes little-endian, so that byte 1 is the least significant, is **unknown, resolve at implementation by capturing on the emulator**: Task 9 sends one notify with only `energy` set and greps logcat for `energy->changed`. If a different key changes, flip the byte order in the one helper and re-run. Nothing else in the plan depends on which way it is.
- **B. `drop_group.frequency`.** It is 0 or 1 in every row this plan reads and no Lua touches it. **Unknown**; Task 10 rolls each `drop_group` row exactly once and ignores `frequency`. If a stage visibly drops too little in the acceptance run, that is the field to look at.
- **C. `stage_info.once`.** Inferred from `LevelLine`'s `flag == 1` branch, which exists to push the client's stage pointer forward for a stage that cannot be re-run, and from the fact that chapter 1's two `once = 1` rows (10010, 10020) are exactly its `catalog = 1` rows, the ones `incCurLevel` advances. **Unknown as a server rule**; Task 13 answers `flag = 1` for a second entry into a cleared `once = 1` stage and Task 17 confirms the client floats `z00224` and reopens the campaign UI rather than wedging.
- **D. `ClientHero.spells`.** `BattleUnit:initByHeroData` builds the hero's active skills from `heroData.spells` and its normal attack from the prototype npc row (`BattleUnit.lua:3696-3741`). Which config table the real server derived the list from is **unknown**; Task 7 sends the prototype's own `npc_info.skill0..skill4` (non-zero ones), real data from the same row the NPC twin of that hero uses. If the hero never fires its ultimate in the acceptance run, that is the line to revisit.
- **E. How far the guide can run.** Past the first campaign fight the chain points at the equip flow (`10180` hero panel, `10190` hero row, `10200` equip slot, `10210` equip button) and later at the angel summon (`10293`, `AngelPreviewCircle`), both out of Plan B1 scope. By finding 4 the guide self-terminates there instead of locking. **Plan B1 therefore defines "the tutorial completed" as: the guide reaches and persists save point `10160`** (`new_player_guide_info` row 10160, `is_save = 1`, registered on the battle-result return button in `BattleEndLayer.lua:1001`) **after the two summons and the first campaign fight**, and a relaunch shows the main city with the guide resumed, not replayed. If the equip pointer does lock the screen on the emulator, Task 17 records it; the fix (one more guide step, or a `guide_id` bump) is a Plan B2 item, not a silent scope grab.
- **F. `GachaInfoRes.todays` and `.week`.** Both optional/repeated and only read as a fallback `cardInfo` in `TavernUI:getCardInfo`. Their meaning (daily/weekly soul tables `gacha_day_soul`, `gacha_week_soul`) is **unknown and out of scope**; Task 11 sends `todays` empty and `week = 0`.

## Review Focus

Five failure modes the spec and the client imply that no obvious task test would catch, most likely first. Each has its test pinned to the task that owns the code.

1. **A `LevelOutReq` arriving twice for one fight grants the drops twice.** `BattleFactoryBase:requestServerInfo` arms a 6-second timeout and, on expiry, pops `all10104` and resends the same `5_2203` up to two more times (`BattleFactoryBase.lua:871-930`). A server that reads the pre-rolled drops without consuming them pays out two or three times. Covered by Task 14 (`test_level_out_twice_grants_once`).
2. **A `ClientHero` whose `quality` has no `hero_quality` row kills the Lua VM.** `ClientHero:getNpcProperty` resolves `hero_quality(hero, quality) -> prototype` and then indexes `npcList[1][key]` with no nil check (`ClientHero.lua:60-82`), so a quality the table does not carry crashes the client right after login. Hero 100000's lowest quality is **10**, while `hero_info.quality` reads 0. Covered by Task 7 (`test_client_hero_quality_exists_in_hero_quality`).
3. **A `chapters` entry the client's `chapter_info` does not know crashes `LevelManager:readBoxInfo`**, which does `self.chapterEntryTable[tostring(curBoxInfo.chapter)].server_award = ...` with no nil check (`LevelManager.lua:337-349`). Covered by Task 12 (`test_chapters_only_contains_real_chapter_entries`).
4. **`urandom` of any length other than 64, or a value of 10000 or more, stops the battle before its first frame** (settled point 11). Covered by Task 13 (`test_urandom_is_64_values_under_10000`).
5. **An empty repeated field the Lua measures with `#`.** `RoleData:updateRechangeCardsList` runs `for i = 1,#data` over `QueryBtCardRecordRes.btCards` — the Plan A parked crash — and the same shape exists for `GachaRes.items`, which `TavernUI` hands to `g_tools:randomTable`. Covered by Task 4 (`test_bt_cards_carries_both_privilege_cards`) and Task 11 (`test_gacha_res_always_has_at_least_one_item`).

---

## Verified inputs, read 23-10-2026 from `.stock/`. Quote these, do not re-derive.

**Message definitions, printed from the registry (`server/net/registry.py` over `.stock/assets/res/utils/net/allProtos.pb`). Verbatim; field order as the descriptor lists it.**

```proto
message SaveGuideIdReq { required uint32 guide_id = 1; }
message SaveGuideIdRes { optional uint32 status = 1; }

message LevelIntoReq { required uint32 level = 1; }
message LevelIntoRes {
  repeated ClientPrizeEntry drop = 2;
  repeated uint32 urandom = 3;
  optional uint32 flag = 1;
  optional uint32 star = 4;
}
message LevelOutReq {
  required uint32 level = 1;
  repeated uint32 heroes = 2;
  required uint32 angel = 3;
  required int32 star = 4;
  repeated ClientOp ops = 5;
}
message LevelOutRes {
  optional uint32 status = 1;
  optional ClientLevelXp owner = 2;
  optional ClientLevelXp angel = 3;
  repeated ClientLevelXp heroes = 4;
  optional bool warn = 5;
  optional uint32 star = 6;
  optional ClientFightResultFromServer fight = 7;
  optional bool if_mail = 8;
  repeated ClientPrizeEntry drop = 9;
}
message LevelCleanReq { required uint32 level = 1; required uint32 times = 2; }
message LevelCleanRes {
  repeated CleanLevelEntry drops = 2;
  repeated ClientPrizeEntry reward = 3;
  optional uint32 flag = 1;
  optional uint32 times = 4;
  optional bool if_mail = 5;
}
message LevelResetReq { required uint32 level = 1; }
message LevelResetRes { optional uint32 status = 1; optional uint32 reset_count = 2; }
message LevelChapterPrizeReq { required uint32 chapter = 1; required uint32 prize = 2; }
message LevelChapterPrizeRes { optional uint32 status = 1; optional uint32 chapter = 2; }

message GachaInfoReq { }
message GachaInfoRes {
  optional uint32 status = 1;
  repeated ClientGachaInfo gachaInfos = 2;
  repeated uint32 todays = 3;
  optional uint32 week = 4;
  optional int32 next = 5;
  optional int32 gold_next = 6;
  optional uint32 gold_gacha = 7;
  optional uint32 diamond_gacha = 8;
  optional uint32 diamond_ten_gacha = 9;
}
message GachaReq { required uint32 gacha = 1; }
message GachaRes {
  optional uint32 status = 1;
  repeated ClientPrizeEntry items = 2;
  optional int32 next = 3;
  optional int32 gold_next = 4;
  optional uint32 gold_gacha = 5;
  optional uint32 diamond_gacha = 6;
  optional uint32 diamond_ten_gacha = 7;
  optional YunyinActivity extreme_augury = 8;
  optional YunyinActivity mystical_augury = 9;
}
message ClientGachaInfo {
  required uint32 gacha = 1;
  required uint32 cooldown = 2;
  required uint32 freetimes = 3;
}

message ClientPrizeEntry {
  required uint32 category = 1;
  optional uint32 refer = 2;
  optional int32 amount = 3;
  optional ClientPrizeExtra extra = 4;
}
message ClientOp { repeated uint32 op = 1; }
message ClientLevelXp { required uint32 refer = 1; required uint32 level = 2; required uint32 xp = 3; }
message ClientLevel {
  required uint32 level = 1;
  required uint32 star = 2;
  required uint32 count = 3;
  required uint32 deadline = 4;
  required uint32 reset_count = 5;
  required uint32 clean_elite_count = 6;
  optional string first_reporter_id = 7;
  repeated string reporter_ids = 8;
}
message ClientChapter { required uint32 chapter = 1; optional uint32 award = 2; }
message ClientStock {
  required uint32 id = 1;
  required uint32 entry = 2;
  optional uint32 state = 3;
  optional uint32 index = 4;
  required uint32 amount = 5;
}
message ClientNotification {
  required uint32 ident = 1;
  required fixed64 flags = 2;
  optional uint32 refer = 3;
  repeated double data = 4;
}
message BatchNotify { repeated ClientNotification notifications = 1; }
message LevelUpNotify {
  required uint32 oldLevel = 1;
  required uint32 newLevel = 2;
  required uint32 oldEnergy = 3;
  required uint32 newEnergy = 4;
  required uint32 oldMaxEnergy = 5;
  required uint32 newMaxEnergy = 6;
  optional uint32 status = 7;
}
message AddHeroNotify { required ClientHero hero = 1; optional uint32 status = 99; }
message QueryBtCardRecordReq { }
message QueryBtCardRecordRes { repeated BtCardInfo btCards = 1; }
message BtCardInfo { required uint32 entry = 1; required bool isActivation = 2; required bool isAward = 3; }
```

`ClientHero`'s 10 required fields, in descriptor order, are `id`, `entry`, `prototype`, `quality`, `star`, `xp`, `level`, `unit` (`ClientHeroUnit`), `ability`, `base_unit` (`ClientHeroUnit`); `items`, `spells`, `supports`, `runes`, `gemstones`, `signets` are repeated and 13 more fields are optional.

`ClientHeroUnit` required fields, in descriptor order: `max_hp` (uint32), then the doubles `power`, `defence`, `magic`, `magic_defence`, `agility`, `hit_base`, `duck_base`, `crit_base`, `crit_damage_base`, `block_base`, `tenacity_base`, `spell_damage_add_scale`, `treat_damage_add_scale`, `hit_rate`, `duck_rate`, `crit_rate`, `crit_damage_rate`, `block_rate`, `tenacity_rate`. Optional and worth setting from the npc row: `resistance_base`, `hp_recovery`, `rage_recovery`, `initial_energy`, `max_energy`.

**Message ids, from `.stock/assets/res/utils/net/msgIDMap.lua`:**

```lua
id_5_2008 = "ClientNotification",   id_5_2012 = "AddHeroNotify",
id_5_2036 = "LevelUpNotify",        id_5_2041 = "SaveGuideIdReq",
id_5_2042 = "SaveGuideIdRes",       id_5_2121 = "GachaInfoReq",
id_5_2122 = "GachaInfoRes",         id_5_2123 = "GachaReq",
id_5_2124 = "GachaRes",             id_5_2201 = "LevelIntoReq",
id_5_2202 = "LevelIntoRes",         id_5_2203 = "LevelOutReq",
id_5_2204 = "LevelOutRes",          id_5_2205 = "LevelCleanReq",
id_5_2206 = "LevelCleanRes",        id_5_2207 = "LevelResetReq",
id_5_2208 = "LevelResetRes",        id_5_2209 = "LevelChapterPrizeReq",
id_5_2210 = "LevelChapterPrizeRes", id_5_2223 = "MailReceiveReq",
id_5_2224 = "MailReceiveRes",       id_5_2039 = "SyncRedPointReq",
id_5_2943 = "QueryBtCardRecordReq", id_5_2944 = "QueryBtCardRecordRes",
```

`5_2008`, `5_2012`, `5_2036` and `5_4004` are notify ids with no paired `Req`: the server writes them with `Session.send(service, cmd, msg)` and never through `msgmap.res_key`.

**Status codes, from `.stock/assets/res/data/split/language.db`, table `language` (`id`, `content`, `desc`):**

| id | content | desc | used for |
|---|---|---|---|
| 0 | 成功 | 全模块 | success |
| 327937 | 金币不足 | 玩家 | not enough gold (gacha) |
| 327938 | 钻石不足 | 玩家 | not enough diamonds (gacha) |
| 327939 | 体力不足 | 玩家 | not enough energy; the one id the client names in code, `MMMsgDispatcher:autoHandleErrMsg` has `if status==327939 then --体力不足` |
| 328193 | 关卡未开启 | 关卡 | stage locked or unknown stage |
| 328194 | 关卡不可重复刷 | 关卡 | stage cannot be re-run |
| 328195 | 已经达到最大次数 | 关卡 | max plays reached |
| 328196 | 没有进入关卡 | 关卡 | a `LevelOutReq` with no matching `LevelIntoReq` |
| 328197 | 星级不够 | 关卡 | not enough stars for the chapter chest |
| 328202 | 达到关卡重置限制 | 女神 | stage reset limit, used to refuse `5_2207` |

**Client category constants, `ClientPlayer.lua:146-186`.** The same numbers are `ClientPrizeEntry.category`, `drop_base.drop_type` and `gacha_info.cost_type`: **1 gold, 2 energy, 9 diamond, 11 player xp, 12 hero xp, 13 angel xp, 20 item, 30 hero, 40 angel**.

**`ClientPlayer.PLAYER_FIELD_DIC`, `ClientPlayer.lua`, 48 entries, 1-based, in order:** `vip, vip_expires, paycount, xp, level, energy, max_energy, gold, diamond, login_month, login_flags, award_flags, last_level, last_elite, avatar, angel_money, arena_point, vvip1, battlefield_point, gold_trails_cooldown, login_award, vip_xp, paid_user, guild_id, nobility_level, nobility_exp, guild_money, toparena_money, artifact_smelt, gve_money, discount_money, cross_money, cross_rise_money, crusade_point, honor, signet_essence, signet_fight_cnt, card_master_gacha, card_master_points, magic_money, recharge_score, devil_money, star_soul_money, syb_money, gemstone_money, gemstone_prize_money, realname_check, pet_money`.

**Config rows this plan relies on.**

`stage_info.db:stage_info`, the five rows of chapter 1 (`chapter = 10000`), ordered by `idx`:

| entry | name | idx | once | energy | maxcount | group0 | group1 | group2 | unit_xp | angel_xp | visible_drops | invisible_drops | gold | player_xp | unlock_level | catalog | story_id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10000 | 飞鹰岗哨 | 1 | 0 | 6 | 0 | 100020 | 100021 | 0 | 20 | 20 | 10000 | 10005 | 516 | 6 | 1 | 2 | 1001 |
| 10010 | 战斧要塞1 | 2 | 1 | 6 | 0 | 100100 | 100101 | 0 | 21 | 21 | 10010 | 10015 | 516 | 6 | 1 | 1 | 1002 |
| 10012 | 战斧要塞 | 3 | 0 | 6 | 0 | 100120 | 100121 | 0 | 21 | 21 | 10012 | 10017 | 516 | 6 | 1 | 2 | 10021 |
| 10020 | 死亡矿洞1 | 4 | 1 | 6 | 0 | 100201 | 100202 | 0 | 22 | 22 | 10020 | 10025 | 518 | 6 | 1 | 1 | 0 |
| 10022 | 死亡矿洞 | 5 | 0 | 6 | 0 | 100220 | 100221 | 100222 | 22 | 22 | 10022 | 10027 | 518 | 6 | 1 | 3 | 1003 |

`chapter_info.db:chapter_info` row `entry = 10000`: `type = 1`, `name = 第一章-妖精之乡`, `idx = 1`, `star_req0 = 9`, `award0 = 600100`, `star_req1 = 0`, `award1 = 0`, `background = 1000`, `hero_req = 0`. The next two type-1 chapters are 11000 (`idx` 2, `star_req0` 15) and 12000 (`idx` 3). 306 rows in total.

`xp_for_level.db:xp_for_level`, 105 rows, `lvl` 1..105:

| lvl | player_xp_for_next_level | hero_xp_for_next_level | angel_xp_for_next_level | levelup_recovery_energy | max_energy | hero_max_level |
|---|---|---|---|---|---|---|
| 1 | 12 | 20 | 20 | 12 | 60 | 10 |
| 2 | 6 | 30 | 30 | 12 | 62 | 11 |
| 3 | 12 | 40 | 40 | 12 | 64 | 12 |

`variables.db:variables` (`key`, `value`, `memo`), the keys this plan reads:

| key | value | memo |
|---|---|---|
| HERO_FIRST_ENTRY | 100000 | 初始英雄编号 |
| HERO_GOLD_INIT | 1280000 | 初始金币数 |
| HERO_DIAMOND_INIT | 18888 | 初始钻石数 |
| PLAYER_ITEMS_INIT | 1100\|3,1200\|2 | 初始装备 |
| ENERGY_INIT | 60 | 初始体力 |
| ENERGY_MAX_INIT | 60 | 初始最大体力(经验表中要设成一样的值） |
| PLAYER_ENERGY_RECOVER_CYCLE | 360 | 体力回复周期（单位：秒） |
| PLAYER_ENERGY_RECOVER | 1 | 每个周期回复的体力值 |
| BT_CARD_AWARD | 100000\|950816,100100\|950811 | 特权卡每日奖励 |
| ANGEL_FIRST_ENTRY | *(empty string)* | 初始女神编号 |

`hero_info.db:hero_info` row `entry = 100000`: `name = 玫瑰骑士`, `star = 1`, `item = 100000`, `init_level = 1`, `quality = 0`, `break_level = 15`, `get_in_gacha = 1`. 77 rows.
`hero_quality.db:hero_quality`, hero 100000, three lowest qualities: quality 10 -> prototype 100000, quality 20 -> prototype 100010, quality 21 -> prototype 100020. **The lowest quality is 10; `hero_info.quality` reads 0 and is not a `hero_quality` key.**
`hero_growth.db:hero_growth` row (hero 100000, star 1): `star_up_cost 10`, `max_hp 40.92`, `power 5.346`, `magic 5.346`, `defence 3.564`, `magic_defence 3.3`, `agility 2.64`, `hit_base 0.33`, `duck_base 2.42`, `crit_base 0.55`, `crit_damage_base 0`, `tenacity_base 1.43`, `resistance_base 0`, `block_base 1.87`.
`npc_info.db:npc_info` row `entry = 100000`, the prototype of hero 100000 at quality 10: `name 玫瑰骑士`, `class 1`, `level 1`, `star 1`, `quality 10`, `attack_type 1`, `max_hp 100`, `power 15`, `defence 5`, `magic 15`, `magic_defence 5`, `agility 5`, `hit_base 0`, `duck_base 0`, `crit_base 0`, `crit_damage_base 0`, `block_base 0`, `tenacity_base 0`, `resistance_base 0`, `spell_damage_add_scale 0`, `treat_damage_add_scale 0`, `hit_rate 0.95`, `duck_rate 0`, `crit_rate 0`, `crit_damage_rate 0`, `block_rate 0`, `tenacity_rate 0`, `hp_recovery 0`, `rage_recovery 0`, `initial_energy 500`, `max_energy 1000`, `ability 1000`, `normal_attack_skill 100000`, `skill0 1000000`, `skill1..skill4 0`.

`gacha_info.db:gacha_info`, all 5 rows:

| entry | drop_id | cost_type | cost | free_cooldown_cycle | free_times | item | item_cost |
|---|---|---|---|---|---|---|---|
| 1200000 | 190000 | 1 | 20000 | 0 | 0 | 100 | 1 |
| 1300000 | 200000 | 1 | 180000 | 0 | 0 | 100 | 10 |
| 2400000 | 300000 | 9 | 2000 | 86400 | 1 | 0 | 0 |
| 2500000 | 400000 | 9 | 18880 | 0 | 0 | 0 | 0 |
| 3000000 | 0 | 9 | 5888 | 0 | 0 | 0 | 0 |

The tutorial draws 1200000 first (guide 10061 sits on the single-draw button of card 1, where `TavernBase.faceIDTable = {1200000, 1300000, 2400000, 2500000, 3000000, 0}` and `TavernFace:onBtnClick` sends `self.clientInfo[1].entry`) and 2400000 second (guide 10081, card 2). With the config starting gold of 1,280,000 and 18,888 diamonds, both are affordable.

**Drop chain, worked through for the rows the tests pin:**

- `drop_group.db:drop_group` columns are `(drop_group_id, drop_id, probability, frequency)`, 10,188 rows, INTEGER and NUMERIC. `drop_base.db:drop_base` columns are `(drop_base_id, drop_group_id, drop_type, item_id, amount, weight)`, 43,117 rows, INTEGER. `drop_base_2.db` carries **two** tables and the one to read is `drop_base_2`: 26,799 rows, every column TEXT, `drop_group_id` range 10,000,000 to 90,078,400.
- `drop_id = 10000` (stage 1-1 `visible_drops`) resolves to one group, `drop_group_id 10001, probability 1, frequency 1`, whose single `drop_base` row is `drop_base_id 106535, drop_type 20, item_id 10000, amount 2, weight 1`. `item_info` entry 10000 is 粗布头巾, class 1, quality 1 — equipment, which is exactly what guide step 10160 (哇~获得装备了耶！快让英雄穿上它！) expects to exist.
- `drop_id = 10005` (stage 1-1 `invisible_drops`) resolves to three groups: 3001 at probability 0.2 -> item 1050 amount 2; 4001 at 0.29 -> item 1100 amount 3; 5001 at 0.1 -> 12 equipment rows of amount 2, all weight 1.
- `drop_id = 190000` (gacha 1200000) resolves to one group, 190000 at probability 1, with **125** weighted `drop_base` rows: item 1000 w81, item 1010 w27, item 1020 w9, item 1030 w3, item 1040 w1, item 1100 amount 20 w160, item 1110 amount 6 w80, item 1120 amount 2 w40, then `drop_type 30` hero rows (100000, 101000, 102000, 103000 and more) at w10 each.
- `drop_id = 10000000` resolves to groups 10000000, 10000010, 10000020 and more, each at probability 1, and their rows live in `drop_base_2.db:drop_base_2` as TEXT: group 10000000 -> drop_type 9, amount 1128 (diamonds); group 10000010 -> drop_type 1, amount 600000 (gold); group 10000020 -> drop_type 20, item 1110, amount 20. This is the case that proves the 10,000,000 split is handled.
- `chapter_info.award0 = 600100` resolves to four groups, each at probability 1: 600110 -> drop_type 9 amount 600 (diamonds); 600120 -> item 104000 amount 6; 600130 -> drop_type 1 amount 60000 (gold); 600140 -> item 1100 amount 12. Chapter 1 chest is deterministic.
- `item_info.db:item_info` stores every column as TEXT (`entry` reads as the four characters 1,0,0,0 followed by 0 for 10000). SQLite TEXT affinity converts an integer parameter before the comparison, so either form matches; this plan passes `str(entry)` and says so in the code.

**`new_player_guide_info.db:new_player_guide_info`** (191 rows, ids 10000 to 14304, highest `is_over = 1` is 14302), the rows the tutorial walks and where each node is registered:

| id | nextid | jump_id | is_over | is_save | play_type | lua | node registered in |
|---|---|---|---|---|---|---|---|
| 10000 | 10010 | 0 | 0 | 0 | 1 | 0 | intro movie, `playStartMovie` |
| 10010 | 10025 | 0 | 0 | 0 | 2 | 0 | guide battle, `playFight`, client-only |
| 10041 | 10050 | 0 | 0 | 1 | 0 | 100001 | story script, the first `5_2041`, guide_id 10041 |
| 10050 | 10060 | 0 | 1 | 0 | 0 | 0 | `GameLeftToolsPanel.lua:121` tavern button |
| 10060 | 10061 | 0 | 1 | 0 | 0 | 0 | `TavernFg.lua:72` card 1 |
| 10061 | 10070 | 10071 | 1 | 1 | 0 | 0 | `TavernFace.lua:156` draw button, sends `5_2123 {gacha = 1200000}` |
| 10080 | 10081 | 0 | 1 | 0 | 0 | 0 | `TavernFg.lua:74` card 2 |
| 10081 | 10090 | 10100 | 1 | 1 | 0 | 0 | `TavernFace.lua:160` draw button, sends `5_2123 {gacha = 2400000}` |
| 10100 | 10101 | 0 | 0 | 0 | 0 | 0 | `TavernUI.lua:76` back button |
| 10110 | 10120 | 0 | 1 | 0 | 0 | 0 | `GameBottomToolsPanel.lua:155` campaign button |
| 10120 | 10130 | 0 | 0 | 0 | 0 | 0 | `LevelBuild.lua:45` stage node on the map |
| 10130 | 10140 | 0 | 0 | 0 | 0 | 0 | `DesSweepPanel.lua:253` enter button |
| 10140 | 10150 | 0 | 0 | 0 | 0 | 0 | `LineFrame.lua:442` one-key layout |
| 10150 | 10160 | 10100 | 1 | 1 | 0 | 0 | `LineFrame.lua:501` fight button, sends `LevelIntoReq` |
| 10160 | 10180 | 10160 | 1 | 1 | 0 | 0 | `BattleEndLayer.lua:1001` return button — the Plan B1 finish line |
| 10180 | 10190 | 0 | 1 | 0 | 0 | 0 | `GameRightToolsPanel.lua:151` hero panel — equip flow, Plan B2 |

`SHOW_NEW_GUIDE` is true on Android: `main.lua:237` sets it false, then line 250 sets it true for every platform that is not Windows, and `client/build_assets.py` does not patch it.

**Plan A code this plan extends. Read it before writing.**

- `server/net/server.py`: `fill_required(msg)`, `stub_response(registry, service, cmd, status=0)`, `Session(writer, peer, bound_port, district, player_id, data)` with `async send(service, cmd, msg, status=0)`, `Server(registry, settings, handlers, bind_host="0.0.0.0")`, `_on_frame`, and `_reply`, which calls `msgmap.res_key` and then `fill_required`.
- `server/db.py`: `SCHEMA` with the tables `players`, `heroes`, `angels`, `items`; `connect(path)`, `find_player(conn, username)`, `create_player(conn, username, nickname, guide_id)`.
- `server/modules/player.py`: `build_client_player(registry, row)`, `build_daily_stats(registry)`, `build_query_myself_res(registry, row)`, and `handlers(...)` holding `(5,2005)`, `(5,2317)`, `(5,2801)`, `(5,2943)`, `(153,2001)`, `(151,2041)`.
- `server/modules/login.py`: `handlers(...)` holding `(194,2001)`, `(3,2005)`, `(3,2015)`, `(3,2001)`, `(3,2003)`, `(3,2009)`; the inner `_player_id(sent_username)` creates the character on `3_2001`.
- `server/__main__.py:build_handlers(registry, settings)` opens the player DB and merges each module dict.
- `tests/test_server_core.py` exports the helpers every socket test reuses: the class `Client` (`connect`, `send`, `recv`, `close`), `_run_server(server)`, `_stop(task)`, and the `reg` and `settings` fixtures.
- `tools/fake_client.py`: `Conn.open/call/close`, `_login_body(reg, name, username)`, `replay(host, port, username, reg)`.

---

## File Structure

Every path is NEW unless marked MODIFY.

```
server/config/__init__.py       Config: read-only typed lookups over the stock split .db files
server/drops.py                 roll(cfg, drop_id, rng) -> list[Drop]; one pure function plus a dataclass
server/db.py             MODIFY levels + chapters tables, items unique index, energy_at column, repositories
server/net/server.py     MODIFY Session.outbox and its flush; zero-stub log wording
server/settings.py       MODIFY bind
server/__main__.py       MODIFY build_handlers wires Config and the five new modules, passes bind_host
server/modules/guide.py         5_2041
server/modules/hero.py          ClientHero builder from config
server/modules/item.py          ClientStock builder, grant and spend helpers
server/modules/notify.py        5_2008 player and item notifications, 5_2036, 5_2012
server/modules/gacha.py         5_2121, 5_2123
server/modules/level.py         5_2201, 5_2203, 5_2205, 5_2207, 5_2209
server/modules/player.py MODIFY heroes, inventory, levels, chapters, energy in QueryMyselfRes; real 5_2944
server/modules/login.py  MODIFY character creation grants the config starting kit
settings.toml            MODIFY [net] bind
.gitattributes                  text eol=lf
tools/fake_client.py     MODIFY --stage replays a chapter-1 fight
docs/dev-loop.md         MODIFY fresh-character and acceptance-run section
docs/TODO.md             MODIFY Plan B1 done, Plan B2 next
tests/test_config.py     tests/test_drops.py   tests/test_guide.py   tests/test_hero.py
tests/test_item.py       tests/test_notify.py  tests/test_gacha.py   tests/test_level.py
tests/test_player.py  MODIFY    tests/test_login.py MODIFY   tests/test_settings.py MODIFY
tests/test_server_core.py MODIFY tests/test_db.py MODIFY     tests/test_fake_client.py MODIFY
```

## Task order and what may run in parallel

| wave | tasks | why they are safe together |
|---|---|---|
| 1 | **T1** and **T2** | disjoint files: T1 touches settings/server core/gitattributes, T2 only adds `server/config/` |
| 2 | **T4 -> T3** in order, with **T10** in parallel | pre-flight ruling 23-10-2026: T3 and T4 both edit `server/__main__.py:build_handlers`, and T4 changes `player.handlers` to the four-argument form that T3's combined-server test must then use; T10 touches `drops.py` only |
| 3 | **T5 -> T6 -> T7 -> T8** strictly in order (all touch `db.py` and `player.py`), with **T9** in parallel (only `net/server.py` and `notify.py`) |
| 4 | **T11** after T6, T7, T8, T9, T10 (it consumes `item.grant_prizes` from T8) |
| 5 | **T12 -> T13 -> T14 -> T15** strictly in order (all touch `level.py`, `db.py`, `player.py`) |
| 6 | **T16**, then **T17** last |

T17 is the emulator acceptance run and must be the final task: it needs every handler in place.

---

### Task 1: Plan A parked items — `[net] bind`, `.gitattributes`, the zero-stub log wording

**Files:**
- Create: `.gitattributes`
- Modify: `settings.toml`, `server/settings.py`, `server/__main__.py:40-56`, `server/net/server.py:185-194`
- Test: `tests/test_settings.py`, `tests/test_server_core.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `server.settings.Settings` gains the field `bind: str` (after `host`, before `port`); `server.settings.load` reads `cfg["net"]["bind"]` with the default `"0.0.0.0"` when the key is absent, so an old `settings.toml` still loads. `server/__main__.py` constructs `Server(registry, settings, handlers, bind_host=settings.bind)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_load_reads_the_bind_address(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE.replace("port = 8112", "bind = \"0.0.0.0\"\nport = 8112"),
                   encoding="utf-8")
    assert load(cfg).bind == "0.0.0.0"


def test_bind_defaults_to_all_interfaces_when_absent(tmp_path: Path) -> None:
    """An older settings.toml must keep working: Plan A had no [net] bind key."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    assert load(cfg).bind == "0.0.0.0"
```

The existing `test_load_reads_every_field` builds `Settings` positionally nowhere, but `tests/test_server_core.py` and `tests/test_player.py` build it with keywords and one positional form. Update the positional call in `tests/test_player.py` (`Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)`) to pass `bind="127.0.0.1"` by keyword after `host`, or the new field lands in the wrong slot. Grep first: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa` and `grep -rn "Settings(" tests server`.

Add to `tests/test_server_core.py`:

```python
def test_unknown_id_with_a_paired_res_says_it_answers_a_stub(reg, settings, caplog) -> None:
    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        with caplog.at_level(logging.INFO, logger="loa.net"):
            await client.send(5, 2223)          # MailReceiveReq, paired with 5_2224
            frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2224)
        assert "answering a zero stub" in caplog.text
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_unknown_id_without_a_res_says_it_sends_nothing(reg, settings, caplog) -> None:
    """Review Focus 5 of Plan A, reworded: the log must not claim a stub it never sent."""
    async def scenario() -> None:
        server = Server(reg, settings, {}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        with caplog.at_level(logging.INFO, logger="loa.net"):
            await client.send(5, 2039)          # SyncRedPointReq, no paired Res
            await asyncio.sleep(0.2)
        assert "no paired Res exists, sending nothing" in caplog.text
        assert "answering a zero stub" not in caplog.text
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_settings.py tests/test_server_core.py --basetemp=C:/tmp/pytest-loa`
Expected: `AttributeError: 'Settings' object has no attribute 'bind'` and an assertion failure on the log text (today both branches log "answering a zero stub").

- [ ] **Step 3: Add `bind` to the settings dataclass and loader**

In `server/settings.py`, add `bind: str` to `Settings` directly after `host`, and in `load`:

```python
        host=cfg["net"]["host"],
        # The listening address. settings.host is the client-side address baked
        # into the APK (10.0.2.2 for the emulator) and cannot be bound here.
        bind=cfg["net"].get("bind", "0.0.0.0"),
```

- [ ] **Step 4: Add the key to `settings.toml`**

Under `[net]`, above `port`:

```toml
# The address the server listens on. Separate from host above, which is the
# client-side address: 10.0.2.2 is an emulator alias this PC cannot bind.
bind = "0.0.0.0"
```

- [ ] **Step 5: Pass it through `server/__main__.py`**

In `main`, replace `server = Server(registry, settings, build_handlers(registry, settings))` with:

```python
    server = Server(
        registry, settings, build_handlers(registry, settings), bind_host=settings.bind
    )
```

- [ ] **Step 6: Fix the zero-stub log wording in `server/net/server.py`**

Replace the `handler is None` block in `_on_frame` with:

```python
        handler = self.handlers.get(key)
        if handler is None:
            res = stub_response(self.registry, *key)
            if key not in self._logged_unknown:
                self._logged_unknown.add(key)
                if res is None:
                    log.info(
                        "no handler for %d_%d %s and no paired Res exists, "
                        "sending nothing", *key, name,
                    )
                else:
                    log.info(
                        "no handler for %d_%d %s, answering a zero stub", *key, name
                    )
            if res is not None:
                self.sent_unknown.add(key)
                await self._reply(session, key, res)
            return
```

- [ ] **Step 7: Write `.gitattributes`**

```gitattributes
* text=auto eol=lf
gradlew text eol=lf
*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
```

- [ ] **Step 8: Prove the attributes change nothing already committed**

Run, in Git Bash from the repo root:

```bash
git add .gitattributes
git status --porcelain
git ls-files --eol client/android/gradlew client/build_assets.py server/__main__.py
```

Expected: `git status --porcelain` lists only the files this task edited, no surprise modifications, and `--eol` reports `i/lf` for each path. **Do not run `git add --renormalize`**: if `git status` shows files this task did not touch, stop and report it instead; a mass line-ending rewrite is not part of this task.

- [ ] **Step 9: Run the full suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: 98 Plan A tests plus 4 new ones pass, nothing skipped.

- [ ] **Step 10: Commit**

```bash
git add .gitattributes settings.toml server/settings.py server/__main__.py \
        server/net/server.py tests/test_settings.py tests/test_server_core.py \
        tests/test_player.py
git commit -m "chore(server): [net] bind key, eol=lf attributes and an honest zero-stub log line"
```

**Done looks like:** `py -3.14 -m server` logs `listening on 0.0.0.0:8112`, the suite is green, `.gitattributes` is committed and `git status` is clean.

---

### Task 2: `server/config/` — read-only typed lookups over the stock tables

**Files:**
- Create: `server/config/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `server.settings.Settings.stock_dir`.
- Produces: `server.config.Config` with the classmethod `load(stock_dir: Path) -> Config` and these methods, each returning an `sqlite3.Row` or `None` unless stated: `stage(entry)`, `stages_in_chapter(chapter) -> list[Row]`, `next_stage(entry) -> int`, `first_stage(chapter_type=1) -> int`, `chapter(entry)`, `chapters_of_type(type_) -> list[Row]`, `hero(entry)`, `hero_qualities(hero) -> list[Row]`, `hero_growth(hero, star)`, `npc(entry)`, `item(entry)`, `xp_for_level(lvl)`, `variable(key) -> str or None`, `variable_int(key, default) -> int`, `gacha(entry)`, `gachas() -> list[Row]`, `guide(gid)`, `language(status) -> str or None`, `drop_groups(drop_id) -> list[Row]`, `drop_rows(drop_group_id) -> list[dict[str, int]]`, `conn(db_name)`, `close()`.

- [ ] **Step 1: Write the failing test `tests/test_config.py`, part 1 of 2**

```python
"""Config lookups against known rows of the stock tables (spec 3.1).

Every value asserted here was read out of .stock on 23-10-2026 and is quoted in
the plan. If one of these fails, the stock tree is not the one the plan read.
"""

from pathlib import Path

import pytest

from server.config import Config

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


def test_stage_one_one(cfg: Config) -> None:
    row = cfg.stage(10000)
    assert row["name"] == "飞鹰岗哨"
    assert int(row["chapter"]) == 10000
    assert int(row["energy"]) == 6
    assert int(row["gold"]) == 516
    assert int(row["player_xp"]) == 6
    assert int(row["unit_xp"]) == 20
    assert int(row["angel_xp"]) == 20
    assert int(row["visible_drops"]) == 10000
    assert int(row["invisible_drops"]) == 10005
    assert int(row["once"]) == 0
    assert int(row["maxcount"]) == 0
    assert int(row["catalog"]) == 2


def test_unknown_stage_is_none(cfg: Config) -> None:
    assert cfg.stage(999999) is None


def test_chapter_one_has_five_stages_in_idx_order(cfg: Config) -> None:
    assert [int(r["entry"]) for r in cfg.stages_in_chapter(10000)] == [
        10000, 10010, 10012, 10020, 10022
    ]


def test_next_stage_walks_the_chapter_then_the_next_chapter(cfg: Config) -> None:
    assert cfg.next_stage(10000) == 10010
    assert cfg.next_stage(10022) == int(cfg.stages_in_chapter(11000)[0]["entry"])
    assert cfg.first_stage() == 10000


def test_chapter_one(cfg: Config) -> None:
    row = cfg.chapter(10000)
    assert row["name"] == "第一章-妖精之乡"
    assert int(row["type"]) == 1
    assert int(row["idx"]) == 1
    assert int(row["star_req0"]) == 9
    assert int(row["award0"]) == 600100


def test_hero_100000_is_the_rose_knight(cfg: Config) -> None:
    assert cfg.hero(100000)["name"] == "玫瑰骑士"
    assert int(cfg.hero(100000)["star"]) == 1


def test_lowest_hero_quality_is_ten_not_the_hero_info_zero(cfg: Config) -> None:
    rows = cfg.hero_qualities(100000)
    assert int(rows[0]["quality"]) == 10
    assert int(rows[0]["prototype"]) == 100000
    assert int(cfg.hero(100000)["quality"]) == 0


def test_hero_growth_and_npc_rows(cfg: Config) -> None:
    growth = cfg.hero_growth(100000, 1)
    assert float(growth["max_hp"]) == 40.92
    assert float(growth["power"]) == 5.346
    npc = cfg.npc(100000)
    assert int(npc["max_hp"]) == 100
    assert float(npc["power"]) == 15
    assert int(npc["ability"]) == 1000
    assert int(npc["attack_type"]) == 1
    assert int(npc["normal_attack_skill"]) == 100000
    assert int(npc["skill0"]) == 1000000
    assert int(npc["skill1"]) == 0


def test_item_info_is_keyed_by_a_text_entry(cfg: Config) -> None:
    assert cfg.item(10000)["name"] == "粗布头巾"
    assert int(cfg.item(10000)["quality"]) == 1
    assert cfg.item(1100)["name"] == "小经验药水"
```

- [ ] **Step 2: Write the failing test `tests/test_config.py`, part 2 of 2 (same file, appended)**

```python
def test_xp_for_level(cfg: Config) -> None:
    one = cfg.xp_for_level(1)
    assert int(one["player_xp_for_next_level"]) == 12
    assert int(one["hero_xp_for_next_level"]) == 20
    assert int(one["levelup_recovery_energy"]) == 12
    assert int(one["max_energy"]) == 60
    assert int(one["hero_max_level"]) == 10
    assert int(cfg.xp_for_level(2)["max_energy"]) == 62


def test_variables(cfg: Config) -> None:
    assert cfg.variable("HERO_FIRST_ENTRY") == "100000"
    assert cfg.variable_int("HERO_GOLD_INIT", 0) == 1280000
    assert cfg.variable_int("HERO_DIAMOND_INIT", 0) == 18888
    assert cfg.variable("PLAYER_ITEMS_INIT") == "1100|3,1200|2"
    assert cfg.variable_int("PLAYER_ENERGY_RECOVER_CYCLE", 0) == 360
    assert cfg.variable_int("PLAYER_ENERGY_RECOVER", 0) == 1
    assert cfg.variable("BT_CARD_AWARD") == "100000|950816,100100|950811"
    assert cfg.variable("NO_SUCH_KEY") is None
    assert cfg.variable_int("NO_SUCH_KEY", 7) == 7


def test_gacha_rows(cfg: Config) -> None:
    row = cfg.gacha(1200000)
    assert int(row["drop_id"]) == 190000
    assert int(row["cost_type"]) == 1
    assert int(row["cost"]) == 20000
    assert int(cfg.gacha(2400000)["cost_type"]) == 9
    assert int(cfg.gacha(2400000)["cost"]) == 2000
    assert len(cfg.gachas()) == 5


def test_guide_rows(cfg: Config) -> None:
    assert int(cfg.guide(10160)["is_save"]) == 1
    assert int(cfg.guide(10160)["is_over"]) == 1
    assert int(cfg.guide(10010)["play_type"]) == 2


def test_language_texts_for_the_codes_this_plan_sends(cfg: Config) -> None:
    assert cfg.language(0) == "成功"
    assert cfg.language(327937) == "金币不足"
    assert cfg.language(327938) == "钻石不足"
    assert cfg.language(327939) == "体力不足"
    assert cfg.language(328193) == "关卡未开启"
    assert cfg.language(328196) == "没有进入关卡"
    assert cfg.language(328197) == "星级不够"
    assert cfg.language(328202) == "达到关卡重置限制"


def test_drop_chain_for_stage_one_one(cfg: Config) -> None:
    groups = cfg.drop_groups(10000)
    assert [(int(g["drop_group_id"]), float(g["probability"])) for g in groups] == [
        (10001, 1.0)
    ]
    assert cfg.drop_rows(10001) == [
        {"drop_type": 20, "item_id": 10000, "amount": 2, "weight": 1}
    ]


def test_drop_chain_reads_drop_base_2_above_the_split(cfg: Config) -> None:
    assert cfg.drop_rows(10000000) == [
        {"drop_type": 9, "item_id": 0, "amount": 1128, "weight": 1}
    ]
    assert cfg.drop_rows(10000010) == [
        {"drop_type": 1, "item_id": 0, "amount": 600000, "weight": 1}
    ]


def test_gacha_drop_group_is_weighted(cfg: Config) -> None:
    rows = cfg.drop_rows(190000)
    assert len(rows) == 125
    assert rows[0] == {"drop_type": 20, "item_id": 1000, "amount": 1, "weight": 81}
    assert any(r["drop_type"] == 30 and r["item_id"] == 100000 for r in rows)


def test_chapter_one_chest_is_deterministic(cfg: Config) -> None:
    groups = cfg.drop_groups(600100)
    assert [int(g["drop_group_id"]) for g in groups] == [600110, 600120, 600130, 600140]
    assert all(float(g["probability"]) == 1.0 for g in groups)
    assert cfg.drop_rows(600110) == [
        {"drop_type": 9, "item_id": 0, "amount": 600, "weight": 1}
    ]


def test_the_stock_tree_cannot_be_written_to(cfg: Config) -> None:
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        cfg.conn("variables").execute("UPDATE variables SET value = 1")
```

- [ ] **Step 3: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_config.py --basetemp=C:/tmp/pytest-loa`
Expected: a collection error, `ModuleNotFoundError: No module named server.config`.

- [ ] **Step 4: Write `server/config/__init__.py`, part 1: connections and helpers**

```python
"""Read-only typed lookups over the client config tables (spec 3.1).

The stock .db files under .stock/assets/res/data/split are the single source of
truth for game data; nothing is copied or converted. Every connection is opened
mode=ro, one per .db file, lazily, and kept for the process lifetime.

Table and column names interpolated into the SQL below are literals from this
module, never request data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SPLIT_RELPATH = Path("assets/res/data/split")

# DataManager.DROP_BASE_SPLIT, DataManager.lua:14. Groups at or above this id
# live in drop_base_2.db, table drop_base_2, whose columns are TEXT.
DROP_BASE_SPLIT = 10_000_000


class Config:
    def __init__(self, split_dir: Path) -> None:
        self.split_dir = Path(split_dir)
        self._conns: dict[str, sqlite3.Connection] = {}

    @classmethod
    def load(cls, stock_dir: Path) -> "Config":
        return cls(Path(stock_dir) / SPLIT_RELPATH)

    def conn(self, db_name: str) -> sqlite3.Connection:
        cached = self._conns.get(db_name)
        if cached is None:
            path = (self.split_dir / f"{db_name}.db").resolve()
            # A sqlite URI needs forward slashes even on Windows.
            cached = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            cached.row_factory = sqlite3.Row
            self._conns[db_name] = cached
        return cached

    def close(self) -> None:
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()

    def _one(self, db: str, table: str, column: str, value):
        return self.conn(db).execute(
            f"SELECT * FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()

    def _all(self, db: str, table: str, where: str, params: tuple) -> list:
        return list(self.conn(db).execute(f"SELECT * FROM {table} {where}", params))
```

- [ ] **Step 5: `server/config/__init__.py`, part 2: stages, chapters and the stage walk (same class)**

```python
    # --- stages and chapters ------------------------------------------------
    def stage(self, entry: int):
        return self._one("stage_info", "stage_info", "entry", int(entry))

    def stages_in_chapter(self, chapter: int) -> list:
        return self._all(
            "stage_info", "stage_info",
            "WHERE chapter = ? ORDER BY CAST(idx AS INTEGER)", (int(chapter),),
        )

    def chapter(self, entry: int):
        return self._one("chapter_info", "chapter_info", "entry", int(entry))

    def chapters_of_type(self, type_: int = 1) -> list:
        return self._all(
            "chapter_info", "chapter_info",
            "WHERE type = ? ORDER BY CAST(idx AS INTEGER)", (int(type_),),
        )

    def first_stage(self, chapter_type: int = 1) -> int:
        """LevelManager.comEntryTable[1][1]: first stage of the first chapter."""
        chapters = self.chapters_of_type(chapter_type)
        return int(self.stages_in_chapter(int(chapters[0]["entry"]))[0]["entry"])

    def next_stage(self, entry: int) -> int:
        """LevelManager:readStageInfo nextLevel: the next idx in this chapter,
        else the first stage of the next chapter of the same type, else itself.
        """
        row = self.stage(entry)
        if row is None:
            return int(entry)
        chapter_entry = int(row["chapter"])
        siblings = [int(r["entry"]) for r in self.stages_in_chapter(chapter_entry)]
        here = siblings.index(int(entry))
        if here + 1 < len(siblings):
            return siblings[here + 1]
        chapter_row = self.chapter(chapter_entry)
        if chapter_row is None:
            return int(entry)
        entries = [int(c["entry"]) for c in self.chapters_of_type(int(chapter_row["type"]))]
        at = entries.index(chapter_entry)
        for following in entries[at + 1:]:
            stages = self.stages_in_chapter(following)
            if stages:
                return int(stages[0]["entry"])
        return int(entry)
```

- [ ] **Step 6: `server/config/__init__.py`, part 3: heroes, items, variables, text, drops (same class)**

```python
    # --- heroes -------------------------------------------------------------
    def hero(self, entry: int):
        return self._one("hero_info", "hero_info", "entry", int(entry))

    def hero_qualities(self, hero: int) -> list:
        return self._all(
            "hero_quality", "hero_quality",
            "WHERE hero = ? ORDER BY CAST(quality AS INTEGER)", (int(hero),),
        )

    def hero_growth(self, hero: int, star: int):
        rows = self._all(
            "hero_growth", "hero_growth", "WHERE hero = ? AND star = ?",
            (int(hero), int(star)),
        )
        return rows[0] if rows else None

    def npc(self, entry: int):
        return self._one("npc_info", "npc_info", "entry", int(entry))

    # --- items, levels, variables, text -------------------------------------
    def item(self, entry: int):
        # item_info stores every column as TEXT.
        return self._one("item_info", "item_info", "entry", str(int(entry)))

    def xp_for_level(self, lvl: int):
        return self._one("xp_for_level", "xp_for_level", "lvl", int(lvl))

    def variable(self, key: str):
        row = self._one("variables", "variables", "key", key)
        return None if row is None else str(row["value"])

    def variable_int(self, key: str, default: int) -> int:
        raw = self.variable(key)
        if raw is None or raw == "":
            return default
        return int(float(raw))

    def gacha(self, entry: int):
        return self._one("gacha_info", "gacha_info", "entry", int(entry))

    def gachas(self) -> list:
        return self._all("gacha_info", "gacha_info", "ORDER BY entry", ())

    def guide(self, gid: int):
        return self._one("new_player_guide_info", "new_player_guide_info", "id", int(gid))

    def language(self, status: int):
        row = self._one("language", "language", "id", int(status))
        return None if row is None else str(row["content"])

    # --- drops --------------------------------------------------------------
    def drop_groups(self, drop_id: int) -> list:
        """DataManager:getDropBaseAry step 1: a drop id to its groups."""
        return self._all(
            "drop_group", "drop_group",
            "WHERE drop_id = ? ORDER BY drop_group_id", (int(drop_id),),
        )

    def drop_rows(self, drop_group_id: int) -> list[dict[str, int]]:
        """Step 2, with the drop_base_2 split. drop_base_2 stores TEXT, so both
        the parameter and every value are cast."""
        group = int(drop_group_id)
        db = table = "drop_base"
        param = group
        if group >= DROP_BASE_SPLIT:
            db = table = "drop_base_2"
            param = str(group)
        rows = self.conn(db).execute(
            f"SELECT drop_type, item_id, amount, weight FROM {table} "
            "WHERE drop_group_id = ? ORDER BY CAST(drop_base_id AS INTEGER)",
            (param,),
        )
        return [
            {
                "drop_type": int(r["drop_type"]),
                "item_id": int(r["item_id"]),
                "amount": int(r["amount"]),
                "weight": int(r["weight"]),
            }
            for r in rows
        ]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_config.py --basetemp=C:/tmp/pytest-loa`
Expected: `21 passed`. A `sqlite3.OperationalError: unable to open database file` means `.stock/` was never extracted; run `py -3.14 tools/extract_stock.py` first.

- [ ] **Step 8: Commit**

```bash
git add server/config/__init__.py tests/test_config.py
git commit -m "feat(server): read-only config layer over the client split .db tables"
```

**Done looks like:** `Config.load(Path(".stock")).stage(10000)` returns the 飞鹰岗哨 row, a write against any config connection raises `sqlite3.OperationalError`, and the 21 config tests pass.

---

### Task 3: `5_2041 SaveGuideIdReq` — the tutorial stops replaying

**Files:**
- Create: `server/modules/guide.py`, `tests/test_guide.py`
- Modify: `server/db.py` (add `set_guide_id`), `server/__main__.py:40-45` (register the module)
- Test: `tests/test_guide.py`

**Interfaces:**
- Consumes: `server.db.find_player`, `Session.player_id`, `settings.username`.
- Produces: `server.db.set_guide_id(conn, player_id, guide_id) -> None`; `server.modules.guide.handlers(registry, settings, conn) -> {(5, 2041): save_guide_id}`.
- Note for later tasks: `QueryMyselfRes.player.guide_id` is already wired in `build_client_player`, so persisting the column is the whole feature.

- [ ] **Step 1: Write the failing test `tests/test_guide.py`**

```python
"""5_2041 SaveGuideIdReq: the guide id the client saves must survive a restart.

NewGuideManager sends this at four sites (NewGuideManager.lua:234, 331, 404, 725)
and it is the only request the new-player guide makes. RPGGame:init (RPGGame.lua:78)
opens the main scene directly when player.guide_id is not 0, so persisting this
value is exactly what stops the tutorial replaying.
"""

import asyncio
from pathlib import Path

import pytest

from server.db import connect, create_player, find_player
from server.modules import guide, player
from server.net.registry import Registry
from server.net.server import Server
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind=BIND, port=0, username="stefan", guide_id=0,
    )


def test_save_guide_id_persists_and_answers_status_zero(reg, settings) -> None:
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)

    async def scenario() -> None:
        handlers = {}
        handlers.update(guide.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))
        server = Server(reg, settings, handlers, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        body = reg.message_class("SaveGuideIdReq")(guide_id=10041).SerializeToString()
        await client.send(5, 2041, body)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2042)
        res = reg.message_class("SaveGuideIdRes")()
        res.ParseFromString(frame.body)
        assert res.status == 0
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
    assert int(find_player(conn, "stefan")["guide_id"]) == 10041


def test_a_later_guide_id_overwrites_an_earlier_one(reg, settings) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    from server.db import set_guide_id
    set_guide_id(conn, pid, 10041)
    set_guide_id(conn, pid, 10160)
    assert int(find_player(conn, "stefan")["guide_id"]) == 10160


def test_query_myself_reports_the_saved_guide_id(reg, settings) -> None:
    """The client seeds NewGuideManager from QueryMyselfRes.player.guide_id."""
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    from server.db import set_guide_id
    set_guide_id(conn, pid, 10160)
    res = player.build_query_myself_res(reg, find_player(conn, "stefan"))
    assert res.player.guide_id == 10160
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_guide.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.guide`. If instead it errors on `Settings(... bind=...)`, Task 1 was skipped.

- [ ] **Step 3: Add `set_guide_id` to `server/db.py`**

```python
def set_guide_id(conn: sqlite3.Connection, player_id: int, guide_id: int) -> None:
    conn.execute(
        "UPDATE players SET guide_id = ? WHERE id = ?", (int(guide_id), int(player_id))
    )
    conn.commit()
```

- [ ] **Step 4: Write `server/modules/guide.py`**

```python
"""The new-player guide: 5_2041 SaveGuideIdReq.

The guide sends nothing else. NewGuideManager:check reads
g_roleData.player.guide_id, follows that row jump_id when it has one, and
resumes there, so this one column is what makes the tutorial run once.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.net.registry import Registry
from server.net.server import Handler, Session
from server.settings import Settings

log = logging.getLogger("loa.guide")


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection
) -> dict[tuple[int, int], Handler]:
    def save_guide_id(session: Session, req):
        player_id = session.player_id
        if player_id is None:
            row = db.find_player(conn, settings.username)
            player_id = None if row is None else int(row["id"])
        if player_id is None:
            log.warning("5_2041 guide_id %d before any character exists", req.guide_id)
            return registry.message_class("SaveGuideIdRes")(status=1)
        db.set_guide_id(conn, player_id, int(req.guide_id))
        log.info("guide_id %d saved for player %d", req.guide_id, player_id)
        return registry.message_class("SaveGuideIdRes")(status=0)

    return {(5, 2041): save_guide_id}
```

- [ ] **Step 5: Register it in `server/__main__.py`**

```python
from server.modules import guide, login, player
...
    handlers.update(login.handlers(registry, settings, conn))
    handlers.update(player.handlers(registry, settings, conn))
    handlers.update(guide.handlers(registry, settings, conn))
```

- [ ] **Step 6: Run the tests**

Run: `py -3.14 -m pytest -q tests/test_guide.py --basetemp=C:/tmp/pytest-loa`
Expected: `3 passed`. Then the whole suite: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`.

- [ ] **Step 7: Commit**

```bash
git add server/modules/guide.py server/db.py server/__main__.py tests/test_guide.py
git commit -m "feat(server): persist the new-player guide id (5_2041)"
```

**Done looks like:** a `5_2041` from the client updates `players.guide_id`, the paired `5_2042` carries `status = 0`, and a fresh `QueryMyselfRes` reports the saved id. The emulator proof is in Task 17.

---

### Task 4: `5_2944 QueryBtCardRecordRes` with the real privilege cards

**Files:**
- Modify: `server/modules/player.py` (the `bt_cards` handler, plus a `cfg` parameter on `handlers`), `server/__main__.py` (pass `cfg`)
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: `server.config.Config.variable("BT_CARD_AWARD")`.
- Produces: `server.modules.player.handlers(registry, settings, conn, cfg)` — **the signature grows by one positional parameter `cfg: Config`**, and `build_bt_cards(registry, cfg) -> QueryBtCardRecordRes`. Every later task that touches `player.handlers` uses the four-argument form.

- [ ] **Step 1: Write the failing test, appended to `tests/test_player.py`**

```python
def test_bt_cards_carries_both_privilege_cards(reg) -> None:
    """Review Focus 5: RoleData:updateRechangeCardsList does for i = 1,#data
    over btCards, and RechangeCardPanel builds its boxes from the same
    variables.db key, so the entries must be 100000 and 100100 in that order."""
    from server.config import Config
    from server.modules.player import build_bt_cards

    cfg = Config.load(STOCK)
    res = build_bt_cards(reg, cfg)
    assert [c.entry for c in res.btCards] == [100000, 100100]
    assert [c.isActivation for c in res.btCards] == [False, False]
    assert [c.isAward for c in res.btCards] == [False, False]
    res.SerializeToString()
    cfg.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_player.py -k bt_cards --basetemp=C:/tmp/pytest-loa`
Expected: `ImportError: cannot import name build_bt_cards`.

- [ ] **Step 3: Implement it in `server/modules/player.py`**

Add the import `from server.config import Config`, then:

```python
def build_bt_cards(registry: Registry, cfg: Config):
    """variables.BT_CARD_AWARD is 100000|950816,100100|950811: entry|drop_id per
    privilege card. RechangeCardPanel:_init builds its reward boxes from exactly
    that key, and RoleData:updateRechangeCardsList measures the repeated field
    with #, so both entries are always sent, owned by nobody yet."""
    res = registry.message_class("QueryBtCardRecordRes")()
    raw = cfg.variable("BT_CARD_AWARD") or ""
    for part in (p for p in raw.split(",") if p):
        entry = int(part.split("|")[0])
        card = res.btCards.add()
        card.entry = entry
        card.isActivation = False
        card.isAward = False
    fill_required(res)
    return res
```

Change the module signature to `def handlers(registry, settings, conn, cfg):` and the handler to:

```python
    def bt_cards(session: Session, req):
        return build_bt_cards(registry, cfg)
```

- [ ] **Step 4: Pass the config in `server/__main__.py`**

```python
from server.config import Config
...
def build_handlers(registry: Registry, settings) -> dict:
    conn = db.connect(settings.db_path)
    cfg = Config.load(settings.stock_dir)
    handlers: dict = {}
    handlers.update(login.handlers(registry, settings, conn))
    handlers.update(player.handlers(registry, settings, conn, cfg))
    handlers.update(guide.handlers(registry, settings, conn))
    return handlers
```

- [ ] **Step 5: Update the other callers of `player.handlers`**

Grep and fix: `grep -rn "player.handlers(" tests server`. `tests/test_player.py` and `tests/test_guide.py` both build it; pass a module-scoped `Config.load(STOCK)` fixture.

- [ ] **Step 6: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green, with one new test.

- [ ] **Step 7: Commit**

```bash
git add server/modules/player.py server/__main__.py tests/test_player.py tests/test_guide.py
git commit -m "fix(server): 5_2944 answers with the two real privilege cards"
```

**Done looks like:** `5_2944` returns two `BtCardInfo` rows, so `RoleData:updateRechangeCardsList` has a list to measure instead of nil.

---

### Task 5: energy — `max_energy` from `xp_for_level`, regeneration from `variables`

**Files:**
- Modify: `server/db.py` (the `energy_at` column, `ensure_columns`, `refresh_energy`, `spend_energy`, `add_energy`), `server/modules/player.py` (`build_client_player` takes `cfg`)
- Test: `tests/test_db.py`, `tests/test_player.py`

**Interfaces:**
- Consumes: `Config.xp_for_level`, `Config.variable_int`.
- Produces, all in `server/db.py`:
  - `ensure_columns(conn) -> None`, called from `connect`, adding `players.energy_at INTEGER NOT NULL DEFAULT 0` when it is missing.
  - `refresh_energy(conn, cfg, row, now=None) -> sqlite3.Row` — recomputes `max_energy` from `xp_for_level(level).max_energy`, adds `PLAYER_ENERGY_RECOVER` per whole `PLAYER_ENERGY_RECOVER_CYCLE` elapsed since `energy_at`, clamps at `max_energy`, writes back and returns the fresh row.
  - `spend_energy(conn, player_id, amount) -> None` and `add_energy(conn, cfg, player_id, amount) -> None`.
- `build_client_player(registry, row)` keeps its signature; the refresh happens before it is called, in the `5_2005` handler and in the level handlers.

- [ ] **Step 1: Write the failing tests, appended to `tests/test_db.py`**

```python
def test_energy_at_column_is_added_to_an_old_database(tmp_path) -> None:
    """Additive migration only: a Plan A player.db must open and keep its row."""
    import sqlite3
    from server.db import PLAN_A_SCHEMA_PROBE, connect, create_player, find_player

    path = tmp_path / "player.db"
    raw = sqlite3.connect(path)
    raw.executescript(PLAN_A_SCHEMA_PROBE)
    raw.execute(
        "INSERT INTO players (username, nickname, guide_id, created_at)"
        " VALUES (?, ?, ?, ?)", ("stefan", "stefan", 10041, "2026-10-21T00:00:00+00:00"),
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    row = find_player(conn, "stefan")
    assert int(row["guide_id"]) == 10041
    assert int(row["energy_at"]) == 0


def test_refresh_energy_regenerates_one_per_360_seconds(tmp_path) -> None:
    from server.config import Config
    from server.db import connect, create_player, find_player, refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET energy = 40, energy_at = 1000 WHERE id = ?", (pid,)
    )
    conn.commit()

    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=1000 + 3 * 360)
    assert int(row["energy"]) == 43
    assert int(row["energy_at"]) == 1000 + 3 * 360
    # The remainder of a cycle is not thrown away.
    row = refresh_energy(conn, cfg, row, now=1000 + 3 * 360 + 359)
    assert int(row["energy"]) == 43
    assert int(row["energy_at"]) == 1000 + 3 * 360
    cfg.close()


def test_refresh_energy_clamps_at_the_level_cap(tmp_path) -> None:
    from server.config import Config
    from server.db import connect, create_player, find_player, refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET energy = 59, energy_at = 0 WHERE id = ?", (pid,))
    conn.commit()
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=100_000)
    assert int(row["energy"]) == 60          # xp_for_level lvl 1 max_energy
    assert int(row["max_energy"]) == 60
    cfg.close()


def test_max_energy_follows_the_player_level(tmp_path) -> None:
    from server.config import Config
    from server.db import connect, create_player, find_player, refresh_energy

    cfg = Config.load(STOCK)
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute("UPDATE players SET level = 3 WHERE id = ?", (pid,))
    conn.commit()
    row = refresh_energy(conn, cfg, find_player(conn, "stefan"), now=0)
    assert int(row["max_energy"]) == 64      # xp_for_level lvl 3
    cfg.close()
```

`STOCK = Path(".stock")` already exists at the top of `tests/test_db.py`; add it if not.

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_db.py --basetemp=C:/tmp/pytest-loa`
Expected: `ImportError: cannot import name PLAN_A_SCHEMA_PROBE` / `refresh_energy`.

- [ ] **Step 3: Implement the migration and the energy helpers in `server/db.py`**

Add near `SCHEMA`:

```python
# The Plan A schema exactly as it shipped, for the migration test only. Keep it
# frozen: it is the shape a real player.db on disk has before this plan runs.
PLAN_A_SCHEMA_PROBE = """
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    nickname   TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    gold       INTEGER NOT NULL DEFAULT 0,
    diamond    INTEGER NOT NULL DEFAULT 0,
    vip        INTEGER NOT NULL DEFAULT 0,
    energy     INTEGER NOT NULL DEFAULT 60,
    max_energy INTEGER NOT NULL DEFAULT 60,
    avatar     INTEGER NOT NULL DEFAULT 0,
    guide_id   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
"""

# Columns added after Plan A. ALTER TABLE ADD COLUMN only, never a rebuild.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("players", "energy_at", "INTEGER NOT NULL DEFAULT 0"),
    ("players", "last_level", "INTEGER NOT NULL DEFAULT 0"),
)


def ensure_columns(conn: sqlite3.Connection) -> None:
    for table, column, decl in ADDED_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()
```

`last_level` is added here with `energy_at` so the migration happens once; Task 12 is the task that uses it.

In `connect`, after `conn.executescript(SCHEMA)` and its commit, call `ensure_columns(conn)`.

Then the energy helpers:

```python
def refresh_energy(conn, cfg, row, now: int | None = None):
    """Lazy regeneration. variables.PLAYER_ENERGY_RECOVER (1) energy per
    PLAYER_ENERGY_RECOVER_CYCLE (360 s), capped at xp_for_level(level).max_energy.
    The client reads the same two keys for its own notification
    (MyGroupInfoData.lua:131-146); xp_for_level.levelup_recovery_energy is the
    level-up bonus, not the regen rate.
    """
    now = int(time.time()) if now is None else int(now)
    cycle = cfg.variable_int("PLAYER_ENERGY_RECOVER_CYCLE", 360)
    per_cycle = cfg.variable_int("PLAYER_ENERGY_RECOVER", 1)
    level_row = cfg.xp_for_level(int(row["level"]))
    max_energy = int(level_row["max_energy"]) if level_row else int(row["max_energy"])
    energy = int(row["energy"])
    energy_at = int(row["energy_at"]) or now
    cycles = 0 if cycle <= 0 else max(0, (now - energy_at) // cycle)
    if energy < max_energy and cycles:
        energy = min(max_energy, energy + cycles * per_cycle)
        energy_at = energy_at + cycles * cycle
    if energy >= max_energy:
        energy = max_energy
        energy_at = now
    conn.execute(
        "UPDATE players SET energy = ?, max_energy = ?, energy_at = ? WHERE id = ?",
        (energy, max_energy, energy_at, int(row["id"])),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
    ).fetchone()


def spend_energy(conn, player_id: int, amount: int) -> None:
    conn.execute(
        "UPDATE players SET energy = MAX(0, energy - ?) WHERE id = ?",
        (int(amount), int(player_id)),
    )
    conn.commit()


def add_energy(conn, cfg, player_id: int, amount: int) -> None:
    row = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    level_row = cfg.xp_for_level(int(row["level"]))
    cap = int(level_row["max_energy"]) if level_row else int(row["max_energy"])
    conn.execute(
        "UPDATE players SET energy = MIN(?, energy + ?) WHERE id = ?",
        (cap, int(amount), int(player_id)),
    )
    conn.commit()
```

Add `import time` at the top of `server/db.py`.

- [ ] **Step 4: Refresh the energy in the `5_2005` handler**

In `server/modules/player.py`, inside `query_myself`, right after the row is fetched and `session.player_id` is set:

```python
        row = db.refresh_energy(conn, cfg, row)
```

- [ ] **Step 5: Pin it from the socket side, appended to `tests/test_player.py`**

```python
def test_query_myself_reports_the_regenerated_energy(reg, settings, cfg_fixture) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    conn.execute(
        "UPDATE players SET energy = 10, energy_at = 0 WHERE id = ?", (pid,)
    )
    conn.commit()
    handlers = player.handlers(reg, settings, conn, cfg_fixture)
    res = handlers[(5, 2005)](
        Session(writer=None, peer="t", bound_port=0), reg.message_class("QueryMyselfReq")()
    )
    assert res.player.energy == 60
    assert res.player.max_energy == 60
```

`Session(writer=None, ...)` is safe here: `query_myself` never writes to the socket, it only returns a message. Import `Session` from `server.net.server`.

- [ ] **Step 6: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green with 5 new tests.

- [ ] **Step 7: Commit**

```bash
git add server/db.py server/modules/player.py tests/test_db.py tests/test_player.py
git commit -m "feat(server): energy cap from xp_for_level and lazy regeneration from variables"
```

**Done looks like:** a Plan A `player.db` opens and gains `energy_at` and `last_level` without losing its row; a player at 40 energy and 18 minutes idle reads 43; a level-3 player caps at 64.

---

### Task 6: character creation grants the config starting kit

**Files:**
- Modify: `server/db.py` (`create_player` signature, `grant_hero`, `grant_item`, `heroes_of`, `items_of`), `server/modules/login.py` (`_player_id` grants the kit), `server/__main__.py` (login gets `cfg`)
- Test: `tests/test_login.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: `Config.variable`, `Config.variable_int`, `Config.hero_qualities`.
- Produces, in `server/db.py`:
  - `create_player(conn, username, nickname, guide_id, gold=0, diamond=0, energy=60, max_energy=60) -> int` — the four new parameters are keyword with defaults, so existing calls keep working.
  - `grant_hero(conn, player_id, entry, quality, star=1, level=1, xp=0) -> int` returning the hero row id; it adds a `quality` column to `heroes` through `ADDED_COLUMNS`.
  - `grant_item(conn, player_id, entry, amount) -> int` returning the new absolute amount, upserting on `(player_id, entry)`.
  - `heroes_of(conn, player_id) -> list[Row]`, `items_of(conn, player_id) -> list[Row]`.
  - A new `ADDED_COLUMNS` entry `("heroes", "quality", "INTEGER NOT NULL DEFAULT 0")` and `SCHEMA` gains `CREATE UNIQUE INDEX IF NOT EXISTS items_player_entry ON items(player_id, entry);`.
- `server/modules/login.py:handlers(registry, settings, conn, cfg)` — the signature grows by `cfg`.

- [ ] **Step 1: Write the failing tests, appended to `tests/test_login.py`**

```python
def test_a_fresh_character_gets_the_config_starting_kit(reg, settings) -> None:
    """variables.db, not invented numbers: HERO_GOLD_INIT 1280000,
    HERO_DIAMOND_INIT 18888, PLAYER_ITEMS_INIT 1100|3,1200|2,
    HERO_FIRST_ENTRY 100000 at its lowest hero_quality (10), ENERGY_INIT 60.
    LineFrame:startFight refuses to start a stage with no hero on the field,
    which is why the first hero is granted here and not by the gacha."""
    from server.config import Config
    from server.db import connect, find_player, heroes_of, items_of
    from server.modules import login

    cfg = Config.load(STOCK)
    conn = connect(settings.db_path)
    handlers = login.handlers(reg, settings, conn, cfg)
    body = reg.message_class("LoginReq")(
        username="stefan", token="local", datetime=1, args=["1"]
    )
    handlers[(3, 2001)](Session(writer=None, peer="t", bound_port=0), body)

    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000
    assert int(row["diamond"]) == 18888
    assert int(row["energy"]) == 60
    assert int(row["max_energy"]) == 60
    heroes = heroes_of(conn, int(row["id"]))
    assert [int(h["entry"]) for h in heroes] == [100000]
    assert int(heroes[0]["quality"]) == 10
    assert int(heroes[0]["star"]) == 1
    assert int(heroes[0]["level"]) == 1
    assert {int(i["entry"]): int(i["amount"]) for i in items_of(conn, int(row["id"]))} == {
        1100: 3, 1200: 2
    }
    cfg.close()


def test_logging_in_again_does_not_grant_the_kit_twice(reg, settings) -> None:
    from server.config import Config
    from server.db import connect, find_player, heroes_of, items_of
    from server.modules import login

    cfg = Config.load(STOCK)
    conn = connect(settings.db_path)
    handlers = login.handlers(reg, settings, conn, cfg)
    body = reg.message_class("LoginReq")(
        username="stefan", token="local", datetime=1, args=["1"]
    )
    session = Session(writer=None, peer="t", bound_port=0)
    handlers[(3, 2001)](session, body)
    handlers[(3, 2001)](session, body)

    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000
    assert len(heroes_of(conn, int(row["id"]))) == 1
    assert len(items_of(conn, int(row["id"]))) == 2
    cfg.close()
```

And appended to `tests/test_db.py`:

```python
def test_grant_item_adds_to_the_same_entry(tmp_path) -> None:
    from server.db import connect, create_player, grant_item, items_of

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    assert grant_item(conn, pid, 1100, 3) == 3
    assert grant_item(conn, pid, 1100, 2) == 5
    assert grant_item(conn, pid, 10000, 2) == 2
    assert {int(r["entry"]): int(r["amount"]) for r in items_of(conn, pid)} == {
        1100: 5, 10000: 2
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_login.py tests/test_db.py --basetemp=C:/tmp/pytest-loa`
Expected: `TypeError: handlers() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Extend `server/db.py`**

Add to `SCHEMA` (additive, runs on every open):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS items_player_entry ON items(player_id, entry);
```

Add `("heroes", "quality", "INTEGER NOT NULL DEFAULT 0")` to `ADDED_COLUMNS`, then:

```python
def create_player(
    conn: sqlite3.Connection,
    username: str,
    nickname: str,
    guide_id: int,
    gold: int = 0,
    diamond: int = 0,
    energy: int = 60,
    max_energy: int = 60,
) -> int:
    cur = conn.execute(
        "INSERT INTO players (username, nickname, guide_id, gold, diamond,"
        " energy, max_energy, energy_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            username, nickname, guide_id, int(gold), int(diamond),
            int(energy), int(max_energy), int(time.time()),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def grant_hero(
    conn: sqlite3.Connection,
    player_id: int,
    entry: int,
    quality: int,
    star: int = 1,
    level: int = 1,
    xp: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO heroes (player_id, entry, quality, star, level, xp)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (int(player_id), int(entry), int(quality), int(star), int(level), int(xp)),
    )
    conn.commit()
    return int(cur.lastrowid)


def grant_item(conn: sqlite3.Connection, player_id: int, entry: int, amount: int) -> int:
    """Upsert on (player_id, entry) and return the new absolute amount.

    The client keeps one ClientStock per item entry (RoleData:updateItemNum
    looks items up by entry), so the server does too.
    """
    conn.execute(
        "INSERT INTO items (player_id, entry, amount) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, entry) DO UPDATE SET amount = amount + ?",
        (int(player_id), int(entry), int(amount), int(amount)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT amount FROM items WHERE player_id = ? AND entry = ?",
        (int(player_id), int(entry)),
    ).fetchone()
    return int(row["amount"])


def heroes_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute("SELECT * FROM heroes WHERE player_id = ? ORDER BY id", (int(player_id),))
    )


def items_of(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute("SELECT * FROM items WHERE player_id = ? ORDER BY id", (int(player_id),))
    )
```

Note on the index: if a pre-existing `data/player.db` already holds two rows for one `(player_id, entry)` pair, `CREATE UNIQUE INDEX` raises. Plan A never wrote an items row, so this cannot happen on Stefan machine; if it ever does, the implementer reports it rather than deleting rows.

- [ ] **Step 4: Grant the kit in `server/modules/login.py`**

Change the signature to `def handlers(registry, settings, conn, cfg):`, add `from server.config import Config` and:

```python
def starting_kit(cfg: Config) -> dict:
    """Everything a fresh character owns, from variables.db."""
    items: list[tuple[int, int]] = []
    for part in (p for p in (cfg.variable("PLAYER_ITEMS_INIT") or "").split(",") if p):
        entry, _, amount = part.partition("|")
        items.append((int(entry), int(amount or 1)))
    hero_entry = cfg.variable_int("HERO_FIRST_ENTRY", 0)
    quality = 0
    if hero_entry:
        qualities = cfg.hero_qualities(hero_entry)
        # The lowest hero_quality row, not hero_info.quality: hero 100000 reads
        # quality 0 there, and a quality with no hero_quality row crashes
        # ClientHero:getNpcProperty on the client.
        quality = int(qualities[0]["quality"]) if qualities else 0
    return {
        "gold": cfg.variable_int("HERO_GOLD_INIT", 0),
        "diamond": cfg.variable_int("HERO_DIAMOND_INIT", 0),
        "energy": cfg.variable_int("ENERGY_INIT", 60),
        "max_energy": cfg.variable_int("ENERGY_MAX_INIT", 60),
        "hero_entry": hero_entry,
        "hero_quality": quality,
        "items": items,
    }
```

and replace the body of the inner `_player_id` after the `row is not None` early return with:

```python
        kit = starting_kit(cfg)
        player_id = db.create_player(
            conn, username, username, settings.guide_id,
            gold=kit["gold"], diamond=kit["diamond"],
            energy=kit["energy"], max_energy=kit["max_energy"],
        )
        if kit["hero_entry"]:
            db.grant_hero(
                conn, player_id, kit["hero_entry"], kit["hero_quality"], star=1, level=1
            )
        for entry, amount in kit["items"]:
            db.grant_item(conn, player_id, entry, amount)
        log.info(
            "created character %r as player id %d with hero %d, %d gold, %d diamonds",
            username, player_id, kit["hero_entry"], kit["gold"], kit["diamond"],
        )
        return player_id
```

- [ ] **Step 5: Pass `cfg` in `server/__main__.py`**

```python
    handlers.update(login.handlers(registry, settings, conn, cfg))
```

- [ ] **Step 6: Fix every other caller**

Run `grep -rn "login.handlers(" tests server tools` and pass a `Config` in each.

- [ ] **Step 7: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green. `tests/test_login.py` assertions that a fresh player has `gold = 0` have to change to 1280000 — that is the point of the task, not a regression.

- [ ] **Step 8: Commit**

```bash
git add server/db.py server/modules/login.py server/__main__.py \
        tests/test_login.py tests/test_db.py
git commit -m "feat(server): a fresh character gets the config starting kit (hero, gold, items)"
```

**Done looks like:** a brand-new `player.db` after one login holds one hero row (entry 100000, quality 10), two item rows (1100 x3, 1200 x2), 1,280,000 gold and 18,888 diamonds; a second login changes nothing.

---

### Task 7: `ClientHero` from config, and `QueryMyselfRes.heroes`

**Files:**
- Create: `server/modules/hero.py`, `tests/test_hero.py`
- Modify: `server/modules/player.py` (`build_query_myself_res` takes `cfg` and `conn`)
- Test: `tests/test_hero.py`, `tests/test_player.py`

**Interfaces:**
- Consumes: `Config.hero`, `Config.hero_qualities`, `Config.hero_growth`, `Config.npc`, `db.heroes_of`.
- Produces:
  - `server.modules.hero.build_client_hero_unit(registry, cfg, npc_row, growth_row, level) -> ClientHeroUnit`
  - `server.modules.hero.build_client_hero(registry, cfg, row) -> ClientHero` where `row` is a `heroes` table row.
  - `server.modules.hero.prototype_for(cfg, entry, quality) -> int`
  - `build_query_myself_res(registry, cfg, conn, row)` — **the signature grows by `cfg` and `conn`**, in that order, and every later task uses that form.

**Why these numbers.** `ClientHeroUnit` field names are column names of `npc_info` one for one (`max_hp`, `power`, `defence`, `magic`, `magic_defence`, `agility`, `hit_base`, `duck_base`, `crit_base`, `crit_damage_base`, `block_base`, `tenacity_base`, `resistance_base`, `spell_damage_add_scale`, `treat_damage_add_scale`, `hit_rate`, `duck_rate`, `crit_rate`, `crit_damage_rate`, `block_rate`, `tenacity_rate`, `hp_recovery`, `rage_recovery`, `initial_energy`, `max_energy`), so a level-1 hero is its prototype npc row verbatim. Levels above 1 add `hero_growth(hero, star)` once per level above the first, for the 13 columns that table carries. `ability` comes from `npc_info.ability`. `spells` are the prototype `skill0..skill4` non-zero (open question D).

- [ ] **Step 1: Write the failing test `tests/test_hero.py`**

```python
"""ClientHero built from hero_quality + npc_info + hero_growth, never invented."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_hero, heroes_of
from server.modules.hero import build_client_hero, prototype_for
from server.net.registry import Registry

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def hero_row(tmp_path, cfg):
    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_hero(conn, pid, 100000, 10, star=1, level=1)
    return heroes_of(conn, pid)[0]


def test_prototype_comes_from_hero_quality(cfg) -> None:
    assert prototype_for(cfg, 100000, 10) == 100000
    assert prototype_for(cfg, 100000, 20) == 100010


def test_client_hero_quality_exists_in_hero_quality(reg, cfg, hero_row) -> None:
    """Review Focus 2: ClientHero:getNpcProperty indexes npcList[1][key] with no
    nil check, so a quality with no hero_quality row kills the Lua VM."""
    hero = build_client_hero(reg, cfg, hero_row)
    assert hero.quality in {int(r["quality"]) for r in cfg.hero_qualities(100000)}
    assert cfg.npc(hero.prototype) is not None


def test_client_hero_level_one_is_the_prototype_row(reg, cfg, hero_row) -> None:
    hero = build_client_hero(reg, cfg, hero_row)
    assert hero.entry == 100000
    assert hero.prototype == 100000
    assert hero.quality == 10
    assert hero.star == 1
    assert hero.level == 1
    assert hero.xp == 0
    assert hero.ability == 1000
    assert hero.unit.max_hp == 100
    assert hero.unit.power == 15.0
    assert hero.unit.defence == 5.0
    assert hero.unit.hit_rate == 0.95
    assert hero.unit.initial_energy == 500.0
    assert hero.unit.max_energy == 1000.0
    assert hero.base_unit.max_hp == 100
    assert list(hero.spells) == [1000000]
    assert hero.SerializeToString()


def test_client_hero_level_three_adds_growth_twice(reg, cfg, tmp_path) -> None:
    conn = connect(tmp_path / "p.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_hero(conn, pid, 100000, 10, star=1, level=3)
    row = heroes_of(conn, pid)[0]
    hero = build_client_hero(reg, cfg, row)
    # npc 100 + 2 x hero_growth(100000, 1).max_hp 40.92 = 181.84, int for uint32
    assert hero.unit.max_hp == 181
    assert round(hero.unit.power, 3) == round(15 + 2 * 5.346, 3)


def test_every_required_field_is_set(reg, cfg, hero_row) -> None:
    """Review Focus 1 of Plan A: proto2 required fields raise at send time."""
    hero = build_client_hero(reg, cfg, hero_row)
    hero.SerializeToString()
    assert not hero.FindInitializationErrors()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_hero.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.hero`.

- [ ] **Step 3: Write `server/modules/hero.py`**

```python
"""ClientHero shapes, built from the client own hero tables.

Field names of ClientHeroUnit are npc_info column names one for one, so a
level-1 hero is its prototype npc row verbatim; each level above the first adds
one hero_growth(hero, star) row. hero_quality maps (hero, quality) to the
prototype npc entry, and ClientHero:getNpcProperty on the client does the same
lookup with no nil check, so quality must always be a hero_quality key.
"""

from __future__ import annotations

import logging
import sqlite3

from server.config import Config
from server.net.registry import Registry
from server.net.server import fill_required

log = logging.getLogger("loa.hero")

# ClientHeroUnit fields that exist as npc_info columns with the same name.
NPC_UNIT_FIELDS = (
    "max_hp", "power", "defence", "magic", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "block_base",
    "tenacity_base", "resistance_base", "spell_damage_add_scale",
    "treat_damage_add_scale", "hit_rate", "duck_rate", "crit_rate",
    "crit_damage_rate", "block_rate", "tenacity_rate", "hp_recovery",
    "rage_recovery", "initial_energy", "max_energy",
)

# The 13 columns hero_growth carries, added once per level above the first.
GROWTH_FIELDS = (
    "max_hp", "power", "magic", "defence", "magic_defence", "agility",
    "hit_base", "duck_base", "crit_base", "crit_damage_base", "tenacity_base",
    "resistance_base", "block_base",
)


def prototype_for(cfg: Config, entry: int, quality: int) -> int:
    rows = cfg.hero_qualities(entry)
    for row in rows:
        if int(row["quality"]) == int(quality):
            return int(row["prototype"])
    # Fall back to the lowest quality rather than send a prototype npc_info has
    # no row for, which crashes the client.
    log.warning(
        "hero %d has no hero_quality row for quality %d, using the lowest",
        entry, quality,
    )
    return int(rows[0]["prototype"]) if rows else 0


def build_client_hero_unit(registry: Registry, cfg: Config, npc_row, growth_row, level: int):
    msg = registry.message_class("ClientHeroUnit")()
    steps = max(0, int(level) - 1)
    for field in NPC_UNIT_FIELDS:
        value = float(npc_row[field] or 0)
        if growth_row is not None and field in GROWTH_FIELDS and steps:
            value += steps * float(growth_row[field] or 0)
        if field == "max_hp":
            msg.max_hp = int(value)
        else:
            setattr(msg, field, value)
    fill_required(msg)
    return msg


def build_client_hero(registry: Registry, cfg: Config, row: sqlite3.Row):
    entry = int(row["entry"])
    quality = int(row["quality"])
    star = int(row["star"])
    level = int(row["level"])
    prototype = prototype_for(cfg, entry, quality)
    npc_row = cfg.npc(prototype)
    growth_row = cfg.hero_growth(entry, star)
    msg = registry.message_class("ClientHero")(
        id=int(row["id"]),
        entry=entry,
        prototype=prototype,
        quality=quality,
        star=star,
        xp=int(row["xp"]),
        level=level,
        ability=int(npc_row["ability"] or 0),
    )
    msg.unit.CopyFrom(build_client_hero_unit(registry, cfg, npc_row, growth_row, level))
    msg.base_unit.CopyFrom(
        build_client_hero_unit(registry, cfg, npc_row, growth_row, level)
    )
    # BattleUnit:initByHeroData builds the hero active skills from this list and
    # its normal attack from the prototype row (open question D in the plan).
    for key in ("skill0", "skill1", "skill2", "skill3", "skill4"):
        spell = int(npc_row[key] or 0)
        if spell:
            msg.spells.append(spell)
    msg.model = 0
    msg.awaken = 0
    msg.max_level = level
    fill_required(msg)
    return msg
```

- [ ] **Step 4: Put the heroes into `QueryMyselfRes`**

In `server/modules/player.py`, change `build_query_myself_res(registry, row)` to `build_query_myself_res(registry, cfg, conn, row)` and add, before `fill_required(msg)`:

```python
    for hero_row in db.heroes_of(conn, int(row["id"])):
        msg.heroes.add().CopyFrom(hero.build_client_hero(registry, cfg, hero_row))
```

with `from server.modules import hero` at the top. Update the `query_myself` handler call and every test that calls `build_query_myself_res`.

- [ ] **Step 5: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green. `tests/test_player.py:test_query_myself_res_serializes` asserts `len(parsed.heroes) == 0`; with the Task 6 starting kit a fresh character has one hero, so that assertion becomes `== 1` for a created-through-login fixture and stays `== 0` for the bare `create_player` fixture. Pick one and be explicit about which.

- [ ] **Step 6: Commit**

```bash
git add server/modules/hero.py server/modules/player.py tests/test_hero.py tests/test_player.py
git commit -m "feat(server): ClientHero from hero_quality, npc_info and hero_growth"
```

**Done looks like:** `QueryMyselfRes` carries one hero whose `prototype` has an `npc_info` row and whose `quality` has a `hero_quality` row, with 玫瑰骑士 stats straight out of the config.

---

### Task 8: inventory — `ClientStock` and `QueryMyselfRes.inventory`

**Files:**
- Create: `server/modules/item.py`, `tests/test_item.py`
- Modify: `server/modules/player.py`
- Test: `tests/test_item.py`, `tests/test_player.py`

**Interfaces:**
- Consumes: `db.items_of`, `db.grant_item`, `Config.item`.
- Produces:
  - `server.modules.item.build_client_stock(registry, row, index) -> ClientStock`
  - `server.modules.item.build_inventory(registry, conn, player_id) -> list[ClientStock]`
  - `server.modules.item.grant_prizes(conn, cfg, player_id, prizes) -> dict` — applies a list of `(category, refer, amount)` triples to player state and returns `{"gold": int, "diamond": int, "items": [(entry, new_amount)], "heroes": [hero_row_id]}` so callers can both persist and notify. Categories handled: 1 gold, 9 diamond, 20 item, 30 hero; anything else is logged once and skipped.

- [ ] **Step 1: Write the failing test `tests/test_item.py`**

```python
"""ClientStock and prize granting (categories from ClientPlayer.lua:146-186)."""

from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, grant_item, heroes_of, items_of
from server.modules.item import build_client_stock, build_inventory, grant_prizes
from server.net.registry import Registry

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "player.db")


def test_build_client_stock_fields(reg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 10000, 2)
    row = items_of(conn, pid)[0]
    stock = build_client_stock(reg, row, index=0)
    assert stock.id == int(row["id"])
    assert stock.entry == 10000
    assert stock.amount == 2
    assert stock.state == 0
    assert stock.index == 0
    stock.SerializeToString()


def test_build_inventory_is_one_stock_per_entry(reg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_item(conn, pid, 1100, 3)
    grant_item(conn, pid, 1100, 2)
    grant_item(conn, pid, 1200, 1)
    stocks = build_inventory(reg, conn, pid)
    assert [(s.entry, s.amount) for s in stocks] == [(1100, 5), (1200, 1)]
    assert [s.index for s in stocks] == [0, 1]


def test_grant_prizes_applies_every_category_this_plan_sends(reg, cfg, conn) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100, diamond=10)
    out = grant_prizes(conn, cfg, pid, [
        (1, 0, 516),          # gold
        (9, 0, 600),          # diamond
        (20, 10000, 2),       # item
        (30, 101000, 1),      # hero
    ])
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    assert int(row["gold"]) == 616
    assert int(row["diamond"]) == 610
    assert out["gold"] == 616
    assert out["diamond"] == 610
    assert out["items"] == [(10000, 2)]
    assert len(out["heroes"]) == 1
    hero = [h for h in heroes_of(conn, pid) if int(h["entry"]) == 101000][0]
    assert int(hero["quality"]) == int(cfg.hero_qualities(101000)[0]["quality"])


def test_granting_a_hero_twice_keeps_two_rows(reg, cfg, conn) -> None:
    """The client keeps a list of heroes and RoleData:getHero inserts each one,
    so a duplicate summon is a second row, not an error."""
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    grant_prizes(conn, cfg, pid, [(30, 100000, 1)])
    assert len(heroes_of(conn, pid)) == 2


def test_an_unknown_category_is_skipped_not_fatal(reg, cfg, conn, caplog) -> None:
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    out = grant_prizes(conn, cfg, pid, [(40, 5000000, 1)])   # angel, out of scope
    assert out["items"] == [] and out["heroes"] == []
    assert "category 40" in caplog.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_item.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.item`.

- [ ] **Step 3: Write `server/modules/item.py`**

```python
"""Inventory: ClientStock shapes and prize granting.

Categories are the client own constants (ClientPlayer.lua:146-186) and are the
same numbers as drop_base.drop_type: 1 gold, 2 energy, 9 diamond, 11 player xp,
12 hero xp, 13 angel xp, 20 item, 30 hero, 40 angel.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db
from server.config import Config
from server.net.registry import Registry
from server.net.server import fill_required

log = logging.getLogger("loa.item")

CATEGORY_GOLD = 1
CATEGORY_ENERGY = 2
CATEGORY_DIAMOND = 9
CATEGORY_ITEM = 20
CATEGORY_HERO = 30

_warned: set[int] = set()


def build_client_stock(registry: Registry, row: sqlite3.Row, index: int):
    msg = registry.message_class("ClientStock")(
        id=int(row["id"]),
        entry=int(row["entry"]),
        amount=int(row["amount"]),
        state=0,
        index=int(index),
    )
    fill_required(msg)
    return msg


def build_inventory(registry: Registry, conn: sqlite3.Connection, player_id: int) -> list:
    return [
        build_client_stock(registry, row, index)
        for index, row in enumerate(db.items_of(conn, player_id))
    ]


def grant_prizes(
    conn: sqlite3.Connection, cfg: Config, player_id: int, prizes
) -> dict:
    """Apply (category, refer, amount) triples and report what changed."""
    out: dict = {"gold": None, "diamond": None, "energy": None, "items": [], "heroes": []}
    for category, refer, amount in prizes:
        category = int(category)
        amount = int(amount)
        if category == CATEGORY_GOLD:
            conn.execute(
                "UPDATE players SET gold = gold + ? WHERE id = ?", (amount, player_id)
            )
        elif category == CATEGORY_DIAMOND:
            conn.execute(
                "UPDATE players SET diamond = diamond + ? WHERE id = ?",
                (amount, player_id),
            )
        elif category == CATEGORY_ENERGY:
            db.add_energy(conn, cfg, player_id, amount)
        elif category == CATEGORY_ITEM:
            total = db.grant_item(conn, player_id, int(refer), amount)
            out["items"].append((int(refer), total))
        elif category == CATEGORY_HERO:
            qualities = cfg.hero_qualities(int(refer))
            if not qualities:
                log.warning("hero %s has no hero_quality row, not granted", refer)
                continue
            for _ in range(max(1, amount)):
                out["heroes"].append(
                    db.grant_hero(
                        conn, player_id, int(refer), int(qualities[0]["quality"])
                    )
                )
        elif category not in _warned:
            _warned.add(category)
            log.info("prize category %d is not implemented in Plan B1, skipped", category)
    conn.commit()
    row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    out["gold"] = int(row["gold"])
    out["diamond"] = int(row["diamond"])
    out["energy"] = int(row["energy"])
    return out
```

- [ ] **Step 4: Put the inventory into `QueryMyselfRes`**

In `server/modules/player.py`, inside `build_query_myself_res`, before `fill_required(msg)`:

```python
    for stock in item.build_inventory(registry, conn, int(row["id"])):
        msg.inventory.add().CopyFrom(stock)
```

with `from server.modules import hero, item`.

- [ ] **Step 5: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green; the `inventory` length assertion in `tests/test_player.py` moves from 0 to 2 for the login-created fixture.

- [ ] **Step 6: Commit**

```bash
git add server/modules/item.py server/modules/player.py tests/test_item.py tests/test_player.py
git commit -m "feat(server): inventory in QueryMyselfRes and a prize-granting helper"
```

**Done looks like:** the bag shows 小经验药水 x3 and 符文晶石(小) x2 after a fresh login, and `grant_prizes` is the one place that turns a drop into player state.

---

### Task 9: `Session.outbox` and the client notification helpers

**Files:**
- Create: `server/modules/notify.py`, `tests/test_notify.py`
- Modify: `server/net/server.py` (`Session.outbox`, flush in `_on_frame`)
- Test: `tests/test_notify.py`, `tests/test_server_core.py`

**Interfaces:**
- Consumes: `Session.send`.
- Produces:
  - `Session.outbox: list[tuple[int, int, object]]` (default empty) and `Session.queue(service, cmd, msg) -> None`. `Server._on_frame` drains it after the reply, in order, through `Session.send`, and clears it even when a send raises.
  - `server.modules.notify.player_changed(registry, session, fields: dict[str, float]) -> None` queues `5_2008 ClientNotification{ident=1, flags, data}`.
  - `server.modules.notify.items_changed(registry, session, pairs: list[tuple[int, int]]) -> None` queues `5_2008 {ident=4, flags=0, data=[entry, amount, ...]}`.
  - `server.modules.notify.level_up(registry, session, old, new) -> None` queues `5_2036 LevelUpNotify`; `old` and `new` are `(level, energy, max_energy)` tuples.
  - `server.modules.notify.hero_added(registry, session, client_hero) -> None` queues `5_2012 AddHeroNotify`.
  - `server.modules.notify.PLAYER_FIELDS: tuple[str, ...]` is `ClientPlayer.PLAYER_FIELD_DIC` verbatim, and `notify.flags_for(names) -> int` builds the mask.

**Handlers stay synchronous.** Plan A dispatch calls `res = handler(session, req)` and then awaits `_reply`; nothing in a handler can await. The outbox is how a handler asks for extra frames, and it is the smallest change that keeps every existing handler signature.

- [ ] **Step 1: Write the failing test `tests/test_notify.py`**

```python
"""5_2008 ClientNotification and friends.

RoleData:onPlayerInfoChange walks ClientPlayer.PLAYER_FIELD_DIC and, for each
set bit, consumes the next value out of data. flags is a fixed64 in the proto
but Lua reads it with string.byte, so the mask is byte-indexed: bit
2^((i-1) mod 8) of byte floor((i-1)/8)+1 for the 1-based field index.
Whether those 8 bytes reach Lua little-endian is open question A in the plan;
these tests pin the little-endian reading, which is what protobuf writes.
"""

import asyncio
from pathlib import Path

import pytest

from server.modules import notify
from server.net.registry import Registry
from server.net.server import Server, Session
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")
BIND = "127.0.0.1"


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind=BIND, port=0, username="stefan", guide_id=0,
    )


def test_player_field_dic_matches_the_client_list(reg) -> None:
    assert notify.PLAYER_FIELDS[:9] == (
        "vip", "vip_expires", "paycount", "xp", "level", "energy", "max_energy",
        "gold", "diamond",
    )
    assert notify.PLAYER_FIELDS[12] == "last_level"
    assert len(notify.PLAYER_FIELDS) == 48


def test_flags_for_sets_one_bit_per_field() -> None:
    assert notify.flags_for(["vip"]) == 1 << 0
    assert notify.flags_for(["energy"]) == 1 << 5
    assert notify.flags_for(["gold"]) == 1 << 7
    assert notify.flags_for(["last_level"]) == 1 << 12
    assert notify.flags_for(["energy", "gold"]) == (1 << 5) | (1 << 7)


def test_player_changed_orders_data_by_field_index(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.player_changed(reg, session, {"gold": 1616, "energy": 54, "xp": 6})
    (service, cmd, msg) = session.outbox[0]
    assert (service, cmd) == (5, 2008)
    assert msg.ident == 1
    assert msg.flags == (1 << 3) | (1 << 5) | (1 << 7)
    assert list(msg.data) == [6.0, 54.0, 1616.0]      # xp, energy, gold
    msg.SerializeToString()


def test_items_changed_is_flat_entry_amount_pairs(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.items_changed(reg, session, [(10000, 2), (1100, 5)])
    (_, _, msg) = session.outbox[0]
    assert msg.ident == 4
    assert list(msg.data) == [10000.0, 2.0, 1100.0, 5.0]


def test_level_up_notify_carries_all_six_values(reg) -> None:
    session = Session(writer=None, peer="t", bound_port=0)
    notify.level_up(reg, session, (1, 54, 60), (2, 66, 62))
    (service, cmd, msg) = session.outbox[0]
    assert (service, cmd) == (5, 2036)
    assert (msg.oldLevel, msg.newLevel) == (1, 2)
    assert (msg.oldEnergy, msg.newEnergy) == (54, 66)
    assert (msg.oldMaxEnergy, msg.newMaxEnergy) == (60, 62)
    msg.SerializeToString()


def test_the_dispatcher_flushes_the_outbox_after_the_reply(reg, settings) -> None:
    def handler(session: Session, req):
        notify.player_changed(reg, session, {"energy": 54})
        return reg.message_class("SaveGuideIdRes")(status=0)

    async def scenario() -> None:
        server = Server(reg, settings, {(5, 2041): handler}, bind_host=BIND)
        task, port = await _run_server(server)
        client = await Client.connect(port)
        body = reg.message_class("SaveGuideIdReq")(guide_id=1).SerializeToString()
        await client.send(5, 2041, body)
        first = await client.recv()
        second = await client.recv()
        assert (first.service, first.cmd) == (5, 2042)
        assert (second.service, second.cmd) == (5, 2008)
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_notify.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.notify`.

- [ ] **Step 3: Add the outbox to `server/net/server.py`**

In the `Session` dataclass:

```python
    # Extra frames a synchronous handler wants pushed after its reply, in order.
    # Dispatch drains this; handlers only append through queue().
    outbox: list[tuple[int, int, object]] = field(default_factory=list)

    def queue(self, service: int, cmd: int, msg) -> None:
        self.outbox.append((service, cmd, msg))
```

At the end of `_on_frame`, after the reply:

```python
        if res is not None:
            await self._reply(session, key, res)
        await self._flush(session)
```

and in the `handler is None` branch, before each `return`, call `await self._flush(session)` as well — or restructure so the single tail does it. Then:

```python
    async def _flush(self, session: Session) -> None:
        """Send and clear whatever the handler queued. A notify id has no Req,
        so these go out through Session.send directly, not through res_key."""
        queued, session.outbox = session.outbox, []
        for service, cmd, msg in queued:
            fill_required(msg)
            await session.send(service, cmd, msg)
```

- [ ] **Step 4: Write `server/modules/notify.py`**

```python
"""Server-to-client pushes: 5_2008, 5_2036, 5_2012.

These are notify ids with no paired Req, so they are queued on the session and
written by the dispatcher through Session.send.
"""

from __future__ import annotations

import logging

from server.net.registry import Registry
from server.net.server import Session, fill_required

log = logging.getLogger("loa.notify")

IDENT_PLAYER = 1
IDENT_HERO = 2
IDENT_ITEM = 4

# ClientPlayer.PLAYER_FIELD_DIC, verbatim and in order. The 1-based index into
# this tuple is the bit RoleData:onPlayerInfoChange tests.
PLAYER_FIELDS = (
    "vip", "vip_expires", "paycount", "xp", "level", "energy", "max_energy",
    "gold", "diamond", "login_month", "login_flags", "award_flags",
    "last_level", "last_elite", "avatar", "angel_money", "arena_point",
    "vvip1", "battlefield_point", "gold_trails_cooldown", "login_award",
    "vip_xp", "paid_user", "guild_id", "nobility_level", "nobility_exp",
    "guild_money", "toparena_money", "artifact_smelt", "gve_money",
    "discount_money", "cross_money", "cross_rise_money", "crusade_point",
    "honor", "signet_essence", "signet_fight_cnt", "card_master_gacha",
    "card_master_points", "magic_money", "recharge_score", "devil_money",
    "star_soul_money", "syb_money", "gemstone_money", "gemstone_prize_money",
    "realname_check", "pet_money",
)


def flags_for(names) -> int:
    mask = 0
    for name in names:
        mask |= 1 << PLAYER_FIELDS.index(name)
    return mask


def player_changed(registry: Registry, session: Session, fields: dict) -> None:
    """One notification per change set. data is ordered by field index, and
    carries only the fields whose bit is set."""
    ordered = [n for n in PLAYER_FIELDS if n in fields]
    unknown = set(fields) - set(PLAYER_FIELDS)
    if unknown:
        log.warning("not a ClientPlayer notify field, dropped: %s", sorted(unknown))
    msg = registry.message_class("ClientNotification")(
        ident=IDENT_PLAYER, flags=flags_for(ordered)
    )
    for name in ordered:
        msg.data.append(float(fields[name]))
    fill_required(msg)
    session.queue(5, 2008, msg)


def items_changed(registry: Registry, session: Session, pairs) -> None:
    """RoleData:onItemInfoChange reads data as flat (entry, new amount) pairs
    and calls updateItemNum, which sets the absolute amount."""
    if not pairs:
        return
    msg = registry.message_class("ClientNotification")(ident=IDENT_ITEM, flags=0)
    for entry, amount in pairs:
        msg.data.append(float(entry))
        msg.data.append(float(amount))
    fill_required(msg)
    session.queue(5, 2008, msg)


def level_up(registry: Registry, session: Session, old, new) -> None:
    old_level, old_energy, old_max = old
    new_level, new_energy, new_max = new
    msg = registry.message_class("LevelUpNotify")(
        oldLevel=int(old_level), newLevel=int(new_level),
        oldEnergy=int(old_energy), newEnergy=int(new_energy),
        oldMaxEnergy=int(old_max), newMaxEnergy=int(new_max),
    )
    fill_required(msg)
    session.queue(5, 2036, msg)


def hero_added(registry: Registry, session: Session, client_hero) -> None:
    msg = registry.message_class("AddHeroNotify")()
    msg.hero.CopyFrom(client_hero)
    fill_required(msg)
    session.queue(5, 2012, msg)
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `py -3.14 -m pytest -q tests/test_notify.py --basetemp=C:/tmp/pytest-loa` then the whole suite.
Expected: `6 passed`, suite green.

- [ ] **Step 6: Resolve open question A on the emulator**

This is the one step in this task that needs the AVD; it is cheap and it de-risks Tasks 11 and 14. With the server running and the app on the main city (`docs/dev-loop.md` section 5), send a single `energy` notify from a Python REPL against the live session is not possible, so do it the other way round: temporarily set `energy` to 54 in `data/player.db`, restart the server, relaunch the app, and in the same session trigger any handled request so that `player_changed(reg, session, {"energy": 54})` fires from a one-line temporary call inside the `5_2041` handler. Then:

```bash
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"; A="$SDK/platform-tools/adb.exe"
"$A" logcat -d | grep -E "changed :>>|roleDtaReciveChange"
```

Expected: a line reading `energy->changed :>> 54`. If the key is a different field name, the byte order is reversed: change `flags_for` to byte-swap the mask (`int.from_bytes(mask.to_bytes(8, "little"), "big")`), add the reversed expectation to `test_flags_for_sets_one_bit_per_field`, and re-run. Remove the temporary call before committing and record the outcome in the task report.

- [ ] **Step 7: Commit**

```bash
git add server/net/server.py server/modules/notify.py tests/test_notify.py \
        tests/test_server_core.py
git commit -m "feat(server): session outbox and the client notification pushes"
```

**Done looks like:** a handler can queue `5_2008` and the client logs `energy->changed`, with the flag byte order settled by observation rather than assumption.

---

### Task 10: the drop roller

**Files:**
- Create: `server/drops.py`, `tests/test_drops.py`
- Test: `tests/test_drops.py`

**Interfaces:**
- Consumes: `Config.drop_groups`, `Config.drop_rows`.
- Produces:
  - `server.drops.Drop` — a frozen dataclass with `category: int`, `refer: int`, `amount: int`.
  - `server.drops.roll(cfg, drop_id, rng=None) -> list[Drop]` — for each `drop_group` row with that `drop_id`, roll `probability`; on a hit, pick one `drop_base` row of that group weighted by `weight`. `rng` is a `random.Random`; the default is a module-level `random.SystemRandom`.
  - `server.drops.to_prize_entries(registry, drops) -> list[ClientPrizeEntry]`.
  - `server.drops.as_triples(drops) -> list[tuple[int, int, int]]` for `item.grant_prizes`.

- [ ] **Step 1: Write the failing test `tests/test_drops.py`**

```python
"""Drop rolling over drop_group plus drop_base (DataManager:getDropBaseAry)."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.drops import Drop, as_triples, roll, to_prize_entries
from server.net.registry import Registry

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


def test_a_certain_group_always_drops(cfg) -> None:
    # stage 1-1 visible_drops 10000 -> group 10001 at probability 1 -> item 10000 x2
    for seed in range(5):
        assert roll(cfg, 10000, random.Random(seed)) == [Drop(20, 10000, 2)]


def test_probability_is_respected(cfg) -> None:
    """invisible_drops 10005: groups at 0.2, 0.29 and 0.1, so 1000 rolls must
    land between a tenth and nine tenths of the maximum, never always or never."""
    rng = random.Random(7)
    counts = [len(roll(cfg, 10005, rng)) for _ in range(1000)]
    assert 0 in counts
    assert max(counts) >= 1
    assert sum(counts) < 3 * 1000


def test_weighted_pick_inside_a_group(cfg) -> None:
    """Gacha 1200000 drop_id 190000: one group, 125 weighted rows, exactly one
    result per roll."""
    rng = random.Random(1)
    seen = set()
    for _ in range(200):
        drops = roll(cfg, 190000, rng)
        assert len(drops) == 1
        seen.add((drops[0].category, drops[0].refer))
    assert len(seen) > 1
    valid = {(r["drop_type"], r["item_id"]) for r in cfg.drop_rows(190000)}
    assert seen <= valid


def test_the_chapter_chest_is_deterministic(cfg) -> None:
    drops = roll(cfg, 600100, random.Random(0))
    assert drops == [
        Drop(9, 0, 600), Drop(20, 104000, 6), Drop(1, 0, 60000), Drop(20, 1100, 12)
    ]


def test_drop_base_2_groups_are_reached(cfg) -> None:
    drops = roll(cfg, 10000000, random.Random(0))
    assert Drop(9, 0, 1128) in drops
    assert Drop(1, 0, 600000) in drops


def test_an_unknown_drop_id_rolls_nothing(cfg) -> None:
    assert roll(cfg, 13002, random.Random(0)) == []
    assert roll(cfg, 999999999, random.Random(0)) == []


def test_prize_entries_and_triples(reg, cfg) -> None:
    drops = [Drop(20, 10000, 2), Drop(1, 0, 516)]
    entries = to_prize_entries(reg, drops)
    assert [(e.category, e.refer, e.amount) for e in entries] == [
        (20, 10000, 2), (1, 0, 516)
    ]
    for entry in entries:
        entry.SerializeToString()
    assert as_triples(drops) == [(20, 10000, 2), (1, 0, 516)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_drops.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.drops`.

- [ ] **Step 3: Write `server/drops.py`**

```python
"""Rolling a drop id into concrete prizes.

The chain is the one the client walks in DataManager:getDropBaseAry
(DataManager.lua:444-474):

    drop id -> drop_group rows with that drop_id -> for each, its drop_group_id
            -> drop_base rows of that group -> one of them, by weight

probability is per group row. frequency is ignored: no Lua reads it and it is 0
or 1 everywhere this plan looks (open question B in the plan).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from server.config import Config
from server.net.registry import Registry

log = logging.getLogger("loa.drops")

_default_rng = random.SystemRandom()


@dataclass(frozen=True)
class Drop:
    category: int   # drop_base.drop_type, the ClientPrizeEntry category
    refer: int      # drop_base.item_id: item entry, hero entry, or 0 for money
    amount: int


def roll(cfg: Config, drop_id: int, rng: random.Random | None = None) -> list[Drop]:
    rng = _default_rng if rng is None else rng
    out: list[Drop] = []
    for group in cfg.drop_groups(drop_id):
        probability = float(group["probability"] or 0)
        if probability < 1.0 and rng.random() >= probability:
            continue
        rows = cfg.drop_rows(int(group["drop_group_id"]))
        if not rows:
            # Dead config: plenty of drop ids point at groups with no rows.
            continue
        total = sum(max(0, r["weight"]) for r in rows)
        if total <= 0:
            continue
        pick = rng.randrange(total)
        for row in rows:
            pick -= max(0, row["weight"])
            if pick < 0:
                out.append(Drop(row["drop_type"], row["item_id"], row["amount"]))
                break
    return out


def to_prize_entries(registry: Registry, drops) -> list:
    entries = []
    for drop in drops:
        msg = registry.message_class("ClientPrizeEntry")(
            category=drop.category, refer=drop.refer, amount=drop.amount
        )
        entries.append(msg)
    return entries


def as_triples(drops) -> list[tuple[int, int, int]]:
    return [(d.category, d.refer, d.amount) for d in drops]
```

- [ ] **Step 4: Run the test, then the suite**

Run: `py -3.14 -m pytest -q tests/test_drops.py --basetemp=C:/tmp/pytest-loa` then the full suite.
Expected: `7 passed`, suite green.

- [ ] **Step 5: Commit**

```bash
git add server/drops.py tests/test_drops.py
git commit -m "feat(server): roll drop ids through drop_group and drop_base"
```

**Done looks like:** `roll(cfg, 10000)` always yields 粗布头巾 x2, the gacha group yields exactly one weighted row per roll, and a group above 10,000,000 is read out of `drop_base_2`.

---

### Task 11: the summon the tutorial asks for — `5_2121` and `5_2123`

**Files:**
- Create: `server/modules/gacha.py`, `tests/test_gacha.py`
- Modify: `server/__main__.py`
- Test: `tests/test_gacha.py`

**Interfaces:**
- Consumes: `Config.gachas`, `Config.gacha`, `drops.roll`, `item.grant_prizes`, `hero.build_client_hero`, `notify.*`, `db.heroes_of`.
- Produces: `server.modules.gacha.handlers(registry, settings, conn, cfg) -> {(5, 2121): gacha_info, (5, 2123): gacha}`, plus `build_gacha_info(registry, cfg) -> GachaInfoRes`.

**What the client does with the answer.** `FunctionType` opens `UI_TAVERN_UI` on `5_2122` with the whole message (`FunctionType.lua:653-657`); `TavernBase:initParam` walks `self.serverMsg.gachaInfos` looking for each of `1200000, 1300000, 2400000, 2500000, 3000000` and tolerates a miss (`getSeverInfo` returns nil). `TavernUI` on `GachaRes` requires `msg.status == 0`, then `g_tools:randomTable(msg.items)` and `TavernStage.new`, so `items` must never be empty. `TavernUI:synData` copies `next`, `gold_next`, `gold_gacha`, `diamond_gacha`, `diamond_ten_gacha` out of the response, so send all five.

**Cost.** `gacha_info.cost_type` 1 is gold, 9 is diamond. The tutorial draws 1200000 (20,000 gold) and 2400000 (2,000 diamonds), both affordable out of the Task 6 starting kit. Refuse with `327937 金币不足` or `327938 钻石不足`; those codes reach the player because `GachaRes` has a real `status` field.

- [ ] **Step 1: Write the failing test `tests/test_gacha.py`**

```python
"""5_2121 GachaInfoReq and 5_2123 GachaReq: the two summons the guide points at."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, heroes_of, items_of
from server.modules import gacha
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind="127.0.0.1", port=0, username="stefan", guide_id=0,
    )


@pytest.fixture
def world(settings, cfg, reg):
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = gacha.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def test_gacha_info_lists_every_configured_banner(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2121)](session, reg.message_class("GachaInfoReq")())
    assert res.status == 0
    assert [g.gacha for g in res.gachaInfos] == [
        1200000, 1300000, 2400000, 2500000, 3000000
    ]
    assert all(g.cooldown == 0 for g in res.gachaInfos)
    assert [g.freetimes for g in res.gachaInfos] == [0, 0, 1, 0, 0]
    assert res.gold_gacha == 0 and res.diamond_gacha == 0
    res.SerializeToString()


def test_gacha_res_always_has_at_least_one_item(reg, cfg, world) -> None:
    """Review Focus 5: TavernUI feeds msg.items to g_tools:randomTable."""
    conn, pid, handlers, session = world
    for _ in range(20):
        res = handlers[(5, 2123)](
            session, reg.message_class("GachaReq")(gacha=1200000)
        )
        assert res.status == 0
        assert len(res.items) >= 1
        res.SerializeToString()


def test_a_gold_draw_costs_the_configured_gold(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000 - 20000


def test_a_diamond_draw_costs_the_configured_diamonds(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=2400000))
    row = find_player(conn, "stefan")
    assert int(row["diamond"]) == 18888 - 2000


def test_too_little_gold_is_refused_with_the_client_status(reg, cfg, settings) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=10, diamond=0)
    handlers = gacha.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert res.status == 327937                     # language.db 金币不足
    assert len(res.items) == 0
    assert int(find_player(conn, "stefan")["gold"]) == 10


def test_an_unknown_banner_is_refused(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=42))
    assert res.status != 0


def test_a_drawn_hero_is_persisted_and_pushed(reg, cfg, world, monkeypatch) -> None:
    """A type-30 drop is a hero: it lands in the heroes table and the client is
    told through 5_2012 AddHeroNotify, which RoleData:getHero consumes."""
    conn, pid, handlers, session = world
    from server import drops as drops_mod

    monkeypatch.setattr(
        drops_mod, "roll", lambda cfg_, drop_id, rng=None: [drops_mod.Drop(30, 101000, 1)]
    )
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert [(e.category, e.refer) for e in res.items] == [(30, 101000)]
    assert [int(h["entry"]) for h in heroes_of(conn, pid)] == [101000]
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2012), (5, 2008)]


def test_a_drawn_item_lands_in_the_bag_and_is_pushed(reg, cfg, world, monkeypatch) -> None:
    conn, pid, handlers, session = world
    from server import drops as drops_mod

    monkeypatch.setattr(
        drops_mod, "roll", lambda cfg_, drop_id, rng=None: [drops_mod.Drop(20, 1100, 20)]
    )
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert {int(i["entry"]): int(i["amount"]) for i in items_of(conn, pid)} == {1100: 20}
    idents = [m.ident for (_s, _c, m) in session.outbox if _c == 2008]
    assert 4 in idents and 1 in idents
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_gacha.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.gacha`.

- [ ] **Step 3: Write `server/modules/gacha.py`**

```python
"""Hero summon: 5_2121 GachaInfoReq, 5_2123 GachaReq.

The tutorial draws banner 1200000 (guide 10061) and 2400000 (guide 10081);
TavernFace:onBtnClick sends the entry of the card it sits on. gacha_info gives
the cost and the drop id, and the drop id rolls through drop_group / drop_base
exactly like a stage drop.
"""

from __future__ import annotations

import logging
import sqlite3

from server import db, drops
from server.config import Config
from server.modules import hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.gacha")

STATUS_OK = 0
STATUS_NOT_ENOUGH_GOLD = 327937      # language.db 金币不足
STATUS_NOT_ENOUGH_DIAMOND = 327938   # language.db 钻石不足
STATUS_UNKNOWN_BANNER = 327681       # language.db 系统内部错误

COST_GOLD = 1
COST_DIAMOND = 9


def build_gacha_info(registry: Registry, cfg: Config):
    res = registry.message_class("GachaInfoRes")(
        status=STATUS_OK, week=0, next=0, gold_next=0,
        gold_gacha=0, diamond_gacha=0, diamond_ten_gacha=0,
    )
    for row in cfg.gachas():
        info = res.gachaInfos.add()
        info.gacha = int(row["entry"])
        # No cooldown is being tracked in Plan B1: a free draw is always ready.
        info.cooldown = 0
        info.freetimes = int(row["free_times"] or 0)
    fill_required(res)
    return res


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def gacha_info(session: Session, req):
        return build_gacha_info(registry, cfg)

    def gacha(session: Session, req):
        row = _player(session)
        banner = cfg.gacha(int(req.gacha))
        if row is None or banner is None:
            log.warning("5_2123 for unknown banner %s", req.gacha)
            res = registry.message_class("GachaRes")(status=STATUS_UNKNOWN_BANNER)
            fill_required(res)
            return res

        cost = int(banner["cost"] or 0)
        cost_type = int(banner["cost_type"] or 0)
        if cost_type == COST_GOLD and int(row["gold"]) < cost:
            res = registry.message_class("GachaRes")(status=STATUS_NOT_ENOUGH_GOLD)
            fill_required(res)
            return res
        if cost_type == COST_DIAMOND and int(row["diamond"]) < cost:
            res = registry.message_class("GachaRes")(status=STATUS_NOT_ENOUGH_DIAMOND)
            fill_required(res)
            return res

        player_id = int(row["id"])
        rolled = drops.roll(cfg, int(banner["drop_id"] or 0))
        if not rolled:
            # TavernUI hands items to g_tools:randomTable, so never answer empty.
            log.warning(
                "banner %s drop id %s rolled nothing, falling back to its first row",
                req.gacha, banner["drop_id"],
            )
            groups = cfg.drop_groups(int(banner["drop_id"] or 0))
            rows = cfg.drop_rows(int(groups[0]["drop_group_id"])) if groups else []
            if rows:
                first = rows[0]
                rolled = [drops.Drop(first["drop_type"], first["item_id"], first["amount"])]

        column = "gold" if cost_type == COST_GOLD else "diamond"
        if cost:
            conn.execute(
                f"UPDATE players SET {column} = {column} - ? WHERE id = ?",
                (cost, player_id),
            )
            conn.commit()

        changed = item.grant_prizes(conn, cfg, player_id, drops.as_triples(rolled))
        res = registry.message_class("GachaRes")(
            status=STATUS_OK, next=0, gold_next=0,
            gold_gacha=0, diamond_gacha=0, diamond_ten_gacha=0,
        )
        for entry in drops.to_prize_entries(registry, rolled):
            res.items.add().CopyFrom(entry)

        for hero_id in changed["heroes"]:
            hero_row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (hero_id,)
            ).fetchone()
            notify.hero_added(registry, session, hero.build_client_hero(registry, cfg, hero_row))
        notify.items_changed(registry, session, changed["items"])
        notify.player_changed(
            registry, session, {"gold": changed["gold"], "diamond": changed["diamond"]}
        )
        log.info(
            "banner %s drawn for player %d: %s", req.gacha, player_id,
            [(d.category, d.refer, d.amount) for d in rolled],
        )
        fill_required(res)
        return res

    return {(5, 2121): gacha_info, (5, 2123): gacha}
```

- [ ] **Step 4: Register it in `server/__main__.py`**

```python
    handlers.update(gacha.handlers(registry, settings, conn, cfg))
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `py -3.14 -m pytest -q tests/test_gacha.py --basetemp=C:/tmp/pytest-loa` then the full suite.
Expected: `8 passed`, suite green.

- [ ] **Step 6: Commit**

```bash
git add server/modules/gacha.py server/__main__.py tests/test_gacha.py
git commit -m "feat(server): hero summon (5_2121, 5_2123) with real drop tables"
```

**Done looks like:** the tavern opens with five banners, a gold draw costs 20,000 gold, the result is always at least one prize, a drawn hero is persisted and pushed with `5_2012`, and a draw without the currency floats 金币不足.

---

### Task 12: stage progress — `levels`, `chapters`, `last_level` in `QueryMyselfRes`

**Files:**
- Modify: `server/db.py` (tables and repositories), `server/modules/player.py` (`levels`, `chapters`, `last_level`)
- Test: `tests/test_db.py`, `tests/test_player.py`

**Interfaces:**
- Produces, in `server/db.py`:
  - `SCHEMA` gains the two tables below.
  - `level_progress(conn, player_id, level) -> Row | None`, `levels_of(conn, player_id) -> list[Row]`,
    `upsert_level(conn, player_id, level, star=None, count_delta=0, reset_count=None) -> Row`,
    `chapters_of(conn, player_id) -> list[Row]`, `set_chapter_award(conn, player_id, chapter, award) -> None`,
    `set_last_level(conn, player_id, level) -> None`.
- `build_query_myself_res` fills `msg.levels`, `msg.chapters` and sets `player.last_level`, `player.last_elite = 0`, `player.last_signet = 0`.

```sql
CREATE TABLE IF NOT EXISTS levels (
    player_id         INTEGER NOT NULL REFERENCES players(id),
    level             INTEGER NOT NULL,
    star              INTEGER NOT NULL DEFAULT 0,
    count             INTEGER NOT NULL DEFAULT 0,
    reset_count       INTEGER NOT NULL DEFAULT 0,
    clean_elite_count INTEGER NOT NULL DEFAULT 0,
    deadline          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, level)
);
CREATE TABLE IF NOT EXISTS chapters (
    player_id INTEGER NOT NULL REFERENCES players(id),
    chapter   INTEGER NOT NULL,
    award     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, chapter)
);
```

- [ ] **Step 1: Write the failing tests, appended to `tests/test_db.py`**

```python
def test_upsert_level_keeps_the_best_star_and_counts_plays(tmp_path) -> None:
    from server.db import connect, create_player, level_progress, upsert_level

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    upsert_level(conn, pid, 10000, star=2, count_delta=1)
    row = level_progress(conn, pid, 10000)
    assert (int(row["star"]), int(row["count"])) == (2, 1)
    upsert_level(conn, pid, 10000, star=1, count_delta=1)
    row = level_progress(conn, pid, 10000)
    assert (int(row["star"]), int(row["count"])) == (2, 2)   # 1 does not beat 2
    upsert_level(conn, pid, 10000, star=3, count_delta=0)
    assert int(level_progress(conn, pid, 10000)["star"]) == 3


def test_chapter_award_is_remembered(tmp_path) -> None:
    from server.db import chapters_of, connect, create_player, set_chapter_award

    conn = connect(tmp_path / "player.db")
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_chapter_award(conn, pid, 10000, 1)
    set_chapter_award(conn, pid, 10000, 1)
    assert [(int(r["chapter"]), int(r["award"])) for r in chapters_of(conn, pid)] == [
        (10000, 1)
    ]
```

And appended to `tests/test_player.py`:

```python
def test_levels_and_last_level_reach_the_client(reg, settings, cfg_fixture) -> None:
    """LevelManager:readLastLevelInfo takes the unlock frontier from
    player.last_level, and readServerLevelInfo takes the stars from levels."""
    from server.db import connect, create_player, find_player, set_last_level, upsert_level

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    set_last_level(conn, pid, 10000)
    res = player.build_query_myself_res(
        reg, cfg_fixture, conn, find_player(conn, "stefan")
    )
    assert [(l.level, l.star, l.count) for l in res.levels] == [(10000, 3, 1)]
    assert res.player.last_level == 10000
    assert res.player.last_elite == 0
    res.SerializeToString()


def test_chapters_only_contains_real_chapter_entries(reg, settings, cfg_fixture) -> None:
    """Review Focus 3: LevelManager:readBoxInfo indexes chapterEntryTable by the
    entry we send, with no nil check, so an entry chapter_info does not know
    crashes the client."""
    from server.db import connect, create_player, find_player, set_chapter_award

    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0)
    set_chapter_award(conn, pid, 10000, 1)
    set_chapter_award(conn, pid, 424242, 1)        # not a chapter_info entry
    res = player.build_query_myself_res(
        reg, cfg_fixture, conn, find_player(conn, "stefan")
    )
    assert [c.chapter for c in res.chapters] == [10000]
    assert res.chapters[0].award == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_db.py tests/test_player.py --basetemp=C:/tmp/pytest-loa`
Expected: `ImportError: cannot import name upsert_level`.

- [ ] **Step 3: Add the tables and repositories to `server/db.py`**

```python
def level_progress(conn, player_id: int, level: int):
    return conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = ?",
        (int(player_id), int(level)),
    ).fetchone()


def levels_of(conn, player_id: int) -> list:
    return list(
        conn.execute("SELECT * FROM levels WHERE player_id = ? ORDER BY level",
                     (int(player_id),))
    )


def upsert_level(conn, player_id: int, level: int, star=None, count_delta: int = 0,
                 reset_count=None):
    """Stars only ever go up; count counts plays."""
    conn.execute(
        "INSERT INTO levels (player_id, level) VALUES (?, ?)"
        " ON CONFLICT(player_id, level) DO NOTHING",
        (int(player_id), int(level)),
    )
    if star is not None:
        conn.execute(
            "UPDATE levels SET star = MAX(star, ?) WHERE player_id = ? AND level = ?",
            (int(star), int(player_id), int(level)),
        )
    if count_delta:
        conn.execute(
            "UPDATE levels SET count = count + ? WHERE player_id = ? AND level = ?",
            (int(count_delta), int(player_id), int(level)),
        )
    if reset_count is not None:
        conn.execute(
            "UPDATE levels SET reset_count = ? WHERE player_id = ? AND level = ?",
            (int(reset_count), int(player_id), int(level)),
        )
    conn.commit()
    return level_progress(conn, player_id, level)


def chapters_of(conn, player_id: int) -> list:
    return list(
        conn.execute("SELECT * FROM chapters WHERE player_id = ? ORDER BY chapter",
                     (int(player_id),))
    )


def set_chapter_award(conn, player_id: int, chapter: int, award: int) -> None:
    conn.execute(
        "INSERT INTO chapters (player_id, chapter, award) VALUES (?, ?, ?)"
        " ON CONFLICT(player_id, chapter) DO UPDATE SET award = ?",
        (int(player_id), int(chapter), int(award), int(award)),
    )
    conn.commit()


def set_last_level(conn, player_id: int, level: int) -> None:
    conn.execute(
        "UPDATE players SET last_level = ? WHERE id = ?", (int(level), int(player_id))
    )
    conn.commit()
```

- [ ] **Step 4: Fill the three fields in `server/modules/player.py`**

In `build_client_player`, after the existing optional assignments:

```python
    # LevelManager:readLastLevelInfo: 0 means a fresh account and the client
    # starts the player at the first stage of chapter 1.
    msg.last_level = int(row["last_level"])
    msg.last_elite = 0
    msg.last_signet = 0
```

`last_level` and `last_elite` are proto2 `required`, so they would be zero-filled anyway; writing them explicitly keeps the intent readable, and `last_signet` is optional but `LevelManager` compares it against 0.

In `build_query_myself_res`, before `fill_required(msg)`:

```python
    player_id = int(row["id"])
    for level_row in db.levels_of(conn, player_id):
        msg.levels.add().CopyFrom(build_client_level(registry, level_row))
    for chapter_row in db.chapters_of(conn, player_id):
        chapter = int(chapter_row["chapter"])
        if cfg.chapter(chapter) is None:
            # LevelManager:readBoxInfo would index a nil chapter and kill the VM.
            log.warning("chapter %d is not in chapter_info, not sent", chapter)
            continue
        entry = msg.chapters.add()
        entry.chapter = chapter
        entry.award = int(chapter_row["award"])
```

and the builder:

```python
def build_client_level(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("ClientLevel")(
        level=int(row["level"]),
        star=int(row["star"]),
        count=int(row["count"]),
        deadline=int(row["deadline"]),
        reset_count=int(row["reset_count"]),
        clean_elite_count=int(row["clean_elite_count"]),
    )
    fill_required(msg)
    return msg
```

- [ ] **Step 5: Run the suite**

Run: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`
Expected: green with 4 new tests.

- [ ] **Step 6: Commit**

```bash
git add server/db.py server/modules/player.py tests/test_db.py tests/test_player.py
git commit -m "feat(server): stage and chapter progress in QueryMyselfRes"
```

**Done looks like:** a player with stage 10000 at 3 stars and `last_level = 10000` logs in to a campaign map that shows those three stars and stage 10010 unlocked.

---

### Task 13: `5_2201 LevelIntoReq` — unlock check, energy, urandom, pre-rolled drops

**Files:**
- Create: `server/modules/level.py`, `tests/test_level.py`
- Modify: `server/__main__.py`
- Test: `tests/test_level.py`

**Interfaces:**
- Consumes: `Config.stage`, `Config.next_stage`, `Config.first_stage`, `db.refresh_energy`, `db.spend_energy`, `db.level_progress`, `drops.roll`, `notify.player_changed`.
- Produces:
  - `server.modules.level.URANDOM_SIZE = 64`, `URANDOM_SCALE = 10000`
  - `server.modules.level.roll_urandom(rng=None) -> list[int]`
  - `server.modules.level.frontier(cfg, row) -> int` — the one stage the player may newly clear: `next_stage(last_level)` when `last_level` is set, else `first_stage()`.
  - `server.modules.level.is_unlocked(cfg, conn, row, level) -> bool` — true for the frontier stage and for anything already in the `levels` table.
  - `server.modules.level.PENDING_KEY = "level_pending"` — `session.data[PENDING_KEY]` is a `dict[int, list[Drop]]` keyed by stage entry.
  - `handlers(registry, settings, conn, cfg)` returning `{(5, 2201): level_into, (5, 2203): level_out, (5, 2205): level_clean, (5, 2207): level_reset, (5, 2209): chapter_prize}`. Tasks 14 and 15 fill the last four; this task writes `level_into` and registers the module with the other four raising nothing because they are added in those tasks. **Task 13 adds only `(5, 2201)` to the returned dict**; Task 14 adds `(5, 2203)`, Task 15 the rest.

**Rulings this task implements.**
- Energy is spent on entry, from `stage_info.energy` (6 for every chapter-1 stage).
- `LevelIntoRes` has no `status` field (settled point 12), so a refusal is `flag`. `flag = 1` (the client floats `z00224` and reopens the campaign UI) for a locked stage, for a cleared `once = 1` stage, and for too little energy; `flag = 2` (`z00225`) when `maxcount` is set and reached. `DesSweepPanel:goLine` already blocks the energy case client-side, so `flag = 1` is a backstop, logged at warning level with the real code 327939 in the message so the log says what the client cannot show.
- The pre-rolled drops are stored on the session, keyed by stage entry (brief decision, not to be reopened). A server restart or a dropped connection mid-fight therefore loses the entry and the following `LevelOutReq` is answered `328196 没有进入关卡`; that is the documented behaviour, see Risks.

- [ ] **Step 1: Write the failing test `tests/test_level.py`, part 1 of 2**

```python
"""5_2201 LevelIntoReq. Stage rows are quoted in the plan: chapter 1 is
10000, 10010, 10012, 10020, 10022, each costing 6 energy."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, set_last_level, upsert_level
from server.modules import level
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind="127.0.0.1", port=0, username="stefan", guide_id=0,
    )


@pytest.fixture
def world(settings, cfg, reg):
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = level.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def test_the_frontier_of_a_fresh_player_is_stage_one_one(cfg, world) -> None:
    conn, pid, _h, _s = world
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10000


def test_the_frontier_follows_last_level(cfg, world) -> None:
    conn, pid, _h, _s = world
    set_last_level(conn, pid, 10000)
    assert level.frontier(cfg, find_player(conn, "stefan")) == 10010


def test_urandom_is_64_values_under_10000(world, reg) -> None:
    """Review Focus 4: BattleAlthm.NewAlgorithm refuses any other length and
    Random() divides by SCALE 10000."""
    values = level.roll_urandom(random.Random(0))
    assert len(values) == 64
    assert all(0 <= v < 10000 for v in values)
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert len(res.urandom) == 64
    assert all(0 <= v < 10000 for v in res.urandom)


def test_entering_stage_one_one_spends_six_energy_and_pre_rolls_the_drops(
    reg, cfg, world
) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0
    assert int(find_player(conn, "stefan")["energy"]) == 54
    # visible_drops 10000 is certain: 粗布头巾 x2
    assert (20, 10000, 2) in [(d.category, d.refer, d.amount) for d in res.drop]
    assert session.data[level.PENDING_KEY][10000]
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2008)]
    res.SerializeToString()
```

- [ ] **Step 2: `tests/test_level.py`, part 2 of 2 (same file)**

```python
def test_a_locked_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10022))
    assert res.flag == 1
    assert int(find_player(conn, "stefan")["energy"]) == 60      # nothing spent
    assert level.PENDING_KEY not in session.data or not session.data[level.PENDING_KEY]


def test_an_unknown_stage_is_refused_with_flag_one(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=999999))
    assert res.flag == 1


def test_a_cleared_stage_can_be_replayed_when_once_is_zero(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10000, star=3, count_delta=1)
    set_last_level(conn, pid, 10000)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 0                                   # stage_info.once is 0


def test_a_cleared_once_stage_is_refused_with_flag_one_and_its_star(
    reg, cfg, world
) -> None:
    """stage 10010 has once = 1 (open question C in the plan)."""
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10010, star=2, count_delta=1)
    set_last_level(conn, pid, 10010)
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10010))
    assert res.flag == 1
    assert res.star == 2


def test_too_little_energy_is_refused_and_logged_with_the_real_code(
    reg, cfg, world, caplog
) -> None:
    conn, pid, handlers, session = world
    conn.execute("UPDATE players SET energy = 2, energy_at = ? WHERE id = ?",
                 (2 ** 31, pid))
    conn.commit()
    res = handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    assert res.flag == 1
    assert "327939" in caplog.text
    assert int(find_player(conn, "stefan")["energy"]) == 2
```

The `energy_at = 2 ** 31` in the last test parks the regeneration clock in the future so `refresh_energy` adds nothing; a comment in the test says so.

- [ ] **Step 3: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa`
Expected: `ModuleNotFoundError: No module named server.modules.level`.

- [ ] **Step 4: Write `server/modules/level.py`**

```python
"""Campaign stages: 5_2201 LevelIntoReq (and, from Task 14, 5_2203 and friends).

Wire shape per spec section 4: the server validates the unlock, spends the
energy, rolls 64 randoms and pre-rolls the drops, and the client fights.
LevelIntoRes has no status field, so a refusal is flag: 1 makes the client float
z00224 and reopen the campaign UI, 2 floats z00225 (LevelLine.lua:37-60).
"""

from __future__ import annotations

import logging
import random
import sqlite3

from server import db, drops
from server.config import Config
from server.modules import notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.level")

# BattleAlthm.MAX_URANDOM_SIZE and SCALE (BattleAlthm.lua:14, 27). Any other
# length makes NewAlgorithm return nil and the battle never starts.
URANDOM_SIZE = 64
URANDOM_SCALE = 10000

FLAG_OK = 0
FLAG_STAGE_CHANGED = 1     # z00224, client reopens the campaign UI
FLAG_MAX_TIMES = 2         # z00225

STATUS_NOT_ENOUGH_ENERGY = 327939   # language.db 体力不足, cannot be delivered on 5_2202
STATUS_STAGE_LOCKED = 328193        # language.db 关卡未开启
STATUS_NOT_ENTERED = 328196         # language.db 没有进入关卡

PENDING_KEY = "level_pending"

_rng = random.SystemRandom()


def roll_urandom(rng: random.Random | None = None) -> list[int]:
    rng = _rng if rng is None else rng
    return [rng.randrange(URANDOM_SCALE) for _ in range(URANDOM_SIZE)]


def frontier(cfg: Config, row: sqlite3.Row) -> int:
    last = int(row["last_level"])
    return cfg.next_stage(last) if last else cfg.first_stage()


def is_unlocked(cfg: Config, conn: sqlite3.Connection, row: sqlite3.Row, lvl: int) -> bool:
    if lvl == frontier(cfg, row):
        return True
    return db.level_progress(conn, int(row["id"]), lvl) is not None
```

- [ ] **Step 5: the handler, same file**

```python
def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _player(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def _refused(flag: int, star: int = 0):
        res = registry.message_class("LevelIntoRes")(flag=flag, star=star)
        fill_required(res)
        return res

    def level_into(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        if row is None or stage is None:
            log.warning("5_2201 for stage %d: no such stage (%d)", lvl, STATUS_STAGE_LOCKED)
            return _refused(FLAG_STAGE_CHANGED)
        session.player_id = int(row["id"])
        row = db.refresh_energy(conn, cfg, row)
        progress = db.level_progress(conn, int(row["id"]), lvl)

        if not is_unlocked(cfg, conn, row, lvl):
            log.warning("5_2201 stage %d is locked (%d)", lvl, STATUS_STAGE_LOCKED)
            return _refused(FLAG_STAGE_CHANGED)
        if progress is not None and int(stage["once"]) == 1 and int(progress["star"]) > 0:
            log.info("5_2201 stage %d is a once-only stage already cleared", lvl)
            return _refused(FLAG_STAGE_CHANGED, star=int(progress["star"]))
        maxcount = int(stage["maxcount"] or 0)
        if maxcount and progress is not None and int(progress["count"]) >= maxcount:
            return _refused(FLAG_MAX_TIMES, star=int(progress["star"]))

        cost = int(stage["energy"] or 0)
        if int(row["energy"]) < cost:
            log.warning(
                "5_2201 stage %d needs %d energy, player has %d; the client cannot be "
                "told status %d on 5_2202 (no status field), answering flag 1",
                lvl, cost, int(row["energy"]), STATUS_NOT_ENOUGH_ENERGY,
            )
            return _refused(FLAG_STAGE_CHANGED, star=0 if progress is None
                            else int(progress["star"]))

        if cost:
            db.spend_energy(conn, int(row["id"]), cost)
        rolled = drops.roll(cfg, int(stage["visible_drops"] or 0))
        rolled += drops.roll(cfg, int(stage["invisible_drops"] or 0))
        session.data.setdefault(PENDING_KEY, {})[lvl] = rolled

        res = registry.message_class("LevelIntoRes")(flag=FLAG_OK, star=0)
        for value in roll_urandom():
            res.urandom.append(value)
        for entry in drops.to_prize_entries(registry, rolled):
            res.drop.add().CopyFrom(entry)
        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        notify.player_changed(registry, session, {"energy": int(fresh["energy"])})
        log.info(
            "stage %d entered by player %d, %d energy spent, drops %s",
            lvl, int(row["id"]), cost,
            [(d.category, d.refer, d.amount) for d in rolled],
        )
        fill_required(res)
        return res

    return {(5, 2201): level_into}
```

- [ ] **Step 6: Register the module in `server/__main__.py`**

```python
    handlers.update(level.handlers(registry, settings, conn, cfg))
```

- [ ] **Step 7: Run the tests, then the suite**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa` then the full suite.
Expected: `9 passed`, suite green.

- [ ] **Step 8: Commit**

```bash
git add server/modules/level.py server/__main__.py tests/test_level.py
git commit -m "feat(server): LevelIntoReq validates the unlock, spends energy and pre-rolls drops"
```

**Done looks like:** entering stage 1-1 answers 64 randoms and the certain 粗布头巾 x2 drop, costs 6 energy, pushes the new energy to the client, and a locked stage is refused without spending anything.

---

### Task 14: `5_2203 LevelOutReq` — trust the star, pay out, unlock the next stage

**Files:**
- Modify: `server/modules/level.py`, `server/db.py` (`add_player_xp`, `add_hero_xp`)
- Test: `tests/test_level.py`

**Interfaces:**
- Consumes: everything Task 13 produced, plus `item.grant_prizes`, `notify.level_up`, `Config.xp_for_level`.
- Produces:
  - `server.db.add_player_xp(conn, cfg, player_id, amount) -> dict` returning `{"before": (level, xp, energy, max_energy), "after": (level, xp, energy, max_energy), "levelled": bool}`. Levelling loops while `xp >= xp_for_level(level).player_xp_for_next_level`, subtracts that cost, adds `levelup_recovery_energy` of the new level and re-reads `max_energy` from the new level row.
  - `server.db.add_hero_xp(conn, cfg, player_id, entries, amount) -> list[tuple[int, int, int]]` returning `(entry, level, xp)` per hero it touched. A hero levels while `xp >= hero_xp_for_next_level(hero level)` and `level < hero_max_level(player level)`.
  - `level.handlers` gains `(5, 2203)`.

**Rulings this task implements.**
- `star` is trusted (`LevelOutReq.star`, spec section 4 and the brief). It is clamped to 0..3.
- A `LevelOutReq` whose level has no pending entry on the session is answered `status = 328196` (没有进入关卡), which `BattleFactoryBase:requestServerInfo` turns into "back to the main city" and `MMMsgDispatcher` floats. This also covers the brief phrase "answered with the stage locked status": 328196 is the exact code for this case, 328193 is for a stage that is locked or unknown.
- The pending entry is **popped** before anything is granted, so the 6-second retry in `requestServerInfo` cannot pay twice (Review Focus 1).
- `LevelOutRes.heroes` entries use the hero **entry** as `refer`, not the row id: `BattleFactoryLevel:toExpInfo` keys them by `v.refer` and `BattleEndLayer` looks them up by `unit:getValue(BattleDefine.entry)`. `owner.refer` is the player id, which nothing reads.
- `warn` is never set and `fight` is never sent: `needCheckWarn` turns `warn == true` into a cheat alert, and `checkNeddReportServer` only touches `resData.fight` behind a nil guard.
- No angel exists in Plan B1, so the optional `angel` field is left absent; `toExpInfo` guards it with `if serExpInfo.angel then`.

- [ ] **Step 1: Write the failing tests, appended to `tests/test_level.py`**

```python
def _fight(handlers, session, reg, lvl, star, heroes=(100000,)):
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=lvl))
    req = reg.message_class("LevelOutReq")(level=lvl, star=star, angel=0)
    for entry in heroes:
        req.heroes.append(entry)
    return handlers[(5, 2203)](session, req)


def test_a_cleared_stage_pays_xp_gold_drops_and_unlocks_the_next(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    from server.db import grant_hero, items_of
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    res = _fight(handlers, session, reg, 10000, star=3)
    assert res.status == 0
    assert res.star == 3
    row = find_player(conn, "stefan")
    # stage 10000: player_xp 6, gold 516, energy 6 spent
    assert int(row["gold"]) == 1280000 + 516
    assert int(row["last_level"]) == 10000
    assert int(row["energy"]) == 54
    prog = conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = 10000", (pid,)
    ).fetchone()
    assert (int(prog["star"]), int(prog["count"])) == (3, 1)
    assert {int(i["entry"]) for i in items_of(conn, pid)} >= {10000}
    assert res.owner.level >= 1
    assert [h.refer for h in res.heroes] == [100000]
    res.SerializeToString()


def test_level_out_twice_grants_once(reg, cfg, world) -> None:
    """Review Focus 1: requestServerInfo retries the same 5_2203 after 6 s."""
    conn, pid, handlers, session = world
    from server.db import grant_hero
    grant_hero(conn, pid, 100000, 10, star=1, level=1)

    first = _fight(handlers, session, reg, 10000, star=3)
    gold_after_first = int(find_player(conn, "stefan")["gold"])
    again = reg.message_class("LevelOutReq")(level=10000, star=3, angel=0)
    again.heroes.append(100000)
    second = handlers[(5, 2203)](session, again)
    assert first.status == 0
    assert second.status == 328196                  # language.db 没有进入关卡
    assert int(find_player(conn, "stefan")["gold"]) == gold_after_first


def test_a_loss_keeps_the_stage_locked_and_pays_nothing(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    res = _fight(handlers, session, reg, 10000, star=0)
    assert res.status == 0
    row = find_player(conn, "stefan")
    assert int(row["last_level"]) == 0
    assert int(row["gold"]) == 1280000
    prog = conn.execute(
        "SELECT * FROM levels WHERE player_id = ? AND level = 10000", (pid,)
    ).fetchone()
    assert int(prog["star"]) == 0
    assert int(prog["count"]) == 1


def test_player_xp_levels_up_and_notifies(reg, cfg, world) -> None:
    """xp_for_level lvl 1 needs 12 player xp; stage 10000 pays 6 per clear."""
    conn, pid, handlers, session = world
    _fight(handlers, session, reg, 10000, star=3)
    session.outbox.clear()
    _fight(handlers, session, reg, 10000, star=3)
    row = find_player(conn, "stefan")
    assert int(row["level"]) == 2
    assert int(row["max_energy"]) == 62
    assert (5, 2036) in [(s, c) for (s, c, _m) in session.outbox]


def test_a_level_out_for_the_wrong_stage_is_refused(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    handlers[(5, 2201)](session, reg.message_class("LevelIntoReq")(level=10000))
    req = reg.message_class("LevelOutReq")(level=10012, star=3, angel=0)
    assert handlers[(5, 2203)](session, req).status == 328196
```

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa`
Expected: `KeyError: (5, 2203)`.

- [ ] **Step 3: Add the xp helpers to `server/db.py`**

```python
def add_player_xp(conn, cfg, player_id: int, amount: int) -> dict:
    """xp_for_level.player_xp_for_next_level is the cost of the next level, and
    levelup_recovery_energy is the energy a level-up hands out (it is not the
    regeneration rate: that is variables.PLAYER_ENERGY_RECOVER)."""
    row = conn.execute("SELECT * FROM players WHERE id = ?", (int(player_id),)).fetchone()
    before = (int(row["level"]), int(row["xp"]), int(row["energy"]), int(row["max_energy"]))
    level, xp, energy, max_energy = before
    while True:
        need_row = cfg.xp_for_level(level)
        if need_row is None:
            break
        need = int(need_row["player_xp_for_next_level"] or 0)
        if need <= 0 or xp + amount < need:
            break
        amount -= need - xp
        xp = 0
        level += 1
        new_row = cfg.xp_for_level(level)
        if new_row is None:
            level -= 1
            break
        max_energy = int(new_row["max_energy"])
        energy = min(max_energy, energy + int(new_row["levelup_recovery_energy"] or 0))
    xp += amount
    conn.execute(
        "UPDATE players SET level = ?, xp = ?, energy = ?, max_energy = ? WHERE id = ?",
        (level, xp, energy, max_energy, int(player_id)),
    )
    conn.commit()
    after = (level, xp, energy, max_energy)
    return {"before": before, "after": after, "levelled": after[0] != before[0]}


def add_hero_xp(conn, cfg, player_id: int, entries, amount: int) -> list:
    """One xp grant per hero entry that fought. A hero cannot pass
    xp_for_level(player level).hero_max_level."""
    player = conn.execute(
        "SELECT * FROM players WHERE id = ?", (int(player_id),)
    ).fetchone()
    caps = cfg.xp_for_level(int(player["level"]))
    cap = int(caps["hero_max_level"]) if caps else 1
    out: list[tuple[int, int, int]] = []
    for entry in {int(e) for e in entries if int(e)}:
        row = conn.execute(
            "SELECT * FROM heroes WHERE player_id = ? AND entry = ? ORDER BY id",
            (int(player_id), entry),
        ).fetchone()
        if row is None:
            continue
        level, xp = int(row["level"]), int(row["xp"]) + int(amount)
        while level < cap:
            need_row = cfg.xp_for_level(level)
            need = int(need_row["hero_xp_for_next_level"] or 0) if need_row else 0
            if need <= 0 or xp < need:
                break
            xp -= need
            level += 1
        conn.execute(
            "UPDATE heroes SET level = ?, xp = ? WHERE id = ?", (level, xp, int(row["id"]))
        )
        out.append((entry, level, xp))
    conn.commit()
    return out
```

- [ ] **Step 4: Write `level_out` in `server/modules/level.py`**

```python
    def level_out(session: Session, req):
        lvl = int(req.level)
        row = _player(session)
        stage = cfg.stage(lvl)
        pending = session.data.get(PENDING_KEY, {})
        if row is None or stage is None:
            res = registry.message_class("LevelOutRes")(status=STATUS_STAGE_LOCKED)
            fill_required(res)
            return res
        if lvl not in pending:
            log.warning(
                "5_2203 for stage %d with no matching 5_2201 on this session, "
                "answering %d", lvl, STATUS_NOT_ENTERED,
            )
            res = registry.message_class("LevelOutRes")(status=STATUS_NOT_ENTERED)
            fill_required(res)
            return res

        # Popped before anything is granted: the client retries 5_2203 twice
        # more after a 6 s timeout (BattleFactoryBase.lua:871-930).
        rolled = pending.pop(lvl)
        player_id = int(row["id"])
        star = max(0, min(3, int(req.star)))
        won = star > 0

        db.upsert_level(conn, player_id, lvl, star=star, count_delta=1)
        res = registry.message_class("LevelOutRes")(status=0, star=star)

        granted = {"gold": int(row["gold"]), "diamond": int(row["diamond"]), "items": []}
        hero_xp: list[tuple[int, int, int]] = []
        xp_change = {"before": None, "after": None, "levelled": False}
        if won:
            prizes = drops.as_triples(rolled)
            prizes.append((item.CATEGORY_GOLD, 0, int(stage["gold"] or 0)))
            granted = item.grant_prizes(conn, cfg, player_id, prizes)
            xp_change = db.add_player_xp(conn, cfg, player_id, int(stage["player_xp"] or 0))
            hero_xp = db.add_hero_xp(
                conn, cfg, player_id, list(req.heroes), int(stage["unit_xp"] or 0)
            )
            if lvl == frontier(cfg, row):
                db.set_last_level(conn, player_id, lvl)
            for entry in drops.to_prize_entries(registry, rolled):
                res.drop.add().CopyFrom(entry)
            gold_entry = res.drop.add()
            gold_entry.category = item.CATEGORY_GOLD
            gold_entry.refer = 0
            gold_entry.amount = int(stage["gold"] or 0)

        fresh = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        # BattleEndLayer reads owner.xp and owner.level; refer is unused there.
        res.owner.refer = player_id
        res.owner.level = int(fresh["level"])
        res.owner.xp = int(fresh["xp"])
        for entry, hlevel, hxp in hero_xp:
            # refer is the hero entry: toExpInfo keys heroes by v.refer and
            # BattleEndLayer looks them up by the unit entry.
            client_xp = res.heroes.add()
            client_xp.refer = entry
            client_xp.level = hlevel
            client_xp.xp = hxp

        if won:
            notify.items_changed(registry, session, granted["items"])
            notify.player_changed(registry, session, {
                "gold": int(fresh["gold"]), "diamond": int(fresh["diamond"]),
                "xp": int(fresh["xp"]), "level": int(fresh["level"]),
                "energy": int(fresh["energy"]), "max_energy": int(fresh["max_energy"]),
                "last_level": int(fresh["last_level"]),
            })
            if xp_change["levelled"]:
                before = xp_change["before"]
                after = xp_change["after"]
                notify.level_up(
                    registry, session,
                    (before[0], before[2], before[3]), (after[0], after[2], after[3]),
                )
        log.info(
            "stage %d finished by player %d with %d star(s), won=%s", lvl, player_id,
            star, won,
        )
        fill_required(res)
        return res
```

Add `(5, 2203): level_out` to the returned dict and `from server.modules import item, notify` at the top of the module.

- [ ] **Step 5: Run the tests, then the suite**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa` then the full suite.
Expected: `14 passed` in that file, suite green.

- [ ] **Step 6: Commit**

```bash
git add server/modules/level.py server/db.py tests/test_level.py
git commit -m "feat(server): LevelOutReq grants xp, gold and drops and unlocks the next stage"
```

**Done looks like:** clearing stage 1-1 at 3 stars adds 516 gold, the rolled items, 6 player xp and 20 hero xp, sets `last_level = 10000`, pushes the changes, and a retried `5_2203` is refused with 328196 instead of paying again.

---

### Task 15: the chapter chest `5_2209`, and honest refusals for `5_2205` / `5_2207`

**Files:**
- Modify: `server/modules/level.py`
- Test: `tests/test_level.py`

**Interfaces:**
- Consumes: `Config.chapter`, `Config.stages_in_chapter`, `db.levels_of`, `db.set_chapter_award`, `db.chapters_of`, `drops.roll`, `item.grant_prizes`.
- Produces: `level.handlers` gains `(5, 2209): chapter_prize`, `(5, 2205): level_clean`, `(5, 2207): level_reset`, plus `level.chapter_stars(cfg, conn, player_id, chapter) -> int`.

**Rulings.**
- `LevelChapterPrizeReq{chapter, prize}` with `prize = 0` is the only form the chapter-1 UI sends (`LevelBoxStarPanel:regUI` builds `{chapter = self.chapterInfo.entry, prize = 0}`). The reward is `chapter_info.award0` rolled through the same drop chain; chapter 1 pays 600 diamonds, item 104000 x6, 60,000 gold and item 1100 x12, all at probability 1.
- `LevelChapterPrizeRes` must carry **both** `status = 0` and `chapter`: the listener does `g_levelManager:getChapterByEntry(msg.chapter)` and bails out silently when that is nil.
- Not enough stars is `328197 星级不够`; already claimed is `328194 关卡不可重复刷` (the closest real code, and the client floats it as text).
- Sweep and reset are **not implemented** in Plan B1. `5_2207` answers `LevelResetRes{status = 328202, reset_count = 0}`, which the client floats as 达到关卡重置限制 and `DesBuyPanel:onReset` ignores. `5_2205` answers `LevelCleanRes{flag = 2, times = 0}` with empty lists; field 1 of that message is named `flag`, not `status` (settled point 13), so it cannot float an error, and an explicit handler at least keeps the log honest about the refusal instead of letting the zero-stub policy claim success.

- [ ] **Step 1: Write the failing tests, appended to `tests/test_level.py`**

```python
def test_chapter_stars_add_up_across_the_chapter(reg, cfg, world) -> None:
    conn, pid, _h, _s = world
    upsert_level(conn, pid, 10000, star=3)
    upsert_level(conn, pid, 10010, star=2)
    assert level.chapter_stars(cfg, conn, pid, 10000) == 5


def test_the_chapter_chest_pays_award0_once(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    for entry in (10000, 10010, 10012):
        upsert_level(conn, pid, entry, star=3)       # 9 stars, star_req0 of chapter 1
    before = int(find_player(conn, "stefan")["diamond"])
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert res.status == 0
    assert res.chapter == 10000
    row = find_player(conn, "stefan")
    assert int(row["diamond"]) == before + 600
    assert int(row["gold"]) == 1280000 + 60000
    assert [(int(c["chapter"]), int(c["award"])) for c in
            __import__("server.db", fromlist=["x"]).chapters_of(conn, pid)] == [(10000, 1)]

    again = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert again.status == 328194                   # language.db 关卡不可重复刷
    assert int(find_player(conn, "stefan")["diamond"]) == before + 600
    res.SerializeToString()


def test_too_few_stars_is_refused(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    upsert_level(conn, pid, 10000, star=1)
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=10000, prize=0)
    )
    assert res.status == 328197                     # language.db 星级不够


def test_an_unknown_chapter_is_refused(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    res = handlers[(5, 2209)](
        session, reg.message_class("LevelChapterPrizeReq")(chapter=424242, prize=0)
    )
    assert res.status != 0


def test_sweep_and_reset_refuse_in_the_client_own_language(reg, cfg, world) -> None:
    _conn, _pid, handlers, session = world
    clean = handlers[(5, 2205)](
        session, reg.message_class("LevelCleanReq")(level=10000, times=1)
    )
    assert clean.flag == 2
    assert len(clean.drops) == 0 and len(clean.reward) == 0
    clean.SerializeToString()
    reset = handlers[(5, 2207)](
        session, reg.message_class("LevelResetReq")(level=10000)
    )
    assert reset.status == 328202                   # language.db 达到关卡重置限制
    assert reset.reset_count == 0
    reset.SerializeToString()
```

The `__import__` line in the chest test is ugly; import `chapters_of` at the top of the file instead and use it directly.

- [ ] **Step 2: Run them to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa`
Expected: `KeyError: (5, 2209)`.

- [ ] **Step 3: Implement them in `server/modules/level.py`**

Module-level constants and helper:

```python
STATUS_ALREADY_CLAIMED = 328194     # language.db 关卡不可重复刷
STATUS_NOT_ENOUGH_STARS = 328197    # language.db 星级不够
STATUS_RESET_LIMIT = 328202         # language.db 达到关卡重置限制


def chapter_stars(cfg: Config, conn: sqlite3.Connection, player_id: int, chapter: int) -> int:
    entries = {int(r["entry"]) for r in cfg.stages_in_chapter(chapter)}
    return sum(
        int(r["star"]) for r in db.levels_of(conn, player_id)
        if int(r["level"]) in entries
    )
```

Handlers, inside `handlers(...)`:

```python
    def chapter_prize(session: Session, req):
        chapter = int(req.chapter)
        row = _player(session)
        info = cfg.chapter(chapter)
        if row is None or info is None:
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_STAGE_LOCKED, chapter=chapter
            )
            fill_required(res)
            return res
        player_id = int(row["id"])
        claimed = {
            int(c["chapter"]): int(c["award"]) for c in db.chapters_of(conn, player_id)
        }
        if claimed.get(chapter):
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_ALREADY_CLAIMED, chapter=chapter
            )
            fill_required(res)
            return res
        need = int(info["star_req0"] or 0)
        have = chapter_stars(cfg, conn, player_id, chapter)
        if have < need:
            log.info("chapter %d chest needs %d stars, player has %d", chapter, need, have)
            res = registry.message_class("LevelChapterPrizeRes")(
                status=STATUS_NOT_ENOUGH_STARS, chapter=chapter
            )
            fill_required(res)
            return res

        rolled = drops.roll(cfg, int(info["award0"] or 0))
        granted = item.grant_prizes(conn, cfg, player_id, drops.as_triples(rolled))
        db.set_chapter_award(conn, player_id, chapter, 1)
        notify.items_changed(registry, session, granted["items"])
        notify.player_changed(registry, session, {
            "gold": granted["gold"], "diamond": granted["diamond"],
        })
        log.info(
            "chapter %d chest paid to player %d: %s", chapter, player_id,
            [(d.category, d.refer, d.amount) for d in rolled],
        )
        # The client renders the reward panel itself from chapter_info.award0;
        # it only needs status 0 and the chapter back (LevelBoxStarPanel.lua:78).
        res = registry.message_class("LevelChapterPrizeRes")(status=0, chapter=chapter)
        fill_required(res)
        return res

    def level_clean(session: Session, req):
        # Sweep is Plan B3. LevelCleanRes field 1 is flag, not status, so this
        # cannot float an error text; flag 2 is the clients own "max times".
        log.info("5_2205 sweep of stage %s is not implemented in Plan B1", req.level)
        res = registry.message_class("LevelCleanRes")(flag=FLAG_MAX_TIMES, times=0)
        fill_required(res)
        return res

    def level_reset(session: Session, req):
        log.info("5_2207 reset of stage %s is not implemented in Plan B1", req.level)
        res = registry.message_class("LevelResetRes")(
            status=STATUS_RESET_LIMIT, reset_count=0
        )
        fill_required(res)
        return res
```

and extend the returned dict to

```python
    return {
        (5, 2201): level_into,
        (5, 2203): level_out,
        (5, 2205): level_clean,
        (5, 2207): level_reset,
        (5, 2209): chapter_prize,
    }
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `py -3.14 -m pytest -q tests/test_level.py --basetemp=C:/tmp/pytest-loa` then the full suite.
Expected: `19 passed` in that file, suite green.

- [ ] **Step 5: Commit**

```bash
git add server/modules/level.py tests/test_level.py
git commit -m "feat(server): chapter star chest, and explicit refusals for sweep and reset"
```

**Done looks like:** 9 stars in chapter 1 pays 600 diamonds, 60,000 gold and two item stacks exactly once, a second claim floats 关卡不可重复刷, and a sweep or reset attempt is refused in the client own words instead of silently appearing to work.

---

### Task 16: `tools/fake_client.py --stage` replays a chapter-1 fight

**Files:**
- Modify: `tools/fake_client.py`
- Test: `tests/test_fake_client.py`

**Interfaces:**
- Consumes: the running server over a real socket; `Conn.call`.
- Produces: `tools.fake_client.replay_stage(conn, reg, level=10000, star=3, heroes=None) -> dict` returning `{"into": LevelIntoRes, "out": LevelOutRes}`, and `replay(host, port, username, reg, stage=None)` which runs the login burst and, when `stage` is given, the stage fight on the same game connection. `main` gains `--stage` (default none) and `--star` (default 3).

**Why on the same connection:** the pre-rolled drops live on the session (Task 13), so a second connection would be answered 328196.

- [ ] **Step 1: Write the failing test, appended to `tests/test_fake_client.py`**

```python
def test_replay_stage_fights_chapter_one_stage_one(reg, settings, tmp_path) -> None:
    """End to end over a socket: login burst, then LevelIntoReq and LevelOutReq
    on the same connection."""
    import asyncio

    from server.config import Config
    from server.db import connect, find_player
    from server.modules import gacha, guide, level, login, player
    from server.net.server import Server
    from tools.fake_client import replay

    cfg = Config.load(Path(".stock"))
    conn = connect(settings.db_path)
    handlers = {}
    handlers.update(login.handlers(reg, settings, conn, cfg))
    handlers.update(player.handlers(reg, settings, conn, cfg))
    handlers.update(guide.handlers(reg, settings, conn))
    handlers.update(gacha.handlers(reg, settings, conn, cfg))
    handlers.update(level.handlers(reg, settings, conn, cfg))
    server = Server(reg, settings, handlers, bind_host="127.0.0.1")

    async def scenario() -> None:
        ready = asyncio.Event()
        task = asyncio.create_task(server.serve(ready))
        await asyncio.wait_for(ready.wait(), 5)
        answered = await replay("127.0.0.1", server.port, "stefan", reg, stage=10000)
        assert (5, 2202) in answered
        assert (5, 2204) in answered
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    row = find_player(conn, "stefan")
    assert int(row["last_level"]) == 10000
    assert int(row["energy"]) == 54
    cfg.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_fake_client.py --basetemp=C:/tmp/pytest-loa`
Expected: `TypeError: replay() got an unexpected keyword argument stage`.

- [ ] **Step 3: Extend `tools/fake_client.py`**

```python
async def replay_stage(game, reg, level: int = 10000, star: int = 3, heroes=None) -> dict:
    """LevelIntoReq then LevelOutReq, on the connection the login burst used:
    the pre-rolled drops live on that session."""
    into_body = reg.message_class("LevelIntoReq")(level=level).SerializeToString()
    frame = await game.call(5, 2201, into_body)
    into = reg.message_class("LevelIntoRes")()
    into.ParseFromString(frame.body)
    assert into.flag == 0, f"stage {level} refused with flag {into.flag}"
    assert len(into.urandom) == 64, len(into.urandom)
    assert all(v < 10000 for v in into.urandom)

    out_req = reg.message_class("LevelOutReq")(level=level, star=star, angel=0)
    for entry in heroes or [100000]:
        out_req.heroes.append(entry)
    frame = await game.call(5, 2203, out_req.SerializeToString())
    out = reg.message_class("LevelOutRes")()
    out.ParseFromString(frame.body)
    assert out.status == 0, out.status
    print(
        f"stage {level}: {out.star} star(s), owner level {out.owner.level} "
        f"xp {out.owner.xp}, {len(out.drop)} prize entries"
    )
    return {"into": into, "out": out}
```

In `replay`, add the parameter `stage: int | None = None` and `star: int = 3`, and after the main-city burst and before the heartbeat:

```python
    if stage is not None:
        result = await replay_stage(game, reg, level=stage, star=star)
        answered.append((5, 2202))
        answered.append((5, 2204))
        del result
```

In `main`, add the two arguments. **No literal percent sign in any help string** (Python 3.14 reads it as a format directive):

```python
    parser.add_argument("--stage", type=int, default=None,
                        help="also replay a campaign stage, e.g. 10000 for 1-1")
    parser.add_argument("--star", type=int, default=3,
                        help="the star count to report for that stage, 0 to 3")
```

and pass them into `replay`.

- [ ] **Step 4: Run it against a live server**

Run, in two Git Bash windows from the repo root:

```bash
rm -f data/player.db
py -3.14 -m server
```

```bash
py -3.14 tools/fake_client.py --port 8112 --stage 10000 --star 3
```

Expected: the login lines from Plan A, then `stage 10000: 3 star(s), owner level 1 xp 6, 3 prize entries` (the exact prize count varies with the invisible-drop roll), then `answered ...` lines including `5_2202` and `5_2204`.

- [ ] **Step 5: Run the suite and commit**

```bash
py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa
git add tools/fake_client.py tests/test_fake_client.py
git commit -m "feat(tools): fake client replays a chapter-1 stage fight"
```

**Done looks like:** `py -3.14 tools/fake_client.py --stage 10000` drives a complete stage against a live server and leaves `last_level = 10000`, 54 energy and the drops in the database.

---

### Task 17: emulator acceptance run on `LOA_API30`

**Files:**
- Modify: `docs/dev-loop.md` (a new section 7, "Milestone 2 acceptance run"), `docs/TODO.md`
- No source changes. If this task finds a bug it is reported and fixed in a follow-up task, not folded in here.

**Interfaces:** none.

**Preconditions:** every earlier task committed, suite green, the APK already installed on the AVD from Plan A. No rebuild is needed: nothing under `client/` changed, `settings.toml` `[net] host` stays `10.0.2.2`, the assets are untouched.

- [ ] **Step 1: Start a fresh world**

```bash
cd "/c/Users/Stefan.Nasev/Downloads/Claude Cowork/Claude Code/Projects/loa-private-server"
rm -f data/player.db
py -3.14 -m server > /c/tmp/loa-server-b1.log 2>&1 &
```

Expected in the log: `listening on 0.0.0.0:8112` and the `advertising game address 10.0.2.2:8112` line.

- [ ] **Step 2: Boot the AVD detached and launch the app**

Use the exact `Start-Process` line and the boot wait from `docs/dev-loop.md` section 4, then:

```bash
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"; A="$SDK/platform-tools/adb.exe"
"$A" logcat -c
"$A" shell am start -n bg.stefan.loa/.GameActivity
```

- [ ] **Step 3: Drive the tutorial and screenshot each milestone**

Tap through the guide. Screenshot after each of these, with these exact names:

```bash
mkdir -p /c/tmp/loa-b1
shot () { "$A" shell screencap -p /sdcard/$1.png && "$A" pull /sdcard/$1.png "C:/tmp/loa-b1/$1.png"; }
shot b1-01-guide-summon        # the guide hand on the tavern draw button
shot b1-02-guide-battle        # the guide battle, before its result screen
shot b1-03-city-after-tutorial # the main city after the first campaign fight
shot b1-04-campaign-chapter1   # the chapter-1 map, stage 2 unlocked
shot b1-05-bag-with-drops      # the bag showing the stage 1-1 equipment drop
shot b1-06-chapter-chest       # the chapter-1 star chest paid out
```

- [ ] **Step 4: Assert the five milestone facts**

1. The intro movie and the guide battle play once, and `grep -c "saved for player" /c/tmp/loa-server-b1.log` is at least 1.
2. `adb shell am force-stop bg.stefan.loa`, then relaunch: **the main city appears with no intro and no guide battle.** That is the definition of done for the first half of the milestone.
3. The energy readout drops by 6 on entering stage 1-1, with no relog.
4. Stage 2 (战斧要塞1) is unlocked on the map and the stars on stage 1-1 match the fight.
5. Stop the server, start it again, relaunch the app: stars, energy, bag and unlocks are unchanged.

Then grep for anything the server could not answer:

```bash
grep -E "no handler for|answering a zero stub|sending nothing|Traceback" /c/tmp/loa-server-b1.log | sort -u
"$A" logcat -d > /c/tmp/loa-b1/logcat.txt
grep -E "LUA ERROR|FATAL|AndroidRuntime" /c/tmp/loa-b1/logcat.txt
```

Expected: zero `LUA ERROR`, zero tracebacks. Unanswered ids are expected and are the Plan B2 and B3 worklist; copy that sorted list into the task report verbatim.

- [ ] **Step 5: Write `docs/dev-loop.md` section 7**

One table of the six screenshots with what each proves, the five assertions with their observed outcome, the unanswered-id list, and the outcome of open questions A, B, C, D and E. Dates render dd-mm-yyyy.

- [ ] **Step 6: Update `docs/TODO.md`**

Move the Plan B1 bullet into a Done section with the commit range and the test count, leave Plan B2 as the next item, and say plainly that Stefan own emulator pass is the gate and has not happened yet. The wording is "ready for your emulator pass", never "done" or "shipped".

- [ ] **Step 7: Commit**

```bash
git add docs/dev-loop.md docs/TODO.md
git commit -m "docs: milestone 2 emulator acceptance run and the Plan B1 status"
```

**Done looks like:** six named screenshots under `C:/tmp/loa-b1/`, the five assertions recorded with their outcome, and a written answer for each open question A to E.

---

## Risks

1. **The guide may point at the equip flow and lock the screen.** `NewGuideManager` masks the whole screen while a guide point is active and only passes clicks inside its hotspot. Finding 4 says an unregistered node self-clears, but the equip chain (10180 to 10241) does have registered nodes, so the pointer will appear and the equip request will be answered by the zero-stub policy. Mitigation: Task 17 assertion 2 only needs the guide not to replay; if the pointer wedges the city, the report says so and the fix (one more guide step, or writing `guide_id = 14302` once) is a Plan B2 task.
2. **The pending drops live on the session.** A dropped connection or a server restart between `LevelIntoReq` and `LevelOutReq` loses the entry: the player is out 6 energy with no reward and the next `5_2203` is answered 328196, which sends the client back to the main city. That is the brief decision; a `level_pending` table is the Plan B2 alternative if it ever bites.
3. **`ClientNotification.flags` byte order** (open question A). Worst case the client updates the wrong field in its local copy until the next login, which `QueryMyselfRes` corrects. Task 9 step 6 settles it before Tasks 11 and 14 depend on it.
4. **Hero spells** (open question D). If `npc_info.skill0..skill4` is not what the real server sent, the hero fights with the wrong ultimate or none. It cannot crash: `BattleUnit:initByHeroData` skips zero ids and `initSkillInfo` handles the rest.
5. **The unique index on `items`.** `CREATE UNIQUE INDEX IF NOT EXISTS items_player_entry` raises on a database that already holds duplicate `(player_id, entry)` rows. Plan A never wrote an items row, so it cannot happen here; if it does, the implementer reports rather than deleting rows.
6. **Two handler signatures change.** Task 4 adds `cfg` to `player.handlers`, Task 6 adds `cfg` to `login.handlers`. Every call site in `tests/` and `server/__main__.py` moves with them, and a missed keyword is a silent wrong-slot bug rather than an error, which is why both tasks carry an explicit grep step.
7. **Chapter 1 only has 15 stars available and the chest needs 9**, so the chest needs three 3-star clears (or more two-star ones). If the client battle is lost repeatedly the chest stays shut; that is correct behaviour, not a bug, and Task 17 step 3 screenshot 6 may need a few replays of stage 10000 and 10012 (both `once = 0`).

## Out of scope for Plan B1

Hero level-up, star-up, gear, equip, awaken, runes, signets, gemstones (Plan B2). Angels beyond the fields `QueryMyselfRes` already carries. Sign-in, shop, mail with attachments, tasks and events (Plan B3). Arena, guild, cross-server, events, chat, friends, payments, anti-cheat. English text (Plan C). Elite and王者 chapters; sweep and reset mechanics (refused explicitly in Task 15). The phone build and the S20 Ultra pass. Any server-side battle engine: `star` is trusted.

## Self-review

Run against the brief and the spec with fresh eyes, 23-10-2026.

**Brief coverage.** Scope 1, tutorial and persistence: Tasks 3 and 17, with the finish line defined in open question E. Scope 2, hero summon and the minimum hero module: Tasks 6, 7, 11. Scope 3, campaign chapter 1 including energy and `max_energy`: Tasks 5, 12, 13, 14, 15. Scope 4, inventory and items: Tasks 6 and 8. Scope 5, the Plan A parked items: `5_2041` in Task 3, `5_2944` in Task 4, the log wording plus `[net] bind` plus `.gitattributes` in Task 1, energy from the config in Task 5. Scope 6, the config layer: Task 2. The emulator acceptance run with named screenshots: Task 17. The fake-client stage replay: Task 16.

**Where the code contradicts the brief, resolved here rather than silently.**
- Energy regeneration comes from `variables.PLAYER_ENERGY_RECOVER_CYCLE` and `PLAYER_ENERGY_RECOVER`, not from `xp_for_level.levelup_recovery_energy`, which is the level-up bonus (settled point 9, Task 5). `max_energy` does come from `xp_for_level` as the brief says.
- A `LevelOutReq` with no matching `LevelIntoReq` is answered `328196 没有进入关卡`, the exact code for that case, not the "stage locked" code `328193` the brief names (Task 14).
- The guide battle sends neither `LevelIntoReq` nor `LevelOutReq` (settled point 2): the brief question about it has a negative answer and therefore no task.
- `LevelIntoRes` has no `status` field, so energy and lock refusals travel in `flag`, and `327939` only reaches the log (Task 13).
- The first hero is granted at character creation from `variables.HERO_FIRST_ENTRY`, not by the gacha: `LineFrame:startFight` refuses a stage with no hero on the field, and the guide reaches the campaign before any draw is guaranteed to produce one (Task 6).

**Placeholder scan.** No TBD, no "add error handling", no "similar to Task N". Every code step carries its code and every test step its assertions.

**Type consistency.** `handlers(registry, settings, conn)` for `guide`; `handlers(registry, settings, conn, cfg)` for `player`, `login`, `gacha` and `level`. `build_query_myself_res(registry, cfg, conn, row)` from Task 7 onward. `Drop(category, refer, amount)` throughout. `grant_prizes` returns the keys `gold`, `diamond`, `energy`, `items`, `heroes`, read under those names in Tasks 11, 14 and 15. `PENDING_KEY` is defined in Task 13 and used in Tasks 13, 14 and 16. `notify.player_changed` takes a dict of `ClientPlayer.PLAYER_FIELD_DIC` names in every caller.

**Review Focus.** All five lines have a named test in the task that owns the code: Task 14 `test_level_out_twice_grants_once`, Task 7 `test_client_hero_quality_exists_in_hero_quality`, Task 12 `test_chapters_only_contains_real_chapter_entries`, Task 13 `test_urandom_is_64_values_under_10000`, and Tasks 4 and 11 `test_bt_cards_carries_both_privilege_cards` plus `test_gacha_res_always_has_at_least_one_item`.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-21-plan-b1-tutorial-and-campaign.md`. Please review it. The brief already names the execution method (subagent-driven, a sonnet pre-flight scan first, per-task reviews, then the emulator acceptance run), so the only question is: does this plan capture what you want?
