# LOA private server — design

Date: 20-10-2026. Status: draft for Stefan's review.

## 1. Goal

Make the dead mobile game 女神联盟 / League of Angels: Fire Raiders (Yoozoo, client
build 4.6.99.4, Sep 2022) playable again for one person: Stefan, on his Galaxy S20
Ultra, over home Wi-Fi, against a server running on his home PC. Private use only;
nothing is redistributed.

"Playable" (agreed 20-10-2026) = the core single-player loop:

1. Login, character creation, main city.
2. Campaign stages with real battles, drops and XP.
3. Heroes: recruit, level, star up, gear, angels.
4. Dailies: sign-in, shop, mail, rewards.

Arena, guild, cross-server and events are hidden or stubbed. The UI text is
translated to English (added 20-10-2026, see 3.3); text baked into images stays
Chinese in v1.

## 2. What we have (verified facts)

- Two APKs in Downloads (`LOA Fire Raiders 277sy.apk` is the base; the Milu build is
  identical in scripts, data and native lib, differs only in channel SDK and carries
  Substrate hooks, so it is not used).
- Package `com.nslmrkqm.xaml`, quick-cocos2d-x 2.2.2 + LuaJIT 2.0.2, native lib
  `lib/armeabi/libgame.so` only (32-bit ARM, symbols not stripped). The S20 Ultra runs
  32-bit apps; S24-class phones do not.
- 1,707 plaintext Lua scripts. Login flow, server list, SDK glue and update logic
  are all in Lua.
- `assets/res/utils/net/allProtos.proto` (1,359 proto2 messages) and `msgIDMap.lua`
  (1,098 ids, `id_<service>_<cmd>`). The client sends 327 distinct message ids in total.
- 144 SQLite config tables under `assets/res/data/split/` (heroes, angels, spells,
  buffs, drops, stages, shops, mail templates, sign-in rewards).
- All art and audio in the APK; the dead patch CDN downloaded nothing we need.
- Transport: one TCP connection to `serverIp:8112`, protobuf bodies, framing done
  in native `MMMsgProcessHandler`; the Lua layer sees `(service, cmd, status, body)`.
- Battle: the client runs its own deterministic engine. For a campaign stage the
  server sends `LevelIntoRes{urandom[64], drop[], star}`; the client fights and sends
  `LevelOutReq{level, heroes, angel, star, ops}`; the server answers with XP and
  drops. Only arena-type fights need a server-computed result, and arena is out of
  scope. The server therefore needs no battle engine.

## 3. Architecture

Four deliverables, one repo (`loa-private-server`, this folder):

```
loa-private-server/
  server/            Python 3.14 asyncio TCP server (the game server)
  client/            our own Android app (Gradle) + asset/Lua build script
  localise/          Chinese → English pipeline (Gemma 4 on llm00)
  tools/             protocol capture, proto compile, dev helpers
  docs/              this spec, plans, protocol notes
```

The stock APK, the extracted client tree, `libgame.so` and the assembled assets
stay outside git (size, licence); build scripts refer to them by path.

### 3.1 Server (`server/`)

- **Runtime:** Python 3.14, `asyncio` streams, one process, port 8112, bound to the
  home PC's LAN address. Started with `py -3.14 -m server` or in Docker; Docker is
  not required for a single player on a LAN.
- **Protocol layer:** `allProtos.proto` compiled once with `grpcio-tools` into
  `server/proto/allprotos_pb2.py`; `msgIDMap.lua` parsed into a Python dict
  `(service, cmd) -> message class`. Framing (header layout) is recorded in
  `docs/protocol.md` after the capture step (see 5.1) and implemented in
  `server/net/framing.py`. A handler is a plain function
  `handle(session, req_msg) -> res_msg` registered by `(service, cmd)`.
- **Config access:** `server/config/` opens the client's `.db` files read-only
  (path from `settings.toml`) and exposes typed lookups (`hero(entry)`,
  `stage(level)`, `drop_group(id)`, `checkin(day)`). No copying or converting of the
  tables; the client's data is the single source of truth.
- **Player state:** one SQLite file `data/player.db` with tables mirroring the
  client's `Client*` protobuf shapes (player, heroes, angels, items, bag, stage
  progress, mail, sign-in, shop purchases). A thin repository layer; no ORM.
- **Game logic modules** (one per milestone, see 5.3): `login`, `player`, `level`
  (campaign), `hero`, `angel`, `item`, `mail`, `checkin`, `shop`. Each module owns
  its handlers and its slice of player state.
- **Unknown messages:** answered with the matching `*Res` carrying `status = 0` and
  empty fields where a `*Res` exists, and logged once per id. The client keeps
  working for systems we have not implemented; the log tells us what to do next.
- **Heartbeat / ping:** answered immediately.

### 3.2 Our own client APK (`client/`)

Decision 20-10-2026: Stefan will not grant permissions to the stock APK (channel
SDKs for Alipay, WeChat, umeng-spy, turingad, xinstall, mob.com, plus phone-state
and storage demands). So the stock dex, manifest and SDK native libs are **not
reused at all**. We build our own Android app from source and take only three
things from the stock APK: the native engine `libgame.so`, the assets, and the
Lua scripts (patched).

Why this is safe to build (verified on the binary):
- `libgame.so` links only Android system libs (`libGLESv2`, `liblog`, `libz`,
  `libstdc++`, `libm`, `libc`, `libdl`). None of the SDK `.so` files
  (substrate, sygamehelper, umeng-spy, turingad, xenv, gism, EncryptorP,
  gdbserver) are needed; they are dropped.
- Its JNI surface is small and standard: the cocos2d-x 2.2.2 Java runtime
  (`Cocos2dxRenderer` 12 natives, `Cocos2dxLuaJavaBridge` 4, `Cocos2dxHelper` 2,
  `Cocos2dxBitmap`, `Cocos2dxETCLoader`, `Cocos2dxAccelerometer`,
  `Cocos2dxGLSurfaceView`), which is open source (fetched from the cocos2d-x
  2.2.2 tag, byte-identical signatures), plus one Yoozoo class `comSdk.IComSdk`
  with 13 native callbacks (SDK results). We ship that class with the native
  declarations and never call them.
- Lua reaches Java only through `luaj` static calls on
  `com/uuzu/nslm/JavaSuperSDKManager`, `JavaComSDKManager`, `Nslm` (login, pay,
  float window, device id, forum, audio record). We ship stub classes with those
  static methods returning safe constants, and the patched Lua does not call the
  SDK login at all.

Project layout: `client/android/` is a Gradle app (Android Studio and SDK
platforms 36 already on this PC; Java from the Studio JBR):
- `app/src/main/java/org/cocos2dx/lib/*` — cocos2d-x 2.2.2 runtime sources.
- `app/src/main/java/comSdk/IComSdk.java`, `com/uuzu/nslm/*Stub.java` — stubs.
- `app/src/main/java/.../GameActivity.java` — `Cocos2dxActivity` subclass
  that loads `libgame.so` and starts the GL view; nothing else.
- `app/src/main/jniLibs/armeabi-v7a/libgame.so` — copied from the stock APK by
  the build script, never committed.
- `app/src/main/assets/` — assembled by `client/build_assets.py` from the
  extracted stock tree: `res/`, `scripts/` (patched), fonts.
- Manifest: package `bg.stefan.loa` (new id, no collision with the stock app),
  permissions `INTERNET` only (`VIBRATE` optional), `android:debuggable=false`,
  `usesCleartextTraffic` irrelevant (raw TCP). No storage, no phone state, no
  overlay, no tasks.
- Signing: a dedicated release keystore generated once and kept outside git.

Lua patches applied by `build_assets.py`:
1. `config.lua` / `GameLoginScene.lua`: static server list with one entry
   `{name="Home", serverIp=<home PC LAN IP>, socket_port=8112, server_id=1}`;
   remote server-list fetch removed.
2. `sdk/LuaSuperSDKManager.lua`: SDK login replaced by a fixed local account
   (`username="stefan"`, `token="local"`); pay, share, analytics, float window
   become no-ops; device id and IMEI replaced by a constant.
3. `config.lua`: `CONFIG_DEVELOP = 1` (skips the server version string match and the
   DB MD5 check); `DEBUG_LOG = 0`.
4. `upgrade/*.lua`, `app/MyApp.lua`: resource and script hot-update skipped; the
   game boots straight from the APK's own assets.
5. English build (once 3.3 has run): `Language_cn.lua` replaced by the English
   table under the same keys, patched `language.db` and config `.db` files copied
   over the originals in `res/data/split/`. The server reads the same patched
   tables so names match on both sides.

What remains closed-source inside our APK: `libgame.so` itself (the Yoozoo game
engine: cocos2d-x, LuaJIT, protobuf, curl, OpenSSL, DragonBones, SQLite). It has
no network destination of its own; every host it connects to comes from the Lua
config we control. The stock APK should be uninstalled from the phone; it is not
needed again.

Risk, now moved to the first build: the engine may expect specific Java
behaviour we have not seen (an extra `FindClass` at runtime, an asset path
convention). The symbol table is unstripped, so a crash log names the missing
piece directly. The old 5.2 phone test of the stock APK is dropped.

**Amendment (21-10-2026).** The text above says we ship `comSdk.IComSdk` with
its 13 native declarations. We do not, and there was never such a class to
copy: `comSdk.IComSdk` exists in neither stock dex (jadx 1.5.6), so the stock
build runs without it too. JNI binds a `Java_comSdk_IComSdk_*` export only when
a Java `native` method of that name is declared, and the short-form symbol
names carry no parameter types to recover, so the declarations cannot be
reconstructed. Ruling from Task 5: the class is not shipped, and the
`comSdk/ComSdkImpl` `FindClass` failure in logcat is the dead ComSDK channel
rather than a missing file. Detail: `client/comsdk_natives_note.md`. The
`app/src/main/java/comSdk/IComSdk.java` entry in the layout above is therefore
void; the `com/uuzu/nslm/*` stubs are shipped as described.

### 3.3 English localisation (`localise/`)

The Western localisation is not in these APKs (the 2016 global APK is behind
download walls; not pursued). The English text is produced by **Gemma 4
(`gemma4:e4b`) on llm00**, Stefan's choice on 20-10-2026.

- **Source text:** every Chinese string the player can see lives in three places:
  `res/language/Language_cn.lua` (3,425 UI keys), `data/split/language.db` (539
  server status texts) and text columns of the config tables (names and
  descriptions of heroes, angels, items, skills, buffs, stages, chapters, shop,
  mail). Measured: 53,428 unique strings, 816k characters; after masking digits
  with `#` they collapse to 10,788 templates, 142k characters, median 11 chars.
- **Pipeline (`localise/translate.py`):** extract → template (digits → `#`) →
  translate templates in batches of 40 through Ollama `/api/generate`,
  temperature 0.1, line-numbered plain text output (not JSON; escapes broke
  parsing in the probe) → validate (line count, every `#`, `%s`, `%d`, `{n}` and
  `<color>` tag preserved, else retry the batch) → cache `template → en` in
  `localise/cache.sqlite` so the job is resumable → re-expand digits → write
  `Language_en.lua`, patched `language.db` and patched config `.db` copies.
- **Glossary first:** hero, angel, item, skill and stage *names* are translated
  in a first pass and fed as a glossary to every later batch, so a hero has one
  name everywhere. Measured probe: Gemma renders 玫瑰骑士 "Rose Knight", 烈焰女神
  "Blazing Goddess", UI strings correctly; one skill line dropped "to all
  enemies", so skill and buff descriptions get a spot-check sample of 100 before
  the pass is accepted.
- **Throughput:** ~10 tokens/s on llm00, so the full pass is roughly 14 to 20
  hours, run detached on llm00 or this PC per the event-watcher pattern, with the
  cache making restarts free. Milestone 1 ships with Chinese text; the English
  tables are swapped into the APK build (3.2 step 6) when the pass is done.
- **Out of v1:** text inside PNGs (button labels, hero-name images under
  `img/hero/name`, titles in UI atlases). Could be re-rendered later from the
  glossary; not needed to play.

### 3.4 Tools (`tools/`)

- `capture_server.py`: a dummy TCP listener that logs raw bytes of whatever the
  client sends; used once to learn the framing, kept for debugging.
- `compile_proto.py`: regenerates `allprotos_pb2.py` from the client tree.
- `msgmap.py`: parses `msgIDMap.lua` and prints unknown-id statistics from the
  server log.

## 4. Data flow

**Login:** phone connects → `ProtocolReq(3_2005)` → `ProtocolRes{issue_required =
"<version>:<md5>"}` (ignored by the client because `CONFIG_DEVELOP=1`) →
`QuerySrvStateReq(3_2015)` → `LoginReq(3_2001){username, token, args=[server_id]}`
→ `LoginRes{status=0, token, session, timestamp}` → `GameplayReq(3_2003)` →
`GameplayRes` → `QueryMyselfReq(5_2005)` → `QueryMyselfRes{player…}`. Then the
main-city burst: `GameReadyReq(5_2317)`, `QueryMyPushMessageReq(5_2801)`,
`QueryBtCardRecordReq(5_2943)`, `MagicStateReq(153_2001)`,
`TounamentQuerySeasonStateReq(151_2041)`, hero/angel/bag/mail queries, heartbeat
every few seconds.

**Amendment (21-10-2026).** The `LoginRes` → `GameplayReq(3_2003)` step above
does not happen. The emulator run showed the server answering
`LoginRes{status=327682}` ("no character yet") and the client's own dump
printing `"status" = 327682`, while `LoginSocketData:loginReceiveHdr` still took
its `rs.status == 0` branch and sent `QueryMyselfReq(5_2005)` instead of
`GameplayReq(3_2003)`: the body's status never reaches that gate, so the
character-creation handshake the design assumed can never be triggered. The
server therefore creates the character on `LoginReq(3_2001)` itself
(commit 67652bb), and `3_2003` stays supported as a handler that still creates
exactly one character, for a client build that does send it.

**Campaign stage:** `LevelIntoReq{level}` → server checks the stage is unlocked,
rolls `urandom[64]` (uint32 0..9999, same scale the client's guide battle uses),
pre-rolls drops from `drop_group`/`drop_base`, stores them against the session →
client fights → `LevelOutReq{level, heroes, angel, star, ops}` → server trusts
`star` (single player, no anti-cheat), grants XP from `stage_info`, hands out the
stored drops, unlocks the next stage, persists → `LevelOutRes`.

**Hero actions:** `SummonHero`, `UpgradeHeroLevel`, `UpgradeHeroStar`, equip and
gear upgrade: each validates cost against config tables, mutates player state,
returns the updated `ClientHero`/`ClientItem` shapes the client expects.

## 5. Order of work and de-risking

5.1 **Framing capture (first task).** Point the stock client at `capture_server.py`
on the LAN, read the first packet (`ProtocolReq` with the known version string
inside), derive the header layout. Expected: a length prefix plus service, cmd and
status fields; confirmed from the bytes, not guessed. Written to
`docs/protocol.md`.

5.2 **First own-shell build (second task).** Gradle app from 3.2 with the stock
assets and unpatched Lua except the server list, pointed at the capture server.
Done when the S20 Ultra shows the game's login scene and the capture server logs
the first packet. Observation from 20-10-2026: the stock APK installs and starts
on the S20 Ultra up to its permission gate, so the 32-bit library runs on the
phone; Stefan declined to grant it permissions, which is why we build our own
shell.

5.3 Milestones, each ending in a phone test by Stefan:

| # | Deliverable | Server modules | Done when |
|---|---|---|---|
| 1 | Boot to main city | login, player, stubs | Stefan sees the main city with his character on the S20 Ultra |
| 2 | Campaign | level, item (drops), xp | Stage 1-1 through chapter 1 fought, stars and drops persist across restarts |
| 3 | Heroes | hero, angel, item (gear) | Recruit, level, star up, equip; values match config tables |
| 4 | Dailies | checkin, mail, shop | Sign-in reward claimed, shop purchase, mail with attachment |

Milestone 1 reached on the emulator on 21-10-2026 (task-15 evidence); the phone
pass on the S20 Ultra, which is the milestone's own "done when", is pending.

5.4 Dev loop: the Android Studio emulator on this PC (x86_64 image with ARM
translation) is tried first for my own iteration; if the 32-bit lib does not run
under translation, the phone over `adb` on Wi-Fi is the loop and Stefan's tests are
the gate.

## 6. Error handling

- Malformed frame or unknown message: log, answer with status 0 stub if a `*Res`
  exists, never drop the connection.
- Handler exception: logged with the request dump, `status = 1` returned, connection
  kept.
- Validation failure (not enough gold, stage locked): the client's own status codes
  from `allProtos.proto` comments and Lua handlers; mapped per module.
- Player state writes are per-request transactions; a crash mid-request loses at
  most that request.

## 7. Testing

- `pytest` for every module: framing round-trip against captured bytes; proto
  encode/decode for every message id used in scope; config lookups against known
  rows (e.g. hero 100000 玫瑰骑士); each handler with an in-memory player DB.
- A scripted fake client (`tools/fake_client.py`) that replays the login burst and
  a stage fight end to end against a running server, used in CI-style runs before
  any phone test.
- Phone tests by Stefan are the acceptance gate per milestone; no "done" claim
  before his pass.

## 8. Out of scope

Arena, guild, cross-server, events, chat, friends, payments, anti-cheat,
multi-account, public exposure of the server, English text inside images, arm64
build.

## 9. Open points

- Home PC = this machine (assumed; Docker 29 and Python 3.14 present). LAN address
  for the APK is read at build time.
- First own-shell build (5.2) may reveal an engine expectation we have not seen; fixed from the crash log.
- Exact status-code conventions per module, filled in as each module is built.
