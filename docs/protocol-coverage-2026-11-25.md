# LOA protocol coverage — 25-11-2026 (recomputed from the code at 02f70ab)

Replaces the scout inventory of 23-11-2026 (`docs/coverage-2026-11-23.md`, commit c4ac843:
513 Req, 15 handled). Every number below was recomputed on 25-11-2026 from the code and the
stock client, not copied.

## Method

1. **Req ids.** Every `id_<svc>_<cmd> = "...Req"` in the client's
   `.stock/assets/res/utils/net/msgIDMap.lua`, parsed by `server/net/msgmap.py` (a later duplicate
   key overwrites, as in Lua). A Req has a Res when `msgmap.res_key` finds `cmd + 1` named
   `<Name>Res`.
2. **Handled.** The keys of `server.__main__.build_handlers(registry, settings)` built against a
   throwaway `player.db` (21 modules registered: login, player, guide, gacha, level, team, angel,
   hero, chat, checkin, mail, buy, shop, bag, train, activity, events, goldtrial, herotrial,
   angeltrial, rune). 118 keys, all Req ids.
3. **Status.**
   - **IMPL**: a handler with real behaviour.
   - **ANS**: a registered handler that gives a deliberate, valid answer but is not a feature:
     - the 33 server-run activities answered 327974 "closed" (`activity.py` `CLOSED_IDS`);
     - chat `11_2005`/`11_2009` (empty world channel);
     - `5_2801` (empty push list), `5_2943` (privilege cards, none owned);
     - `151_2041`/`153_2001` (off-season);
     - `8_2517`/`8_2519` (angel-trial rank with the player alone).
   - **NONE**: no handler. `server/net/server.py:194-211` answers a zero stub when a Res exists,
     and sends nothing when none exists.
4. **Driving Lua.** Each Req's numeric id (`"5_2701"`) and its name (`"HeroDevelopReq"`) were
   searched as `sendMsg(...)` arguments, and otherwise as quoted strings, over the 1,707 Lua files
   under `.stock/assets/scripts`. "No sender" means no such string was found. It does not prove
   that nothing sends the id.
5. **Unlock levels.** `functions.db` table `function` (112 rows), `unlock_level`, with the
   `FunctionType.lua` constant that opens it.
6. **Row counts.** Counted as `len(SELECT * ... NOT INDEXED)`, not `count(*)`. See the warning
   below.

## Counts

| | Req ids |
|---|---|
| Total | **513** |
| IMPL | **77** |
| ANS | **41** |
| NONE | **395**: 389 get the generic zero stub, 6 have no Res and get nothing (`5_2031`, `5_2039`, `5_2343`, `134_2001`, `148_2093`, `150_2059`) |
| NONE, single-player | 138 |
| NONE, multiplayer | 257 |

Against 23-11: handled 15 → 118.

**Unanswered on the emulator in run 11** (`docs/dev-loop.md` §7, the server's "no handler"
lines):

- `5_2039 SyncRedPointReq`: there is no Res, so the server cannot answer it.
  - Sent by `GameToolsBtnPanel.lua:102` at main-city build and again every 60 s while the city
    is visible (`:105-120`, `:627`).
  - It is logged once per server process. Run 11 counted 9, one per login.
- `5_2623 LevelReporterQueryReq`: it gets the zero stub today.
  - Sent when a stage's flag panel opens (`DesFlagPanel.lua:62-63`).
  - The listener draws cells only `if firstReporter` (`DesFlagPanel.lua:66-75`), so an empty
    answer is harmless.

## Warning: `count(*)` is wrong on four stock tables

These tables declare `[id] INT PRIMARY KEY` but store `id = NULL`. Their autoindex does not match
the rows (`PRAGMA integrity_check`: "row N missing from index"). `count(*)` and any `WHERE id = ?`
go through that index. A full scan returns the real rows.

| Table | `count(*)` | Rows (full scan) | Who reads it |
|---|---|---|---|
| `hero_rune_develop_info` | 0 | **51** (levels 0-50: `add_rate` 0→2.0, `need_rune_essence`, `need_gold`, `min`/`max`, `rune_develop_max`) | `RuneDataHelp.lua:65-69` (whole table, keyed by `rune_develop_level`) |
| `hero_godhood_info` | 480 | **2,430** | godhood (W4) |
| `item_buy_info` | 6 | **7** (the 7th row is refer 1210810, rate 3000) | `cfg.item_buy` filters on `refer`, so it is not affected |
| `reward_display_info` | 259 | **246** | not read by the server |

The Wave 2 plan's "`hero_rune_develop_info` has 0 rows" was this artefact. The Milu APK's copy
has the same broken index and the same 51 rows. The rows also explain why run 11 saw no crash at
`RuneDataHelp.lua:107-108` (`curDBInfo.add_rate`): level 0 resolves. **Rule for every config
lookup: filter on a data column (`level`, `refer`), never on `id`, and count by full scan.**

## Handled systems

| System | Req | IMPL | ANS | Module |
|---|---|---|---|---|
| Login/session (`3_*`, `194_2001`) | 7 | 6 | 0 | `login` (`3_2011` ClientHello is NONE, no sender) |
| Player / main city | 17 | 2 | 2 | `player` (`5_2005`, `5_2317` IMPL; `5_2801`, `5_2943` ANS) |
| Sign-in / login award | 6 | 6 | 0 | `checkin` |
| Energy / gold buy | 5 | 5 | 0 | `buy` |
| Guide | 1 | 1 | 0 | `guide` |
| Server-run activities | 33 | 0 | 33 | `activity` (closed, 327974) |
| Hero management | 10 | 8 | 0 | `hero` (`5_2721`/`5_2723` NONE, no sender) |
| Training | 6 | 5 | 0 | `train` (`5_2159` NONE, no sender) |
| Gacha | 2 | 2 | 0 | `gacha` |
| Shops | 4 | 2 | 0 | `shop` (`5_2133`, `5_2589` NONE) |
| Bag / items | 4 | 4 | 0 | `bag` |
| Runes | 2 | 2 | 0 | `rune` |
| Campaign / elite | 8 | 6 | 0 | `level` (`5_2511` no sender, `5_2623` NONE) |
| Gold trial | 3 | 3 | 0 | `goldtrial` |
| Mail | 3 | 3 | 0 | `mail` |
| Achievements / daily tasks | 2 | 2 | 0 | `events` |
| Angel | 6 | 4 | 0 | `angel` (`5_2301`/`5_2307` NONE, no sender) |
| Team | 1 | 1 | 0 | `team` |
| Hero trials | 3 | 3 | 0 | `herotrial` |
| Angel trials (`8_*`) | 14 | 12 | 2 | `angeltrial` |
| Chat (`11_*`, `5_2707-2715`) | 14 | 0 | 2 | `chat` |

## Unhandled systems, by unlock level

"SP" means single-player, "MP" means multiplayer. Config rows are full-scan counts. "Lua" names
the main sender files.

| Unlock (function → level) | System | NONE ids | SP/MP | Client Lua | Config tables (rows) |
|---|---|---|---|---|---|
| 1 (none) | Profile: avatar, nickname, avatar list | `5_2027`, `5_2029`, `5_2169` | SP (cosmetic) | `myGroupInfo/GruopInfoCtr.lua` | `head_half_relation` (59, not checked) |
| 1 | Main-city / SDK leftovers | `5_2017`, `5_2031`†, `5_2039`†, `5_2599`, `5_2603`, `5_2851`, `5_2903`, `5_2935`, `5_2937`, `134_2001`† | — | `GameToolsBtnPanel.lua` (`5_2039`), `AuthenticationUI.lua`, `sdk/FaceBookEventCtr.lua`, `GameGlobal.lua` | — |
| 1 | Stage reporters | `5_2623` | MP-flavoured; empty answer is SP-safe | `des/DesFlagPanel.lua:62-75` | — |
| 1 | Hidden or unsent | `3_2011`, `5_2159`, `5_2301`, `5_2307`, `5_2511`, `5_2721`, `5_2723` | — | no sender found | — |
| 1, VIP ≥ 14 | Buy the mystery store permanently | `5_2133` | SP, payment-gated | `mystery/PurchasePanel.lua:133` | `store_info` 2 (`buy_cost` 6880, `vip_buy_level` 14) |
| 10370 → **19** | Celestial merchant, store 7 ("send away") | `5_2589` | **SP** | `LegendsUI.lua:159-160`; open `FunctionType.lua:1404`; push branch `RPGGame.lua:884-911`, `:955-962` | `store_info` 7 (6 slots, appear 200/400, rate 0.005, stay 3600); `merchandise_info` store 7 (179 rows) |
| 10180 → 1 | Friends | `5_2605`-`5_2619` (8) | MP | `FriendsChatUI.lua`, `AddFriendPanel.lua` | — |
| 10080 → **15** | Arena | `7_3001`-`7_3027`, `7_3051` (14) | MP (bots possible) | `arena/ArenaCtr.lua`; open `FunctionType.lua:1036,1213`; guide 11700-11750 | `arena_daily_rank_prize_info` (30), store 3 |
| 10510 → 25 | Spar | `5_2513` | MP | `challenge/ChallengeBattleLine.lua` | — |
| 10250 → 30 | Guild | 24 ids (`5_2401`-`2429`, `2459`, `2461`, `2463`, `2471`, `2475`, `2699`, `2717`, `2719`, `2817`) | MP | `sociaty/*.lua`; guide 13002 | `guild_*` (8 tables) |
| 10250 | Guild hire, picnic, red envelopes | `5_2339`-`2347`, `5_2479`; `5_2431`-`2445`, `5_2601`; `5_2079`-`2091` | MP | `sociaty/*`, `redpack/*` | `mercenarise_info` (4), `guild_picnic_info` (2) |
| 60020 → 40 | Guild vault (GVE) | `5_2639`, `5_2651`-`2669` (11) | MP (guild) | `GVELevelListUI.lua`; guide 14202 | `guildlevel_*` (3), chapter type 10 |
| 10190 → 40 | Chat sending | 12 | MP | `chatRoom/ChatRoom.lua` | — |
| — | Other-player views / ladders | `5_2033`, `5_2077`, `5_2433`, `5_2465`, `5_2567`, `5_2591`, `5_2745` | MP | `challenge/ChallengeRoleDetailInfo.lua`, `top/*` | — |
| 10420 → **45** | Blessing (护佑) | `5_2571`, `2573`, `2575`, `2577`, `2597`, `2671` | **SP** | `FunctionType.lua:1596-1597`, `:988-992`; `MedalDetailInfoUI.lua`; `protect/OpenMedalFieldPanel.lua`; `protect/CombinePanel.lua`; `BagCtr.lua`; guide 14210-14215 | `bless_medal_info` (10), `bless_crystal_level_info` (150), `bless_medal_ranklevel` (160), `BLESS_*` (13 vars) |
| 90040 → **46** | Hero develop (英雄养成) | `5_2701`, `2703`, `2705` | **SP** | `heroGrowth/HeroGrowthInfo.lua:713-885` | `hero_constellation_info` (8), `HERO_DEVELOP_*` (5), `HERO_QUALITY_OPEN` |
| 10092 → **47** | Demon Onslaught (魔君来袭) | `5_2727`, `2729`, `2731` | **SP** | `MojunStruckUI.lua:25-141`, `mojunStruck/MojunLine.lua:56-161`, `MojunDataHelp.lua` | chapter type 12 (7 chapters, 105 stages), `magic_army_recommand_info` (105), `MAGIC_ARMY_DAY_TIMES` 2 |
| 90280 → **49** | Angel Radiance (圣辉) | `5_2909`, `2911`, `2913` | **SP** | `angel/AngelShengHui.lua:431-472`, `AngelShengHuiInheritancePanel.lua` | `angel_glory_info` (601), `ANGEL_GLORY_INHERIT_COST` |
| 80010 / 80020 → **52** | Signet + Master Dungeon (印记 / 王者副本) | `5_2621`, `2733`, `2735`, `2737`, `2739`, `2747`‡, `2805` | **SP** | `StampUI.lua`; `FunctionType.lua:1446-1457`, `:1016-1027`; `LevelDes.lua:206,311`; `level/fg/LevelTab.lua:43`; `LevelManager.lua:446-457` | `signet_info` (1,246), `signet_attribute_info` (66), `signet_change_info` (150), `signet_quality_info` (5), `signet_set_info` (50), `signet_upgrade_info` (96); chapter type 13 (10 chapters, 30 stages); `SIGNET_*` (7 vars) |
| 90070 → **54** | Hero breakthrough | `5_2811`, `2813`, `2815` | **SP** (`5_2811` lists other players) | `roleUI/roleLeft/RoleBreakthroughPanel.lua:756-809`; gate `RoleUI.lua:382` | `hero_breakthrough_info` (21) |
| 90000 → **55** | Rebirth (转生) | `5_2695` | **SP** | `roleUI/roleRebirth/RoleRebirthPanel.lua:250-262`, `train/TrainCtr.lua:120-134` | `hero_transmigrate` (15) |
| 50000 → **57** | Divine Ruins (神之遗迹, artifact PvE) | 12 (`5_2517`-`2531`, `2543`, `2547`, `2551`, `2563`) | **SP** | `NpcTowerUI.lua:83-922`, `npcTower/NpcTowerLine.lua:46-321`, `NpcTowerSweepDetailUI.lua` | chapter type 8 (20 chapters, 200 stages, 6 energy); `GOD_*` (8 vars) |
| 50010 → **57** | Artifact (神器) | 9 (`5_2533`-`2541`, `2545`, `2549`, `2553`, `2555`) | **SP** | `FunctionType.lua:1440`, `:983-985`; `ArtifactUI.lua:155-362`; `artifact/*`; guide 14000-14031 | `artifact_info` (881), `artifact_level_info` (100), `artifact_set` (37), `ARTIFACT_*` (9 vars), store 11 |
| 10081 → 60 | Ancient Arena (top arena) | `7_3029`-`7_3049` (11) | MP | `HighArenaUI.lua` | `toparena_rank_prize_info` (28), store 10 |
| 90030 → **60** | Angel advance + inheritance | `5_2779`, `2781`, `2783`, `2785`, `2803` | **SP** (`5_2785` lists other players) | `angel/AngelAdvance.lua:61-668`, `AngelInheritancePanel.lua` | `angel_advance_info` (22), `ANGEL_ADVANCE_BUY_DROP_ID` |
| 60030 → 60 (guild 30) | Crusade / GVG (`152_*`) | 18 | MP | `GVGMapUI.lua`, `crossServerGvG/*` | `crusade_*` (2) |
| 90080 → 60 | Cross-server PvP (`153_*`) | 10 | MP | `crossServerPVP/*` | — |
| 90240 → 62 | Divine Soul | `5_2861`-`2881` (11) | SP | `heroSoul/*`; `FunctionType.lua:1346` | `god_soul_info` (48), `god_soul_level_exp_info` (120), `god_soul_property_value_info` (960), `pray_god_soul` (5) |
| 10460 → 64 | Hero Chronicles (memory) | `5_2673`-`2693`, `2697` (12) | SP | `Recall*.lua`, `recall/RecallLine.lua`; guide 14302 | `memory_chapter_info` (12), chapter type 11 (92 chapters) |
| 70000 → 64 | Awakening | `5_2641` | SP | `roleUI/roleLeft/RoleAwakeView.lua` | `awaken_info` (2,628), `awaken_model_info` (73) |
| 90020 → 65 | Assistant (auto dailies) | `5_2769`-`2775` | SP | `assistant/AssistantPanel.lua` | `ANGELTRIALS_HELPER_LEVELS_COST` |
| 90110 → 66 | Divinity (godhood) | `5_2823`, `2825` | SP | `godhead/*` | `hero_godhood_info` (**2,430**; `count(*)` says 480) |
| 90210 → 68 | Demon Lord's Catacombs | 11 (`5_2827`-`2849`, not `2841`) | SP | `devilTry/*`; `FunctionType.lua:1646-1648` | chapter type 14 (100 floors), store 25 |
| 90220 → 68 | Rune engraving (rune develop) | `5_2841` | SP | `rune/SealPanel.lua:483-486`; gate `RunePanel.lua:487` ("opens with the devil palace") | `hero_rune_develop_info` (**51**; `count(*)` says 0) |
| 90260 → 70 | Star Soul | `5_2887`-`2893` | SP | `heroStar/HeroStarInfo.lua`; `FunctionType.lua:1349` | `star_soul_info` (140) |
| 90350 → 72 | Divine Beast (pet) | `5_2939`, `2941` | SP | `petGrowth/PetGrowthCtrl.lua` | `pet_info` (9), `pet_upgrade_info` (54), store 28 |
| 80000 → 75 | Cross-server tournament (`151_*`) | 17 | MP | `crossServerArena/*` | — |
| hero star ≥ 5 | Upgrade soul (升灵) | `5_2883` | SP | `roleUI/RoleCostStonePanel.lua:308-313`; opened from `RoleUpStarPanel.lua:164,255-258` | `upgrade_soul_info` (101) |
| 90300 → 999 | Gemstone (disabled) | `5_2917`-`2929` | SP | `gemstone/*` | `gemstone_info` (135) |
| 90230 → 1, blacklisted | Charity donation | `5_2853`-`2859` | server-run | `DonateUI.lua` | — |
| 90290 → 1, blacklisted | Angel Smash (2048) | `154_2001`-`2005` | SP mini-game, server-run | `angelPeng/AngelPengUICtrl.lua` | — |
| guild | Guild war / guild boss (`148_*`) | 39 | MP | `ConsortiaBattleScene.lua`, `sociatyBattle/*` | `guildwar_*` (11), `boss_coming_*` (3) |
| guild (20080) | Island Conquest (`150_*`) | 35 | MP | `GuildBattleScene.lua`, `guildBattle/*` | `sparda_*` (10) |
| — | Battlefield (`149_*`) | 23 | MP, no sender for any id | — | `battlefield_*` (5) |
| — | Fight reports / test (`211_*`) | 7 | MP / debug | `BattleAutoResult.lua`, `BattleTestUI.lua` | — |

† no paired Res. ‡ no sender found.

### Notes for planning

- **Prize categories the SP systems drop** (scan of `drop_group` → `drop_base` from each stage
  set):
  - chapter type 8 (ruins): only 20;
  - chapter type 12 (mojun): 20 and **86** (`PRIZE_PET_MONEY`, `ClientPlayer.lua:177`);
  - chapter type 13 (signet stages): only **21** (a signet, refer = `signet_info.entry`).
  - The server grants 1, 2, 9, 11, 20, 30, 40, 51 and 52 today (`item.py:35-55`). Signet
    decompose pays category **75** (`COST_SIGNET_TYPE`).
- **Fight types** (`FightType.lua:13-53`): GOD_PVE 17 (ruins), NPC_TOWER_AUTO 19, MOJUN 27,
  HERO_TRY 8. `team.py` answers `5_2327` for any fight type and adds the support hero only for
  type 2.
- **Arena does not block single-player progress in the code.** No single-player table or Lua
  gate needs an arena result. Two things touch it:
  - daily tasks 10090 and 14030-14070 and the arena store (coin 51), which Wave 2 left out;
  - **the level-15 guide 11700-11750** (`new_player_guide_info`: "The Arena is open!" → "set up
    your defense lineup" → confirm). No run has fired this guide yet, because runs 10-11 raised
    levels on copies. The same holds for the guild guides 13002 (level 30) and 14201-14204
    (level 40). Whether they wedge the city is **not verified** (Wave 3 task A1).

Single-player build order after Wave 2: 19 store 7 → 40 hero-trial cooldown → 45 blessing →
46 hero develop → 47 demon onslaught → 49 angel radiance → 52 signet + master dungeon →
54 breakthrough → 55 rebirth → 57 divine ruins + artifact → 60 angel advance. Then (Wave 4):
62 divine soul, 64 chronicles and awakening, 65 assistant, 66 divinity, 68 catacombs and rune
engraving, 70 star soul, 72 pet, upgrade soul, the profile gaps, and the multiplayer
substitutes (arena bots first).
