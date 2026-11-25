# LOA private server — status and roadmap

Updated 25-11-2026.

## Done — Plan B1 "tutorial + hero summon + campaign chapter 1" (master, 32 commits `673e300..HEAD`, 257 tests)

Built and unit-tested: the config layer over the stock `.db` files, `5_2041` guide persistence, the
starting kit at character creation, `ClientHero` from `npc_info`/`hero_quality`/`hero_growth`, the
drop roller, item and hero payouts, the `5_2008` change notification, the tavern gacha, and the
campaign handlers (`5_2201` enter, `5_2203` finish, `5_2209` chapter chest, `5_2205`/`5_2207`
refused), the fight team `5_2327`, and the scripted first draws of the tutorial.
`docs/dev-loop.md` section 7 holds the six emulator acceptance runs of 23-10-2026
and 26-10-2026.

**Milestone 2 is MET on both halves, on 26-10-2026 (run 6 in `docs/dev-loop.md` section 7).
Ready for your own emulator pass.**

The tutorial half, on `LOA_API30`: both summons pay out, the guide reaches and persists **10160**
(twice, on two independent characters), a relaunch shows the main city with the guide resumed — no
intro, no guide battle — and a server restart keeps the database. `5_2327 QuerySelfTeamReq` is
handled (`server/modules/team.py`, commit `c3e6923`), so the campaign fight opens at all, with
**zero `LUA ERROR` in the whole run**.

The campaign half, as run 6 proved it on 26-10-2026: **stage 1-1 won, 3 stars, in 40 s; stage 1-2
won, 3 stars, in 48 s.** Drops are paid (粗布头巾 10000 x2 from 1-1; soul stone 500000 x10 and three
gear items from 1-2), gold and xp land, the player and all three heroes reach level **2**,
`last_level` is 10010, both `levels` rows stand at **star 3**, stage 2 is unlocked on the chapter
map, and both persistence checks are green — a relaunch resumes the guide at **10290** with no
intro and no guide battle, a server restart logs `login ok` with no `created character`. Zero
`Traceback`, zero `LUA ERROR`, zero `FATAL` in the run, and the unanswered-id list is unchanged.
The post-loss guide deadlock is **gone**. The chapter chest was **not** reached, and not for lack of
energy (61/62 left): guide step 10290, the 女神 summon, masks the chapter map, and that flow is
Plan B2.

Why it took five runs to get there. The tutorial's first gold and diamond single draws are
**scripted**: `variables.FIRST_GOLD_GACHA` 188000 pays hero 104000 and
`variables.FIRST_DIAMOND_GACHA` 189000 pays hero 210000, so the original tutorial team is
100000 + 104000 + 210000, not the one or two heroes a random roll handed us (commit `bc59fec`).
Even then runs 4 and 5 **lost** every attempt with the ultimates firing: hero ultimates are
**manual taps only** (`BattleHeroItem:onTouchHeroSkill`; the auto path is commented out below
player level 3), there is **no battle timeout**, the client fights with our `unit` block verbatim —
and three level-1 heroes do not clear the two waves of stage 10000. The stock server gave a new
character more: `variables.NEW_FIGHT_HELP_HERO` = NPC 1103009 冰雪女皇 (level 6, 2,098 HP, 222
power), memo "the hero that supports the newbie fights (stages 1-2)". **That support hero is now
implemented, server and client**: the rule in `server/modules/team.py` (`423a684`, narrowed to the
campaign fight type in `9bf9af6`) and Lua patch 11 in `client/build_assets.py` (`92dac3f`), which
builds a type-3 `team_base` unit that has no local counterpart in the line-up. Run 6's fight was
decided by it — **two casts of its own ultimate `3110001`** plus one knight cast, where seven hero
casts had lost the same stage. `team_base.fightAbility` stays the player's own heroes. One cosmetic
shortfall: the support NPC gets HP and rage bars but **no portrait card** in the HUD (stock draws
cards for the local line-up only). It fights and it casts.

One finding not patched, kept because it explains runs 2 to 5: after a **lost** first fight the
new-player guide deadlocked, its touch mask over steps 10180-10280 allowing only stage 2 (refused
as locked) while the equip step wanted item 10000, which drops only from stage 1-1. Winning 1-1
removes it, and run 6 confirmed that.

Nothing is shipped and nothing is confirmed until you drive it yourself.

## Next — in order

- [ ] **Your own emulator pass.** `docs/dev-loop.md` section 7, "Pre-launch checklist for the next
      run": move `data/player.db` aside (never delete it), win stage 1-1 with the support hero —
      tap the cards while they glow — then the relaunch and server-restart persistence pass, and
      both greps at zero. The APK installed on `LOA_API30` is already the patch-11 build.
- [ ] **Plan B2: heroes.** Level, star-up, gear, awaken, angels. Modules `hero`, `angel`, `item` per spec 3.1.
      It also carries what Plan B1 left out and run 6 ran into: the **angel step 10290**, the
      **chapter chest** sitting behind it, the equip chain 10180-10210 (which needs **hero level 2**,
      reached after stage 1-2), and the **HUD portrait card for the support NPC** as a cosmetic.
      **Status 24-11-2026 (branch `plan-b2-wave1`, Phase A T1-T8 done, 473 tests; ACC-1 = run 7 in
      `docs/dev-loop.md` section 7):** the guide now runs through the equip chain (10210), the angel
      summon (10293), the angel line-up, Equip All with crafting (10313) and quality-up (10380) to
      10390 with no wedge; relaunch and server restart keep gear and angel. Open from that run: the
      **chapter chest** needs boss stage 10022 (the client counts only `once = 0` stages), which our
      three heroes lose without the support NPC; one stock-client `LUA ERROR` in
      `RoleEquipGetEquipPanel.lua:44` during the guided equip; the chat `11_2006` error (task B1).
      **Status 24-11-2026, later (Phase B, W1, E1 and prize categories 51/52 at `cc2c778`, 594
      tests; ACC-2 = run 8 in `docs/dev-loop.md` section 7):** sign-in, the 7-day gift (day 1 on
      the real world, days 3 and 5 with their arena and trial coins on a throwaway copy), the VIP-0
      purchase refusals, the 6-minute energy timer, mail and the shop pass, and so do relaunch and
      server restart. Zero `Traceback`, zero `LUA ERROR` (the chat error is gone). Open from that
      run: boss 10022 lost twice, so achievement kind 2 / guide 10400 and the chapter chest are
      still unreached; sweep needs level 8. A lost fight's guide burst can lower `guide_id` until
      the next relaunch re-saves it. Fixed on 25-11-2026: `5_2149` sell-all is answered
      (`56038c6`), and 累计签到礼包 / 已领取 / 已售 are in English (`b044af3`).
      **Status 25-11-2026 (boss 10022 diagnosis = run 9 in `docs/dev-loop.md` section 7, 605
      tests):** the loss is **not a server bug**. The server's `unit` block is what the client
      fights with and what the Attributes tab shows (level growth, gear and quality all land;
      `Power 1000` is cosmetic), the enemies come from the client's own tables, and by the engine's
      formula the three level-3 one-star heroes are about five times too weak for the wave-3 dragon
      (1,189 HP, 37 attack; two more losses, `09:06:29` and `09:11:38`). The original's levers for
      this point are listed in run 9 and are **design decisions for you**, none implemented:
      `5_2103 HeroSkillUpReq` (no handler; `spell_level_up` allows skill level 2 at hero level 3),
      Train with XP potions (`5_2139` is a stub), the free daily diamond draw (`gacha_info`
      2400000 `free_times 1`; charged 2,000 diamonds today) scripted by
      `FIRST_DIAMOND_GACHA_AFTER_NEWGUIDE` 182000 to pay a level-5 2-star hero (ignored today),
      `NEW_PLAYER_PRIZE` 10003800 (200 XP potions, 600 diamonds, 200,000 gold, a hero's worth of
      stones; delivery unknown, not granted), and extending the support NPC to 10022 (the memo
      says stages 1-2). One bug fixed on the way: a prize hero (7-day gift day 2's 3-star 304000,
      the 182000 pool) was born at star 1 level 1 instead of `hero_info.star`/`init_level`
      (`de0d03a`). Two corrections to the facts above: the boss stage shows a **2:30 timer per
      wave**, and the **angel's rage never rose** from its 50 % start in either fight (stock
      client path, not chased). The chapter chest, achievement kind 2 and guide 10400 stay behind
      10022 until one of the levers is chosen.
      **Status 25-11-2026, later (branch `plan-b2-wave2`, Wave 2 A1-A5 at `bdfc89c`, 667 tests;
      ACC-W2-1 = run 10 in `docs/dev-loop.md` section 7):** a fresh character **wins 10022** with
      3 stars on the first try. It got there through the free post-guide draw (`k=1`, 182000 →
      2-star 209000 at level 5), a stage-10012 grind to player level 8, skill upgrades (`5_2103`,
      skill0 Lv.9), and training with 242 potions of 1100 (233 bought for 69,900 gold) to hero
      level 17 "EXP Full". The chapter-1 chest, the kind-2 achievement (event 10920 via guide
      10400-10410) and guide 10451 (the fifth hero, 202000) follow, and relaunch and server
      restart keep spell levels, `trains` and `diamond_free_day`. Server greps 0. Logcat has 2
      `LUA ERROR`s: the known `RoleEquipGetEquipPanel:44`, and `AngelSkill:97` from the unbuilt
      `5_2323` (task B1), which is new in the unanswered list. Open from that run: the train
      screen does not refresh passive xp until it reopens; the post-fight guide burst also follows
      a win (`guide_id` 11208 → 10380); fight xp banks past the hero cap (Risk 5); angel levels
      pass the heroes' cap in training.
      **Status 25-11-2026, evening (Wave 2 B1-B7, W2 wiring and E2 daily tasks at `cebf90b`;
      ACC-W2-2 = run 11 in `docs/dev-loop.md` section 7, every row on a copy, `data/player.db`
      SHA-1 unchanged):** angel spell and aura upgrades, elite 110000 (3 stars, the frontier
      moves) with the elite item sweep (10 tickets, no energy), daily tasks (count, single claim
      and claim-all), the mystery merchant (appears at 600 energy, sells from store 2), angel
      trials (open, fight floor won, buff bought), the gold trial (manual run and the 20,000 rung)
      and the rune feed (no crash) pass, and so do relaunch and server restart. The hero trial
      enters, fights and logs a loss without using a run, but it was lost twice, and its first
      stage needs player level **40**, not 36. Server greps 0. `5_2323` has left the unanswered
      list and nothing new appeared. Logcat has 4 `LUA ERROR`s: `MMTaskListView.lua:29` on a
      single daily claim. Open from that run: the gold-trial **auto fight pays 0** (the client
      sends damage 0); **Deluxe Lunch claimed at full energy pays nothing** (`db.add_energy`
      clamps at the cap); the post-fight guide burst follows elite and angel-trial wins too;
      the angel passes the hero cap through passive training (19 → 29); sweeps do not count for
      Stage Slayer; the hero-trial V-VII cooldown and the draw "Again" ticket check were not
      reachable in this run.
      **Fixed 25-11-2026 after run 11 (unit-tested, no emulator run yet):** lunch and dinner energy
      may pass the cap (`357f804`); the gold-trial auto fight pays from the server's damage
      (`194f27f`); a single daily claim keeps the row `MMTaskListView` reads (`02f70ab`); the
      post-fight guide burst saves only the guide's own next step, so `guide_id` no longer falls
      to 10380 (`ff8ce25`); angels stop at the heroes' cap in training (`0ccf0d3`); energy and item
      sweeps count `times` toward Stage Slayer 10070 / 10080 (`7b1081a`); the draw screen's "Again"
      on a ticket card is refused without the tickets instead of charging diamonds (`589e039`).
      Ready for your emulator pass, not done.

## Done — Plan A "boot to main city" (master, 41 commits, 98 tests)

- Own Android app `bg.stefan.loa` (cocos2d-x 2.2.2 Java runtime, quick-cocos2d-x Lua bridge, generated
  SDK stubs, stock `libgame.so`, stock assets, 10 Lua patches). Permissions INTERNET + VIBRATE only. Signed
  with `~/.loa-keystore` (never commit it, never lose it: same key = in-place upgrades).
- Python server `py -3.14 -m server`: framing from a live capture (`docs/protocol.md`), login (3_2001 creates
  the character), QueryMyselfRes for a fresh player, five main-city stubs, zero-stub policy for unknown ids.
- Dev loop on this PC: AVD `LOA_API30` (Android 11 x86_64, 32-bit ARM translation). `docs/dev-loop.md` has
  every command. The API 36 AVD cannot run the APK (64-bit only).
- Verified on the emulator: login scene → tutorial → main city as "stefan", level 1, energy 60/60, heartbeats.

## How to run (desktop, emulator)

```powershell
cd "C:\Users\Stefan.Nasev\Downloads\Claude Cowork\Claude Code\Projects\loa-private-server"
py -3.14 -m server                                   # window 1, log to data\server.log if redirected
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd LOA_API30 -no-snapshot-load   # window 2
# app is installed in the AVD; reinstall after a rebuild:
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r "$env:USERPROFILE\Downloads\LOA-private-release.apk"
```

Fresh character: stop the server, **move** `data\player.db` aside, start again. Never delete it — the
Plan A and Plan B1 worlds are kept beside it as `data/player.db.*` backups
(`data/player.db.plan-a-2026-10-21` is Stefan's Plan A character). Tests:
`py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`.

## Later — in order

- [x] **Plan B3: dailies.** Done inside Plan B2 Wave 1 (24-11-2026): sign-in and the 7-day gift (`7109f6b`), mail
      with attachments (`186e1e4`), gold and diamond shops (`c4bde66`), rewards and prize overflow (`0f8dd8c`,
      `6b6cd4c`); daily tasks followed in Wave 2 E2 (`5cc228a`). Acceptance: run 8 (`b8d83fd`) and run 11 in
      `docs/dev-loop.md` section 7. Arena and guild were not built.
- [x] **Plan C: English UI.** Done (`0921568` 20-10-2026 .. `19c03b3` 25-11-2026, 47 `localise`/`english`
      commits): text through the Claude batch translator (`713d5e8`) instead of the llm00 Gemma run, images
      re-drawn (`localise.images`), story dialogue, and the League of Angels logo; the English APK
      (versionName 1.0.0.5) ran in runs 7-11. Emulator sheets in `docs/screens/en-2026-11-2*`. Leftover
      Chinese strings are listed per run in `docs/dev-loop.md` section 7.
- [ ] **Phone build (S20 Ultra), when wanted.** `settings.toml [net] host` = home Wi-Fi IPv4 of this PC,
      `py -3.14 -m client.build_assets`, `client\android\gradlew.bat assembleRelease` (JAVA_HOME = Android
      Studio JBR), same keystore, sideload. Firewall rule on the Private profile only; never forward port 8112
      (the server has no authentication: anyone on the LAN who connects is the character).
- [ ] Later: `.gitattributes`, `Registry.message_class` error type, `fake_client` docstring, commit-trailer
      uniformity (history rewrite is Stefan's call), DecodeError handling is done.

## Known client behaviour (do not re-discover)

- The client ignores `LoginRes.status = 327682`; character creation happens on `3_2001` (see spec amendment).
- `comSdk.IComSdk` does not exist in any stock dex; the 13 JNI exports stay undeclared.
- The boot waits for `comSdk_checkVersionCallback_event`; Lua patch 9 kicks `checkVersion()` after the listener.
- `files/upgrade/` must exist before the DB copy (patch 10).
- Header: 24 bytes, length = body only, district at offset 4 echoed by the client, no status on the wire.
- Non-fatal Lua errors on the main city today: `RoleData:updateRechangeCardsList` (5_2944 empty) and chat 11_2006.
- `QuerySelfTeamRes` has no `status` field, yet the client branches on `msg.status`: the native layer supplies 0
  from the header, so an empty zero-stub answer takes the SUCCESS branch and dies in `LineTeam.lua:34` instead of
  floating `x01025`. Same mechanism as the 327682 LoginRes finding.
