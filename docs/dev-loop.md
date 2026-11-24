# Dev loop — where a build gets tested

Bounded emulator check, Task 9 of plan *Plan A: boot to main city*, plus the Task 9b
follow-up that got a 32-bit-capable AVD. One install attempt and 90 seconds of logcat
per AVD. Neither emulator was debugged beyond reading its output.

## Verdict

**Outcome A — the APK runs on an emulator, so the dev loop is the AVD on this PC.**

Not the AVD the plan assumed. The pre-existing `Medium_Phone_API_36.1` cannot host the
APK at all; a newly created `LOA_API30` can, and the game boots on it.

| AVD | API | `abilist32` | install | result |
|---|---|---|---|---|
| `Medium_Phone_API_36.1` | 36 | *(empty)* | `INSTALL_FAILED_NO_MATCHING_ABIS` | unusable |
| **`LOA_API30`** | **30** | **`x86,armeabi-v7a,armeabi`** | **`Success`** | **game boots** |

## 1. `LOA_API30` — the working AVD (21-10-2026)

| | |
|---|---|
| AVD name | `LOA_API30` |
| System image | `system-images;android-30;google_apis;x86_64` (rev 16) |
| Device profile | `pixel_4` |
| Guest | `sdk_gphone_x86_64`, Android 11, SDK 30 |
| `ro.dalvik.vm.isa.arm` | `x86` |
| `ro.product.cpu.abilist` | `x86_64,x86,arm64-v8a,armeabi-v7a,armeabi` |
| `ro.product.cpu.abilist32` | `x86,armeabi-v7a,armeabi` |
| `ro.zygote` | `zygote64_32` |
| APK | `LOA-private-release.apk`, 340,862,699 bytes, signed, `bg.stefan.loa` / `.GameActivity` |
| Install | `Success`, 24 seconds |

### What happened on launch

The process started and was **still alive at +10 s, +60 s and +90 s** (pid 4766).
`GameActivity` is the resumed activity, state `S (sleeping)`, no ANR.

```
10-21 10:16:09.818 I ndk_translation: Initialized NDK translation (armv7l), version 0.2.2
10-21 10:16:11.117 D Cocos2dxActivity: model=sdk_gphone_x86_64
10-21 10:16:13.926 D cocos2d-x debug info: FTGlypFactory initing, read font ttf
10-21 10:16:13.932 D cocos2d-x debug info: FTGlypFactory init res/font/msyh.ttf
10-21 10:16:14.527 D cocos2d-x debug info: [0.9724] DEFAULT_OPID:  1
10-21 10:16:14.770 D cocos2d-x debug info: [1.2163] [INFO] # device.platform  = android
10-21 10:16:14.785 D cocos2d-x debug info: [1.2317] [INFO] # device.writablePath = /data/user/0/bg.stefan.loa/files/
10-21 10:16:14.828 D cocos2d-x debug info: [1.2748] [INFO] # CONFIG_SCREEN_WIDTH  = 2400.00
10-21 10:16:14.913 D cocos2d-x debug info: [1.3590] g_sdkManager: LuaSuperSDKManager  3  3
10-21 10:16:14.913 D luajc  : CCLuaJavaBridge::callJavaStaticMethod(lua_State *L)
10-21 10:16:14.914 I LOAStub: JavaSuperSDKManager.getPlatformConfigByName
10-21 10:16:14.914 D cocos2d-x debug info: [1.3611] opid >>  1
10-21 10:16:15.620 D cocos2d-x debug info: [2.0664] 开始初始化 sdk.....
10-21 10:16:15.620 D cocos2d-x debug info: [2.0665] 当前的sdk为 >>>   LuaSuperSDKManager
10-21 10:16:15.620 D cocos2d-x debug info: [2.0668] 开始 android   sdk init  .....
10-21 10:16:15.620 D luajc  : CCLuaJavaBridge::callJavaStaticMethod(lua_State *L)
10-21 10:16:15.620 I LOAStub: JavaSuperSDKManager.lua_setCallBack
10-21 10:16:15.621 D luajc  : CCLuaJavaBridge::callJavaStaticMethod(... "lua_setCallBack", args, "(I)V") SUCCESS
```

Everything the brief predicted on success is there: `DEFAULT_OPID: 1`,
`g_sdkManager: LuaSuperSDKManager`, the `LOAStub` lines from the generated stubs.
`libgame.so` loads and runs under `ndk_translation` **armv7l 0.2.2** — 32-bit ARM
translation works. Zero `UnsatisfiedLinkError`, zero `FATAL EXCEPTION`, zero
`AndroidRuntime`, zero `dlopen failed` in the whole 90 s.

### Where it stopped on 21-10-2026, and how that gate was closed

On the first run `lua_setCallBack ... SUCCESS` at **10:16:15.621** was the last line the
app ever logged. For the remaining 86 seconds it stayed alive, foregrounded and
completely silent; the screenshot at +60 s was a plain black 2280x1080 landscape frame.
It never reached the login scene and never opened a socket, so the server address was
not what stopped it. The Lua SDK-init chain registered its callback through the
generated `JavaSuperSDKManager` stub and then waited: on Android the real channel SDK's
Java side is what fires the init/version callbacks, and the generated stub answers the
registration without ever calling back.

**Task 9c closed that gate** (commits `997fdb3`, `094d2ca`, 21-10-2026) with two more
Lua patches in `client/build_assets.py`:

- call `g_sdkManager:checkVersion()` from `upgrade:init()`, right after the
  `comSdk_checkVersionCallback_event` listener is registered, so the boot leaves SDK
  init on its own;
- `lfs.mkdir(wrireUrl .. "/upgrade")` before `MyApp:updateDB()` copies the split `.db`
  files, which otherwise died on a missing directory.

With those in, the **login scene renders in about 4 seconds** (`denglu 成功` at
`[3.8545]`) and zero `LUA ERROR` appears in the capture. Tapping Start game connects to
**`10.0.2.2:8112`** — the emulator's alias for this PC — and sends `194_2001`
(`QuerySrvInfoReq`). `settings.toml` `[net] host` is `10.0.2.2` for emulator builds; a
phone build needs the LAN address put back.

## 2. `Medium_Phone_API_36.1` — why it is unusable

Kept for the record; do not retry this AVD.

| | |
|---|---|
| System image | `system-images/android-36.1/google_apis_playstore/x86_64` |
| Guest | `sdk_gphone64_x86_64`, Android 16, SDK 36 |
| `ro.dalvik.vm.isa.arm` | `x86` |
| `ro.product.cpu.abilist` | `x86_64,arm64-v8a` |
| `ro.product.cpu.abilist32` | *(empty)* |
| `ro.zygote` | `zygote64` |
| `/system/lib/arm` | does not exist |

```
$ adb install -r /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
Failure [INSTALL_FAILED_NO_MATCHING_ABIS: Failed to extract native libraries, res=-113]

$ adb shell am start -n bg.stefan.loa/.GameActivity
Error: Activity class {bg.stefan.loa/bg.stefan.loa.GameActivity} does not exist.

10-21 10:02:30.203 I ActivityTaskManager: START u0 {cmp=bg.stefan.loa/.GameActivity}
    ... result code=-92          # START_CLASS_NOT_FOUND
```

`android-36.1` is a 64-bit-only image. `ro.dalvik.vm.isa.arm=x86` is set and
`libndk_translation` is present, but only in `/system/lib64` — it translates
`arm64-v8a`, not `armeabi-v7a`. The APK is `armeabi-v7a`-only, so no ABI matches. The
property alone is not the test; `abilist32` is.

## 3. Toolchain that actually built the APK

Reuse this pair; it is the first pair tried and the fallback was never needed.

| | |
|---|---|
| Gradle | 9.3.1 (`client/android/gradle/wrapper/gradle-wrapper.properties`) |
| Android Gradle Plugin | 9.0.0 (`client/android/build.gradle.kts`) |
| JDK | `C:\Program Files\Android\Android Studio\jbr` |
| compileSdk / targetSdk / minSdk | 36 / 33 / 21 |

## 4. One-time AVD setup

Done on 21-10-2026; repeat only on a fresh machine or if `LOA_API30` is deleted.

**Command-line tools.** `Sdk/cmdline-tools` did not exist and Android Studio does not
install it. Get the current build number from Google's own package list instead of
guessing it:

```bash
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
curl -sS -o /c/tmp/repo2-3.xml https://dl.google.com/android/repository/repository2-3.xml
grep -oE "commandlinetools-win-[0-9]+_latest\.zip" /c/tmp/repo2-3.xml | sort -u | tail -1
# 21-10-2026: commandlinetools-win-16111833_latest.zip  (rev 23.0, 155 MB)

curl -sS -L -o /c/tmp/cmdline-tools.zip \
    https://dl.google.com/android/repository/commandlinetools-win-16111833_latest.zip
mkdir -p /c/tmp/cltools "$SDK/cmdline-tools"
unzip -q /c/tmp/cmdline-tools.zip -d /c/tmp/cltools
mv /c/tmp/cltools/cmdline-tools "$SDK/cmdline-tools/latest"   # inner folder becomes "latest"

export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
"$SDK/cmdline-tools/latest/bin/sdkmanager.bat" --version      # -> 1.0.16625370 (Android CLI)
```

**System image.** `sdkmanager --licenses` is now a no-op ("the --licenses option is no
longer needed"); nothing gates on it.

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/cmdline-tools/latest/bin/sdkmanager.bat" \
    --sdk_root="C:\\Users\\Stefan.Nasev\\AppData\\Local\\Android\\Sdk" \
    --install "system-images/android-30/google_apis/x86_64"
```

**The slash-vs-semicolon split — the two tools disagree, and one of them lies.**

| tool | package form | what the other form does |
|---|---|---|
| `sdkmanager.bat` (Android CLI shim) | **slashes**: `system-images/android-30/google_apis/x86_64` | the semicolon form prints `Package system-images not found.` / `android-30 not found` / `google_apis not found` / `x86_64 not found` **and still exits rc=0** |
| `avdmanager.bat` | **semicolons**: `system-images;android-30;google_apis;x86_64` | the slash form is not a package id it knows |

So a script that installs an SDK package must use slashes **and must not trust the exit
code** — grep the output for the downloaded zip instead.

**Create the AVD** (semicolon form here):

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/cmdline-tools/latest/bin/avdmanager.bat" create avd \
    -n LOA_API30 -k "system-images;android-30;google_apis;x86_64" -d pixel_4 --force
"$SDK/emulator/emulator.exe" -list-avds        # -> LOA_API30
```

**Launch it:**

```bash
"$SDK/emulator/emulator.exe" -avd LOA_API30 -no-snapshot-load
```

On Windows run that detached, or it dies with the shell that started it — and note that
a `run_in_background` shell is killed at end of turn, which kills the emulator with it:

```bash
powershell.exe -NoProfile -Command "Start-Process \
  -FilePath 'C:\Users\Stefan.Nasev\AppData\Local\Android\Sdk\emulator\emulator.exe' \
  -ArgumentList '-avd','LOA_API30','-no-snapshot-load' \
  -RedirectStandardOutput 'C:\tmp\loa-emu30-out.txt' \
  -RedirectStandardError 'C:\tmp\loa-emu30-err.txt'"
```

`emulator.exe` then exits and `qemu-system-x86_64.exe` carries the AVD on its own.
Cold boot takes about 20 s; wait for it properly:

```bash
"$SDK/platform-tools/adb.exe" wait-for-device
until [ "$("$SDK/platform-tools/adb.exe" shell getprop sys.boot_completed | tr -d '\r\n')" = "1" ]; do sleep 5; done
```

## 5. The loop

Iterate on `LOA_API30`, on this PC. Nothing needs Stefan or the phone for a routine check.

1. Rebuild and reinstall with the commands in section 6. `adb install -r` takes about
   25 seconds for the 340 MB APK.
2. Run the server on this host and let the client reach it at **`10.0.2.2:8112`**, the
   AVD's built-in alias for the host loopback — that is what `settings.toml` holds and
   it needs no `adb reverse`. Changing the address means editing `settings.toml` and
   re-running `py -3.14 -m client.build_assets`, because it is baked into the assets.
3. Device logcat is available. Clear, launch, capture, then filter on the app's pid plus
   the engine tags:

   ```bash
   SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"; A="$SDK/platform-tools/adb.exe"
   "$A" logcat -c
   "$A" shell am start -n bg.stefan.loa/.GameActivity
   sleep 90
   "$A" logcat -d > /c/tmp/loa-logcat.txt
   PID=$("$A" shell pidof bg.stefan.loa | tr -d '\r\n')
   grep -E "(^[0-9-]+ [0-9:.]+ +$PID )|FindClass|UnsatisfiedLink|dlopen|cocos2d|LuaJIT|LOAStub|luajc|FATAL|AndroidRuntime|ndk_translation" \
       /c/tmp/loa-logcat.txt
   ```

   `LUA ERROR` is the one to grep for first after a Lua patch; a clean boot has none.
4. **The phone stays the acceptance gate.** The AVD is an x86 host running ARM
   translation on Android 11; it proves the build boots and lets changes be iterated
   cheaply, it does not prove the build works on Stefan's device. Nothing ships on a
   green AVD alone.

Standing caveat kept from the API 36 round: `adb` over USB to the **phone** has never
been set up or tested. Do not assume a device logcat when the loop moves to the phone;
the server's own logging is the diagnostic channel there.

## 6. Rebuild, reinstall, relaunch — the exact commands

```bash
cd "/c/Users/Stefan.Nasev/Downloads/Claude Cowork/Claude Code/Projects/loa-private-server"
py -3.14 -m localise.images                         # English images into data/en (after images.toml changes)
py -3.14 -m client.build_assets                       # only after settings.toml changes (~1 min)
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleRelease
cp app/build/outputs/apk/release/app-release.apk /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk

SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/platform-tools/adb.exe" install -r /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
"$SDK/platform-tools/adb.exe" shell am start -n bg.stefan.loa/.GameActivity
```

If the AVD is not already up, boot it with the detached `Start-Process` line in
section 4.

A change to the `PATCHES` list of `client/build_assets.py` — patch 11, the support hero
of the newbie fights, added 26-10-2026 — is a change to the Lua that ships inside the
APK, so it needs both lines above: `py -3.14 -m client.build_assets` and the gradle
rebuild, not only a server restart.

## 7. Milestone 2 acceptance runs (Plan B1), 23-10-2026 to 26-10-2026

Six runs, kept in order. **Run 1 below is history — read "Run 2 and 3" for the current state of
the branch.** The `5_2328` blocker run 1 found was fixed in `c3e6923` and runs 2 and 3 were made
against the fix.

### Run 1, 23-10-2026 — HISTORY (before the `5_2327` handler existed)

Run on `LOA_API30`, cold boot (`-no-snapshot-load`), the APK installed on 21-10-2026 (nothing
under `client/` changed in Plan B1, so no rebuild). Fresh world: `data/player.db` moved aside to
`data/player.db.plan-a-2026-10-21` and a new one created by the run. Server
`py -3.14 -m server`, log `data/server.log`, banner `listening on 0.0.0.0:8112`.

**Outcome as it stood on 23-10-2026 before `c3e6923`: the first half of the milestone passed, the
campaign half was blocked by one missing handler.** The tutorial ran, both summons paid out, guide
progress persisted and a relaunch showed the main city with the guide resumed instead of replayed.
The first campaign fight never started: the client asks `5_2327 QuerySelfTeamReq` after
`LevelIntoRes` and the zero stub of the day answered an empty `5_2328`, which killed
`LineTeam:initByServerTeamBase` in Lua. **That blocker is closed** — see "The 5_2328 blocker"
below and then "Run 2 and 3".

#### The six screenshots

Saved in `C:/tmp/loa-b1/` and in the SDD workspace.

| File | What it proves |
|---|---|
| `b1-01-guide-summon.png` | Tavern UI, guide hand on the single-draw button of banner 1200000. Gold 1,280,000 / diamond 18,888 / energy 60/60 from `QueryMyselfRes`, i.e. the starting kit of Task 6 reached the client. |
| `b1-02-guide-battle.png` | The client-side guide battle mid-fight, guide hand on a skill card, before the result screen. Confirms plan finding 2: the guide battle asks the server for nothing. |
| `b1-03-city-after-tutorial.png` | Main city after `am force-stop` + relaunch. No intro movie, no guide battle; the guide **resumed** with its pointer on 探险. Name `stefan`, VIP 0, gold 1,260,000, diamond 16,888, energy 0/60, both heroes in the hall. This is the milestone's "never replays". |
| `b1-04-campaign-chapter1.png` | Chapter-1 map, opened with **zero** server traffic (plan finding 5). Only stage 1 飞鹰岗哨 is on the map: stage 2 is **not** unlocked, because `last_level` is still 0 (no `LevelOutReq` ever happened). `b1-04a-...-guide-pointer.png` is the same map with the guide hand on stage 1. |
| `b1-05-bag-with-drops.png` | Bag: 圣骑腿甲 x1 (20240, the banner-1200000 draw), 小经验药水 x3 (1100), 符文晶石(小) x2 (1200). Exactly the three `items` rows. **No stage drop**, for the same reason. |
| `b1-06-chapter-chest.png` | Chapter-1 chest 第一章-妖精之乡, stars **0/9**, claim greyed out. The preview is award 600100 read live: 600 diamond, 灵魂石 x6, 60,000 gold, 小经验药水 x12 — the values Task 15 pinned. |

Supporting frames in the same folder: `shot-07-stage1-noenergy.png` (stage panel, 消耗体力 x6 and
可能掉落 x2 — the client's own copy of the energy cost and the visible drop),
`shot-08-challenge-noenergy.png` (the client refuses the fight locally at 0 energy with its own
购买体力 dialog; no `5_2201` leaves the device), `shot-11-after-server-restart.png`.

#### The five assertions (run 1; rows 3 and 4 are superseded by run 2)

| # | Assertion | Outcome | Evidence |
|---|---|---|---|
| 1 | Intro + guide battle play once, `grep -c "saved for player"` at least 1 | **PASS** | 5 saves: guide_id 10037, 10041, 10061, 10081, 10150 (`data/server.log`, 15:58:04 to 15:59:11). |
| 2 | force-stop, relaunch: main city, no intro, no guide battle | **PASS** | `b1-03-city-after-tutorial.png`; server log `login ok, player id 1` with no `created character`. The decisive half of the milestone. |
| 3 | Energy drops by 6 on entering stage 1-1, no relog | **SUPERSEDED — run 2 PASSES.** Then: PASS for one entry, FAIL in aggregate | Each `5_2201` cost exactly 6 and the client saw it live: `energy->changed :>> 54`, then 48, 42, 36. But the client re-sent `5_2201` ten times (the 5_2328 blocker below), so 60 energy went in ten 6-point steps with no fight. **Run 2: one `5_2201` per attempt, no retry storm, 0 energy for a refused entry.** |
| 4 | Stage 2 战斧要塞1 unlocked, stars on 1-1 match the fight | **SUPERSEDED — still not reached in run 2, for a different reason.** Then: FAIL (no fight ran) | No fight ran, so no `5_2203`; `levels` and `chapters` were empty, `last_level` 0, and the map showed stage 1 alone (`b1-04`). **Run 2: the fight runs and `5_2203` arrives, but every fight was lost, so the unlock was never earned.** |
| 5 | Server restart keeps stars, energy, bag, unlocks | **PASS** | DB diffed before and after the restart: identical except `energy` 0 → 1, which is the 360-second regen cycle, not a loss. `shot-11-after-server-restart.png` shows the same city, same balances, guide at the same point. |

#### The 5_2328 blocker — FIXED in `c3e6923`, kept for the Lua trace

**Not current.** `server/modules/team.py` has answered `5_2327` since `c3e6923` and runs 2 and 3
saw zero `LUA ERROR`. What follows is the diagnosis as run 1 recorded it.

`LevelIntoRes` arrives fine. The client then sends `5_2327 QuerySelfTeamReq`
(`FunctionType.lua:1133`) and waits for `5_2328 QuerySelfTeamRes`, which the server does not
handle, so the zero-stub policy answers an empty body:

```
15:59:11 INFO loa.level stage 10000 entered by player 1, 6 energy spent, ...
15:59:12 INFO loa.net   no handler for 5_2327 QuerySelfTeamReq, answering a zero stub
```

```
15:59:11.894 [MMMsgDispatcher:onNetMessage] key=5_2328, msg=table: 0xb0139510, len=0
15:59:11.895 LUA ERROR: [string ".../model/LineTeam.lua"]:34: attempt to index local 'team' (a nil value)
15:59:11.895     [string ".../model/LineTeam.lua"]:34: in function 'initByServerTeamBase'
```

`FunctionType.lua:763-770` branches on `msg.status ~= 0`; status is not a field of
`QuerySelfTeamRes` at all and the native layer supplies 0 from the header (the Plan A finding
again), so the client takes the **success** branch, calls `FightData:initSelfTeam(msg)` with
`msg.team_base` nil and dies at `LineTeam.lua:34`. `openFight` is never reached, the player is
dropped back on the lineup screen, and the retry costs another 6 energy. Four such Lua errors are
in the kept logcat; ten `5_2201` lines are in the server log.

`QuerySelfTeamRes` is `team_base` (`ClientFightTeamBase`: id, source, level, fightAbility, name,
avatar, origin, district, avatar_type, repeated `units` of `ClientFightUnit`), `if_sync`, `refer`,
repeated `urandom`, repeated `buffs`. `FightData:initSelfTeam` also reads `serverSelfTeam.urandom`
and wants 64 values there, so the campaign fight needs its random stream from `5_2328`, not only
from `LevelIntoRes`. That handler is the single thing standing between this build and the campaign
half of milestone 2.

#### Ids the server did not answer in run 1

Verbatim from `grep -E "no handler for|answering a zero stub|sending nothing|Traceback"`, sorted
and de-duplicated. Zero tracebacks, zero `FATAL EXCEPTION`, zero `AndroidRuntime` crashes.

```
no handler for 11_2005 QueryTalkDataReq, answering a zero stub
no handler for 11_2009 QueryHistoryTalkReq, answering a zero stub
no handler for 5_2039 SyncRedPointReq and no paired Res exists, sending nothing
no handler for 5_2145 QueryBuyEnergyReq, answering a zero stub
no handler for 5_2327 QuerySelfTeamReq, answering a zero stub
no handler for 5_2623 LevelReporterQueryReq, answering a zero stub
```

Lua errors seen in the whole run, both harmless apart from the first:

- `LineTeam.lua:34` x4 — the blocker above.
- `ChatRoom...:1163` x1 — the known Plan A chat stub, chat is out of scope.

#### Open questions, as run 1 left them (C, D and E all moved on in run 2)

| | Question | Answer from this run |
|---|---|---|
| **A** | `ClientNotification.flags` byte order | **Settled: little-endian, `notify.FLAGS_BYTE_ORDER = "little"` is correct.** The client logged `energy->changed :>>.................. > 54` after the first stage entry — the exact field and value the brief predicted. The two gacha draws also logged `gold->changed > 1260000` and `diamond->changed > 16888`, so multi-field masks land on the right names too. No patch. |
| **B** | `drop_group.frequency` | **Unchanged, no evidence against ignoring it.** The stage panel's 可能掉落 preview (item 10000 x2) matched the visible roll every time. No payout ran, so "drops too little" could not be judged. |
| **C** | `stage_info.once` and the second entry into a cleared stage | **NOT REACHED.** Nothing was ever cleared, so stage 10010 could not be re-entered. The flag-1 branch was not exercised from the server either: at 0 energy the client refuses locally with its own 购买体力 dialog and never sends `5_2201` (`shot-08-challenge-noenergy.png`). Still open for the re-run after 5_2328. |
| **D** | `ClientHero.spells` | **NOT REACHED.** No campaign battle started, so no hero fired an ultimate from `ClientHero`. The guide battle that did run is entirely client-side with hard-coded units and proves nothing about this. |
| **E** | How far the guide can run | **SUPERSEDED: run 2 reaches and persists 10160, twice.** As run 1 left it: **it stopped at 10150, one step short of the 10160 the plan calls "tutorial completed"** — and for the blocker's reason, not the guide's: 10160 is registered on the battle-result return button, and there is no battle result. Plan Risk 1 (the equip pointer wedging the screen after 10160) **did not happen**: the pointer never got that far, and when the guide ran out of reachable steps it self-terminated and left the city fully usable. |
### Run 2 and 3 (Task 17b, 23-10-2026): after the 5_2327 handler

Same AVD `LOA_API30`, same installed APK, HEAD `c3e6923` (Task 18's `server/modules/team.py`).
No code was changed by these runs. Run-1 energy was below the 6 a stage costs, so `data/player.db`
was **moved** aside to `data/player.db.b1-run1` and a fresh world created; a second fresh world
(`data/player.db.b1-run2`) was started to retry the fight, and a third is the DB in place today.
Server banner `23-10-2026 17:01:24 INFO loa.net listening on 0.0.0.0:8112`.

**Outcome: the blocker is gone. The campaign fight runs end to end with zero Lua errors, one
`5_2201` per attempt, a real `5_2203`/`5_2204` round trip and a result screen. What is still not
proven is a WON stage: three fights across two characters all ended `win = 0`, so the star, the
drop payout, `last_level` and the stage-2 unlock were never exercised. The tutorial half of
milestone 2 is MET; the campaign half is unproven.**

| Assertion | Result | Evidence |
|---|---|---|
| The campaign fight starts at all | **PASS** | `17:06:23 loa.team 5_2327 fight_type 2 for player 1: team of 2 unit(s) [(2, 100000), (5, 108000)]`, then the battlefield renders. **Zero `LUA ERROR` in the whole run** — `LineTeam.lua:34` is gone. |
| Energy decreases by 6 per entry | **PASS** | One `5_2201` per attempt, not ten: 60 → 54, then 54 → 48. A **refused** entry costs nothing (54 → 54, 56 → 56 across two locked refusals), so the unlock is checked before the energy is spent. |
| `levels` has (10000, star > 0) | **FAIL (star 0)** | `levels = (10000, star 0, count 1)`: the loss path. The fight was genuinely lost (`win = 0`). |
| `last_level` = 10000 | **FAIL (still 0)** | Correct for a loss — `last_level` only advances on a win. |
| `items` grew | **FAIL (unchanged)** | `award = {}` in `LevelOutRes`; a loss pays nothing. |
| Stage-2 unlock shows in the campaign UI | **NOT REACHED** | Stage 2 is drawn and its panel opens, but entering is refused: `WARNING loa.level 5_2201 stage 10010 is locked (328193)`, right while `last_level` is 0. |
| Stage 2 fought, then re-entered (`once`) | **NOT REACHED** | Nothing was cleared. The **locked** arm of `flag = 1` was exercised instead and behaved as predicted: `incCurLevel`, `closeAllUI`, campaign UI reopened, no wedge. |
| Force-stop + relaunch after the fight shows the city | **PASS** | Main city, no intro, no guide battle, `login ok, player id 1` with no `created character`. |
| Server restart keeps the state | **PASS** | DB diffed before/after: identical except energy 56 → 57, the 360 s regen. |
| Guide reaches and persists 10160 | **PASS (new vs run 1)** | `16:44:38 INFO loa.guide guide_id 10160 saved for player 1`, and again on the second character at 17:07. The plan's definition of "tutorial completed", reached because the result screen now exists. |

**Why the fight was lost, three times** — not a server fault, and the root cause is worth keeping:

- The tutorial's first gold and diamond single draws are **scripted** by `variables.FIRST_GOLD_GACHA`
  (188000, one row: hero 104000) and `variables.FIRST_DIAMOND_GACHA` (189000, one row: hero 210000).
  The original tutorial team is therefore **100000 + 104000 + 210000** (500 HP / 29 atk), where our
  random rolls gave two heroes (300 / 22) or one (100 / 15). `bc59fec` implements the scripted draws.
- **Ultimates are manual taps only** (`BattleHeroItem:onTouchHeroSkill`; the auto path is commented
  out at `BattleHeroItem.lua:403-406` and auto defaults on only from player level 3). The ultimate
  ids the server sends are right, but `spell:1000000` / `spell:1080000` never fired: rage never
  filled in fights that lasted 5 to 17 seconds.
- **There is no battle timeout** (`timeoutStopBattle` has no callers), and the client fights with our
  `unit` block **verbatim** (`BattleUnit:initByPropertyUnit:4145-4171`, no recompute). Attempt 1 was
  left idle for 2 min 28 s between waves while screenshots were taken; attempt 2 had one level-1
  hero. Both are run-technique, not server, problems.

**New finding — the guide deadlocks after a lost first fight** (reproduced on two independent
characters, not patched). Guide 10160 saves on the result-screen return button, then the guide
advances into the equip chain 10180 → 10190 → 10210 → 10280. Its full-screen touch mask allows only
its own target, which on the chapter map is **stage 2** — refused as locked, and a refusal does not
advance the guide (10280 saved twice with no progress). Stage 1-1 cannot be tapped, nor 抽卡 in the
city after a relaunch. The equip step cannot complete either: the slot wants item **10000**, which
drops only from stage 1-1 (`拥有 0 件`). Circular. It gates, it does not freeze — every panel still
renders. **Winning 1-1 removes it.**

**Ids the server still does not answer** (runs 2 and 3, verbatim; `5_2327` is gone from this list,
`5_2013` is new and caused no visible problem). Zero `Traceback`, zero `LUA ERROR`, zero
`FATAL EXCEPTION` across both runs:

```
no handler for 11_2005 QueryTalkDataReq, answering a zero stub
no handler for 11_2009 QueryHistoryTalkReq, answering a zero stub
no handler for 5_2013 SyncEnergyReq, answering a zero stub
no handler for 5_2039 SyncRedPointReq and no paired Res exists, sending nothing
no handler for 5_2145 QueryBuyEnergyReq, answering a zero stub
no handler for 5_2623 LevelReporterQueryReq, answering a zero stub
```

Screenshots `r2-*` and `r3-*` and the kept logs (`C:/tmp/loa-b1/server-r2-run1.log`, `server-r3.log`,
`logcat-r2.txt`, `logcat-r2b.txt`, `logcat-r3.txt`, `db-r2-before-restart.json`,
`db-r2-after-restart.json`) are listed in full in the Task 17b report in the SDD workspace.

### Runs 4 and 5 (Tasks 17c and 17d, 26-10-2026): after the scripted draws

Both on fresh worlds (`data/player.db.b1-run3`, `.b1-run4a`, `.b1-run4b` kept beside the live DB).
Run 4 drove the fight by hand, run 5 with a script tapping the three hero cards every 0.4 s at two
candidate positions for the whole fight and a screenshot every 4 s.

| Fact | Outcome | Evidence |
|---|---|---|
| Scripted first draws | **PASS**, on three characters | `first gold single draw ... drop id 188000` / `... 189000` in the server log; hero hall 100000 + 104000 + 210000, lineup 战力 3000 |
| Relaunch and server restart keep the world | **PASS** | run 4: DB identical except the 360 s energy regen |
| Guide mask during the fight | **none** | logcat: `新手引导 > scene 清除成功` at the stage entry, every guide check during the fight `引导接不上`; the toasts on the defeat screen come from step 10160's mask on the Continue button |
| Hero ultimates | **fire**: 7 casts in run 5 (`spell:1000000` x2, `spell:1040000` x2, `spell:2100000` x3) | logcat-run5.txt; a card glows exactly when its rage is full |
| Stage 1-1 | **LOST** in every attempt (runs 4 and 5: 89 s, 71 s, 89 s) | `LevelOutRes win = 0`; first `战斗人物退出` 14 s in |
| Our hero `unit` block | equals the client's own computation, field by field | `BattleUnit:initByPropertyUnit` is the same path for heroes and npcs; every value = `npc_info` |

The stock server's answer to this fight is `variables.NEW_FIGHT_HELP_HERO` = 1103009 冰雪女皇
(level 6, 2,098 HP, 222 power, memo: the supporting hero of the newbie fights, stages 1-2). No
client code references it and the campaign factory creates only the local lineup's units, so
the route is a client patch plus a server rule — see `docs/TODO.md`, "Next". Logs and screenshots:
`C:/tmp/loa-b1/logcat-run4*.txt`, `logcat-run5.txt`, `r4-*`, `r4b-*`, `r5-*`, and the Task 17c/17d
reports in the SDD workspace. Ids still unanswered: unchanged (5_2013, 5_2039, 5_2145, 5_2623,
11_2005, 11_2009).

### Run 6 (Task 17e, 26-10-2026): with the support hero — the campaign half is MET

Same AVD `LOA_API30`, warm. HEAD `df4db75` (the Task 19 support-hero rule plus patch 11); no code
was changed by the run. **Step 0 is new here: patch 11 lives inside the APK's assets**, so
`py -3.14 -m client.build_assets` ran first (eleven `patched` lines, the last one
`BattleFactoryBase.lua`) and then `./gradlew.bat --no-daemon :app:assembleRelease`,
**BUILD SUCCESSFUL in 3 m 26 s**. The APK is 340,864,368 bytes — 1,669 bytes more than run 5's
installed build — and `adb install -r` upgraded it **in place**: `firstInstallTime` stays
21-10-2026, `lastUpdateTime` 26-10-2026 12:44, nothing uninstalled, no app data lost. Fresh world:
`data/player.db` **moved** aside to `data/player.db.b1-run5`. Server banner
`26-10-2026 12:45:13 INFO loa.net listening on 0.0.0.0:8112`.

**Outcome: stage 1-1 won with 3 stars in 40 s, stage 1-2 won with 3 stars in 48 s. The campaign
half of milestone 2 is MET, so milestone 2 is MET on both halves.** The support hero is the whole
difference, not the taps: run 5 lost the same stage with seven hero ultimates; run 6 won it with
**two casts of the npc's own `spell:3110001`** plus one knight cast — and stage 1-1 was played with
mis-measured card coordinates, so most of its taps missed.

| # | Assertion | Result | Evidence |
|---|---|---|---|
| 1 | Three heroes after the two guided summons | **PASS** | `12:49:37 first gold single draw ... banner 1200000 ... [(30, 104000, 1)]` and `12:51:12 ... banner 2400000 ... [(30, 210000, 1)]`; lineup 战力 **3000** (`r6-lineup.png`) |
| 2 | The support hero is in the `5_2327` team for stage 10000 | **PASS** | `12:53:48 loa.team stage 10000 is a newbie fight, support hero 1103009 joins at position 1`, then `team of 4 unit(s) [(2, 100000), (4, 210000), (6, 104000), (1, 1103009)]` |
| 3 | Patch 11 ran on the device | **PASS** | logcat `12:53:47.865 ... support unit from server at place` (once, in `getAttackers`, 1.1 s before `LevelIntoRes` reaches the client); the built asset greps 1 for `initByServerFightHero(serverInfo,false)` |
| 4 | A fourth unit is drawn and fights | **PASS (partial)** | `r6-fight-4.png`: four attacker sprites, the ice queen 1103009 among them; `r6-fight-5.png`: four HP/rage bar pairs but only **three portrait cards** — the support NPC has bars and no card. Cosmetic: it fights and casts |
| 5 | Stage 1-1 won with stars | **PASS** | `12:54:28 stage 10000 finished by player 1 with 3 star(s), won=True`, `r6-result.png` |
| 6 | Energy per entry | **PASS** | 6 per entry on both stages |
| 7 | Payout: gold / xp / items / `levels` / `last_level` | **PASS** | +516 gold and 粗布头巾 10000 x2 from stage 1; +516 gold, soul stone 500000 x10 and three gear items from stage 2; every hero +21 xp → **level 2**; `levels` both rows at **star 3**; `last_level` **10010** |
| 8 | Stage 2 unlocked | **PASS** | `b1-04-campaign-chapter1.png`: 飞鹰岗哨 ★★★ and the 战斧要塞 node live on the map |
| 9 | Item 10000 in the bag | **PASS in the DB** | `items` row `(3, 1, 10000, 2)`; the 包裹 button itself is swallowed by guide 10290 (`b1-05-bag-blocked-by-guide.png`), the same mask run 2 hit |
| 10 | Guide past 10160 | **PASS** | 10150 → 10160 → … → **10290**. The run-2/4/5 deadlock at 10160 is gone |
| 11 | Stage 1-2, the support hero joins there too | **PASS** | `13:02:20 stage 10010 is a newbie fight, support hero 1103009 joins at position 1`, `13:03:08 ... 3 star(s), won=True` (48 s), `r6-s2-8.png` |
| 12 | Chapter chest | **NOT REACHED** | Energy was 61/62, so it was affordable; guide 10290 (女神) masks the chapter map and a tap on the 战斧要塞 node did nothing (`r6-45-stage3-panel.png`). `chapters` empty, no energy bought |
| 13 | Relaunch persistence | **PASS** | No intro, no guide battle, main city with the guide resumed at 10290; level 2, 62/62 energy (`b1-03-city-after-tutorial.png`, `r6-44-city-after-relaunch.png`) |
| 14 | Server-restart persistence | **PASS** | `13:52:48 login ok, player id 1` with **no** `created character` (`r6-after-server-restart.png`) |

Rows 1 to 5 are the chain runs 2 to 5 never completed, and they are the reason the campaign half
now counts as met: the team reaches the client, the patch builds the unit, the unit fights, the
stage is won. Row 4 is the one honest partial, row 12 the one thing not reached.

Greps, verbatim: `grep -cE "Traceback|ERROR"` on the server logs → **0**; logcat (43,768 lines)
`LUA ERROR` **0**, `FATAL` **0**, `FATAL EXCEPTION` **0** (`AndroidRuntime` 1,618, all boot noise).
The unanswered ids are identical to runs 2 to 5: 5_2013, 5_2039, 5_2145, 5_2623, 11_2005, 11_2009.

Two things to know before the next fight. The card row **re-centres when the fourth unit joins** —
the measured centres are `667 901 / 901 901 / 1134 901 / 1368 901`, not run 5's three-card row — and
the device's logcat ring buffer dropped the `cocos2d-x debug info` lines of the stage-1-2 fight
before it was captured, so that stage's evidence is the server log plus screenshots, not a cast
list. The guide's equip chain now stops on `需求英雄等级:2` with the heroes still level 1 at that
moment (they reach level 2 from the stage-1-1 result), and the guide no longer wedges there: it
moves on to 10290 by itself.

Open questions after run 6:

| | Question | State |
|---|---|---|
| **C** | `stage_info.once` and the second entry into a cleared stage | **Still open.** Stage 10010 carries `once = 1` and was cleared at star 3, but it was never re-entered (`levels` count 1), so the flag-1 branch is still unexercised from a *cleared* stage. |
| **D** | `ClientHero.spells` | **Answered by run 5:** hero ultimates fire from the server's `spells` list. Run 6 adds the same for a type-3 unit — the server sent `spells` [3110001, 10000000] and `spell:3110001` fired twice. |

Logs and frames kept: `C:/tmp/loa-server-b1-run6.err.log`, `...run6b.err.log` (post-restart),
`C:/tmp/loa-b1/logcat-run6.txt` (the complete stage-1-1 capture), `fight-window6.txt`,
`logcat-run6-full.txt`, `tapper6.sh`, `shooter6.sh`, and the `r6-*` screenshots, listed in full in
the Task 17e report in the SDD workspace.

### Run 7 (Plan B2 ACC-1, 24-11-2026): tutorial path through the angel summon

Same AVD `LOA_API30`, warm, the English APK installed 24-11-2026 11:39 (versionName 1.0.0.5);
no client change in Plan B2, so no rebuild. Branch `plan-b2-wave1`, server HEAD `dcd8a44` (T1-T8
plus the zero-stock fix). Fresh world: `data/player.db` **moved** to `data/player.db.pre-b2-acc1`.
Server banner `24-11-2026 12:31:09 INFO loa.net listening on 0.0.0.0:8112`. Fights were driven
with run 6's `tapper6.sh` (card row `667/901/1134/1368 x 901` plus wave point `1938 530`).

**Outcome: the guide now runs from the first summon through 10160 → 10210 (equip) → 10290 →
10293 (angel summon) → 10297 → angel fielded (10352) → 10310-10313 (Equip All with crafting) →
10380 (quality-up) → 10390, with no wedge. Assertions 1-4, 6 and 7 pass. The chapter chest
(assertion 5) was not reached: the client counts only `once = 0` stages, so it needs the boss
stage 10022, which was lost twice without the support hero.**

| # | Assertion | Result | Evidence |
|---|---|---|---|
| 1 | Hero list shows Lv.2 without a relaunch | **PASS** | After stage 1-1 (won 3 stars in 48 s, `12:37:28`), the hero list shows all three at **2**, Rose Knight's slot 1 marked Equippable (`02-hero-list-lv2-equippable-no-relaunch.jpg`, `03-...`, `05-...`). Run 6's `需求英雄等级:2` stop is gone. |
| 2 | Guide 10180→10210 equips 10000 on Rose Knight slot 1 | **PASS** | `12:38:45 guide_id 10210 saved`, `12:38:45 loa.hero hero 100000 of player 1 equips 10000 in slot 0`; DB copy `heroes(100000).item0 = 10000`, bag 10000 2 → 1 (`04-hood-10000-equipped-slot1.jpg`). |
| 3 | 10290→10293: summon 500000 opens `AngelSummonAlert`; `angels` row; stones 10 → 0 | **PASS** | `12:41:33 guide_id 10293 saved`, `12:41:33 loa.angel angel 500000 summoned by player 1 for 10x 500000`; DB copy `angels = (500000, level 1, exp 0, star 1)`, the 500000 `items` row gone (10 → 0, deleted by `dcd8a44`) (`06-angel-summon-alert.jpg`, `07-...`, `08-angels-collected-1-of-30.jpg`). |
| 4 | Guide 10294→10297→10340→10352 (angel in line-up)→10370 | **PASS** | The angel panel opens and closes (`09-...`), the guide moves to the next stage (`10-...`), the line-up's Angel tab fields Idol Angel (`11-angel-fielded-in-lineup.jpg`). Only some of these steps save server-side, so the evidence is the screens. |
| 5 | Stage 10012 3-starred; chapter-1 chest pays (`star_req0` 9, 5_2209) | **10012 PASS, chest NOT REACHED** | `12:44:24 stage 10012 finished ... 3 star(s), won=True` (`12-...`). The chest showed **6/9** after 10012 and still 6/9 after 10020 (3 stars, `12:47:09`): `LevelManager:getAllGotStar` sums only stages with `once == 0`, i.e. 10000, 10012 and **10022** (10010 and 10020 are `once = 1`). Boss 10022 was lost twice (`12:52:29`, `12:56:09`, 0 stars). `chapters` stays empty; no 5_2209 was sent (`13-...`, `21-...`, `22-...`, `23-...`). |
| 6 | Threads 10310-10313, 10380, 10440-10451 | **10310-10313 PASS, 10380 PASS, 10440-10451 not triggered** | `12:48:21 guide_id 10310`, `12:48:47 10312`, `12:49:00 10313`, `12:49:00 loa.hero hero 100000 ... equips all: slots [1, 2, 3, 4, 5], 1600 gold` — the client's own preview said the same five items, two crafts, **1600 gold** (`16-...`); DB: six slots `10000, 11010, 11120, 11040, 11020, 11170`, gold 1,262,066 → 1,260,466. Then `12:49:13 guide_id 10380`, `raised to quality 20`; the success panel **appeared** (it needs the Res plus exactly one hero notify), green name, "skill awakening" Holy Sword of Light, slots cleared to the quality-20 set (`18-...`, `19-...`, `20-...`); `12:49:56 guide_id 10390`. |
| 7 | Relaunch keeps gear and angel; server restart logs `login ok` with no `created character` | **PASS** | force-stop + relaunch: `12:58:37 login ok`, Idol Angel stands in the city, Mage's pendant 10030 and Ranger's hood stay in their slots, Rose Knight green (`24-...`, `25-...`). Server killed and restarted (`13:07:07` banner): `13:08:04 login ok, player id 1`, no `created character` (`26-...`). DB before/after the restart: `heroes`, `angels`, `items`, `levels`, `chapters` identical; `players` differs only in `energy` 48 → 49 and `energy_at` (the 360 s regen). |
| 8 | `grep -cE "Traceback\|ERROR"` server = 0; logcat `LUA ERROR` = 0 | **server PASS (0); logcat FAIL (3)** | Server, both logs: **0**. Logcat (5 captures, 159,134 lines): `FATAL` 0, `FATAL EXCEPTION` 0, `LUA ERROR` **3**: 2 x the known `ChatRoom:1163` from `11_2006` on main-city login (Plan B2 task B1 fixes it), and 1 x `RoleEquipGetEquipPanel.lua:44 attempt to index field 'itemVo'` during the guided equip at 12:38:43. That listener reads `self.itemVo.entry` on every `INFO_CHANGE_NTF_ITEM` while the guide's panel has no `itemVo`; any server that pushes the bag decrement on equip trips it, so it is a stock-client quirk, not patched (no Lua change in this plan). |
| 9 | Unanswered ids vs run 6 | **unchanged** | `11_2005`, `11_2009`, `5_2013`, `5_2039`, `5_2145`, `5_2623` — identical to runs 2 to 6. |

Findings for the next tasks:

- **Equip All on a shared material.** Jungle Ranger's quality-10 slot 0 wants 10000 and slot 1
  crafts 10120 from 10000 + 10030. With one 10000 in the bag the client's preview offered both
  (it checks each slot against the whole bag), the server equipped the hood and skipped the craft
  (`12:54:23 ... equips all: slots [0], 0 gold`) because it validates the plan against one simulated
  bag. No gold was charged for the skipped craft. Faithful to the bag; noted in case Stefan sees it.
- **The angel in the fight.** `5_2327` still logs `WARNING loa.team ... asks for angel 500000 in the
  angel slot; angels are not in Plan B1, the fight runs without it` (4 times). Plan settled point 7
  says the client builds the angel unit itself; the result screens show the angel with EXP +21/+22.
  The warning text is stale; `team.py` was not touched in this run.
- **Power.** Hero power stays 3000 / 1000 with gear and quality (O1) and the angel shows Power 0 (O2),
  as the plan's defaults say.

Logs and DB copies (not in the repo): `C:/tmp/loa-acc1/server.log`, `server-restart.log`,
`logcat-part1..5.txt`, `db-after-12.db`, `db-after-summon.db`, `db-pre-equipall.db`,
`db-post-equipall.db`, `db-before-restart.db`, `db-after-restart.db`. Frames:
`docs/screens/en-2026-11-24-acc1/01-...` to `27-...` (JPEG q85).

### Run 8 (Plan B2 ACC-2, 24-11-2026): Wave 1 dailies

Same AVD `LOA_API30`, warm, same English APK (versionName 1.0.0.5); server-only changes since run 7,
so no rebuild. Branch `plan-b2-wave1`, server HEAD `cc2c778` (Phase B, W1, E1, and prize categories
51/52). The ACC-1 world continues: `data/player.db` was **copied** to `data/player.db.pre-b2-acc2`
(and `C:/tmp/loa-acc2/db-start.db`). Server banner `24-11-2026 14:48:20 INFO loa.net listening on
0.0.0.0:8112`. Rows 5 and 7 and the login-gift days 3 and 5 ran on **throwaway copies** in
`C:/tmp/loa-acc2/` served by `C:/tmp/loa-acc2/throwaway_server.py <db>`. That wrapper replaces
`Settings.db_path` after `settings.toml` is loaded, so `data/player.db` was never swapped. Its SHA-1
was `837c9693...` before and after the three throwaway runs.

**Outcome: sign-in, the 7-day gift (day 1 on the real world; days 3 and 5 on a copy), the VIP-0
purchase refusals, the 6-minute energy timer, mail, the shop and both persistence checks pass. Boss
stage 10022 was lost twice, so achievement kind 2 / guide 10400 was not reached; sweep is locked
until level 8.**

| # | Assertion | Result | Evidence |
|---|---|---|---|
| 1 | Sign-in opens, day N pays, `checkins` row written | **PASS** | `14:50:20 loa.checkin player 1 signed in day 24, position 1: (20, 30000154, 1)`; the panel turns from "Not Checked In" to "Checked In Today", 累计签到礼包 0/5 → 1/5, reward Top-Up Item 30. DB: `checkins = (1, 202611, 8388608 = bit 23, 0, 0, total_times 1, 0)`, item 30000154 x1 (`02-...`, `03-...`). |
| 2 | 7-day gift day 1 pays; `login_award` bit 9 set | **PASS** | Login logs `player 1 login day 1 of the 7-day gift (2026-11-24)`; `14:51:01 claimed 7-day gift day 1: [(9, 0, 1000), (1, 0, 40000), (20, 100000, 10), (20, 100, 3)]`; HUD gold 1,260,466 → 1,300,466, diamonds 16,888 → 17,888. DB `login_award = 257` (bit 0 claimable + bit 8, the 9th bit, claimed) (`04-...`, `05-...`). |
| 3 | Buy energy / buy gold at VIP 0 refused | **PASS (client-side)** | Both "+" buttons open the client's own "Daily use limit reached (Used Today 0/0)" box with "Raise your VIP level". The client refuses **before** sending anything: no 5_2141/5_2147 reached the server. This is the English client's dialog, not a floated 购买次数不足, so O8 closes as "the client never asks at VIP 0" (`06-...`, `07-...`). |
| 4 | Energy tooltip matches 360 s; 5_2013 gone from the unanswered list | **PASS** | At 53/64 the long-press tooltip reads "Next Stamina in: 00:05:41 / Full Stamina in: 01:05:41 / Stamina Recovery Time: 6 min" (`12-...`). DB `energy_at` 1795525118 is consistent with that countdown. `5_2013` appears 0 times in the "no handler" lines of all five server logs. |
| 5 | Mail on a throwaway copy: one `QA-DELETE-ME` mail, claim, `items`, delete | **PASS** | `throwaway-mail.db`: inserted mail entry 99999, sender/subject/body `QA-DELETE-ME`, attachment `(20, 100, 1)`. The mailbox lists it (Unread 1); opening it shows the template subject "Item Limit Warning" and the body `The item "QA-DELETE-ME" in your Bag ...`; Claim → Rewards: Divination Crystal. DB: item 100 3 → 4, mail `checked 1, claimed 1`; the row was then deleted (0 mails left). The copy was not used again (`16-...` to `18-...`). |
| 6 | Chapter 1 (10022) completes achievement kind 2; guide 10400→10420 | **NOT REACHED** | Two attempts with the three level-3 heroes: `14:54:36 stage 10022 finished ... 0 star(s), won=False` and `14:57:49 ... won=False` (`10-...`, `11-...`). Each cost 6 energy (64 → 52). No balance or DB change was made to force a win. |
| 7 | Shop on a throwaway copy with level 12: store 1 lists 8 slots, one purchase | **PASS** | `throwaway-shop.db`, `players.level = 12`. General Shop lists the soul-stone slots at 280 diamonds; the `stores` row holds **8** slots (`100480, 100450, 100290, 100310, 100230, 100490, 100240, 100250`). `15:14:24 loa.shop player 1 bought merchandise 100480 (store 1 slot 0) for 280 in 9`; diamonds 17,888 → 17,608, slot 0 `buy: 1` and stamped sold, item 304000 x1 (`20-...` to `22-...`). |
| 8 | Sweep (unlock 8) | **NOT REACHED** | Player level 3; the stage panel says "Alliance Level Reached 8 Lv. or VIP reaches 7 Unlock Sweep", and the map shows "Sweep Ticket (0)" (`09-...`). |
| 9 | Relaunch and server-restart persistence | **PASS** | Force-stop + relaunch: `15:00:16 login ok`, same balances, the 7-day panel starts at day 2 ("Claim Tomorrow"), sign-in says "Checked In Today" (`13-...` to `15-...`). Server killed and restarted (`15:01:52` banner): `15:02:43 login ok, player id 1`, no `created character` (`server-restart.log`). DB before/after the restart: **every table identical**. |
| 10 | Both greps = 0; main-city `LUA ERROR` = 0 | **PASS** | `grep -cE "Traceback\|ERROR"` = **0** in all five server logs. Logcat (7 captures, 132,954 lines): `LUA ERROR` **0**, `FATAL` **0**. The run-7 `ChatRoom:1163` (`11_2006`) error is gone. |

**Login gift days 3 and 5.** Days 3 and 5 need real calendar days on the real world, so they were
not reachable there. On `throwaway-gift.db` (`login_days = 5`, `login_award = 287`), days 2-5 show
"Claimable" (`23-...`). Results:
- Day 3: `15:16:31 claimed 7-day gift day 3: [(9, 0, 3000), (1, 0, 2000000), (20, 100000, 40),
  (52, 0, 1000)]`, rewards panel "Trial Coins 1000" (`24-...`).
- Day 5: `15:17:02 ... day 5: [..., (20, 202000, 40), (51, 0, 1000)]`, "Arena Coins 1000" (`25-...`).

DB `arena_point = 1000`, `angel_money = 1000`. The client applied both notifies; logcat shows
`angel_money->changed ... > 1000` at 15:16:30 and `arena_point->changed ... > 1000` at 15:17:00.

**Unanswered ids** (all server logs): `5_2039` (every login), `5_2623`, and **new** `5_2149
SellAllGoldStockReq`. Runs 2-7 also listed `11_2005`, `11_2009`, `5_2013` and `5_2145`; none of
them appears now.

Findings for the next tasks:

- **5_2149 sell-all.** Opening the shop pops the client's "The merchant begs you to sell him these
  treasures" box (Cloth x2, 1000 gold). Clearance sends `5_2149`, which gets a zero stub, so nothing
  is sold (item 1050 stays 2, gold unchanged) and the box comes back after every purchase (`19-...`,
  `22-...`).
- **The guide burst after a defeat.** Three seconds after each lost 10022 the client sends 5_2041
  for 10160, 10159, 10290, 10330, 10380, 10500, 10540 and 10580. The server saves the ones that
  have a row, so `guide_id` went 10390 → **10380**. The next relaunch re-saved 10390 (`15:00:43`),
  so the world ended at 10390. The server could refuse a lower guide id; that is a decision for
  Stefan, not a run-8 change.
- **Untranslated / layout.** 累计签到礼包 (sign-in), 已领取 (mail claimed stamp) and 已售 (shop
  sold stamp) are still Chinese. The mailbox row overlaps its texts ("ThemItem Limit Warning",
  "Rema7niDays") and prints the date as `2026-11-24` (client-side layout).

Real-world changes from the normal play rows (start → end): gold 1,260,466 → 1,300,466, diamonds
16,888 → 17,888, energy 49 → 53, `login_award` 0 → 257, `login_days` 0 → 1, `last_login_day`
`2026-11-24`, the two new coin columns 0. Items 30000154 x1, 100000 x10 and 100 x3 were added. One
`checkins` row and 9 `events` rows (achievement progress) were added. The `levels` rows got today's
deadline, and 10022 has count 2. `heroes`, `angels`, `chapters`, `mails` and `stores` are
unchanged; `guide_id` is 10390.

Logs and DB copies (not in the repo): `C:/tmp/loa-acc2/server.log`, `server-restart.log`,
`server-throwaway-{mail,shop,gift}.log`, `logcat-part1..4.txt`,
`logcat-part5-throwaway-mail.txt`, `logcat-part6-throwaway-shop.txt`,
`logcat-part7-throwaway-gift.txt`, `db-start.db`, `db-after-signin.db`, `db-after-loginaward.db`,
`db-after-try1.db`, `db-energy.db`, `db-before-restart.db`, `db-after-restart.db`,
`real-before-throwaway.db`, `throwaway-{mail,shop,gift}.db`. Frames:
`docs/screens/en-2026-11-24-acc2/01-...` to `25-...` (JPEG q85).

### Pre-launch checklist for the next run

1. **Move `data/player.db` aside, never delete it.** The worlds kept beside it are
   `data/player.db.plan-a-2026-10-21` (Stefan's Plan A character),
   `data/player.db.b1-run1` and `data/player.db.b1-run2`.
2. **Win stage 1-1 with the support hero.** It joins by itself — the server log says
   `stage 10000 is a newbie fight, support hero 1103009 joins at position N` and the logcat says
   `support unit from server at place` — and run 6 won 1-1 and 1-2 with it, where three level-1
   heroes lose even with every ultimate fired (runs 4 and 5). Tap the glowing cards and advance the
   waves promptly; put the wave-advance point `1938 530` in the tap cycle, and use the four-card
   row `667 901 / 901 901 / 1134 901 / 1368 901` (it re-centres when the support unit joins).
3. **Then the restart-persistence pass:** force-stop and relaunch the app, then stop and restart the
   server, and diff the DB before and after (only energy may move, by the 360 s regen).
4. **Both of these must come out zero:** `grep -c Traceback data/server.log` and
   `adb logcat | grep "LUA ERROR"`.
