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

Arena, guild, cross-server and events are hidden or stubbed. Chinese UI stays as is.

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

Three deliverables, one repo (`loa-private-server`, this folder):

```
loa-private-server/
  server/            Python 3.14 asyncio TCP server (the game server)
  client-patch/      scripts that turn the stock APK into the private-server APK
  tools/             protocol capture, proto compile, dev helpers
  docs/              this spec, plans, protocol notes
```

The stock APK and the extracted client tree stay outside git (size, licence);
`client-patch/` refers to them by path.

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

### 3.2 Client patch (`client-patch/`)

Lua-only edits on the extracted 277sy tree, then re-zip and sign. Native lib,
dex and assets untouched. A script `build_apk.py` applies the patches and produces
`LOA-private.apk`:

1. `config.lua` / `GameLoginScene.lua`: static server list with one entry
   `{name="Home", serverIp=<home PC LAN IP>, socket_port=8112, server_id=1}`;
   remote server-list fetch removed.
2. `sdk/LuaSuperSDKManager.lua`: channel SDK login replaced by a fixed local
   account (`username="stefan"`, `token="local"`); SDK calls for pay, share,
   analytics made no-ops.
3. `config.lua`: `CONFIG_DEVELOP = 1` (skips the server version string match and the
   DB MD5 check); `DEBUG_LOG = 0`.
4. `upgrade/*.lua`, `app/MyApp.lua`: resource and script hot-update skipped; the
   game boots straight from the APK's own assets.
5. Sign: debug keystore via `apksigner` from the Android SDK build-tools already
   installed on this PC (`AppData/Local/Android/Sdk/build-tools/36.x`). Zipalign
   before signing.

Open risk, checked first (5.2): the Java-side channel SDK
(`com.supersdk.openapi.SuperSdkApplication`) may demand its own login or network
before Lua starts. If so, one extra step: `apktool` decode, patch the smali entry
to skip SDK init, rebuild. Jadx is installed for reading; `apktool` would be added.

### 3.3 Tools (`tools/`)

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

5.2 **Boot test on the phone (Stefan, 5 min, can run in parallel).** Install the
stock 277sy APK on the S20 Ultra and report what appears after the splash. Decides
whether the client patch is Lua-only or needs the smali step.

5.3 Milestones, each ending in a phone test by Stefan:

| # | Deliverable | Server modules | Done when |
|---|---|---|---|
| 1 | Boot to main city | login, player, stubs | Stefan sees the main city with his character on the S20 Ultra |
| 2 | Campaign | level, item (drops), xp | Stage 1-1 through chapter 1 fought, stars and drops persist across restarts |
| 3 | Heroes | hero, angel, item (gear) | Recruit, level, star up, equip; values match config tables |
| 4 | Dailies | checkin, mail, shop | Sign-in reward claimed, shop purchase, mail with attachment |

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
multi-account, public exposure of the server, English localisation, arm64 build.

## 9. Open points

- Home PC = this machine (assumed; Docker 29 and Python 3.14 present). LAN address
  for the APK is read at build time.
- Result of 5.2 (Java SDK gate).
- Exact status-code conventions per module, filled in as each module is built.
