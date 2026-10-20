# Brief for Plan A — "boot to main city"

Read first: `docs/superpowers/specs/2026-10-20-loa-private-server-design.md` (approved 20-10-2026).
This plan covers spec sections 3.1 (server core + login/player modules only), 3.2 (own APK), 3.4 (tools),
5.1, 5.2 and milestone 1 of 5.3. Plans B (campaign/heroes/dailies) and C (localisation) come later and
must not be folded in.

## Inputs on disk (read-only, outside git)

- Stock APK: `C:\Users\Stefan.Nasev\Downloads\LOA Fire Raiders 277sy.apk`
- Extracted stock tree (already unzipped):
  `C:\Users\STEFAN~1.NAS\AppData\Local\Temp\claude\c--Users-Stefan-Nasev-Downloads-Claude-Cowork-Claude-Code-Projects-schedule-planner\a94ddd9b-db1f-4be9-8e82-97e049de8ebc\scratchpad\loa277\`
  (this scratchpad is session-bound; the plan's first task must re-extract the APK with Python `zipfile`
  into `<repo>/.stock/` which is gitignored, and every later task reads from there).
  - `lib/armeabi/libgame.so` (15 MB, 32-bit ARM, unstripped)
  - `assets/res/` (art, audio, `data/split/*.db` 144 SQLite tables, `utils/net/allProtos.proto`,
    `utils/net/msgIDMap.lua`, `language/*.lua`), `assets/scripts/` (1,707 Lua), `assets/fonts/`
- cocos2d-x 2.2.2 Java runtime: `https://raw.githubusercontent.com/cocos2d/cocos2d-x/cocos2d-x-2.2.2/cocos2dx/platform/android/java/src/org/cocos2dx/lib/<File>.java`
  (fetched OK with curl on 20-10-2026). Files needed: Cocos2dxActivity, Cocos2dxRenderer, Cocos2dxGLSurfaceView,
  Cocos2dxHelper, Cocos2dxBitmap, Cocos2dxETCLoader, Cocos2dxAccelerometer, Cocos2dxLuaJavaBridge,
  Cocos2dxMusic, Cocos2dxSound, Cocos2dxTypefaces, Cocos2dxEditText, Cocos2dxEditBoxDialog, Cocos2dxEditBox,
  Cocos2dxEditBoxHelper, Cocos2dxHandler, Cocos2dxTextInputWraper, Cocos2dxLocalStorage, Cocos2dxWebView
  (not all may exist at that tag; the task fetches the directory listing via the GitHub API
  `https://api.github.com/repos/cocos2d/cocos2d-x/contents/cocos2dx/platform/android/java/src/org/cocos2dx/lib?ref=cocos2d-x-2.2.2`
  and takes every .java file there).
- Tooling on this PC: Android SDK at `C:\Users\Stefan.Nasev\AppData\Local\Android\Sdk` (platforms android-36,
  build-tools 36.0.0/36.1.0 with apksigner + zipalign, platform-tools adb, emulator with one AVD
  `Medium_Phone_API_36.1` x86_64 google_apis_playstore), Android Studio at `C:\Program Files\Android\Android Studio`
  (JBR Java at `jbr\bin\java.exe`), Gradle via Android Studio's wrapper, Java 21 on PATH, Python 3.14 (`py -3.14`),
  Docker 29. Git Bash is the shell for Bash steps; PowerShell also available.
- Phone: Galaxy S20 Ultra (Android 13, 32-bit capable). Stefan installs APKs by hand; adb over USB may be
  available, do not assume it.

## Facts the plan must use verbatim (verified 20-10-2026)

- JNI natives exported by libgame.so (Java → native), exactly these:
  `org.cocos2dx.lib.Cocos2dxRenderer`: nativeInit, nativeRender, nativeOnPause, nativeOnResume, nativeTouchesBegin,
  nativeTouchesEnd, nativeTouchesMove, nativeTouchesCancel, nativeKeyDown, nativeInsertText, nativeDeleteBackward,
  nativeGetContentText.
  `org.cocos2dx.lib.Cocos2dxLuaJavaBridge`: callLuaFunctionWithString, callLuaGlobalFunctionWithString,
  retainLuaFunction, releaseLuaFunction.
  `org.cocos2dx.lib.Cocos2dxHelper`: nativeSetApkPath, nativeSetEditTextDialogResult.
  `org.cocos2dx.lib.Cocos2dxBitmap`: nativeInitBitmapDC. `org.cocos2dx.lib.Cocos2dxETCLoader`: nativeSetTextureInfo.
  `org.cocos2dx.lib.Cocos2dxAccelerometer`: onSensorChanged.
  `comSdk.IComSdk` (package `comSdk`, class `IComSdk`): onExitGameResult, onNativeBindResult,
  onNativeCheckVersionResult, onNativeFastLoginResult, onNativeGetConfigParam, onNativeGetGameData,
  onNativeInitResult, onNativeLoginPlatform, onNativeLoginResult, onNativeLogoutResult, onNativePayResult,
  onNativeStaticStringMethod, onNativeStaticVoidMethod. Exact Java signatures of these 13 are unknown; the
  plan must include a task that recovers them from the stock dex with jadx
  (`C:\Users\Stefan.Nasev\AppData\Local\Microsoft\WinGet\Packages\Skylot.jadx_Microsoft.Winget.Source_8wekyb3d8bbwe\lib\jadx-gui-1.5.6-all.jar`,
  run headless: `java -jar <jar> --no-res -d <out> <classes.dex>` on `classes.dex` and `classes2.dex` from `.stock/`,
  then grep for `class IComSdk`) and copies the declarations verbatim. Same for the Java side of
  `Cocos2dxLuaJavaBridge` if it differs from the cocos2d-x 2.2.2 tag.
- Native classes the engine looks up by name (FindClass): org/cocos2dx/lib/Cocos2dxBitmap, Cocos2dxETCLoader,
  Cocos2dxGLSurfaceView, Cocos2dxHelper, Cocos2dxRenderer. Package names must match exactly.
- libgame.so DT_NEEDED: libGLESv2, liblog, libz, libstdc++, libm, libc, libdl only. Ship `libgame.so` under
  `jniLibs/armeabi-v7a/` and nothing else. `android:extractNativeLibs="true"`; abiFilters armeabi-v7a only.
- Lua → Java via `luaj.callStaticMethod(class, method, args, sig)`. Classes referenced:
  `com/uuzu/nslm/JavaSuperSDKManager` (methods: initSDK, login, logout, pay, exitSDK, exitSDKOk, checkVersion,
  showAlert, setGameData, openGMStore, openForum, openFloatWindow, closeFloatWindow, hasFloatWindow, onGameEvent,
  onAdEvent, getPlatformConfigByName, getDeviceId, enterPlatformCenter, enterCustomerService, sendInvite,
  lua_setOnLogoutCallBack, lua_setOnLoginPlatformCallBack, lua_setOnInitCallBack, lua_setOnCheckVersionCallBack,
  lua_setGameServers, lua_setCallBack, lua_setOnPayCallBack, getGameServers, openEmbedUrl, closeEmbedUrl, like,
  feed, getFaceBookFriends, getRootPath, callSdkSpecialInterface), `com/uuzu/nslm/JavaComSDKManager` (same set),
  `com/uuzu/nslm/Nslm` (getConnectionStatus), plus an audio class (stopRecording, stopPlaying) referenced as
  `javaAudioClass` in `app/game/manager/MediaManager.lua`. Exact signatures: recover from
  `scripts/sdk/LuaSuperSDKManager.lua`, `LuaComSDKManager.lua`, `framework/luaj.lua` call sites (the `sig`
  string of each call, e.g. "(Ljava/lang/String;)V") and generate stub classes whose static methods match those
  signatures and return "" / 0 / false / do nothing. `getDeviceId` returns the constant "LOA-HOME-0001";
  `getConnectionStatus` returns 1.
- Lua entry: `assets/scripts/main.lua` (quick-cocos2d-x bootstrap) → `app/MyApp.lua`; `config.lua` holds
  `DEBUG`, `DEBUG_LOG`, `GAME_URL`, `CONFIG_DEVELOP` (grep to confirm name; set to 1).
- Login flow (client sends, in order): 3_2005 ProtocolReq{issue=GAME_VERSION} → expects 3_2006 ProtocolRes
  {issue_required="<version>:<md5>"} (client compares only when CONFIG_DEVELOP~=1); 3_2015 QuerySrvStateReq;
  3_2001 LoginReq{username, token, datetime, device, IMEI, args=[server_id]} → 3_2002 LoginRes{status=0, token,
  session, time_zone_offset, timestamp}; 3_2003 GameplayReq → 3_2004 GameplayRes (same shape); 5_2005
  QueryMyselfReq → QueryMyselfRes (shape in allProtos.proto; the plan must quote the message definition and
  the `ClientPlayer`/`ClientRole` sub-messages it needs verbatim from the proto file); then the main-city burst:
  5_2317 GameReadyReq, 5_2801 QueryMyPushMessageReq, 5_2943 QueryBtCardRecordReq, 153_2001 MagicStateReq,
  151_2041 TounamentQuerySeasonStateReq, 3_2009 HeartbeatReq (periodic), and hero/angel/bag/mail queries whose
  ids the plan must look up in `msgIDMap.lua` by name (QueryHeroesReq, QueryAngelsReq, QueryBagReq/QueryItemsReq,
  QueryMailsReq or nearest; verify by grep, do not guess).
- Message id convention: `id_<service>_<cmd>` → message name; every Req's Res is the same name with `Res`,
  and its cmd is `Req cmd + 1` (verify on 3_2001/3_2002, 5_2005/5_2006 in msgIDMap.lua; if the rule does not
  hold for some pair, the map is the truth).
- Wire framing is unknown. The native handler `MMMsgProcessHandler` receives (msgBuf, msgLen, msgId=cmd,
  service, status). The plan must contain a capture task: `tools/capture_server.py` logs hex dumps of
  everything received on :8112; a human (Stefan on the phone, or the emulator if ARM translation works)
  runs the shell APK against it; the task ends with `docs/protocol.md` stating the header layout derived from
  the first packet (which contains the ASCII of GAME_VERSION from `scripts/version.txt` = "211111" or the
  value in `config.lua`, so it is recognisable). Then `server/net/framing.py` implements `encode(service, cmd,
  status, body: bytes) -> bytes` and `decode(buf) -> (service, cmd, status, body, rest)` with tests built from
  the captured bytes. Because the layout is not known at plan time, write the framing task so that the
  constants (header size, field order, endianness) are read from `docs/protocol.md` by the implementer and
  the tests use the real captured first packet pasted into the test file.
- Proto: `allProtos.proto` has no `syntax` line (proto2) and no `package`. Compile with
  `py -3.14 -m grpc_tools.protoc -I<dir> --python_out=server/proto <dir>/allProtos.proto` (grpcio-tools 1.84.0
  on pip). If protoc rejects anything (e.g. duplicate names), the task fixes the copy under `server/proto/` and
  documents the edit.
- Player data: `data/player.db` SQLite; schema for milestone 1 = players(id, username, name, level, exp, gold,
  diamond, vip, created_at), heroes, angels, items, bag empty for now. QueryMyselfRes must return the fields
  the client reads in `scripts/app/game/model/roleData/*.lua` and `LoginSocketData.queryMySelfReceiveHdr` —
  the plan quotes those reads.
- Server config: `settings.toml` with `[paths] stock_dir`, `[net] host, port=8112`, `[account] username="stefan"`.

## Decisions (do not reopen)

- Python 3.14 + asyncio streams; pytest; no ORM; no Docker needed for milestone 1.
- Android app: Gradle project under `client/android/`, package `bg.stefan.loa`, minSdk 21, targetSdk 33,
  compileSdk 36, permissions INTERNET (+VIBRATE), one Activity `GameActivity extends Cocos2dxActivity`,
  `System.loadLibrary("game")`, landscape, fullscreen. Signed with a release keystore created by a script in
  `client/` and stored at `C:\Users\Stefan.Nasev\.loa-keystore\loa.jks` (outside git); password in
  `C:\Users\Stefan.Nasev\.loa-keystore\password.txt` (600).
- Assets assembled by `client/build_assets.py` (Python): copies `res/`, `fonts/`, `scripts/` from `.stock/`
  into `client/android/app/src/main/assets/`, applies the Lua patches from spec 3.2 steps 1-4 with exact
  string replacements that assert the original text was found (fail loudly otherwise), writes the server
  IP from `settings.toml`. Patches are idempotent (run on a fresh copy every time).
- The emulator check (x86_64 image running the 32-bit ARM lib) is one bounded task: if the app starts on the
  AVD, the dev loop uses it; if it crashes with a translation/ABI error, record that in `docs/dev-loop.md`
  and the phone is the loop. Either outcome is a pass for that task.
- Unknown message policy: reply with the paired `*Res` (status=0, empty) when it exists, log once per id.
- No git push anywhere. Local commits per task, conventional commit messages.
- Tests run with `py -3.14 -m pytest -q` in the repo root; Android build with
  `client\android\gradlew.bat assembleRelease` (the plan's first Android task creates the wrapper by copying it
  from any Android Studio-generated project or from `C:\Program Files\Android\Android Studio\plugins\gradle\lib`
  — verify a path exists; otherwise install Gradle 8.x via winget `Gradle.Gradle`).

## Milestone 1 definition of done

Stefan installs `LOA-private-release.apk` on the S20 Ultra, opens it, sees the game's login scene with the
"Home" server, taps enter, creates a character, and sees the main city. Server log shows the login burst with
no unhandled exception. Repo has green pytest, the APK build script, the capture tool, `docs/protocol.md`,
`docs/dev-loop.md`.
