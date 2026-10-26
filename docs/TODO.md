# LOA private server — status and roadmap

Updated 26-10-2026.

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

- [ ] **Plan B3: dailies.** Sign-in (`checkin.db`), shop (`merchandise_info.db`), mail with attachments, rewards.
      Arena and guild hidden or against bots.
- [ ] **Plan C: English UI.** `localise/` pipeline on llm00 `gemma4:e4b` (spec 3.3): 10,788 templates after digit
      masking, names first as a glossary, line-based batches of 40, resumable cache, ~14-20 h detached. Then the
      `Language_en.lua` + patched `.db` swap into the APK and the server.
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
