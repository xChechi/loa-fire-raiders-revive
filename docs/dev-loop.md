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

### Where it stops — the next thing to fix

`lua_setCallBack ... SUCCESS` at **10:16:15.621** is the last line the app ever logs.
For the remaining 86 seconds it is alive, foregrounded and completely silent. The
screenshot at +60 s is a plain black 2280x1080 landscape frame — correct orientation,
no login scene, no error dialog.

It never reaches the login scene, and it never tries to reach `192.168.1.50:8112` — no
socket or connect attempt appears in the log. So **the placeholder server address was
not what stopped it.** The Lua SDK-init chain registers its callback through the
generated `JavaSuperSDKManager` stub and then waits. The stub returns `SUCCESS` for the
registration but nothing ever fires the callback back into Lua, so
`开始 android sdk init .....` never completes and the boot sequence stalls there.

That is a client-stub problem, ahead of anything server-side, and it is the first thing
to deal with before a capture can get useful traffic.

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

SDK command-line tools were missing and were installed for Task 9b:
`cmdline-tools/latest` rev 23.0 (`commandlinetools-win-16111833_latest.zip`). Its
`sdkmanager.bat` is now a deprecation shim over the new Android CLI, and that CLI
**rejects the `system-images;android-30;google_apis;x86_64` semicolon form** — package
paths must use slashes, `system-images/android-30/google_apis/x86_64`.

## 4. The loop

Iterate on `LOA_API30`, on this PC. Nothing needs Stefan or the phone for a routine check.

1. Rebuild and reinstall with the commands in section 5. `adb install -r` takes about
   25 seconds for the 340 MB APK.
2. Run the server on this host. The AVD reaches it either way:
   - `adb reverse tcp:8112 tcp:8112` and point the client at `127.0.0.1:8112`, or
   - point the client at this host's LAN address directly.
   Either needs `settings.toml` changed and `py -3.14 -m client.build_assets` re-run,
   because the address is baked into the assets.
3. Device logcat is available: `adb logcat -c`, launch, `adb logcat -d`. Filter on the
   pid plus `cocos2d`, `LOAStub`, `luajc`.
4. **The phone stays the acceptance gate.** The AVD is an x86 host running ARM
   translation on Android 11; it proves the build boots and lets changes be iterated
   cheaply, it does not prove the build works on Stefan's device. Nothing ships on a
   green AVD alone.

Standing caveat kept from the API 36 round: `adb` over USB to the **phone** has never
been set up or tested. Do not assume a device logcat when the loop moves to the phone;
the server's own logging is the diagnostic channel there.

## 5. Rebuild, reinstall, relaunch — the exact commands

```bash
cd "/c/Users/Stefan.Nasev/Downloads/Claude Cowork/Claude Code/Projects/loa-private-server"
py -3.14 -m client.build_assets                       # only after settings.toml changes (~1 min)
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleRelease
cp app/build/outputs/apk/release/app-release.apk /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk

SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/platform-tools/adb.exe" install -r /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
"$SDK/platform-tools/adb.exe" shell am start -n bg.stefan.loa/.GameActivity
```

Boot the AVD, if it is not already up:

```bash
"$SDK/emulator/emulator.exe" -avd LOA_API30 -no-snapshot-load
```

On Windows, start it detached (`powershell.exe Start-Process`) or it dies with the
shell that launched it.
