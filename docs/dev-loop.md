# Dev loop — where a build gets tested

Bounded emulator check, Task 9 of plan *Plan A: boot to main city*.
One install attempt, one launch attempt, 90 seconds of logcat. Not debugged further.

## 1. What was tested

| | |
|---|---|
| Date | 21-10-2026 |
| AVD | `Medium_Phone_API_36.1` |
| System image | `system-images/android-36.1/google_apis_playstore/x86_64` |
| Emulator | 36.4.10.0 (build_id 15004761), `-no-snapshot-load` |
| Guest | `sdk_gphone64_x86_64`, Android 16, SDK 36 |
| `ro.dalvik.vm.isa.arm` | `x86` |
| `ro.product.cpu.abilist` | `x86_64,arm64-v8a` |
| `ro.product.cpu.abilist32` | *(empty)* |
| `ro.zygote` | `zygote64` |
| APK | `C:\Users\Stefan.Nasev\Downloads\LOA-private-release.apk`, 340,862,699 bytes, signed, `bg.stefan.loa` / `.GameActivity`, `abiFilters = armeabi-v7a` only |

## 2. Outcome

**Outcome B — the APK does not run on this AVD, so the dev loop is the phone.**

The install never got as far as the launch: `android-36.1` is a 64-bit-only image
(`abilist32` empty, `ro.zygote=zygote64`, no `/system/lib/arm`), so its ARM translation
covers `arm64-v8a` only. `ro.dalvik.vm.isa.arm=x86` is present, but the 32-bit ARM
runtime it refers to is not shipped in this image, and `armeabi-v7a` is absent from
`ro.product.cpu.abilist`. The APK is `armeabi-v7a`-only, so there is no matching ABI.

Nothing about `libgame.so`, the engine or the game was learned: the process never
started. `cocos2d`, `LuaJIT`, `UnsatisfiedLinkError`, `FATAL EXCEPTION`,
`AndroidRuntime` and `LOAStub` appear **0 times** in the 90-second capture.

## 3. Evidence

`adb` console, the one install attempt and the one launch attempt:

```
$ adb install -r /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
Performing Streamed Install
adb.exe: failed to install C:/Users/Stefan.Nasev/Downloads/LOA-private-release.apk:
  Failure [INSTALL_FAILED_NO_MATCHING_ABIS: INSTALL_FAILED_NO_MATCHING_ABIS:
  Failed to extract native libraries, res=-113]

$ adb shell pm path bg.stefan.loa          # (rc=1, no output)

$ adb shell am start -n bg.stefan.loa/.GameActivity
Starting: Intent { cmp=bg.stefan.loa/.GameActivity }
Error type 3
Error: Activity class {bg.stefan.loa/bg.stefan.loa.GameActivity} does not exist.

$ adb shell pidof bg.stefan.loa            # (rc=1, no output)
```

Logcat, 10:02:29 to 10:04:01, 13,614 lines. Exactly one line mentions the package —
the rest is Play Store background traffic:

```
10-21 10:02:30.203 812 1304 I ActivityTaskManager: START u0 {flg=0x10000000 xflg=0x4
    cmp=bg.stefan.loa/.GameActivity} with LAUNCH_MULTIPLE from uid 2000
    (com.android.shell) result code=-92
```

`result code=-92` is `START_CLASS_NOT_FOUND`. The `dlopen failed` lines in the capture
are the guest's own Widevine `liboemcrypto.so` and have nothing to do with this APK.
The screenshot taken at the 60-second mark shows the stock Pixel launcher home screen
(wallpaper, Play Store / Gmail / Photos / YouTube row, Google search bar) — no game,
no crash dialog.

The install failure itself predates the `logcat -c` that opened the capture, so it is
recorded above from the `adb` console rather than from the log file.

## 4. Toolchain that actually built the APK

Reuse this pair; it is the first pair tried and the fallback was never needed.

| | |
|---|---|
| Gradle | 9.3.1 (`client/android/gradle/wrapper/gradle-wrapper.properties`) |
| Android Gradle Plugin | 9.0.0 (`client/android/build.gradle.kts`) |
| JDK | `C:\Program Files\Android\Android Studio\jbr` |
| compileSdk / targetSdk / minSdk | 36 / 33 / 21 |

## 5. The loop that follows

The emulator is out. Every build is verified on Stefan's phone:

1. Build and sign here (command in section 6), then hand Stefan
   `C:\Users\Stefan.Nasev\Downloads\LOA-private-release.apk`.
2. **Stefan installs it by hand** on the phone — sideload, "install from unknown
   sources". There is no `adb install -r` in this loop.
3. The phone joins the same Wi-Fi as the server host, and the Task 10 capture runs
   **on the LAN host**: the server binds the `settings.toml` host, port 8112, and the
   client reaches it at that LAN address. `adb reverse` is not available.
4. **Do not assume `adb` over USB exists.** USB debugging on the phone has not been
   set up or tested. Anything that needs a device log must either be arranged with
   Stefan first or be designed to come out of the server side instead.
5. Consequence for the server: logging and the capture must be good enough to diagnose
   the client blind, because the client's own logcat is not routinely reachable.

The client currently points at the placeholder `192.168.1.50:8112`
(`settings.toml`, baked into the assets by `client/build_assets.py`). The real home
LAN address has to replace it, and the assets rebuilt, before a phone test means
anything.

One thing is still worth re-checking cheaply if the phone loop ever becomes the
bottleneck: an `android-30`-or-older `x86` AVD does ship 32-bit ARM translation, and
would take an `armeabi-v7a` APK. That is a new AVD download, which this bounded task
did not do.

## 6. Rebuild and hand over — the exact commands

```bash
cd "/c/Users/Stefan.Nasev/Downloads/Claude Cowork/Claude Code/Projects/loa-private-server"
py -3.14 -m client.build_assets                       # only after settings.toml changes (~1 min)
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleRelease
cp app/build/outputs/apk/release/app-release.apk /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
```

Then give Stefan `LOA-private-release.apk` to install on the phone.
