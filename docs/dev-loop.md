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
