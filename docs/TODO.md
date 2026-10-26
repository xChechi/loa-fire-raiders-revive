# LOA private server — status and roadmap

Updated 26-10-2026.

## Done — Plan B1 "tutorial + hero summon + campaign chapter 1" (branch `plan-b1`, 27 commits `673e300..HEAD`, 243 tests)

Built and unit-tested: the config layer over the stock `.db` files, `5_2041` guide persistence, the
starting kit at character creation, `ClientHero` from `npc_info`/`hero_quality`/`hero_growth`, the
drop roller, item and hero payouts, the `5_2008` change notification, the tavern gacha, and the
campaign handlers (`5_2201` enter, `5_2203` finish, `5_2209` chapter chest, `5_2205`/`5_2207`
refused), the fight team `5_2327`, and the scripted first draws of the tutorial.
`docs/dev-loop.md` section 7 holds the emulator acceptance runs of 23-10-2026.

**Ready for your emulator pass: the tutorial half of milestone 2 is MET, the campaign half is
unproven.**

The tutorial half, on `LOA_API30`: both summons pay out, the guide reaches and persists **10160**
(twice, on two independent characters), a relaunch shows the main city with the guide resumed — no
intro, no guide battle — and a server restart keeps the database. `5_2327 QuerySelfTeamReq` is
handled (`server/modules/team.py`, commit `c3e6923`), so the campaign fight now opens, with a team
of 2 units and **zero `LUA ERROR` in the whole run**.

The campaign half: **every stage 1-1 fight was lost** — three fights across two characters, all
`win = 0` — so the win path (star, drop payout, `last_level`, the stage-2 unlock, the chapter chest)
is unit-tested but never exercised on the emulator. The reason is not the server. The tutorial's
first gold and diamond single draws are **scripted**: `variables.FIRST_GOLD_GACHA` 188000 pays hero
104000 and `variables.FIRST_DIAMOND_GACHA` 189000 pays hero 210000, so the original tutorial team is
100000 + 104000 + 210000, not the one or two heroes a random roll handed us. Commit `bc59fec`
implements that. Three more facts from the same analysis: hero ultimates are **manual taps only**
(`BattleHeroItem:onTouchHeroSkill`; the auto path is commented out below player level 3), there is
**no battle timeout**, and the client fights with our `unit` block verbatim — so the next run has to
tap and advance the waves, not idle through them.

One finding not patched: after a **lost** first fight the new-player guide **deadlocks**. Its touch
mask over steps 10180-10280 allows only stage 2, which the server rightly refuses as locked, while
the equip step wants item 10000 — which drops only from stage 1-1. Winning 1-1 removes it.

Nothing is shipped and nothing is confirmed until you drive it yourself.

## Next — in order

- [ ] **Emulator re-run: prove the win path.** Win stage 1-1 with the three scripted tutorial heroes
      of `bc59fec` — **tap the hero ultimates** (`BattleHeroItem:onTouchHeroSkill`) and advance the
      waves instead of idling — then assert the star, the drop payout, `last_level`, the stage-2
      unlock, the chapter chest, and that the guide walks past the equip chain instead of
      deadlocking. Open questions C (`stage_info.once`) and D (the ultimate firing from
      `ClientHero.spells`) are still waiting on a won fight. Pre-launch checklist and the full run-2
      record: `docs/dev-loop.md` section 7.
- [ ] **Merge `plan-b1` into `master`** once that run passes.
- [ ] **Plan B2: heroes.** Level, star-up, gear, awaken, angels. Modules `hero`, `angel`, `item` per spec 3.1.
      Also carries the guide steps past 10160 (equip 10180-10210, angel 10293) that Plan B1 left out.

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
