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

### Run 9 (boss 10022 diagnosis, 25-11-2026): why the chapter-1 boss is lost, and what the original does

Same AVD `LOA_API30`, warm, same English APK (versionName 1.0.0.5), no rebuild (no Lua change).
Branch `plan-b2-wave1`, server HEAD `fd1a303` for the diagnosis, `de0d03a` after the one fix.
The ACC-2 world continues: `data/player.db` was **copied** to `data/player.db.pre-boss-diag`
(SHA-1 `837c9693...`, identical before the run). Server banner
`25-11-2026 08:59:22 INFO loa.net listening on 0.0.0.0:8112`, `09:00:40 login ok, player id 1`.
Fights were driven with `C:/tmp/loa-boss/tapper9.sh` over the measured three-card row
`787 895 / 1018 895 / 1250 895`, the angel card `163 895` and the wave point `1938 530`.

**Outcome: 10022 lost twice more (`09:06:29` and `09:11:38`, 0 stars, 12 energy). The loss is
not a server bug. Every stat the server sends is what the client fights with, level growth,
gear and quality all reach the fight, and by the engine's own damage formula three level-3
one-star heroes are about five times too weak for the wave-3 dragon (1,189 HP, 37 attack).
The original expects a new player to grow before this stage; the levers it offers are
Train (hero XP potions), Skill Upgrade, the free daily diamond draw that is scripted to pay a
3-star hero right after the guide, and the 7-day gift hero, and the first three of those do
nothing on our server. One real bug was found on the way and fixed: a prize hero was born at
star 1, level 1 instead of `hero_info.star` / `init_level` (`de0d03a`).**

**1. Do gear, quality and level reach the battle stats? Yes.** The client applies the server's
`unit` block verbatim: `BattleUnit:initByPropertyUnit(unit)` copies the 24 stats one for one
(BattleUnit.lua:4145-4171), and the campaign factory refreshes the local hero from the 5_2327
answer (`BattleFactoryBase:initUnitData` → `ClientHero:refreshFightData(serverInfo)` →
`unit:refresh(data.unit)`, BattleFactoryBase.lua:215-231, ClientHero.lua:232-246). The hero's
Attributes tab shows the same numbers (`04-rose-knight-attributes-match-server-unit.jpg`):

| Rose Knight 100000, q20, L3 (ACC-2 row) | server `unit` | Attributes tab |
|---|---|---|
| max_hp / power / defence / magic_defence | 211 / 31.69 / 15.13 / 14.60 | HP 211 / P.ATK 32 / P.DEF 15 / M.DEF 15 |
| agility / hit / dodge / crit / tenacity / block | 13.28 / 0.66 / 7.84 / 1.10 / 4.36 / 3.74 | 13 / 1 / 7 / 1 / 4 / 3 |

Variants (`server.modules.hero.build_client_hero` on a read-only copy of the ACC-2 DB):

| hero / variant | proto | max_hp | power | defence | spells |
|---|---|---|---|---|---|
| 100000 L1 q10 no gear | 100000 | 100 | 15.0 | 5.0 | [1000000] |
| 100000 L3 q10 no gear | 100000 | 181 | 25.7 | 12.1 | [1000000] |
| 100000 L3 q10 + the six q10 items | 100000 | 466 | 60.7 | 26.1 | [1000000] |
| **100000 L3 q20 no gear (now)** | 100010 | 211 | 31.7 | 15.1 | [1000000, 1001000] |
| 100000 L6 q20 no gear | 100010 | 334 | 47.7 | 25.8 | [1000000, 1001000] |
| 104000 L1 / **L3 + 10030 (now)** | 104000 | 200 / 358 | 7.0 / 22.0 | 2.0 / 7.5 | [1040000] |
| 210000 L1 / **L3 + 10000 (now)** | 210000 | 200 / 269 | 7.0 / 24.6 | 0.0 / 7.3 | [2100000] |

Level growth is additive, `npc_info + (level-1) x hero_growth(hero, star)`, and that matches the
real server's own dump in ClientHero.lua:249-288 (hero 300000, L80, star 5, q43): our formula
gives `hit_base` 85.16 against the dump's 86.24 (the rest is level-80 gear/runes the dump
includes). Nothing is missing, unscaled or double-counted. `Power 1000` is cosmetic: `ability`
is stored (`setValue(BattleDefine.ability)`) and never read by the damage path, which uses
`power`/`magic` against `defence`/`magic_defence` (`BattleUnit:EA/ED`, BattleEngine.lua:486-523).
Note that quality-up **lowered** the knight's working stats for now: q10 with the six q10 items
is 466 HP / 60.7 power, q20 with empty slots is 211 / 31.7 (the q20 set is 20010/20020/10120/
10150/10040/10000, none owned).

**2. The enemy.** `stage_info` 10022 死亡矿洞 (idx 5, `once` 0, `catalog` 3, three groups, energy 6):

| wave | group | units (npc_info: HP / atk / def, skills) |
|---|---|---|
| 1 | 100220 | 骷髅射手 1002007: 152 / 34 / 6, strike 107000 + 1070000 (3 hits) |
| 2 | 100221 | 4 x 骷髅怪 1002001: 37 / 16 / 24; 骷髅王 1002008: 198 / 31 / 7, 3010000 |
| 3 | 100222 | **魔龙 1002009: 1,189 / 37 / 10**, strike 900000 = 2 hits on **all** (target 1999, code 999 = 全体), 龙息 10070000 = 4 hits x (0.75 x dmg + 1.6) on all |

Total 1,687 HP over three waves; stage 10020, won with 3 stars the day before, is 564 HP over
two waves with a 153 / 27 / 7 boss. Enemies come from the client's own tables
(`BattleFactoryLevel:getDefendersByCurIndex` → `npc_group_info` → `npc_info`,
BattleFactoryLevel.lua:195-233); the server never touches them.

**3. The formula and the matchup.** `damage = atk x ATT_PARA(1) - def x DEF_PARA(1)`, floor
`0.1 x atk`, then `x spell_damage_add_scale + spell_damage_add_value` of the strike or the
ultimate (BattleEngine.lua:486-559, variables ATT_PARA/DEF_PARA = 1). Against the dragon our
three normal attacks are 21.7 + 12.0 + 14.6 = **48 per round, 25 rounds** to kill it; the dragon's
two strike hits per round are 44 / 59 / 59 on the knight / mage / ranger, so each dies in **4.5
to 6 rounds** before the breath (another 72-96 each per cast). Observed: waves 1 and 2 cleared
at full HP (`08-`, `09-`), the dragon entered at 02:23 of the wave timer, the Rose Knight was
dead and the other two at ~15 % at 02:06 (`10-fight1-wave3-24s-rose-knight-dead.jpg`), Defeat
at ~02:00. Fight 2 the same (`13-`, `14-`). Two corrections to the "known facts": the stage **has
a 2:30 timer per wave** on the HUD (`07-fight1-wave1-timer-0229.jpg`), and the **angel's rage bar
never moved** from its 50 % start in either fight (initial_energy 250 of 500;
`Battle:onafterround` is meant to add ANGEL_ANGER_ADD_PERROUND 250 per round, Battle.lua:1771-1782),
so her 40-point no-defence judgment and 40-point group heal were never available. That path is
the stock client's and runs the same against the original server; noted, not chased.

**4. What the original does for a new player here.** The Defeat screen itself says it
(`12-defeat-tips-train-aura-skill-upgrade.jpg`): "You can boost your power by: Train, Aura
Upgrade, Skill Upgrade". The stock config behind that, and our state:

| lever | stock evidence | our server |
|---|---|---|
| Skill levels | `spell_level_up`: skill0 may be level 2 at hero level 3, 3 at 5, 4 at 7; the client sends `5_2103 HeroSkillUpReq {hero, index, spell_entry}` with gold `spell_info.upgrade_cost` (500, 1000, ...); the real server sends the levelled entries (`spells = 3000039, 3001026, ...` in ClientHero.lua:253-258) | **no handler**; `spells` is always `npc_info.skill0..4` at level 1 |
| Train (hero XP) | item 1100 小经验药水 = 60 hero XP "used in Train"; `xp_for_level.hero_max_level` 12 at player level 3; stage 10022's invisible drop is 3 x 1100 | `5_2139 train_info` is a stub, no train request handled |
| Free diamond draw after the guide | `gacha_info` 2400000: `free_times 1`, `free_cooldown_cycle 86400`; `variables.FIRST_DIAMOND_GACHA_AFTER_NEWGUIDE` 182000 = "the 3-star hero the first diamond single draw after the newbie guide must drop": pool of ten 2-star heroes (105000, 203000-209000, 211000, 301000) born at level 5 with 372-404 HP / 47-54 attack / 17-22 defence each; then `DIAMOND_SINGLE_GACHA_FIRST_INTERVAL` 1 → the next draw pays a hero from 182100 | the free draw is **charged 2,000 diamonds** and the second diamond draw rolls the normal pool 300000 (146 rows, mostly items); the player owns 17,888 diamonds, so he can still buy draws |
| 7-day gift day 2 | `LOGIN_AWARD` drop 700010: hero 304000 月神祭司 (3-star, init level 5) + 3,000 diamonds + 40 x 202000 + 2,000,000 gold | works (calendar-gated); until `de0d03a` the hero would have arrived at star 1 level 1 |
| Opening gift | `NEW_PLAYER_PRIZE` drop 10003800: 600 diamonds, **200 x 1100 (12,000 hero XP)**, 200,000 gold, 30 x 205000 (= one summon of 闪电幽魂); `NEW_PLAYER_PRIZE2` 90041000: 10 soul stones of six heroes. Memo 开服奖励, no client reference, so the delivery (mail at creation?) is the server's | not granted |
| Support NPC | `NEW_FIGHT_HELP_HERO` memo says stages 1-2 only | as the memo: 10000 and 10010 |
| 4th hero | guide 10399-10450: after the chapter-1 **achievement** pays soul stones, "click here to summon", "a strong ally joins" — i.e. after 10022, not before | n/a |
| Lineup | `LineFrame:startFight` warns below 5 heroes; six hero slots were open on the lineup screen (`06-`) | no cap in `team.py`; the player owns three heroes |

So the original new player who reaches 10022 with the tutorial trio alone loses too; the game
expects at least one of: the post-guide free draw's level-5 2-star hero, a few skill levels,
potions through Train, or a replay grind of the `once = 0` stages (hero XP 20-22 per run).

**5. Fix landed.** `de0d03a fix(item): a prize hero starts at hero_info.star and init_level` —
`grant_prizes` gave every category-30 hero star 1, level 1, while the soul-stone summon already
used `hero_info.star`/`init_level`. Test `test_granted_hero_starts_at_hero_info_star_and_init_level`
(red first: `assert 1 == 3`). It does not change the current trio (all 1-star, init_level 1).

Greps, verbatim: `grep -cE "Traceback|ERROR"` on `C:/tmp/loa-boss/server.err.log` and
`server.out.log` → **0** and **0**; logcat (43,918 lines) `LUA ERROR` **0**, `FATAL EXCEPTION`
**0**. Unanswered ids this run: `5_2039`, `5_2623` (as run 8). Suite after the fix: `py -3.14 -m
pytest -q --basetemp=C:/tmp/pytest-loa-boss` → **605 passed in 110.15s** (604 before).

Real-world changes (start → end): energy 64 → 53 (two entries, one regen tick), `guide_id`
10390 → **10380** (the known post-defeat 5_2041 burst, run 8), `levels` 10022 still `star 0`,
`count` **2** (the count is not raised by a loss). `heroes`, `angels`, `items`, `chapters`, gold
and diamonds unchanged. The third allowed attempt was not spent: no server change can affect
this team, and the two losses reproduce runs 7 and 8 exactly.

Frames: `docs/screens/en-2026-11-25-boss-10022/01-...` to `14-...` (JPEG q85). Logs and
frames kept outside the repo: `C:/tmp/loa-boss/server.err.log`, `server.out.log`,
`logcat-run9.txt`, `f1-*.png`, `f2-*.png`, `tapper9.sh`, `shooter9.sh`, `shots.txt`.

### Run 10 (Plan B2 Wave 2 ACC-W2-1, 25-11-2026): a fresh character wins 10022

Same AVD `LOA_API30`, warm, same English APK (versionName 1.0.0.5), no rebuild (no client change
in this plan). Branch `plan-b2-wave2`, server HEAD `bdfc89c` (A1-A5, suite 667 passed). Fresh
world: `data/player.db` **moved** to `data/player.db.pre-w2-acc1`. Server banner
`25-11-2026 10:13:55 INFO loa.net listening on 0.0.0.0:8112`, `10:14:40 created character
'stefan' as player id 1 with hero 100000, 1280000 gold, 18888 diamonds`. Fights were driven with
a tap loop over the card row and the wave point `1938 530`: the four-card row
`667/901/1134/1368 x 901` for the newbie stages, then the measured rows for 3, 4 and 5 cards
(`784/1016/1248 x 900`; `668/900/1132/1364 x 900`; `552/784/1016/1248/1480 x 900`) plus the angel
card `164 900`.

**Outcome: 10022 won with 3 stars on the first attempt (`11:33:43`, 80 s), with four level-17
heroes, skill0 at Lv.9 on all four and the level-17 angel. The chapter-1 chest paid, the kind-2
achievement was claimed through guide 10400-10410, and guide 10451 summoned the fifth hero.
Relaunch and server restart keep spell levels, `trains` and `diamond_free_day`. Server greps are
0; logcat has 2 `LUA ERROR`s (one known stock quirk, one from the unbuilt `5_2323`).**

| # | Assertion | Result | Evidence |
|---|---|---|---|
| 1 | Tutorial supreme draw: diamonds 18,888, log `k=0 ... free=True` | **PASS** | `10:16:58 loa.gacha supreme single k=0 for player 1: drop 189000, free=True`, pays 210000; HUD 18,888 (`03-...`). Afterwards the supreme card already shows the 2-star tip (`04-...`, see finding 1). |
| 2 | After the guide: 今日首抽免费 + 2-star tip; `k=1 ... drop 182000, free=True`; star-2 level-5 hero, diamonds unchanged | **PASS** | At 10390 the card reads "First Draw Free Today" and 首次单抽 必得二星英雄 (`05-...`, `06-...`). `10:37:04 supreme single k=1 for player 1: drop 182000, free=True`, pays 209000 Astral Hunter; DB `heroes(209000) = star 2, level 5`, diamonds 18,888 (`07-...`, `08-...`, `C:/tmp/loa-accw21/db-after-post-guide-draw.db`). |
| 3 | Two `5_2103` lines; the knight's skill Lv.3, `heroes.spell0_lv = 3`; gold -2,500 | **PASS (on two heroes)** | Guide 11300→11411→11412 (`10:46:42`, `10:47:49`, `10:48:04`) picked the **first card in the hero list**, which is now the 2-star Astral Hunter: `10:47:49 hero 209000 ... skill 0 to level 2 (2090001) for 1000 gold`, `10:48:04 ... to level 3 (2090002) for 1500 gold` (`11-...`). The knight was then raised by hand: `10:48:48 hero 100000 ... skill 0 to level 2 (1000001) for 1000 gold`, `10:48:51 ... level 3 (1000002) for 1500 gold`, Rose Blade Lv.3 (`12-...`); DB `spell0_lv = 3` on both (`db-after-skills.db`). 11413 was never saved; `guide_id` stayed 11412. |
| 4 | Train guide: `5_2119` slot 1 hero, `5_2125 {1100, 1, 1}`, `5_2119` slot 2 angel; level and exp bar | **PASS** | `10:59:06 guide_id 11200`; `11:00:17 places hero 210000 on train slot 1`; `11:00:43 guide_id 11205`, `uses 1x 1100 (of 1 asked) on train slot 1: 60 xp` (bar 3/80 → 63/80); `11:01:19 guide_id 11208`, `places angel 500000 on train slot 2` (`15-...` to `17-...`). Slots 1-3 opened free at quality 1. 11210 was never saved; `guide_id` stayed 11208. |
| 5 | `5_2165` purchases and potions take the line-up to 17 with "exp full" | **PASS** | `11:06:57 buys 176x 1100 for 52800 gold`, `11:23:46 buys 57x 1100 for 17100 gold` (`19-...`). 242 potions used in all: the 9 from the kit and the drops, the 233 bought, 25 of them on the angel. The client stops sending on a full hero, and the last potion of each hero is clipped (`... 6 xp`, `... 26 xp`, `... 30 xp`). All four heroes read Lv17 "EXP Full" (`20-...`, `21-...`); DB `heroes.level 17, xp 899` for all four (`db-trained.db`). |
| 6 | `stage 10022 finished ... won=True` | **PASS** | `11:32:23 stage 10022 entered`, `5_2327 ... team of 4 unit(s) [(2, 100000), (4, 210000), (5, 209000), (6, 104000)]`, `11:33:43 stage 10022 finished by player 1 with 3 star(s), won=True` (`22-...`, `23-...` dragon wave at 02:20, `24-...` Victory, all four "EXP Full"). |
| 7 | Chapter-1 chest pays (`5_2209`, `chapters` award 1) | **PASS** | The chest shows 9/9 (`29-...`). `11:43:58 loa.level chapter 10000 chest paid to player 1: [(9, 0, 600), (20, 104000, 6), (1, 0, 60000), (20, 1100, 12)]` (`30-...`); DB `chapters = (1, 10000, 1)`. The guide mask blocked the chest until 11000 was played (finding 4). |
| 8 | Guide 10399/10400→10420 claims the kind-2 achievement (`5_2241`); 10440→10451 if triggered | **PASS** | "You completed an Achievement" (`25-...`); `11:36:52 guide_id 10400`, `11:37:07 guide_id 10410`, `loa.events player 1 claimed event 10920: [(20, 202000, 30), (1, 0, 300000)]` (`26-...`). Then `11:38:06 guide_id 10451`, `hero 202000 called by player 1 for 30x 202000 and 100000 gold` (`27-...`). 10420 and 10440 were not saved server-side. |
| 9 | Relaunch + server restart: spell levels, `trains`, `diamond_free_day` survive; `login ok`, no `created character` | **PASS** | Force-stop + relaunch: `11:40:09 login ok, player id 1` (`28-...`). Server killed, restarted (`11:45:23` banner), `11:45:57 login ok, player id 1`, `created character` count 0 in `server-restart.err.log`. DB before/after the restart: `heroes` (spell levels 9/6), `diamond_free_day '2026-11-25'` and the three `trains` rows identical; only `energy`/`energy_at` and the passive train settlement (`angels.exp`, `trains.cal_time/addxp`) moved. The tavern shows the free draw used (`33-...`), Train keeps its slots (`32-...`), Rose Knight Lv.9/Lv.6 (`34-...`). |
| 10 | `grep -cE "Traceback\|ERROR"` = 0; logcat `LUA ERROR` = 0 | **server PASS (0); logcat FAIL (2)** | Server: `server.err.log` 0, `server.out.log` 0, `server-restart.err.log` 0, `server-restart.out.log` 0. Logcat (458,220 lines): `FATAL` 0, `LUA ERROR` **2**: `10:21:17 roleUI/roleLe...:44: attempt to index field 'itemVo' (a nil value)` during the guided equip (the known stock quirk from run 7); `10:53:45 angel/AngelSk...:97: attempt to index local 'curAngelInfo' (a nil value)` in `onUpskill`, which is the zero stub answering `5_2323` (guide 12510 at player level 6; task B1 builds it). |
| 11 | Unanswered ids vs run 9 | **one new** | `5_2039` (twice, one per login) and `5_2623` as in run 9, plus **new** `5_2323 UpgradeAngelSpellReq` (once, `10:53:46`, guide 12510 → 12530). |

The grind used stage 10012 only (once = 0, 6 player xp), nine replays from 10:41 to 10:58 at 33-50 s
each with four heroes, all 3 stars. Level 5 at `10:46:18` (guide 11300), level 6 at `10:52:23`
(guide 12510, angel skill), level 8 at `10:58:47` (guide 11200). After training, the skills
went to the hero-level-17 cap: skill0 Lv.9 on all four heroes and the knight's skill1 Lv.6.
Equip All ran again on each hero. The line-up for 10022 was the four heroes plus Idol Angel
(level 17). Imperial Sentinel arrived only after 10022 (guide 10451), so five heroes fought only
in 11000 (won, 3 stars, `11:42:00`), which the guide forced before the chest.

Findings (none blocked the run):

1. **The supreme draw without a ticket.** After the free post-guide draw, the reward screen's
   "Again" sent `5_2123` while the player held no ticket 99. The server charged 2,000 diamonds:
   `10:37:58 supreme single k=2 ... drop 182100, free=False`, 18,888 → 16,888. The guarantee pool
   182100 rolled 209000 again, already owned, so it became 18 soul stones (`09-...`). So the
   "Again" path does not go through the ticket check of settled point 2; the server's
   diamond fallback (O-W2-4) covered it. The supreme card's label also showed "cost 1 ticket"
   right after the tutorial draw (`04-...`), because the client decrements its own `freetimes`
   copy. The next `5_2121` restored "First Draw Free Today".
2. **Train cells do not show passive xp until the screen reopens.** The server settles a tick
   every 60 s (`train slot 1 ... 1 ticks, 80 xp to hero 210000`), but the open Train screen kept
   the values from the last potion. The ranger showed Lv8 43/90 while the DB had level 11, 133 xp
   (`18-...`). Reopening the screen showed the right numbers. Potions apply one per tap: tap the
   potion once to arm it, then tap a slot body for each potion.
3. **Xp past the cap.** After 11000 every trained hero shows `EXP 944/900` at level 17
   (`34-...`): `level_out` banks fight xp past the cap, as the plan's Risk 5 leaves it. Training
   still treats them as full. The angel has no cap in training. Idol Angel went from level 6 to
   19 through passive ticks plus the 25 left-over potions, past the heroes' 17.
4. **The guide burst after a won fight too.** Three seconds after the 10022 **win** the client
   sent 10160, 10159, 10290, 10330, 10380, 10500, 10540 and 10580. Five were refused with a WARNING
   ("has no new_player_guide_info row"), and `guide_id` went 11208 → **10380**. The guide then
   resumed at 10400 and masked the chapter chest until stage 11000 was played. The run ended at
   `guide_id` 10490.
5. **The skill guide's hero.** Guide 11300 points at the first card of the hero list. Once the
   2-star hero is owned, that card is the 2-star hero, not the knight.

Real-world changes (start → end): player level 1 → 8; gold 1,280,000 → 1,320,648; diamonds
18,888 → 17,488 (−2,000 for the second draw, +600 from the chest). Five heroes: 100000, 104000,
210000 and 209000 at 17, and 202000 at 5. Angel level 19. `diamond_single_draws` 3,
`diamond_free_day` `2026-11-25`. Three `trains` rows hold the mage, the angel and the hunter.
`chapters (10000, 1)`, `levels` up to 11000, 12 x 1100 left, `guide_id` 10490.

Logs and DB copies (not in the repo): `C:/tmp/loa-accw21/server.err.log`, `server.out.log`,
`server-restart.err.log`, `server-restart.out.log`, `logcat-part1.txt`, `db-after-tutorial-draw.db`,
`db-after-guide-10390.db`, `db-after-post-guide-draw.db`, `db-after-second-draw.db`,
`db-after-skills.db`, `db-level8.db`, `db-after-train-guide.db`, `db-trained.db`,
`db-pre-10022.db`, `db-after-10022.db`, `db-before-relaunch.db`, `db-before-restart.db`,
`db-after-restart.db`, `db-end.db`, fight frames `f1-*.png`, `tapper.sh`, `cycle.sh`, `pour.sh`,
`shooter.sh`. Frames: `docs/screens/en-2026-11-25-acc-w2-1/01-...` to `34-...` (JPEG q85).

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
