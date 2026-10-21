# LOA private server — status and roadmap

Updated 21-10-2026. Paused for the weekly token limit after Plan A.

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

Fresh character: stop the server, delete `data\player.db`, start again. Tests: `py -3.14 -m pytest -q --basetemp=C:/tmp/pytest-loa`.

## Next — in order

- [ ] **Plan B1: tutorial + hero summon + campaign chapter 1.** Brief committed:
      `docs/superpowers/plans/BRIEF-plan-b1-tutorial-and-campaign.md`. Resume = planner agent on the brief
      (writing-plans format → `docs/superpowers/plans/2026-10-21-plan-b1-tutorial-and-campaign.md`), sonnet
      pre-flight scan, then subagent-driven execution with per-task reviews and an emulator acceptance run.
      Includes the Plan A parked items: persist `5_2041 SaveGuideIdReq` (tutorial replays every launch until
      then), real data for `5_2944 QueryBtCardRecordRes`, energy from `xp_for_level` instead of the frozen 60,
      `[net] bind` key, `.gitattributes` eol=lf, the "zero stub" log wording.
- [ ] **Plan B2: heroes.** Level, star-up, gear, awaken, angels. Modules `hero`, `angel`, `item` per spec 3.1.
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
