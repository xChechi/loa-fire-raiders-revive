# Plan A — "Boot to Main City" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first playable slice of the LOA private server — a Python 3.14 asyncio TCP server on port 8112 that answers the client login burst, plus our own Android APK (`bg.stefan.loa`) assembled from the stock `libgame.so`, the stock assets and eight exact Lua patches — so that Stefan installs `LOA-private-release.apk` on his Galaxy S20 Ultra, opens it, sees the game login scene with a single "Home" server, taps enter, gets a character created, and lands in the main city with no unhandled server exception.

**Architecture:** Two halves that meet over one TCP port. The client half is a from-scratch Gradle app: cocos2d-x 2.2.2 Java runtime + `comSdk.IComSdk` + `com.uuzu.nslm.*` stubs + `GameActivity`, with `assets/` and `jniLibs/armeabi-v7a/libgame.so` assembled by `client/build_assets.py` from a gitignored `.stock/` extraction of the APK. The server half loads the compiled descriptor set the client itself uses, `allProtos.pb`, at startup (no protoc), maps `(service, cmd)` to message classes from `msgIDMap.lua`, frames packets per `docs/protocol.md` (layout derived from a real capture, never guessed), and dispatches to `login` and `player` handler modules over a SQLite `data/player.db`. Everything not implemented is answered with the paired `*Res` carrying zero-filled required fields.

**Tech Stack:** Python 3.14.3 (`py -3.14`), `protobuf` 7.36.2 (already installed), `pytest` 9.0.3, stdlib `asyncio`/`sqlite3`/`zipfile`/`tomllib`; Gradle 9.3.1 + Android Gradle Plugin, Java 21 (Android Studio JBR), Android SDK platform 36, jadx 1.5.6 headless; Git Bash for shell steps.

**Spec:** `docs/superpowers/specs/2026-10-20-loa-private-server-design.md` (sections 3.1 server core + login/player, 3.2, 3.4, 5.1, 5.2, milestone 1 of 5.3). Brief: `docs/superpowers/plans/BRIEF-plan-a-boot-to-main-city.md`. Read both before task 1.

## Global Constraints

- Python is `py -3.14` on every command line. Tests: `py -3.14 -m pytest -q` from the repo root. Never `python` or `python3`.
- Pytest temp dirs: always pass an explicit basetemp, `py -3.14 -m pytest -q --basetemp=C:\tmp\pytest-loa`. The sandbox ACLs the default temp root.
- Sockets in tests bind and connect to `127.0.0.1` explicitly, never the name `localhost` (resolves `::1` first, about 2 s per connect on this machine).
- **No `git push`, ever.** One local commit per task, conventional message (`feat(server): ...`, `chore(client): ...`).
- Server port 8112; bind host from `settings.toml`. Account username `stefan`.
- The stock APK and the extracted tree are read-only inputs. Nothing under `.stock/` is modified or committed.
- Android: package `bg.stefan.loa`, minSdk 21, targetSdk 33, compileSdk 36, `abiFilters` = `armeabi-v7a` only, `android:extractNativeLibs="true"`, permissions `INTERNET` + `VIBRATE` only, landscape, fullscreen, one activity.
- Java toolchain for Gradle: `JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"`.
- Gradle: no `gradle` on PATH and no winget package. A full Gradle 9.3.1 distribution is cached at `C:\Users\Stefan.Nasev\.gradle\wrapper\dists\gradle-9.3.1-bin\23ovyewtku6u96viwx3xl3oks\gradle-9.3.1\bin\gradle.bat`. Task 6 runs that `gradle.bat wrapper --gradle-version 9.3.1` once inside `client/android`, then every later build uses `client\android\gradlew.bat`.
- Proto: **do not use protoc or grpcio-tools.** `allProtos.proto` fails strict protoc in 8 places (duplicate field numbers in `SetAttr`, `GuildwarQueryMineRes`, `Island`, `SY`; undefined types `Attr`, `GuildOccupancy`, `SP`, `SZ`/`ZZ`). The client itself loads the compiled descriptor set `assets/res/utils/net/allProtos.pb`, and that file loads cleanly in Python. The server loads the same file.
- Proto2 semantics: every `required` field of every message the server emits must be set or `SerializeToString()` raises `EncodeError`. Verified: `TounamentQuerySeasonStateRes()` with no fields raises `EncodeError: Message TounamentQuerySeasonStateRes is missing required fields: season_state,season_state_end_time`.
- protobuf 7.36.2 removed `FieldDescriptor.label`. Use `fd.is_required` and `fd.is_repeated`; `FieldDescriptor.TYPE_*` constants still exist. Verified on this machine 20-10-2026, and a `fill_required` written against `label` raises `AttributeError` at runtime, not at import.
- `msgIDMap.lua` is the single source of truth for `(service, cmd) -> message name`. It holds 1,098 entries over 1,078 distinct keys: 20 keys are assigned twice and, exactly as a Lua table constructor does, **the last assignment wins**.
- Any date that reaches a human (log banner, doc table) renders `dd-mm-yyyy`; stored/ISO values stay `YYYY-MM-DD`.
- No new abstraction for a single caller. One framing module, one registry, one dispatcher; handlers are plain functions.

## Review Focus

Five failure modes the spec implies that no obvious task test would catch, most likely first. Each has its test pinned to the task that owns the code.

1. **A `*Res` the server sends omits a proto2 `required` field** - `EncodeError` at send time, and the client sits on a white screen with no network error to show. Covered by Task 12 (`test_every_stub_res_serializes`) and Task 14 (`test_query_myself_res_serializes`).
2. **`QueryMyselfRes.player.nobility_level` is absent** - `ClientPlayer:updateData` runs `print("next self.nobility_level = " .. d.nobility_level)` unconditionally on an `optional uint32`, so a missing value kills the Lua VM right after login and the player never reaches the main city. Covered by Task 14 (`test_player_sets_every_field_lua_concatenates`).
3. **Two concurrent connections from one phone.** `GameLoginScene:loginClickHdr2` opens connection A (`SERVER_SER`), sends `194_2001 QuerySrvInfoReq`, and only then opens connection B (`SERVER_GAME`) to the address it got back. A server that keys state per player instead of per connection, or that drops A when B arrives, deadlocks the login. Covered by Task 12 (`test_two_concurrent_sessions_are_independent`) and Task 13 (`test_srvinfo_on_first_socket_then_login_on_second`).
4. **TCP does not deliver one frame per read.** `decode()` must say "need more bytes" for a half frame and must drain two frames that arrive in one buffer. Covered by Task 11 (`test_decode_partial_returns_none`, `test_decode_two_frames_in_one_buffer`).
5. **A message id with no paired `*Res`.** 6 of the 513 `Req` ids have no `Res` at all - `(5,2031) TestApnsReq`, `(5,2039) SyncRedPointReq`, `(5,2343) HeroCallbackNewReq`, `(148,2093) GuildwarRedPointReq`, `(134,2001) BugReportReq`, `(150,2059) SpardaRedPointReq` - and 50 ids are `*Notify` (e.g. `(5,4004) BatchNotify`, `(3,2014) KeyExchangeNotify`). The unknown-message policy must log once and send nothing, not raise `KeyError`. Covered by Task 12 (`test_unknown_id_without_res_sends_nothing`).

---

## Verified inputs, read 20-10-2026 from the extracted stock tree. Quote these, do not re-derive.

**Boot chain.** `assets/scripts/main.lua` sets `GAME_VERSION = "1.0.0.5"` at line 59 and runs `CCDirector:sharedDirector():runWithScene(require("StartEngineScene").new())`. `assets/scripts/version.txt` contains `211111` but no Lua script reads it, so the version on the wire is `1.0.0.5`. `StartEngineScene:onCleanupScene` loads `UF.zip` and `require("upgrade.upgrade").new()`. `upgrade/upgrade.lua:init` registers a listener for `comSdk_checkVersionCallback_event` and calls `g_sdkManager:onInitLogin()`, which on Android does nothing, so without a patch the app stops here forever: that event only ever comes from the channel SDK. The listener creates `upgrade.UpgradeScene`, whose `onEnterScene` starts with:

```lua
    if CONFIG_UPGRADE_PROCESS ~= 1 then
        self:onUpgradeComplete(true,true)
        return
    end
```

so `CONFIG_UPGRADE_PROCESS = 0` short-circuits the whole hot-update path to `startGoGame(true,true)`, `gotoGame()`, `require("check")`, `require("app.game")`, and the last line of `app/game.lua`, which is `requireN(CONFIG_APP_CODE_PATH .. "MyApp").new():run()`.

**MyApp flow.** `MyApp:run()` calls `checkLocalUpgradeZip()`, `copyZip()`, `updateDB()`. `updateDB` copies every `res/data/split/<name>.db` into the writable path and calls `g_SqlManager:openDB()`; its tail branch reads `if isUpdateDBDir == true and false then ... else self:initGame() end`, so `initGame()` always runs. `initGame()` calls `initSdkListener()`, `getGmActivity()`, `initSocket()`, `sendNotification()`. `getGmActivity()` HTTP-GETs the dead CDN at `GAME_URL = "http://nslmbt5-1300632903.cos.ap-shanghai.myqcloud.com/patch/"` and only calls `self:initLogin()` from the response callback: that is the second boot blocker. `initSocket()` wires the heartbeat: on `GAME_PLAYER_LOGIN_SUCCESS_EVENT` it sends `3_2009 {time = ...}` at once and then every 30 s, listening on `3_2010`.

**Login scene.** `GameLoginScene:showLogin()` calls `getRecommendServerIds()`, an HTTP GET to the dead CDN, which chains to `getServerList()`, `againGetServerList()`, `g_sdkManager:getGameServers(...)` (another HTTP), the `comSdk_getGameServerCallback_event` listener, and finally `showServerList(data)`. `showServerList` wants a list of tables carrying `name`, `status`, `server_id`, `socket_port`, `socket_domain`; it selects the entry whose `server_id` equals `CCUserDefault:getStringForKey("USER_LATEAST_LOGIN_DISTRICT", "1")`, i.e. the string `"1"` on a fresh install, then calls `startLogin()` when the login UI is visible and `checkNotice()`, yet another HTTP, when it is not. `startLogin()` on Android calls `g_sdkManager:showLogin()` after a 0.3 s delay. `LuaSuperSDKManager:showLogin()` calls Java `login()` and waits for the SDK to dispatch `comSdk_loginCallback_event`; that listener reads `data[1].userinfo.uid` and `data[1].accessToken` into `self.uid` and `self.accessToken`, falling back to `requireN("LoginUserData").uid`. The Start-game button first checks `self.privacyCheckBtnSelected ~= true` and pops an alert.

**loginClickHdr2 opens two connections.** It reads `serverIp = self.selectedData.socket_domain`, `serverPort = self.selectedData.socket_port`, `self.serverId = self.selectedData.server_id`; sets `g_socketManager.IP_GAME` and `PORT_GAME`; calls `MMMsgProcessHandler:getInstance():setCurDistrict(0)`; installs a connect handler that sends `194_2001 {server_id = self.serverId}`; and connects `SERVER_SER`, connIndex 999. On `194_2002` the handler `querySrvInfoRes` tests `rs.status ~= 0`. `QuerySrvInfoRes` has no `status` field, and `toint(nil)` is 0 because `framework/functions.lua` defines `tonum(v)` as `tonumber(v) or 0`, so the absent field reads as 0 and passes. It then splits `rs.addr` on a colon into ip and port, calls `MMMsgProcessHandler:setCurDistrict(toint(rs.district))`, and builds `LoginSocketData`, which connects `SERVER_GAME`, connIndex 1, to that address. The server therefore receives two TCP connections from one phone.

**LoginSocketData** in `app/game/net/LoginSocketData.lua`, on connect, sends `3_2005 {issue = GAME_VERSION}` then `3_2015 {}`. Its listeners are `3_2002` to `loginReceiveHdr`, `3_2004` to `registerReceiveHdr`, `5_2006` to `queryMySelfReceiveHdr`, `3_2006` to `checkServerVersion`, and an inline `3_2016` handler that returns immediately when `msg.state == 0`. `checkServerVersion` splits `rs.issue_required` on a colon and, because `CONFIG_DEVELOP == 1`, skips both the version compare and the DB MD5 check and calls `checkDBMD5Complete(true)`, which sends:

```lua
    g_socketListener:sendMsg("3_2001", {IMEI = SYSTEM_IMEI, device = SYSTEM_TOPKN,username = self.username,
      token = self.token , datetime = datatime, args = {self.server_id}});
```

`loginReceiveHdr` with `status == 0` calls `g_timeManager:setTime(rs.timestamp, rs.time_zone_offset)` and then `queryMyselfHdr()`, which sends `5_2005 {}`. With `status == 327682` it means "no role": the client sends `3_2003 GameplayReq` with the same body shape, and `3_2004 GameplayRes` with `status == 0` sets `self.createRole = true` and also calls `queryMyselfHdr()`. Any other status pops an error alert and fails the login. There is no separate CreateRole message: `3_2003` and `3_2004` are character creation. Verified by grep, `msgIDMap.lua` contains no `CreateRoleReq`, `RegisterReq`, `QueryHeroesReq`, `QueryBagReq`, `QueryItemsReq` or `QueryMailsReq`; hero, inventory, angel and mail data all ride on `QueryMyselfRes`.

**queryMySelfReceiveHdr** calls `g_roleData:updateData(rs, ...)`, then `g_newGuideManager:initGuideId()` which reads `g_roleData.player.guide_id`, then dispatches `GAME_PLAYER_LOGIN_SUCCESS_EVENT` which starts the heartbeat, then `successFun`, which is `GameLoginScene:gameSocketSuccess`, which does `g_RPGGame = RPGGame.new()`: the main city. `RPGGame` then sends, in order, `5_2317 {}`, `151_2041 {}`, `5_2801 {}`, `153_2001 {}`, `5_2943 {}`.

**RoleData:updateData(d) dereferences unconditionally**: `d.gold_trails.prize`, `d.gold_trails.damage`, the lengths of `d.heroes`, `d.inventory` and `d.levels`, `d.stats` via `self.stats:updateData(d.stats)`, and `d.player`. The fields `d.records`, `d.events`, `d.guild` and `d.mail_new` are nil-tolerant. `ClientPlayer:updateData` concatenates `d.nobility_level` into a `print`, so that optional field must be present or the Lua VM errors.

**Message dispatch.** The comment at `app/game/net/MMMsgDispatcher.lua:102` says, in translation, that the backend must always send `status` and must not leave it as an absent optional, because reading a missing field raises. In practice `onNetMessage` calls `toint(msg["status"])`, and `toint(nil)` is 0, so a Res that has no `status` field at all is treated as success, while a Res that does have one must carry `status = 0` or the client floats an error toast.

**Java surface reachable from Lua.** `sdk/SDKConfig.lua` sets `kSDKTarget = 3`, so `g_sdkManager` is `LuaSuperSDKManager`, whose `javaSDKClass` is `com/uuzu/nslm/JavaSuperSDKManager` and whose `nslmClass` is `com/uuzu/nslm/Nslm`. `app/game/manager/MediaManager.lua` sets `MediaPlayer.javaAudioClass` to `com.uuzu.nslm.Nslm`. All calls go through `framework/luaj.lua`, which forwards to `CCLuaJavaBridge.callStaticMethod(className, methodName, args, sig)`. The complete call-site list with its `sig` strings is the input to `client/gen_luaj_stubs.py` in Task 5.

**Proto bodies, computed on 20-10-2026. Paste these hex strings into tests.**

- `QuerySrvInfoReq(server_id="1")` serializes to `0a0131`, 3 bytes.
- `ProtocolReq(issue="1.0.0.5")` serializes to `0a07312e302e302e35`, 9 bytes.
- `LoginReq(username="stefan", token="local", datetime=1, args=["1"])` serializes to `0a0673746566616e12056c6f63616c1801420131`.
- `QuerySrvInfoRes(district=1, addr="192.168.1.50:8112")` serializes to `080112113139322e3136382e312e35303a38313132`, 21 bytes.
- `HeartbeatRes(status=0, time=1)` serializes to `08001001`.

**Required-field counts**, proto2, all of them must be set before `SerializeToString()`: `ClientPlayer` 30 of 72, `ClientDailyStats` 19 of 37, `ClientHero` 10 of 29, `ClientStock` 3 of 5, `ClientLevel` 6 of 8, `ClientAngel` 5 of 10, `ClientChapter` 1 of 2, `ClientEvent` 3 of 3, `ClientGoldTrails` 0 of 2, `TounamentQuerySeasonStateRes` 2 of 2.

**Asset size.** `.stock/assets/res` is 449 MB, `assets/scripts` 17 MB, `assets/fonts` 7.6 MB. Expect a 450 to 500 MB APK and slow packaging; the Gradle config in Task 6 therefore sets `noCompress` for the bulk extensions.

**New-player guide.** `res/data/split/new_player_guide_info.db`, table `new_player_guide_info`, 191 rows, ids 10000 to 14304, columns `id, nextid, jump_id, is_over, face_id, name, play_type, talk, hand_off_set, size, is_save, is_unlock, dir, prince_set, face_img, isoverturn, lua`. The highest id with `is_over = 1` is **14302**. `NewGuideManager:initGuideId()` seeds itself from `g_roleData.player.guide_id`, so that is the single lever if the tutorial blocks the main city.

---

## File Structure

Created by this plan; every path is NEW unless marked MODIFY.

```
pyproject.toml                       deps + pytest config
settings.toml                        [paths] / [net] / [account] / [player]
.gitignore                           MODIFY: today it ignores all of client/
tools/extract_stock.py               APK -> .stock/ with zipfile
tools/capture_server.py              dummy listener, hex dump with timestamps
tools/fake_client.py                 replays the login burst at a running server
server/__init__.py
server/__main__.py                   py -3.14 -m server
server/settings.py                   tomllib loader -> Settings
server/net/__init__.py
server/net/msgmap.py                 msgIDMap.lua parser
server/net/registry.py               allProtos.pb loader, message_class(name)
server/net/framing.py                encode()/decode() per docs/protocol.md
server/net/server.py                 asyncio server, Session, dispatch, unknown policy
server/db.py                         player.db schema + connection
server/modules/__init__.py
server/modules/login.py              194_2001, 3_2005, 3_2015, 3_2001, 3_2003, 3_2009
server/modules/player.py             5_2005 plus the five main-city stubs
client/fetch_cocos_java.py           GitHub contents API -> cocos2d-x 2.2.2 java
client/gen_luaj_stubs.py             stock Lua call sites -> Java stub sources
client/make_keystore.py              keytool wrapper, writes outside git
client/build_assets.py               assets + 7 Lua patches + libgame.so
client/android/                      Gradle project, tasks 4 to 6 and 8
docs/protocol.md                     framing layout, written from the capture
docs/dev-loop.md                     emulator versus phone verdict
tests/                               one module per source module
```

---

### Task 1: Repo scaffold, settings loader, stock extraction

**Files:**
- Create: `pyproject.toml`, `settings.toml`, `tools/__init__.py`, `tools/extract_stock.py`, `server/__init__.py`, `server/settings.py`, `tests/__init__.py`
- Modify: `.gitignore`, which today contains the line `client/` and would hide every file this plan adds under `client/`
- Test: `tests/test_extract_stock.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `tools.extract_stock.extract(apk_path: Path, dest: Path) -> int`, returning the number of members written; `server.settings.Settings`, a frozen dataclass with `stock_dir: Path`, `db_path: Path`, `host: str`, `port: int`, `username: str`, `guide_id: int`; `server.settings.load(path: Path = Path("settings.toml")) -> Settings`.

- [ ] **Step 1: Write the failing tests**

`tests/test_extract_stock.py`:

```python
import zipfile
from pathlib import Path

import pytest

from tools.extract_stock import extract


def test_extract_writes_every_member(tmp_path: Path) -> None:
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/scripts/main.lua", "GAME_VERSION\n")
        z.writestr("lib/armeabi/libgame.so", b"\x7fELF-not-really")
    dest = tmp_path / ".stock"

    count = extract(apk, dest)

    assert count == 2
    assert (dest / "assets/scripts/main.lua").read_text() == "GAME_VERSION\n"
    assert (dest / "lib/armeabi/libgame.so").read_bytes() == b"\x7fELF-not-really"


def test_extract_refuses_path_traversal(tmp_path: Path) -> None:
    apk = tmp_path / "evil.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("../escaped.txt", "nope")
    dest = tmp_path / ".stock"

    with pytest.raises(ValueError, match="escapes dest"):
        extract(apk, dest)
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_is_idempotent(tmp_path: Path) -> None:
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/a.txt", "one")
    dest = tmp_path / ".stock"

    assert extract(apk, dest) == 1
    assert extract(apk, dest) == 1
    assert (dest / "assets/a.txt").read_text() == "one"
```

`tests/test_settings.py`:

```python
from pathlib import Path

from server.settings import load

SAMPLE = """
[paths]
stock_dir = ".stock"
db_path = "data/player.db"
apk = "C:/x.apk"

[net]
host = "192.168.1.50"
port = 8112

[account]
username = "stefan"

[player]
guide_id = 0
"""


def test_load_reads_every_field(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.toml"
    cfg.write_text(SAMPLE, encoding="utf-8")

    s = load(cfg)

    assert s.stock_dir == Path(".stock")
    assert s.db_path == Path("data/player.db")
    assert s.host == "192.168.1.50"
    assert s.port == 8112
    assert s.username == "stefan"
    assert s.guide_id == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_extract_stock.py tests/test_settings.py --basetemp=C:\tmp\pytest-loa`
Expected: collection errors, `ModuleNotFoundError: No module named 'tools'` and `No module named 'server'`.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "loa-private-server"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["protobuf>=7.36.2"]

[project.optional-dependencies]
dev = ["pytest>=9.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Write `settings.toml`**

`host` is the home PC LAN address. It is both the server bind address and the IP that `client/build_assets.py` bakes into the client server list, so put the real address here before the first APK build. Find it with `py -3.14 -c "import socket;print(socket.gethostbyname(socket.gethostname()))"`.

```toml
[paths]
stock_dir = ".stock"
db_path = "data/player.db"
apk = "C:/Users/Stefan.Nasev/Downloads/LOA Fire Raiders 277sy.apk"

[net]
host = "192.168.1.50"
port = 8112

[account]
username = "stefan"

[player]
# 0 runs the stock new-player guide. If the guide blocks the main city, set
# 14302: the highest id in res/data/split/new_player_guide_info.db with
# is_over = 1 (191 rows, ids 10000 to 14304, verified 20-10-2026).
guide_id = 0
```

- [ ] **Step 5: Write `tools/extract_stock.py` plus an empty `tools/__init__.py`**

```python
"""Extract the stock LOA APK into .stock/ with the standard library only."""

from __future__ import annotations

import argparse
import sys
import tomllib
import zipfile
from pathlib import Path


def extract(apk_path: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    written = 0
    with zipfile.ZipFile(apk_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"zip member escapes dest: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--apk", type=Path, default=None)
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = tomllib.loads(args.settings.read_text(encoding="utf-8"))
    apk = args.apk or Path(cfg["paths"]["apk"])
    dest = args.dest or Path(cfg["paths"]["stock_dir"])

    count = extract(apk, dest)
    print(f"extracted {count} members from {apk} into {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write `server/settings.py`, plus empty `server/__init__.py` and `tests/__init__.py`**

```python
"""settings.toml loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    stock_dir: Path
    db_path: Path
    host: str
    port: int
    username: str
    guide_id: int


def load(path: Path = Path("settings.toml")) -> Settings:
    cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return Settings(
        stock_dir=Path(cfg["paths"]["stock_dir"]),
        db_path=Path(cfg["paths"]["db_path"]),
        host=cfg["net"]["host"],
        port=int(cfg["net"]["port"]),
        username=cfg["account"]["username"],
        guide_id=int(cfg["player"]["guide_id"]),
    )
```

- [ ] **Step 7: Replace `.gitignore` wholesale**

```gitignore
.venv/
__pycache__/
.pytest_cache/
.stock/
data/
captures/
*.apk
*.jks
*.keystore
local.properties
client/android/.gradle/
client/android/build/
client/android/app/build/
client/android/app/src/main/assets/
client/android/app/src/main/jniLibs/
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_extract_stock.py tests/test_settings.py --basetemp=C:\tmp\pytest-loa`
Expected: `4 passed`.

- [ ] **Step 9: Smoke-run the extractor on the real APK**

Run, in Git Bash from the repo root: `py -3.14 tools/extract_stock.py`
Expected: one line reading `extracted <N> members from C:/Users/Stefan.Nasev/Downloads/LOA Fire Raiders 277sy.apk into .stock`. The APK is 305,535,047 bytes; extraction takes a couple of minutes.
Then confirm the inputs every later task reads:

```bash
ls -l .stock/lib/armeabi/libgame.so .stock/assets/res/utils/net/allProtos.pb \
      .stock/assets/res/utils/net/msgIDMap.lua .stock/assets/scripts/main.lua \
      .stock/classes.dex .stock/classes2.dex
```

Expected sizes: `libgame.so` 15,047,664, `allProtos.pb` 117,932, `msgIDMap.lua` 46,956, both dex files present.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml settings.toml .gitignore tools/__init__.py tools/extract_stock.py \
        server/__init__.py server/settings.py tests/__init__.py \
        tests/test_extract_stock.py tests/test_settings.py
git commit -m "chore(repo): scaffold, settings loader and stock APK extractor"
```

---

### Task 2: Proto registry and msgIDMap parser

**Files:**
- Create: `server/net/__init__.py`, `server/net/msgmap.py`, `server/net/registry.py`
- Test: `tests/test_msgmap.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: `server.settings.Settings.stock_dir` from Task 1.
- Produces:
  - `server.net.msgmap.parse(text: str) -> dict[tuple[int, int], str]`
  - `server.net.msgmap.load(stock_dir: Path) -> dict[tuple[int, int], str]`, reading `<stock_dir>/assets/res/utils/net/msgIDMap.lua`
  - `server.net.msgmap.res_key(ids, service: int, cmd: int) -> tuple[int, int] | None`
  - `server.net.registry.Registry` with the classmethod `load(stock_dir: Path) -> Registry` and the methods `message_class(name: str) -> type`, `name_for(service: int, cmd: int) -> str | None`, `class_for(service: int, cmd: int) -> type | None`, plus the attribute `ids: dict[tuple[int, int], str]`.

- [ ] **Step 1: Write the failing test `tests/test_msgmap.py`**

```python
from pathlib import Path

from server.net import msgmap

STOCK = Path(".stock")


def test_parse_reads_service_cmd_and_name() -> None:
    ids = msgmap.parse(
        "local idMapTable =\n{\n"
        '    id_3_2001 = "LoginReq",\n\n'
        '    id_3_2002 = "LoginRes",\n}\nreturn idMapTable'
    )
    assert ids == {(3, 2001): "LoginReq", (3, 2002): "LoginRes"}


def test_parse_last_assignment_wins_like_lua() -> None:
    ids = msgmap.parse(
        '{ id_5_2601 = "ArtifactDebugGiveArtifactsReq",\n'
        '  id_5_2601 = "PicnicInviteeListReq", }'
    )
    assert ids[(5, 2601)] == "PicnicInviteeListReq"


def test_real_map_has_the_login_burst_ids() -> None:
    ids = msgmap.load(STOCK)
    assert len(ids) == 1078
    expected = {
        (3, 2005): "ProtocolReq", (3, 2006): "ProtocolRes",
        (3, 2015): "QuerySrvStateReq", (3, 2016): "QuerySrvStateRes",
        (3, 2001): "LoginReq", (3, 2002): "LoginRes",
        (3, 2003): "GameplayReq", (3, 2004): "GameplayRes",
        (3, 2009): "HeartbeatReq", (3, 2010): "HeartbeatRes",
        (5, 2005): "QueryMyselfReq", (5, 2006): "QueryMyselfRes",
        (194, 2001): "QuerySrvInfoReq", (194, 2002): "QuerySrvInfoRes",
        (5, 2317): "GameReadyReq", (5, 2318): "GameReadyRes",
        (5, 2801): "QueryMyPushMessageReq", (5, 2802): "QueryMyPushMessageRes",
        (5, 2943): "QueryBtCardRecordReq", (5, 2944): "QueryBtCardRecordRes",
        (153, 2001): "MagicStateReq", (153, 2002): "MagicStateRes",
        (151, 2041): "TounamentQuerySeasonStateReq",
        (151, 2042): "TounamentQuerySeasonStateRes",
    }
    for key, name in expected.items():
        assert ids[key] == name
    names = set(ids.values())
    for absent in ("QueryHeroesReq", "QueryBagReq", "QueryItemsReq",
                   "QueryMailsReq", "CreateRoleReq", "RegisterReq"):
        assert absent not in names


def test_res_key_pairs_507_of_513_reqs() -> None:
    ids = msgmap.load(STOCK)
    reqs = [k for k, v in ids.items() if v.endswith("Req")]
    assert len(reqs) == 513
    assert len([k for k in reqs if msgmap.res_key(ids, *k) is not None]) == 507
    assert msgmap.res_key(ids, 3, 2001) == (3, 2002)
    assert msgmap.res_key(ids, 5, 2005) == (5, 2006)
    for key in [(5, 2031), (5, 2039), (5, 2343), (148, 2093), (134, 2001), (150, 2059)]:
        assert msgmap.res_key(ids, *key) is None
    assert msgmap.res_key(ids, 5, 4004) is None
```

- [ ] **Step 2: Write the failing test `tests/test_registry.py`**

```python
from pathlib import Path

import pytest
from google.protobuf.message import EncodeError

from server.net.registry import Registry

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


def test_login_req_matches_the_known_hex(reg: Registry) -> None:
    LoginReq = reg.message_class("LoginReq")
    msg = LoginReq(username="stefan", token="local", datetime=1, args=["1"])
    assert msg.SerializeToString().hex() == "0a0673746566616e12056c6f63616c1801420131"


def test_query_srv_info_req_and_res_hex(reg: Registry) -> None:
    req = reg.message_class("QuerySrvInfoReq")(server_id="1")
    assert req.SerializeToString().hex() == "0a0131"
    res = reg.message_class("QuerySrvInfoRes")(district=1, addr="192.168.1.50:8112")
    assert res.SerializeToString().hex() == (
        "080112113139322e3136382e312e35303a38313132"
    )


def test_protocol_req_hex(reg: Registry) -> None:
    req = reg.message_class("ProtocolReq")(issue="1.0.0.5")
    assert req.SerializeToString().hex() == "0a07312e302e302e35"


def test_query_myself_res_top_level_fields(reg: Registry) -> None:
    fields = [f.name for f in reg.message_class("QueryMyselfRes").DESCRIPTOR.fields][:15]
    assert fields == [
        "status", "player", "guild", "heroes", "inventory", "levels", "stats",
        "chapters", "angels", "events", "mail_new", "last_elite_prize",
        "records", "gold_trails", "first_recharge_reward",
    ]


def test_class_for_resolves_through_the_id_map(reg: Registry) -> None:
    assert reg.name_for(3, 2001) == "LoginReq"
    assert reg.class_for(194, 2002).DESCRIPTOR.name == "QuerySrvInfoRes"
    assert reg.name_for(9999, 9999) is None
    assert reg.class_for(9999, 9999) is None


def test_proto2_required_fields_are_enforced(reg: Registry) -> None:
    with pytest.raises(EncodeError):
        reg.message_class("TounamentQuerySeasonStateRes")().SerializeToString()
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_msgmap.py tests/test_registry.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'server.net'`.

- [ ] **Step 4: Write `server/net/msgmap.py` plus an empty `server/net/__init__.py`**

```python
"""Parse the client msgIDMap.lua into {(service, cmd): message_name}."""

from __future__ import annotations

import re
from pathlib import Path

_ENTRY = re.compile(r"id_(\d+)_(\d+)\s*=\s*\"(\w+)\"")

MAP_RELPATH = Path("assets/res/utils/net/msgIDMap.lua")


def parse(text: str) -> dict[tuple[int, int], str]:
    """Later duplicate keys overwrite earlier ones, as a Lua table constructor does."""
    ids: dict[tuple[int, int], str] = {}
    for service, cmd, name in _ENTRY.findall(text):
        ids[(int(service), int(cmd))] = name
    return ids


def load(stock_dir: Path) -> dict[tuple[int, int], str]:
    return parse((Path(stock_dir) / MAP_RELPATH).read_text(encoding="utf-8-sig"))


def res_key(
    ids: dict[tuple[int, int], str], service: int, cmd: int
) -> tuple[int, int] | None:
    """The (service, cmd) of the Res paired with a Req, or None when there is none."""
    name = ids.get((service, cmd))
    if name is None or not name.endswith("Req"):
        return None
    candidate = (service, cmd + 1)
    return candidate if ids.get(candidate) == name[:-3] + "Res" else None
```

- [ ] **Step 5: Write `server/net/registry.py`**

```python
"""Load the compiled descriptor set the client itself uses, and expose classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from server.net import msgmap

PB_RELPATH = Path("assets/res/utils/net/allProtos.pb")


@dataclass
class Registry:
    pool: descriptor_pool.DescriptorPool
    ids: dict[tuple[int, int], str]
    _cache: dict[str, type] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, stock_dir: Path) -> "Registry":
        raw = (Path(stock_dir) / PB_RELPATH).read_bytes()
        fds = descriptor_pb2.FileDescriptorSet.FromString(raw)
        pool = descriptor_pool.DescriptorPool()
        for proto_file in fds.file:
            pool.Add(proto_file)
        return cls(pool=pool, ids=msgmap.load(stock_dir))

    def message_class(self, name: str) -> type:
        cached = self._cache.get(name)
        if cached is None:
            descriptor = self.pool.FindMessageTypeByName(name)
            cached = message_factory.GetMessageClass(descriptor)
            self._cache[name] = cached
        return cached

    def name_for(self, service: int, cmd: int) -> str | None:
        return self.ids.get((service, cmd))

    def class_for(self, service: int, cmd: int) -> type | None:
        name = self.name_for(service, cmd)
        return None if name is None else self.message_class(name)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_msgmap.py tests/test_registry.py --basetemp=C:\tmp\pytest-loa`
Expected: `10 passed`. A file-not-found on `.stock` means Task 1 step 9 was skipped.

- [ ] **Step 7: Commit**

```bash
git add server/net/__init__.py server/net/msgmap.py server/net/registry.py \
        tests/test_msgmap.py tests/test_registry.py
git commit -m "feat(server): load allProtos.pb descriptor set and parse msgIDMap.lua"
```

---

### Task 3: Capture listener

**Files:**
- Create: `tools/capture_server.py`
- Test: `tests/test_capture_server.py`

**Interfaces:**
- Consumes: nothing (deliberately standalone, so it can run before any framing is known).
- Produces: `tools.capture_server.hexdump(data: bytes, offset: int = 0) -> str` and the coroutine `tools.capture_server.serve(host: str, port: int, log_path: Path, ready: asyncio.Event | None = None) -> None`. The log line format is fixed because `docs/protocol.md` in Task 10 is written from it: one header line per read, `[HH:MM:SS.mmm] conn#<n> <peer> recv <len> bytes`, then `hexdump` lines of 16 bytes each, `OFFSET  HEX(16, space-separated, 8/8 split)  |ASCII|`.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import re
from pathlib import Path

from tools.capture_server import hexdump, serve


def test_hexdump_formats_offset_hex_and_ascii() -> None:
    out = hexdump(bytes.fromhex("0a07") + b"1.0.0.5")
    assert out.splitlines()[0] == (
        "00000000  0a 07 31 2e 30 2e 30 2e  35                       "
        "|..1.0.0.5|"
    )


def test_serve_logs_what_a_client_sends(tmp_path: Path) -> None:
    log = tmp_path / "capture.log"

    async def run() -> None:
        ready = asyncio.Event()
        task = asyncio.create_task(serve("127.0.0.1", 18112, log, ready))
        await asyncio.wait_for(ready.wait(), 5)
        reader, writer = await asyncio.open_connection("127.0.0.1", 18112)
        writer.write(bytes.fromhex("0a0131"))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    text = log.read_text(encoding="utf-8")
    assert re.search(r"conn#1 127\.0\.0\.1:\d+ recv 3 bytes", text)
    assert "00000000  0a 01 31" in text
```

Note: there is no `pytest-asyncio` dependency anywhere in this plan. Every async test drives the loop itself with `asyncio.run`.

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_capture_server.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'tools.capture_server'`.

- [ ] **Step 3: Write `tools/capture_server.py`**

```python
"""Dummy TCP listener that hex-dumps everything a client sends.

Used once to learn the wire framing, then kept for debugging. It answers
nothing, so the client will time out; that is fine, we only need its first
packets.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tomllib
from datetime import datetime
from itertools import count
from pathlib import Path

_PRINTABLE = bytes(range(0x20, 0x7F))


def hexdump(data: bytes, offset: int = 0) -> str:
    lines: list[str] = []
    for start in range(0, len(data), 16):
        chunk = data[start : start + 16]
        left = " ".join(f"{b:02x}" for b in chunk[:8])
        right = " ".join(f"{b:02x}" for b in chunk[8:])
        hexpart = f"{left:<23} {right:<23}"
        ascii_part = "".join(chr(b) if b in _PRINTABLE else "." for b in chunk)
        lines.append(f"{offset + start:08x}  {hexpart} |{ascii_part}|")
    return "\n".join(lines)


async def serve(
    host: str, port: int, log_path: Path, ready: asyncio.Event | None = None
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    conn_ids = count(1)
    log = log_path.open("a", encoding="utf-8", buffering=1)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn_id = next(conn_ids)
        peer = "%s:%d" % writer.get_extra_info("peername")[:2]
        offset = 0
        _emit(log, f"conn#{conn_id} {peer} OPEN")
        try:
            while data := await reader.read(65536):
                _emit(log, f"conn#{conn_id} {peer} recv {len(data)} bytes")
                _emit_raw(log, hexdump(data, offset))
                offset += len(data)
        finally:
            _emit(log, f"conn#{conn_id} {peer} CLOSE after {offset} bytes")
            writer.close()

    server = await asyncio.start_server(handle, host, port)
    _emit(log, f"capture listening on {host}:{port}, writing {log_path}")
    if ready is not None:
        ready.set()
    async with server:
        await server.serve_forever()


def _emit(log, line: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    text = f"[{stamp}] {line}"
    print(text, flush=True)
    log.write(text + "\n")


def _emit_raw(log, text: str) -> None:
    print(text, flush=True)
    log.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LOA protocol capture listener")
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--log", type=Path, default=Path("captures/capture.log"))
    args = parser.parse_args(argv)

    cfg = tomllib.loads(args.settings.read_text(encoding="utf-8"))
    host = args.host or cfg["net"]["host"]
    port = args.port or int(cfg["net"]["port"])
    try:
        asyncio.run(serve(host, port, args.log))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -3.14 -m pytest -q tests/test_capture_server.py --basetemp=C:\tmp\pytest-loa`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/capture_server.py tests/test_capture_server.py
git commit -m "feat(tools): TCP capture listener with timestamped hex dumps"
```

---

### Task 4: cocos2d-x 2.2.2 Java runtime

**Files:**
- Create: `client/fetch_cocos_java.py`, `client/android/app/src/main/java/org/cocos2dx/lib/*.java` (fetched, then committed)
- Test: `tests/test_fetch_cocos_java.py` plus a real `javac` compile

**Interfaces:**
- Consumes: nothing.
- Produces: the package `org.cocos2dx.lib` on disk. The engine resolves these by name at runtime through JNI `FindClass`, so the package and class names are load-bearing: `org/cocos2dx/lib/Cocos2dxBitmap`, `Cocos2dxETCLoader`, `Cocos2dxGLSurfaceView`, `Cocos2dxHelper`, `Cocos2dxRenderer`. The native methods `libgame.so` exports, which these classes must declare, are exactly: `Cocos2dxRenderer` - nativeInit, nativeRender, nativeOnPause, nativeOnResume, nativeTouchesBegin, nativeTouchesEnd, nativeTouchesMove, nativeTouchesCancel, nativeKeyDown, nativeInsertText, nativeDeleteBackward, nativeGetContentText; `Cocos2dxLuaJavaBridge` - callLuaFunctionWithString, callLuaGlobalFunctionWithString, retainLuaFunction, releaseLuaFunction; `Cocos2dxHelper` - nativeSetApkPath, nativeSetEditTextDialogResult; `Cocos2dxBitmap` - nativeInitBitmapDC; `Cocos2dxETCLoader` - nativeSetTextureInfo; `Cocos2dxAccelerometer` - onSensorChanged.
- `client/fetch_cocos_java.py:fetch(dest: Path, listing: list[dict] | None = None) -> list[str]` returns the sorted list of file names written.

- [ ] **Step 1: Write the failing test `tests/test_fetch_cocos_java.py`**

```python
import json
from pathlib import Path

from client.fetch_cocos_java import FindClassError, fetch, verify_natives

FAKE_LISTING = [
    {"name": "Cocos2dxRenderer.java", "type": "file",
     "download_url": "https://example.invalid/Cocos2dxRenderer.java"},
    {"name": "README.md", "type": "file",
     "download_url": "https://example.invalid/README.md"},
]


def test_fetch_writes_only_java_files(tmp_path: Path, monkeypatch) -> None:
    def fake_get(url: str) -> bytes:
        return b"package org.cocos2dx.lib;\nclass Cocos2dxRenderer {}\n"

    monkeypatch.setattr("client.fetch_cocos_java._get", fake_get)
    written = fetch(tmp_path, listing=FAKE_LISTING)

    assert written == ["Cocos2dxRenderer.java"]
    assert (tmp_path / "Cocos2dxRenderer.java").read_text().startswith(
        "package org.cocos2dx.lib;"
    )
    assert not (tmp_path / "README.md").exists()


def test_verify_natives_flags_a_missing_declaration(tmp_path: Path) -> None:
    (tmp_path / "Cocos2dxRenderer.java").write_text(
        "package org.cocos2dx.lib;\nclass Cocos2dxRenderer {\n"
        "  private static native void nativeInit(int w, int h);\n}\n",
        encoding="utf-8",
    )
    missing = verify_natives(tmp_path, {"Cocos2dxRenderer": ["nativeInit", "nativeRender"]})
    assert missing == {"Cocos2dxRenderer": ["nativeRender"]}


def test_real_tree_declares_every_native_libgame_exports() -> None:
    root = Path("client/android/app/src/main/java/org/cocos2dx/lib")
    missing = verify_natives(root, json.loads(Path("client/cocos_natives.json").read_text()))
    assert missing == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_fetch_cocos_java.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'client'`.

- [ ] **Step 3: Write `client/cocos_natives.json`**

This file is the contract from the brief, turned into data the test can check.

```json
{
  "Cocos2dxRenderer": ["nativeInit", "nativeRender", "nativeOnPause", "nativeOnResume",
    "nativeTouchesBegin", "nativeTouchesEnd", "nativeTouchesMove", "nativeTouchesCancel",
    "nativeKeyDown", "nativeInsertText", "nativeDeleteBackward", "nativeGetContentText"],
  "Cocos2dxLuaJavaBridge": ["callLuaFunctionWithString", "callLuaGlobalFunctionWithString",
    "retainLuaFunction", "releaseLuaFunction"],
  "Cocos2dxHelper": ["nativeSetApkPath", "nativeSetEditTextDialogResult"],
  "Cocos2dxBitmap": ["nativeInitBitmapDC"],
  "Cocos2dxETCLoader": ["nativeSetTextureInfo"],
  "Cocos2dxAccelerometer": ["onSensorChanged"]
}
```

`Cocos2dxAccelerometer.onSensorChanged` is the one entry that is not a `native` declaration but a Java method the native side calls back into; `verify_natives` therefore matches on the method name anywhere in the file, not on the `native` keyword.

- [ ] **Step 4: Write `client/fetch_cocos_java.py` plus an empty `client/__init__.py`**

```python
"""Fetch the cocos2d-x 2.2.2 Android Java runtime straight from GitHub."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

LISTING_URL = (
    "https://api.github.com/repos/cocos2d/cocos2d-x/contents/"
    "cocos2dx/platform/android/java/src/org/cocos2dx/lib?ref=cocos2d-x-2.2.2"
)
DEST = Path("client/android/app/src/main/java/org/cocos2dx/lib")


class FindClassError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "loa-private-server"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch(dest: Path, listing: list[dict] | None = None) -> list[str]:
    if listing is None:
        listing = json.loads(_get(LISTING_URL))
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for entry in listing:
        if entry.get("type") != "file" or not entry["name"].endswith(".java"):
            continue
        body = _get(entry["download_url"])
        (dest / entry["name"]).write_bytes(body)
        written.append(entry["name"])
    return sorted(written)


def verify_natives(root: Path, expected: dict[str, list[str]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for cls, methods in expected.items():
        path = root / f"{cls}.java"
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        gone = [m for m in methods if not re.search(rf"\b{re.escape(m)}\s*\(", text)]
        if gone:
            missing[cls] = gone
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args(argv)
    names = fetch(args.dest)
    print(f"wrote {len(names)} java files into {args.dest}")
    expected = json.loads(Path("client/cocos_natives.json").read_text(encoding="utf-8"))
    missing = verify_natives(args.dest, expected)
    if missing:
        raise FindClassError(f"missing native declarations: {missing}")
    print("every native libgame.so needs is declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the fetch for real**

Run, in Git Bash from the repo root:

```bash
py -3.14 client/fetch_cocos_java.py
ls client/android/app/src/main/java/org/cocos2dx/lib/
```

Expected: `wrote <N> java files ...` followed by `every native libgame.so needs is declared`. The brief lists the files expected at that tag: Cocos2dxActivity, Cocos2dxRenderer, Cocos2dxGLSurfaceView, Cocos2dxHelper, Cocos2dxBitmap, Cocos2dxETCLoader, Cocos2dxAccelerometer, Cocos2dxLuaJavaBridge, Cocos2dxMusic, Cocos2dxSound, Cocos2dxTypefaces, Cocos2dxEditText, Cocos2dxEditBoxDialog, Cocos2dxHandler, Cocos2dxTextInputWraper, Cocos2dxLocalStorage. Not all exist at 2.2.2 (Cocos2dxEditBox, Cocos2dxEditBoxHelper and Cocos2dxWebView are later additions); the script takes whatever the directory listing returns, which is the authority. If `FindClassError` is raised, stop and report, because a missing native declaration is a guaranteed runtime crash.

- [ ] **Step 6: Compile the fetched sources with javac**

Run, in Git Bash from the repo root:

```bash
JAVAC="/c/Program Files/Android/Android Studio/jbr/bin/javac.exe"
ANDROID_JAR="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk/platforms/android-36/android.jar"
mkdir -p /c/tmp/loa-javac
"$JAVAC" -nowarn -proc:none -encoding UTF-8 \
  -classpath "C:/Users/Stefan.Nasev/AppData/Local/Android/Sdk/platforms/android-36/android.jar" \
  -d /c/tmp/loa-javac \
  client/android/app/src/main/java/org/cocos2dx/lib/*.java
```

Expected: exit 0 and no `error:` lines (deprecation notes are fine). If exactly one or two files fail on a symbol that is not in `client/cocos_natives.json` (the 2.2.2 edit-box helpers sometimes reference an `R` class that does not exist outside the engine project), delete those files, re-run the command until it is clean, and record the deletion in the commit message. Never delete a class named in `cocos_natives.json` or in the FindClass set.

- [ ] **Step 7: Run the Python test to verify it passes**

Run: `py -3.14 -m pytest -q tests/test_fetch_cocos_java.py --basetemp=C:\tmp\pytest-loa`
Expected: `3 passed`.

- [ ] **Step 8: Commit**

```bash
git add client/__init__.py client/fetch_cocos_java.py client/cocos_natives.json \
        client/android/app/src/main/java/org/cocos2dx/lib \
        tests/test_fetch_cocos_java.py
git commit -m "feat(client): vendor the cocos2d-x 2.2.2 Android Java runtime"
```

---

### Task 5: comSdk.IComSdk recovery and generated luaj stubs

**Files:**
- Create: `client/gen_luaj_stubs.py`, `client/android/app/src/main/java/comSdk/IComSdk.java`, `client/android/app/src/main/java/com/uuzu/nslm/JavaSuperSDKManager.java`, `.../JavaComSDKManager.java`, `.../Nslm.java`
- Test: `tests/test_gen_luaj_stubs.py` plus a real `javac` compile

**Interfaces:**
- Consumes: `.stock/assets/scripts/**/*.lua` and `.stock/classes.dex`, `.stock/classes2.dex`.
- Produces:
  - `client.gen_luaj_stubs.scan(scripts_root: Path) -> dict[str, dict[str, str]]`, mapping a slash-or-dot Java class name to `{method_name: jni_signature}`.
  - `client.gen_luaj_stubs.render(class_name: str, methods: dict[str, str]) -> str`, the Java source.
  - `client.gen_luaj_stubs.java_decl(sig: str) -> tuple[list[str], str]`, the parameter Java types and the return Java type.
  - The three stub classes plus `comSdk.IComSdk`. Lua never calls `IComSdk`; it exists only so the engine can resolve its 13 native callbacks.

**Behaviour the generator must implement**, each value chosen so the patched Lua gets a usable answer:

| class and method | returns |
|---|---|
| `JavaSuperSDKManager.getDeviceId()` and `JavaComSDKManager.getDeviceId()` | the literal `"LOA-HOME-0001"` |
| `*.getPlatformConfigByName(String key, String defaultValue)` | `defaultValue` |
| `Nslm.getConnectionStatus()` | `1` |
| `Nslm.startRecording()` | `""` |
| any other method returning `Z` | `false` |
| any other method returning `I`, `F`, `D`, `J` | `0`, `0f`, `0d`, `0L` |
| any other method returning `Ljava/lang/String;` | `""` |
| any method returning `V` | empty body |

Every stub method is `public static` and logs once with `android.util.Log.i("LOAStub", ...)` so a surprising call shows up in logcat.

- [ ] **Step 1: Write the failing test `tests/test_gen_luaj_stubs.py`**

```python
from pathlib import Path

from client.gen_luaj_stubs import java_decl, render, scan

STOCK_SCRIPTS = Path(".stock/assets/scripts")


def test_java_decl_parses_a_jni_signature() -> None:
    assert java_decl("()V") == ([], "void")
    assert java_decl("(Ljava/lang/String;I)V") == (["String", "int"], "void")
    assert java_decl("()Ljava/lang/String;") == ([], "String")
    assert java_decl("()Z") == ([], "boolean")
    assert java_decl("(II)V") == (["int", "int"], "void")
    assert java_decl(
        "(ILjava/lang/String;Ljava/lang/String;Ljava/lang/String;"
        "Ljava/lang/String;Ljava/lang/String;I)V"
    ) == (["int", "String", "String", "String", "String", "String", "int"], "void")


def test_java_decl_rejects_the_malformed_stock_signature() -> None:
    # sdk/LuaSuperSDKManager.lua line 408 writes "(Ljava/lang/String)V": no
    # trailing semicolon, so the JNI lookup can never succeed. Skip, do not guess.
    assert java_decl("(Ljava/lang/String)V") is None


def test_scan_finds_every_class_lua_calls() -> None:
    found = scan(STOCK_SCRIPTS)
    assert set(found) >= {
        "com/uuzu/nslm/JavaSuperSDKManager",
        "com/uuzu/nslm/JavaComSDKManager",
        "com.uuzu.nslm.Nslm",
        "com/uuzu/nslm/Nslm",
    }
    sup = found["com/uuzu/nslm/JavaSuperSDKManager"]
    assert sup["lua_setCallBack"] == "(I)V"
    assert sup["checkVersion"] == "()V"
    assert sup["login"] == "()V"
    assert sup["setGameData"] == "(Ljava/lang/String;I)V"
    assert sup["getDeviceId"] == "()Ljava/lang/String;"
    assert sup["hasFloatWindow"] == "()Z"
    assert sup["openFloatWindow"] == "(II)V"
    assert sup["openEmbedUrl"] == "(Ljava/lang/String;IIII)V"
    assert sup["getPlatformConfigByName"] == (
        "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;"
    )
    assert found["com.uuzu.nslm.Nslm"]["getConnectionStatus"] == "()I"
    assert found["com.uuzu.nslm.Nslm"]["stopPlaying"] == "()V"


def test_render_emits_the_constant_device_id() -> None:
    src = render("com/uuzu/nslm/JavaSuperSDKManager", {"getDeviceId": "()Ljava/lang/String;"})
    assert "package com.uuzu.nslm;" in src
    assert "public class JavaSuperSDKManager" in src
    assert 'return "LOA-HOME-0001";' in src


def test_render_returns_the_default_for_config_lookups() -> None:
    src = render(
        "com/uuzu/nslm/JavaSuperSDKManager",
        {"getPlatformConfigByName": "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;"},
    )
    assert "return arg1;" in src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_gen_luaj_stubs.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'client.gen_luaj_stubs'`.

- [ ] **Step 3: Write `client/gen_luaj_stubs.py`**

```python
"""Generate Java stub classes from the luaj call sites in the stock Lua."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CALL = re.compile(
    r"luaj\.callStaticMethod\(\s*(?P<cls>\"[^\"]+\"|self\.\w+)\s*,"
    r"\s*\"(?P<method>\w+)\"\s*,.*?,\s*\"(?P<sig>[^\"]+)\"\s*\)",
    re.DOTALL,
)
CLASS_VAR = re.compile(r"(\w+Class)\s*=\s*\"([^\"]+)\"")

_PRIM = {"V": "void", "Z": "boolean", "B": "byte", "C": "char", "S": "short",
         "I": "int", "J": "long", "F": "float", "D": "double"}
_ZERO = {"void": None, "boolean": "false", "byte": "(byte) 0", "char": "'\0'",
         "short": "(short) 0", "int": "0", "long": "0L", "float": "0f",
         "double": "0d", "String": '""'}

DEVICE_ID = "LOA-HOME-0001"


def _parse_type(sig: str, i: int) -> tuple[str, int] | None:
    ch = sig[i]
    if ch in _PRIM:
        return _PRIM[ch], i + 1
    if ch == "L":
        end = sig.find(";", i)
        if end == -1:
            return None
        name = sig[i + 1 : end].replace("/", ".")
        return (name.rsplit(".", 1)[-1] if name.startswith("java.lang.") else name), end + 1
    return None


def java_decl(sig: str) -> tuple[list[str], str] | None:
    """JNI descriptor to (param java types, return java type), or None if malformed."""
    if not sig.startswith("("):
        return None
    close = sig.find(")")
    if close == -1:
        return None
    params: list[str] = []
    i = 1
    while i < close:
        parsed = _parse_type(sig, i)
        if parsed is None or parsed[1] > close:
            return None
        typ, i = parsed
        params.append(typ)
    ret = _parse_type(sig, close + 1)
    if ret is None or ret[1] != len(sig):
        return None
    return params, ret[0]


def scan(scripts_root: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for path in sorted(scripts_root.rglob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        local = {f"self.{k}": v for k, v in CLASS_VAR.findall(text)}
        for m in CALL.finditer(text):
            raw = m.group("cls")
            cls = raw.strip('"') if raw.startswith('"') else local.get(raw)
            if cls is None:
                continue
            sigs = found.setdefault(cls, {}).setdefault(m.group("method"), [])
            if m.group("sig") not in sigs:
                sigs.append(m.group("sig"))
    return found
```

`scan()` keeps **every** distinct sig per method as a list, because the stock Lua
overloads some methods (`JavaComSDKManager.getGameServers` is called as both `()V`
and `(Ljava/lang/String;)V`, `sendInvite` with one and with three strings).
`render()` emits one Java overload per sig; a malformed sig (`java_decl` returns
`None`) is skipped with a comment. Adjust the `render()` code and the Task 5 tests
below accordingly: wherever they index `found[cls][method]` as a single string,
treat it as a list and assert `"(Ljava/lang/String;)V" in found["com/uuzu/nslm/JavaComSDKManager"]["getGameServers"]`.

Second half of the same file:

```python
def _body(cls_simple: str, method: str, params: list[str], ret: str) -> str:
    if method == "getDeviceId" and ret == "String":
        return f'        return "{DEVICE_ID}";'
    if method == "getPlatformConfigByName" and len(params) == 2:
        return "        return arg1;"
    if cls_simple == "Nslm" and method == "getConnectionStatus":
        return "        return 1;"
    zero = _ZERO.get(ret, "null")
    return "" if ret == "void" else f"        return {zero};"


def render(class_name: str, methods: dict[str, str]) -> str:
    dotted = class_name.replace("/", ".")
    package, simple = dotted.rsplit(".", 1)
    out = [f"package {package};", "", "import android.util.Log;", "",
           f"/** Generated stub: see client/gen_luaj_stubs.py. Do not edit by hand. */",
           f"public class {simple} {{", ""]
    for method in sorted(methods):
        decl = java_decl(methods[method])
        if decl is None:
            out.append(f"    // skipped {method}: malformed JNI signature "
                       f"{methods[method]!r} in the stock Lua")
            out.append("")
            continue
        params, ret = decl
        args = ", ".join(f"{t} arg{i}" for i, t in enumerate(params))
        out.append(f"    public static {ret} {method}({args}) {{")
        out.append(f'        Log.i("LOAStub", "{simple}.{method}");')
        body = _body(simple, method, params, ret)
        if body:
            out.append(body)
        out.append("    }")
        out.append("")
    out.append("}")
    return "\n".join(out) + "\n"


DEST = Path("client/android/app/src/main/java")
WANTED = ("com/uuzu/nslm/JavaSuperSDKManager", "com/uuzu/nslm/JavaComSDKManager",
          "com/uuzu/nslm/Nslm")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", type=Path, default=Path(".stock/assets/scripts"))
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args(argv)

    found = scan(args.scripts)
    merged: dict[str, dict[str, str]] = {}
    for raw_cls, methods in found.items():
        key = raw_cls.replace(".", "/")
        merged.setdefault(key, {}).update(methods)

    for cls in WANTED:
        methods = merged.get(cls, {})
        path = args.dest / (cls + ".java")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(cls, methods), encoding="utf-8")
        print(f"{cls}: {len(methods)} methods -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the generator for real**

Run: `py -3.14 client/gen_luaj_stubs.py`
Expected three lines, one per class, with a non-zero method count for each. `com/uuzu/nslm/Nslm` merges the call sites from `MMTools.lua` (`getConnectionStatus`), `LuaSuperSDKManager.lua` (`openUrl`) and `MediaManager.lua` (`playVideo`, `startRecording`, `stopRecording`, `startPlaying`, `stopPlaying`), because the scan keys on the resolved class name and `MediaManager` writes it dotted while the SDK managers write it with slashes.

- [ ] **Step 5: Recover `comSdk.IComSdk` from the stock dex with jadx**

Run, in Git Bash from the repo root:

```bash
JADX="/c/Users/Stefan.Nasev/AppData/Local/Microsoft/WinGet/Packages/Skylot.jadx_Microsoft.Winget.Source_8wekyb3d8bbwe/lib/jadx-gui-1.5.6-all.jar"
JAVA="/c/Program Files/Android/Android Studio/jbr/bin/java.exe"
mkdir -p /c/tmp/loa-jadx
"$JAVA" -jar "$JADX" --no-res -d /c/tmp/loa-jadx .stock/classes.dex .stock/classes2.dex
find /c/tmp/loa-jadx -name "IComSdk.java"
cat /c/tmp/loa-jadx/sources/comSdk/IComSdk.java
```

Expected: a file declaring `package comSdk;` and 13 native methods: `onExitGameResult`, `onNativeBindResult`, `onNativeCheckVersionResult`, `onNativeFastLoginResult`, `onNativeGetConfigParam`, `onNativeGetGameData`, `onNativeInitResult`, `onNativeLoginPlatform`, `onNativeLoginResult`, `onNativeLogoutResult`, `onNativePayResult`, `onNativeStaticStringMethod`, `onNativeStaticVoidMethod`.

Copy the class declaration and those 13 declarations **verbatim** into `client/android/app/src/main/java/comSdk/IComSdk.java`, keeping every parameter type and the `native` keyword, and delete every method body jadx recovered that is not one of the 13 (the stub must declare the natives and nothing else). Add a one-line comment naming jadx and the date as the source. While jadx output is on disk, also `cat /c/tmp/loa-jadx/sources/org/cocos2dx/lib/Cocos2dxLuaJavaBridge.java` and diff its four native declarations against the file fetched in Task 4; if they differ in parameter types, the stock version wins, because that is what `libgame.so` was built against.

- [ ] **Step 6: Compile every Java source written so far**

```bash
JAVAC="/c/Program Files/Android/Android Studio/jbr/bin/javac.exe"
rm -rf /c/tmp/loa-javac && mkdir -p /c/tmp/loa-javac
"$JAVAC" -nowarn -proc:none -encoding UTF-8 \
  -classpath "C:/Users/Stefan.Nasev/AppData/Local/Android/Sdk/platforms/android-36/android.jar" \
  -d /c/tmp/loa-javac \
  $(find client/android/app/src/main/java -name "*.java")
```

Expected: exit 0, no `error:` lines.

- [ ] **Step 7: Run the Python test to verify it passes**

Run: `py -3.14 -m pytest -q tests/test_gen_luaj_stubs.py --basetemp=C:\tmp\pytest-loa`
Expected: `5 passed`.

- [ ] **Step 8: Commit**

```bash
git add client/gen_luaj_stubs.py tests/test_gen_luaj_stubs.py \
        client/android/app/src/main/java/comSdk \
        client/android/app/src/main/java/com/uuzu/nslm
git commit -m "feat(client): generated luaj stubs and the recovered comSdk.IComSdk natives"
```

---

### Task 6: Gradle project, manifest and GameActivity

**Files:**
- Create: `client/android/settings.gradle.kts`, `client/android/build.gradle.kts`, `client/android/gradle.properties`, `client/android/app/build.gradle.kts`, `client/android/app/src/main/AndroidManifest.xml`, `client/android/app/src/main/java/bg/stefan/loa/GameActivity.java`, `client/android/local.properties` (gitignored), `client/android/gradlew`, `client/android/gradlew.bat`, `client/android/gradle/wrapper/*` (generated)
- Test: `client\android\gradlew.bat :app:assembleDebug`

**Interfaces:**
- Consumes: the Java sources from Tasks 4 and 5.
- Produces: `bg.stefan.loa.GameActivity extends org.cocos2dx.lib.Cocos2dxActivity`, which loads `libgame.so`. The debug APK at this point has an empty `assets/` and no `jniLibs/`; it must still build. Task 7 fills both, Task 8 signs the release.

- [ ] **Step 1: Create the Gradle wrapper**

There is no `gradle` on PATH and winget has no Gradle package, but a full distribution is cached.

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
GRADLE="/c/Users/Stefan.Nasev/.gradle/wrapper/dists/gradle-9.3.1-bin/23ovyewtku6u96viwx3xl3oks/gradle-9.3.1/bin/gradle.bat"
mkdir -p client/android
cd client/android && "$GRADLE" wrapper --gradle-version 9.3.1
```

Expected: `BUILD SUCCESSFUL` and `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`, `gradle/wrapper/gradle-wrapper.properties` on disk. Every later Gradle command uses `client\android\gradlew.bat`.

- [ ] **Step 2: Write `client/android/local.properties` (gitignored)**

```properties
sdk.dir=C\:\Users\Stefan.Nasev\AppData\Local\Android\Sdk
```

- [ ] **Step 3: Write `client/android/settings.gradle.kts`**

```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "loa"
include(":app")
```

- [ ] **Step 4: Write `client/android/build.gradle.kts` and `gradle.properties`**

`build.gradle.kts`:

```kotlin
plugins {
    id("com.android.application") version "9.0.0" apply false
}
```

`gradle.properties`:

```properties
org.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8
android.useAndroidX=false
android.nonTransitiveRClass=true
```

Gradle 9.3 needs an AGP 9.x. If the sync fails because `com.android.application:9.0.0` cannot be resolved (no network, or that version does not exist yet), the fallback is exactly: re-run step 1 with `--gradle-version 8.13` and set the plugin version to `8.9.2`. Record whichever pair worked in `docs/dev-loop.md` in Task 9. Do not try a third combination.

- [ ] **Step 5: Write `client/android/app/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application")
}

android {
    namespace = "bg.stefan.loa"
    compileSdk = 36

    defaultConfig {
        applicationId = "bg.stefan.loa"
        minSdk = 21
        targetSdk = 33
        versionCode = 1
        versionName = "1.0.0.5"
        ndk {
            abiFilters += "armeabi-v7a"
        }
    }

    // 449 MB of res/ plus 17 MB of scripts/: compressing it doubles the
    // packaging time for no gain, the engine reads these through
    // CCFileUtils::getFileData anyway.
    androidResources {
        noCompress += listOf("db", "zip", "pb", "proto", "lua", "mp3", "ogg",
                             "png", "jpg", "plist", "csb", "ExportJson", "txt")
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true // android:extractNativeLibs="true"
        }
    }

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            isDebuggable = true
        }
        getByName("release") {
            isMinifyEnabled = false
            isDebuggable = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
    }
}
```

No dependencies block: the cocos2d-x 2.2.2 runtime and the stubs are plain `android.jar` code and pull in nothing.

- [ ] **Step 6: Write `client/android/app/src/main/AndroidManifest.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.VIBRATE" />

    <uses-feature android:glEsVersion="0x00020000" android:required="true" />

    <application
        android:allowBackup="false"
        android:debuggable="false"
        android:extractNativeLibs="true"
        android:hardwareAccelerated="true"
        android:label="LOA"
        android:largeHeap="true"
        tools:ignore="HardcodedDebugMode"
        xmlns:tools="http://schemas.android.com/tools">

        <activity
            android:name="bg.stefan.loa.GameActivity"
            android:configChanges="orientation|keyboardHidden|screenSize|smallestScreenSize|screenLayout|navigation"
            android:exported="true"
            android:launchMode="singleTask"
            android:screenOrientation="sensorLandscape"
            android:theme="@android:style/Theme.NoTitleBar.Fullscreen">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

`android:debuggable="false"` in the manifest plus `isDebuggable = true` on the debug build type is a conflict AGP resolves in favour of the build type, and it emits a lint warning that `lint { abortOnError = false }` tolerates. Keep it: the brief pins `android:debuggable=false` for the shipped artifact.

- [ ] **Step 7: Write `client/android/app/src/main/java/bg/stefan/loa/GameActivity.java`**

```java
package bg.stefan.loa;

import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;

import org.cocos2dx.lib.Cocos2dxActivity;

/** The only activity. Loads libgame.so and hands the screen to the engine. */
public class GameActivity extends Cocos2dxActivity {

    static {
        System.loadLibrary("game");
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }
}
```

If `Cocos2dxActivity` at the 2.2.2 tag declares `onCreate` differently (some revisions use `Cocos2dxActivity.onCreate(Bundle)` plus an abstract `Cocos2dxGLSurfaceView onCreateView()`), add the missing override by copying the body from the `Cocos2dxActivity` source fetched in Task 4. Do not invent an implementation; the compile error in step 8 names what is needed.

- [ ] **Step 8: Build the debug APK (this is the test for this task)**

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleDebug
```

Expected: `BUILD SUCCESSFUL` and `client/android/app/build/outputs/apk/debug/app-debug.apk` on disk. With empty `assets/` and no `jniLibs/` it should be a couple of hundred kilobytes. Any `error:` from javac names a missing override or a bad stub signature; fix that and re-run. Do not proceed with a failing build.

- [ ] **Step 9: Commit**

```bash
git add client/android/settings.gradle.kts client/android/build.gradle.kts \
        client/android/gradle.properties client/android/app/build.gradle.kts \
        client/android/app/src/main/AndroidManifest.xml \
        client/android/app/src/main/java/bg/stefan/loa/GameActivity.java \
        client/android/gradlew client/android/gradlew.bat client/android/gradle
git commit -m "feat(client): Gradle app shell, manifest and GameActivity"
```

---

### Task 7: Asset assembly and the Lua patches

**Files:**
- Create: `client/build_assets.py`
- Test: `tests/test_build_assets.py`

**Interfaces:**
- Consumes: `server.settings.load` from Task 1; `.stock/assets/{res,scripts,fonts}`; `.stock/lib/armeabi/libgame.so`.
- Produces:
  - `client.build_assets.PATCHES: tuple[Patch, ...]` where `Patch` is a frozen dataclass with `relpath: str`, `old: str`, `new: str`.
  - `client.build_assets.apply_patches(assets_root: Path, server_ip: str, username: str) -> list[str]`, returning the relpaths it changed. Raises `PatchNotFound(relpath, old)` when `old` is absent or appears more than once.
  - `client.build_assets.build(stock: Path, dest_assets: Path, dest_jnilibs: Path, server_ip: str, username: str) -> None`.
- The two placeholders `__LOA_SERVER_IP__` and `__LOA_USERNAME__` appear in the `new` strings and are substituted by `apply_patches`, so the patch table stays a plain data literal.

**Idempotence rule:** `build()` deletes `dest_assets` and re-copies from `.stock/` every time, then patches the fresh copy. `apply_patches` therefore always runs against unpatched text and can insist that `old` occurs exactly once. That is the whole idempotence design; there is no "already patched" branch to get wrong.

**The patch table, verbatim.** Every `old` string below was taken from the extracted tree on 20-10-2026 and its occurrence count in its file was checked with `grep -c`. `LuaSuperSDKManager.lua` is indented with tabs, the other three files with spaces; the Python literals below encode that exactly.

| # | file | occurrences of `old` | why |
|---|---|---|---|
| 1 | `scripts/main.lua` | 1 | `CONFIG_DEVELOP = 1` makes `LoginSocketData:checkServerVersion` skip the version compare and the DB MD5 check |
| 2 | `scripts/main.lua` | 1 | `CONFIG_UPGRADE_PROCESS = 0` makes `UpgradeScene:onEnterScene` short-circuit the hot update |
| 3 | `scripts/app/MyApp.lua` | 1 | opens the login scene without waiting on the dead CDN |
| 4 | `scripts/app/game/view/scenes/GameLoginScene.lua` | 1 | one static server entry instead of two HTTP round trips |
| 5 | `scripts/app/game/view/scenes/GameLoginScene.lua` | 1 | skips the login-notice HTTP |
| 6 | `scripts/app/game/view/scenes/GameLoginScene.lua` | 1 (two-line anchor; the one-line form occurs twice) | the privacy checkbox starts ticked, so the Start-game button works on the first tap |
| 7 | `scripts/sdk/LuaSuperSDKManager.lua` | 1 | fires `comSdk_checkVersionCallback_event` locally; without it `upgrade.lua` waits forever |
| 8 | `scripts/sdk/LuaSuperSDKManager.lua` | 1 | fires `comSdk_loginCallback_event` with the local account instead of calling the channel SDK |

- [ ] **Step 1: Write the failing test `tests/test_build_assets.py`**

```python
from pathlib import Path

import pytest

from client.build_assets import PATCHES, PatchNotFound, apply_patches

STOCK_SCRIPTS = Path(".stock/assets/scripts")
TOUCHED = (
    "scripts/main.lua",
    "scripts/app/MyApp.lua",
    "scripts/app/game/view/scenes/GameLoginScene.lua",
    "scripts/sdk/LuaSuperSDKManager.lua",
)


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A fixture copy of only the four Lua files the patches touch."""
    root = tmp_path / "assets"
    for rel in TOUCHED:
        src = STOCK_SCRIPTS / rel[len("scripts/") :]
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    return root


def test_every_old_string_occurs_exactly_once_in_the_stock_file(assets: Path) -> None:
    for patch in PATCHES:
        text = (assets / patch.relpath).read_text(encoding="utf-8")
        assert text.count(patch.old) == 1, patch.relpath + " :: " + patch.old[:60]


def test_apply_patches_rewrites_all_four_files(assets: Path) -> None:
    changed = apply_patches(assets, server_ip="192.168.1.50", username="stefan")
    assert sorted(set(changed)) == sorted(TOUCHED)

    main_lua = (assets / "scripts/main.lua").read_text(encoding="utf-8")
    assert "        CONFIG_DEVELOP = 1;\n" in main_lua
    assert "        CONFIG_UPGRADE_PROCESS = 0;\n" in main_lua

    scene = (assets / "scripts/app/game/view/scenes/GameLoginScene.lua").read_text(
        encoding="utf-8"
    )
    assert 'socket_domain = "192.168.1.50"' in scene
    assert "self:getRecommendServerIds();" not in scene
    assert "self:checkNotice();" not in scene
    assert "    self.privacyCheckBtnSelected = true\n" in scene

    sdk = (assets / "scripts/sdk/LuaSuperSDKManager.lua").read_text(encoding="utf-8")
    assert "comSdk_checkVersionCallback_event" in sdk
    assert 'uid = "stefan"' in sdk
    assert 'luaj.callStaticMethod(self.javaSDKClass, "login", {}, "()V");' not in sdk

    app = (assets / "scripts/app/MyApp.lua").read_text(encoding="utf-8")
    assert "scheduler.performWithDelayGlobal(function() self:initLogin(); end, 0.1);" in app


def test_no_placeholder_survives(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan")
    for rel in TOUCHED:
        text = (assets / rel).read_text(encoding="utf-8")
        assert "__LOA_SERVER_IP__" not in text
        assert "__LOA_USERNAME__" not in text


def test_applying_twice_raises_instead_of_double_patching(assets: Path) -> None:
    apply_patches(assets, server_ip="10.0.0.1", username="stefan")
    with pytest.raises(PatchNotFound):
        apply_patches(assets, server_ip="10.0.0.1", username="stefan")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_build_assets.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'client.build_assets'`.

- [ ] **Step 3: Write the head of `client/build_assets.py` with the patch table**

```python
"""Assemble client/android/app/src/main/assets from .stock, patching the Lua.

Run from the repo root:  py -3.14 client/build_assets.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from server.settings import load as load_settings

SCENE = "scripts/app/game/view/scenes/GameLoginScene.lua"
SDK = "scripts/sdk/LuaSuperSDKManager.lua"


class PatchNotFound(RuntimeError):
    def __init__(self, relpath: str, old: str, count: int) -> None:
        super().__init__(
            f"{relpath}: expected exactly one occurrence of {old[:70]!r}, found {count}"
        )
        self.relpath = relpath
        self.old = old
        self.count = count


@dataclass(frozen=True)
class Patch:
    relpath: str
    old: str
    new: str


_HOME_SERVER_LIST = (
    "    self:showServerList({\n"
    "        {\n"
    '            server        = "s1",\n'
    '            name          = "Home",\n'
    "            status        = 1,\n"
    '            server_id     = "1",\n'
    "            socket_port   = 8112,\n"
    '            socket_domain = "__LOA_SERVER_IP__"\n'
    "        }\n"
    "    });\n"
)

PATCHES: tuple[Patch, ...] = (
    # 1. main.lua: development mode, so the client skips the version string
    #    match and the DB MD5 check in LoginSocketData:checkServerVersion.
    Patch("scripts/main.lua",
          "        CONFIG_DEVELOP = 0;\n",
          "        CONFIG_DEVELOP = 1;\n"),
    # 2. main.lua: UpgradeScene:onEnterScene returns straight to the game.
    Patch("scripts/main.lua",
          "        CONFIG_UPGRADE_PROCESS = 1;\n",
          "        CONFIG_UPGRADE_PROCESS = 0;\n"),
    # 3. MyApp:getGmActivity: do not wait on the dead patch CDN for the
    #    festival id; open the login scene on the next scheduler tick so the
    #    rest of initGame (initSocket) still runs first.
    Patch("scripts/app/MyApp.lua",
          "    callHttpRequestGet(url,function(event)\n",
          "    g_roleData.festivalId = 0;\n"
          "    scheduler.performWithDelayGlobal(function() self:initLogin(); end, 0.1);\n"
          "    do return end\n"
          "    callHttpRequestGet(url,function(event)\n"),
    # 4. GameLoginScene:showLogin: one static server, no recommend/serverList HTTP.
    Patch(SCENE,
          "    self:getRecommendServerIds();\n",
          _HOME_SERVER_LIST),
    # 5. GameLoginScene:showServerList: skip the login-notice HTTP.
    Patch(SCENE,
          "            self:checkNotice();\n",
          "            self:startLogin();\n"),
    # 6. GameLoginScene: privacy checkbox starts ticked. The two-line anchor is
    #    needed because the one-line form also appears in the toggle handler.
    Patch(SCENE,
          "    self.privacyCheckBtnSelected = false\n"
          '    self.privacyCheckBtn = g_cocoGUI_creator:createButton(g_load_ui.."btn/ui_checkBox_bg.png")\n',
          "    self.privacyCheckBtnSelected = true\n"
          '    self.privacyCheckBtn = g_cocoGUI_creator:createButton(g_load_ui.."btn/ui_checkBox_bg1.png")\n'),
    # 7. LuaSuperSDKManager:checkVersion: fire the event upgrade.lua waits for.
    Patch(SDK,
          '\t\tluaj.callStaticMethod(self.javaSDKClass, "checkVersion", {}, "()V");\n',
          '\t\tuf_eventManager:dispatchEvent("comSdk_checkVersionCallback_event",nil,true,self, {""} )\n'),
    # 8. LuaSuperSDKManager:showLogin: local account instead of the channel SDK.
    Patch(SDK,
          '\t\tluaj.callStaticMethod(self.javaSDKClass, "login", {}, "()V");\n',
          '\t\tuf_eventManager:dispatchEvent("comSdk_loginCallback_event",nil,false,self,'
          ' {{userinfo = {uid = "__LOA_USERNAME__"}, accessToken = "local"}} )\n'),
)
```

- [ ] **Step 4: Write the rest of `client/build_assets.py`**

```python
COPY_DIRS = ("res", "scripts", "fonts")
COPY_FILES = ("debug.txt",)


def apply_patches(assets_root: Path, server_ip: str, username: str) -> list[str]:
    changed: list[str] = []
    for patch in PATCHES:
        path = assets_root / patch.relpath
        text = path.read_text(encoding="utf-8")
        count = text.count(patch.old)
        if count != 1:
            raise PatchNotFound(patch.relpath, patch.old, count)
        new = patch.new.replace("__LOA_SERVER_IP__", server_ip)
        new = new.replace("__LOA_USERNAME__", username)
        path.write_text(text.replace(patch.old, new, 1), encoding="utf-8", newline="")
        changed.append(patch.relpath)
    return changed


def build(
    stock: Path,
    dest_assets: Path,
    dest_jnilibs: Path,
    server_ip: str,
    username: str,
) -> None:
    src_assets = stock / "assets"
    if dest_assets.exists():
        shutil.rmtree(dest_assets)
    dest_assets.mkdir(parents=True)
    for name in COPY_DIRS:
        print(f"copying {name} ...", flush=True)
        shutil.copytree(src_assets / name, dest_assets / name)
    for name in COPY_FILES:
        src = src_assets / name
        if src.exists():
            shutil.copy2(src, dest_assets / name)

    changed = apply_patches(dest_assets, server_ip, username)
    for rel in changed:
        print(f"patched {rel}")

    (dest_jnilibs / "armeabi-v7a").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        stock / "lib/armeabi/libgame.so",
        dest_jnilibs / "armeabi-v7a/libgame.so",
    )
    print("copied libgame.so")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path("client/android/app/src/main/assets"),
    )
    parser.add_argument(
        "--jnilibs",
        type=Path,
        default=Path("client/android/app/src/main/jniLibs"),
    )
    args = parser.parse_args(argv)

    s = load_settings(args.settings)
    build(s.stock_dir, args.assets, args.jnilibs, s.host, s.username)
    print(f"assets ready, server list points at {s.host}:{s.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`newline=""` on `write_text` matters: the stock files use LF, and the default on Windows would turn every LF into CRLF, which changes `res/data/split` MD5s the client checks in other code paths and bloats the diff.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_build_assets.py --basetemp=C:\tmp\pytest-loa`
Expected: `4 passed`. A `PatchNotFound` in `test_every_old_string_occurs_exactly_once_in_the_stock_file` means the extracted tree does not match what this plan read on 20-10-2026: stop and report the file and string rather than loosening the anchor.

- [ ] **Step 6: Run the real assembly**

Before running, put the real LAN address in `settings.toml` under `[net] host`.

```bash
py -3.14 client/build_assets.py
du -sh client/android/app/src/main/assets
ls -l client/android/app/src/main/jniLibs/armeabi-v7a/libgame.so
grep -n "socket_domain" client/android/app/src/main/assets/scripts/app/game/view/scenes/GameLoginScene.lua
```

Expected: eight `patched ...` lines, `copied libgame.so`, roughly 474 MB of assets, `libgame.so` at 15,047,664 bytes, and the grep showing the real IP. The copy takes a few minutes.

- [ ] **Step 7: Commit**

```bash
git add client/build_assets.py tests/test_build_assets.py
git commit -m "feat(client): assemble assets and apply the eight Lua boot patches"
```

---

### Task 8: Release keystore and the signed APK

**Files:**
- Create: `client/make_keystore.py`
- Modify: `client/android/app/build.gradle.kts` (add the `signingConfigs` block and wire it to `release`)
- Test: `tests/test_make_keystore.py` plus a real `assembleRelease` and an `apksigner verify`

**Interfaces:**
- Consumes: Task 6 Gradle project, Task 7 assets and jniLibs.
- Produces: `C:\Users\Stefan.Nasev\.loa-keystore\loa.jks` and `C:\Users\Stefan.Nasev\.loa-keystore\password.txt`, both outside git; the signed artifact `client/android/app/build/outputs/apk/release/app-release.apk`, to be copied as `LOA-private-release.apk` for Stefan.
- `client.make_keystore.keytool_argv(keystore: Path, password: str, alias: str = "loa") -> list[str]` and `client.make_keystore.ensure(dir_: Path) -> tuple[Path, str]`, which generates the password and keystore only if they are absent and returns `(keystore_path, password)`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from client.make_keystore import ensure, keytool_argv


def test_keytool_argv_has_the_required_switches(tmp_path: Path) -> None:
    argv = keytool_argv(tmp_path / "loa.jks", "s3cret")
    assert argv[0].endswith("keytool.exe")
    joined = " ".join(argv)
    assert "-genkeypair" in joined
    assert "-keyalg RSA" in joined
    assert "-keysize 2048" in joined
    assert "-validity 10000" in joined
    assert "-alias loa" in joined
    assert "-storetype PKCS12" in joined
    assert "CN=LOA Private" in joined
    assert "s3cret" in joined


def test_ensure_is_a_noop_when_both_files_exist(tmp_path: Path) -> None:
    (tmp_path / "loa.jks").write_bytes(b"not-a-real-keystore")
    (tmp_path / "password.txt").write_text("already", encoding="utf-8")

    keystore, password = ensure(tmp_path)

    assert keystore == tmp_path / "loa.jks"
    assert password == "already"
    assert (tmp_path / "loa.jks").read_bytes() == b"not-a-real-keystore"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_make_keystore.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'client.make_keystore'`.

- [ ] **Step 3: Write `client/make_keystore.py`**

```python
"""Create the release keystore once, outside the repository."""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

KEYSTORE_DIR = Path.home() / ".loa-keystore"
KEYTOOL = Path("C:/Program Files/Android/Android Studio/jbr/bin/keytool.exe")
ALIAS = "loa"
DNAME = "CN=LOA Private, OU=Home, O=Stefan, L=Sofia, C=BG"


def keytool_argv(keystore: Path, password: str, alias: str = ALIAS) -> list[str]:
    return [
        str(KEYTOOL),
        "-genkeypair",
        "-keystore", str(keystore),
        "-storetype", "PKCS12",
        "-storepass", password,
        "-keypass", password,
        "-alias", alias,
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-dname", DNAME,
    ]


def ensure(dir_: Path = KEYSTORE_DIR) -> tuple[Path, str]:
    dir_.mkdir(parents=True, exist_ok=True)
    keystore = dir_ / "loa.jks"
    pw_file = dir_ / "password.txt"
    if keystore.exists() and pw_file.exists():
        return keystore, pw_file.read_text(encoding="utf-8").strip()

    password = secrets.token_urlsafe(24)
    pw_file.write_text(password + "\n", encoding="utf-8")
    subprocess.run(keytool_argv(keystore, password), check=True)
    return keystore, password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=KEYSTORE_DIR)
    args = parser.parse_args(argv)
    keystore, _ = ensure(args.dir)
    print(f"keystore ready at {keystore}; password in {args.dir / 'password.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`keytool` has no way to set POSIX 600 on Windows; the directory is outside the repo and outside any sync folder, which is the protection the brief asks for. Note in the commit message that `password.txt` is plain text in the user profile.

- [ ] **Step 4: Run it for real**

Run: `py -3.14 client/make_keystore.py`
Expected: `keystore ready at C:\Users\Stefan.Nasev\.loa-keystore\loa.jks; password in C:\Users\Stefan.Nasev\.loa-keystore\password.txt`. Running it twice must not regenerate the keystore.

- [ ] **Step 5: Wire the signing config into `client/android/app/build.gradle.kts`**

Insert this inside the existing `android { }` block, above `buildTypes`, and change the release build type to use it. Reading the password from the file keeps it out of git.

```kotlin
    signingConfigs {
        create("release") {
            val dir = File(System.getProperty("user.home"), ".loa-keystore")
            val pw = File(dir, "password.txt")
            storeFile = File(dir, "loa.jks")
            storePassword = if (pw.exists()) pw.readText().trim() else ""
            keyAlias = "loa"
            keyPassword = storePassword
        }
    }
```

and in `buildTypes`:

```kotlin
        getByName("release") {
            isMinifyEnabled = false
            isDebuggable = false
            signingConfig = signingConfigs.getByName("release")
        }
```

- [ ] **Step 6: Build and verify the signed release APK (the test for this task)**

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleRelease
ls -l app/build/outputs/apk/release/app-release.apk
APKSIGNER="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk/build-tools/36.0.0/apksigner.bat"
"$APKSIGNER" verify --print-certs app/build/outputs/apk/release/app-release.apk
```

Expected: `BUILD SUCCESSFUL`; an APK of roughly 450 to 500 MB; `apksigner` printing `Signer #1 certificate DN: CN=LOA Private, ...` with no `DOES NOT VERIFY`. Then copy the artifact to a name Stefan can recognise:

```bash
cp app/build/outputs/apk/release/app-release.apk /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
```

- [ ] **Step 7: Run the Python tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_make_keystore.py --basetemp=C:\tmp\pytest-loa`
Expected: `2 passed`.

- [ ] **Step 8: Commit**

```bash
git add client/make_keystore.py tests/test_make_keystore.py \
        client/android/app/build.gradle.kts
git commit -m "feat(client): release keystore script and signed assembleRelease"
```

---

### Task 9: Emulator check and the dev loop verdict

**Files:**
- Create: `docs/dev-loop.md`
- Test: not a unit test. Both outcomes pass; the deliverable is the written verdict.

**Interfaces:**
- Consumes: the signed APK from Task 8.
- Produces: `docs/dev-loop.md`, which every later task reads to decide whether a check runs on this PC or needs Stefan and the phone.

**What is already known (20-10-2026):** the local AVD `Medium_Phone_API_36.1` is an `android-36.1 google_apis_playstore x86_64` image and it ships `libndk_translation` with `ro.dalvik.vm.isa.arm=x86`, so 32-bit ARM translation is present. The expected outcome is therefore that the APK starts on the AVD and the Task 10 capture can be done entirely on this PC. The phone test stays the acceptance gate regardless.

**Bounded:** one install attempt, one launch attempt, 90 seconds of logcat. If it does not start, write the failure down and move on. Do not debug the emulator.

- [ ] **Step 1: Boot the AVD and install**

```bash
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/emulator/emulator.exe" -avd Medium_Phone_API_36.1 -no-snapshot-load &
"$SDK/platform-tools/adb.exe" wait-for-device
"$SDK/platform-tools/adb.exe" shell getprop ro.dalvik.vm.isa.arm
"$SDK/platform-tools/adb.exe" install -r /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
```

Expected: `x86` from `getprop`, then `Success`. An install that fails with `INSTALL_FAILED_NO_MATCHING_ABIS` is outcome B below.

- [ ] **Step 2: Launch and watch 90 seconds of logcat**

```bash
SDK="/c/Users/Stefan.Nasev/AppData/Local/Android/Sdk"
"$SDK/platform-tools/adb.exe" logcat -c
"$SDK/platform-tools/adb.exe" shell am start -n bg.stefan.loa/.GameActivity
"$SDK/platform-tools/adb.exe" logcat -d > /c/tmp/loa-emulator-logcat.txt &
sleep 90
"$SDK/platform-tools/adb.exe" logcat -d | grep -Ei "loa|cocos|lua|game|FATAL|dlopen" | head -80
"$SDK/platform-tools/adb.exe" exec-out screencap -p > /c/tmp/loa-emulator.png
```

Expected on success: the Lua `print` output from `main.lua` and `SDKConfig.lua` (lines such as `g_sdkManager: LuaSuperSDKManager`, `DEFAULT_OPID: 1`), then `LOAStub` lines from the generated stubs, and a screenshot showing the login scene. Expected on failure: a `FATAL EXCEPTION` with `UnsatisfiedLinkError`, or a `dlopen failed` naming `libgame.so`.

- [ ] **Step 3: Write `docs/dev-loop.md`**

Record, in this order and with real values:
1. Date `20-10-2026` in `dd-mm-yyyy`, AVD name, image, `ro.dalvik.vm.isa.arm`.
2. Outcome A or B, in one sentence.
3. The first 20 relevant logcat lines, in a fenced block.
4. The Gradle and AGP versions that actually built (from Task 6 step 4), because that pair is the one to reuse.
5. The loop that follows from the outcome. **Outcome A:** iterate on the AVD with `adb install -r` and run the Task 10 capture against `127.0.0.1` with `adb reverse tcp:8112 tcp:8112`, or against the LAN host directly since the AVD can reach it. **Outcome B:** the loop is Stefan installing the APK by hand and the capture runs on the LAN host with the phone on Wi-Fi; note that `adb` over USB may not be available and must not be assumed.
6. One line naming the exact command to rebuild and reinstall, so the next task does not have to rediscover it.

- [ ] **Step 4: Commit**

```bash
git add docs/dev-loop.md
git commit -m "docs(dev-loop): emulator ARM-translation check and the resulting dev loop"
```

---

### Task 10: Capture the real framing and write docs/protocol.md

**Files:**
- Create: `docs/protocol.md`, `captures/capture.log` (gitignored; paste the relevant bytes into the doc)
- Test: not a unit test. The deliverable is a `docs/protocol.md` whose header layout is read off real bytes.

**Interfaces:**
- Consumes: `tools/capture_server.py` from Task 3, the APK from Task 8, the verdict in `docs/dev-loop.md` from Task 9.
- Produces: `docs/protocol.md`, the only input Task 11 is allowed to use for the header constants.

**This task contains a human step. It is marked HUMAN below.** On outcome A from Task 9 the operator can be the implementer driving the AVD; on outcome B it must be Stefan with the phone.

**What makes the first packets readable.** The client opens two connections and the first payload on each is tiny and fully known:
- connection 1, `SERVER_SER`: `194_2001 QuerySrvInfoReq{server_id="1"}`, body `0a0131`, 3 bytes.
- connection 2, `SERVER_GAME`: `3_2005 ProtocolReq{issue="1.0.0.5"}`, body `0a07312e302e302e35`, 9 bytes, immediately followed by `3_2015 QuerySrvStateReq{}`, body empty, 0 bytes.

Connection 2 only happens after the server answers `194_2002`, which the capture tool never does, so expect connection 1 alone on the first run. That is enough: one frame whose body is exactly 3 bytes and whose service and cmd are exactly 194 and 2001 pins the header. `0x00c2` is 194 and `0x07d1` is 2001; look for those two 16-bit values and for a 3 or a 3-plus-header-size length field.

- [ ] **Step 1: Start the capture listener on the LAN address**

```bash
py -3.14 tools/capture_server.py --log captures/capture.log
```

Expected: `capture listening on <host>:8112, writing captures/capture.log`. Leave it running. If Windows Firewall prompts, allow private networks.

- [ ] **Step 2: HUMAN - open the app against the capture server**

Outcome A: `adb shell am start -n bg.stefan.loa/.GameActivity` on the AVD.
Outcome B: **Stefan installs `LOA-private-release.apk` on the S20 Ultra, opens it, ticks nothing, and taps the Start-game button** (the patched build pre-ticks the privacy box, so the button works on the first tap). The phone must be on the same Wi-Fi as the PC.

Expected in the capture log: a `conn#1 <phone-ip>:<port> OPEN` line, then one `recv` line with a small byte count, then a hex dump. The client gives up after about 7 seconds (`GameLoginScene.loginClickHdr2` schedules a 7-second timeout) and may retry; several identical frames are normal and useful.

- [ ] **Step 3: Derive the header from the bytes**

Work only from the dump. Answer these five questions and write each answer next to the bytes that prove it:
1. Total frame size minus 3 equals the header size.
2. Which offsets hold the value 194 and in which byte order.
3. Which offsets hold 2001 and in which byte order.
4. Is there a length field, and does it count the body only or the whole frame.
5. Is there a status or sequence field, and what value does the client send.

If the frame also contains a magic or checksum, write it down as an opaque constant with its observed value rather than guessing its meaning.

- [ ] **Step 4: Write `docs/protocol.md`**

The file must contain, in this order, with no hedging and no alternatives:

1. A `## Capture` section: date in `dd-mm-yyyy`, which device, and the raw hex dump of the first frame pasted verbatim from `captures/capture.log`.
2. A `## Header` section: a table with one row per field, columns `offset`, `size`, `type`, `endianness`, `meaning`, `observed value`. Plus one line stating `HEADER_SIZE = <n>`.
3. A `## Worked example` section: the captured frame split into header bytes and body bytes, with the body annotated as `0a 01 31` = protobuf field 1, wire type 2, length 1, `"1"`.
4. A `## Encode rule` section: one sentence per header field saying what the server writes there when it sends a response, including what it does with status and with any sequence or magic field.
5. A `## Open questions` section listing anything the capture did not settle, for example whether a sequence number must be echoed. If this section is not empty, Task 11 still proceeds using the observed values, and the open item is retested in Task 15.

If, against expectation, the client sends nothing at all, do not invent a header. Stop, record in `docs/protocol.md` under `## Capture` that no bytes arrived, and report that the APK did not reach the socket: that is a Task 6 to 9 problem (wrong IP in the server list, app crash before the login scene, firewall), and it is fixed there before this task is retried.

- [ ] **Step 5: Commit**

```bash
git add docs/protocol.md
git commit -m "docs(protocol): wire framing derived from a real client capture"
```

---

### Task 11: server/net/framing.py

**Files:**
- Create: `server/net/framing.py`
- Test: `tests/test_framing.py`

**Interfaces:**
- Consumes: `docs/protocol.md` from Task 10 and nothing else. **Every constant in this module (`HEADER_SIZE`, field offsets, struct format string, endianness, whether the length counts the body or the whole frame) is copied out of `docs/protocol.md`. Do not reuse any number written in this plan; the plan does not know them.**
- Produces:
  - `server.net.framing.HEADER_SIZE: int`
  - `server.net.framing.encode(service: int, cmd: int, status: int, body: bytes) -> bytes`
  - `server.net.framing.decode(buf: bytes) -> tuple[Frame, bytes] | None`, returning `None` when `buf` does not yet hold a whole frame, else the frame and the unconsumed remainder.
  - `server.net.framing.Frame`, a frozen dataclass with `service: int`, `cmd: int`, `status: int`, `body: bytes`.

- [ ] **Step 1: Write the failing test `tests/test_framing.py`**

The first test embeds the real captured bytes. Replace `CAPTURED_HEX` with the hex of the first frame from `docs/protocol.md`, section `## Capture`, as one unbroken lowercase hex string, and leave the assertions as they are: they are facts about that frame that hold whatever the header turns out to be.

```python
import pytest

from server.net.framing import HEADER_SIZE, Frame, decode, encode

# From docs/protocol.md, section "Capture". The frame the client sends first:
# 194_2001 QuerySrvInfoReq{server_id="1"}, body 0a0131.
CAPTURED_HEX = "REPLACE_ME_WITH_THE_CAPTURED_FIRST_FRAME"


def test_decode_the_real_first_frame() -> None:
    frame, rest = decode(bytes.fromhex(CAPTURED_HEX))
    assert rest == b""
    assert frame.service == 194
    assert frame.cmd == 2001
    assert frame.body == bytes.fromhex("0a0131")
    assert len(bytes.fromhex(CAPTURED_HEX)) == HEADER_SIZE + 3


def test_encode_round_trips_through_decode() -> None:
    raw = encode(3, 2002, 0, bytes.fromhex("08001001"))
    frame, rest = decode(raw)
    assert rest == b""
    assert frame == Frame(service=3, cmd=2002, status=0, body=bytes.fromhex("08001001"))


def test_encode_matches_the_captured_header_shape() -> None:
    captured = bytes.fromhex(CAPTURED_HEX)
    mine = encode(194, 2001, 0, bytes.fromhex("0a0131"))
    assert len(mine) == len(captured)
    # The client sends status 0 on a request, so the two frames must agree
    # byte for byte unless docs/protocol.md records a sequence or magic field
    # the server is expected to echo rather than originate.
    assert mine == captured
```

If that last assertion fails because `docs/protocol.md` records a field the client originates and the server must echo (a sequence number, say), weaken it to compare only the slices the doc marks as server-controlled, and add a note in the test naming the echoed field. Do not weaken it for any other reason.

Append the three framing-robustness tests, which do not depend on the layout:

```python
def test_decode_partial_returns_none() -> None:
    raw = encode(3, 2002, 0, bytes.fromhex("08001001"))
    for cut in range(1, len(raw)):
        assert decode(raw[:cut]) is None


def test_decode_two_frames_in_one_buffer() -> None:
    first = encode(3, 2006, 0, b"\x0a\x03abc")
    second = encode(3, 2016, 0, b"\x08\x00")
    frame, rest = decode(first + second)
    assert frame.cmd == 2006
    assert rest == second
    frame2, rest2 = decode(rest)
    assert frame2.cmd == 2016
    assert rest2 == b""


def test_decode_empty_body() -> None:
    raw = encode(5, 2318, 0, b"")
    frame, rest = decode(raw)
    assert frame.body == b""
    assert rest == b""
    assert len(raw) == HEADER_SIZE


@pytest.mark.parametrize("service,cmd", [(0, 0), (255, 65535), (194, 2001)])
def test_encode_accepts_the_full_field_range(service: int, cmd: int) -> None:
    frame, _ = decode(encode(service, cmd, 0, b"x"))
    assert (frame.service, frame.cmd) == (service, cmd)
```

If `docs/protocol.md` says the service field is narrower than 16 bits or the cmd field narrower than 16 bits, shrink the parametrize cases to the documented maxima and say so in a comment.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_framing.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'server.net.framing'`.

- [ ] **Step 3: Write `server/net/framing.py` from docs/protocol.md**

Skeleton. Fill the four marked places from the doc; change nothing else.

```python
"""Wire framing. Every constant here comes from docs/protocol.md.

Do not edit the numbers from memory or from a plan; re-read the capture.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# --- from docs/protocol.md, section "Header" -------------------------------
# 1. the struct format string for the header, including the byte-order prefix
_HEADER = struct.Struct("<REPLACE_ME")
HEADER_SIZE = _HEADER.size
# 2. whether the length field counts the body alone or header plus body
_LENGTH_INCLUDES_HEADER = False  # REPLACE_ME per the doc
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    service: int
    cmd: int
    status: int
    body: bytes


def encode(service: int, cmd: int, status: int, body: bytes) -> bytes:
    length = len(body) + (HEADER_SIZE if _LENGTH_INCLUDES_HEADER else 0)
    # 3. pack the fields in the documented order
    header = _HEADER.pack(length, service, cmd, status)  # REPLACE_ME order
    return header + body


def decode(buf: bytes) -> tuple[Frame, bytes] | None:
    if len(buf) < HEADER_SIZE:
        return None
    # 4. unpack in the same documented order
    length, service, cmd, status = _HEADER.unpack_from(buf, 0)  # REPLACE_ME order
    body_len = length - HEADER_SIZE if _LENGTH_INCLUDES_HEADER else length
    if body_len < 0:
        raise ValueError(f"negative body length {body_len} in frame header")
    end = HEADER_SIZE + body_len
    if len(buf) < end:
        return None
    return Frame(service, cmd, status, buf[HEADER_SIZE:end]), buf[end:]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_framing.py --basetemp=C:\tmp\pytest-loa`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/net/framing.py tests/test_framing.py
git commit -m "feat(server): wire framing implemented from the captured header"
```

---

### Task 12: Server core, dispatch and the unknown-message policy

**Files:**
- Create: `server/net/server.py`, `server/__main__.py`
- Test: `tests/test_server_core.py`

**Interfaces:**
- Consumes: `server.net.framing.encode/decode/Frame`, `server.net.registry.Registry`, `server.net.msgmap.res_key`, `server.settings.Settings`.
- Produces:
  - `server.net.server.Session` with `peer: str`, `player_id: int | None`, `data: dict[str, object]` for per-connection scratch, and the coroutine `send(service: int, cmd: int, msg) -> None`.
  - `server.net.server.Handler = Callable[[Session, object], object | None]`, where the argument is the decoded request message and the return value is the response message or `None` for "I answered myself or there is nothing to say".
  - `server.net.server.Server(registry, settings, handlers: dict[tuple[int, int], Handler])` with the coroutine `serve(ready: asyncio.Event | None = None) -> None`, the attribute `port: int` (the bound port, so a test can use port 0), and the method `sent_unknown: set[tuple[int, int]]` as an attribute for assertions.
  - `server.net.server.fill_required(msg) -> None`, which sets every unset `required` field of a message and, recursively, of its required sub-messages, to the proto2 default: `0`, `0.0`, `False`, `""`, `b""`, or the first enum value.
  - `server.net.server.stub_response(registry, service, cmd)`, returning the paired `*Res` instance with required fields filled and `status` set to 0 when that field exists, or `None` when there is no paired `*Res`.

**Policy, from spec section 3.1 and section 6:**
- Unknown `(service, cmd)`, meaning no registered handler: log once per id at INFO with the message name, answer with `stub_response` when it exists, send nothing when it does not. Record the id in `sent_unknown`.
- Handler raises: log the exception with `repr(req)` truncated to 500 characters, answer with the paired `*Res` carrying `status = 1` when that field exists, keep the connection open.
- A frame whose `(service, cmd)` is not in `msgIDMap.lua` at all: log once, send nothing, keep the connection.
- One `Session` per connection. Nothing is keyed by player across connections in Plan A.

- [ ] **Step 1: Write the failing test `tests/test_server_core.py`, part one**

```python
import asyncio
from pathlib import Path

import pytest

from server.net import framing
from server.net.registry import Registry
from server.net.server import Server, Session, fill_required, stub_response
from server.settings import Settings

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        stock_dir=STOCK,
        db_path=tmp_path / "player.db",
        host="127.0.0.1",
        port=0,
        username="stefan",
        guide_id=0,
    )


def test_fill_required_satisfies_proto2(reg: Registry) -> None:
    msg = reg.message_class("TounamentQuerySeasonStateRes")()
    fill_required(msg)
    assert msg.SerializeToString() == bytes.fromhex("08001000")


def test_fill_required_recurses_into_required_submessages(reg: Registry) -> None:
    msg = reg.message_class("ClientHero")()
    fill_required(msg)
    msg.SerializeToString()  # must not raise: unit and base_unit are required


def test_every_stub_res_serializes(reg: Registry) -> None:
    """Review Focus 1: no Res the dispatcher can emit may miss a required field."""
    burst = [(5, 2317), (5, 2801), (5, 2943), (153, 2001), (151, 2041),
             (3, 2005), (3, 2015), (3, 2001), (3, 2003), (3, 2009), (5, 2005)]
    for service, cmd in burst:
        res = stub_response(reg, service, cmd)
        assert res is not None, (service, cmd)
        res.SerializeToString()


def test_stub_response_is_none_without_a_paired_res(reg: Registry) -> None:
    for key in [(5, 2031), (5, 2039), (5, 2343), (148, 2093), (134, 2001), (150, 2059)]:
        assert stub_response(reg, *key) is None
    assert stub_response(reg, 5, 4004) is None
    assert stub_response(reg, 9999, 9999) is None
```

- [ ] **Step 2: Write part two of the same test file: a fake client over a real socket**

```python
class Client:
    """A minimal framed client. 127.0.0.1 only, never the name localhost."""

    def __init__(self, reader, writer) -> None:
        self.reader = reader
        self.writer = writer
        self.buf = b""

    @classmethod
    async def connect(cls, port: int) -> "Client":
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        return cls(reader, writer)

    async def send(self, service: int, cmd: int, body: bytes = b"") -> None:
        self.writer.write(framing.encode(service, cmd, 0, body))
        await self.writer.drain()

    async def recv(self, timeout: float = 5.0) -> framing.Frame:
        while True:
            decoded = framing.decode(self.buf)
            if decoded is not None:
                frame, self.buf = decoded
                return frame
            chunk = await asyncio.wait_for(self.reader.read(65536), timeout)
            if not chunk:
                raise AssertionError("server closed the connection")
            self.buf += chunk

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


async def _run_server(server: Server) -> tuple[asyncio.Task, int]:
    ready = asyncio.Event()
    task = asyncio.create_task(server.serve(ready))
    await asyncio.wait_for(ready.wait(), 5)
    return task, server.port


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_handler_is_dispatched_by_service_and_cmd(reg, settings) -> None:
    seen: list[tuple[int, str]] = []

    def on_protocol(session: Session, req):
        seen.append((1, req.issue))
        res = reg.message_class("ProtocolRes")(issue_required=req.issue + ":deadbeef")
        return res

    async def scenario() -> None:
        server = Server(reg, settings, {(3, 2005): on_protocol})
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (3, 2006)
        res = reg.message_class("ProtocolRes")()
        res.ParseFromString(frame.body)
        assert res.issue_required == "1.0.0.5:deadbeef"
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
    assert seen == [(1, "1.0.0.5")]


def test_unknown_id_gets_a_zero_filled_res(reg, settings) -> None:
    async def scenario() -> None:
        server = Server(reg, settings, {})
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(151, 2041)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (151, 2042)
        res = reg.message_class("TounamentQuerySeasonStateRes")()
        res.ParseFromString(frame.body)
        assert res.season_state == 0
        assert res.season_state_end_time == 0
        assert (151, 2041) in server.sent_unknown
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
```

- [ ] **Step 3: Write part three: the Review Focus tests**

```python
def test_unknown_id_without_res_sends_nothing(reg, settings) -> None:
    """Review Focus 5: a Req with no paired Res, and a Notify."""

    async def scenario() -> None:
        server = Server(reg, settings, {})
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(134, 2001)  # BugReportReq, no BugReportRes exists
        await client.send(5, 4004)    # BatchNotify
        await client.send(151, 2041)  # a known-answerable id, as a fence
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (151, 2042)
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_two_concurrent_sessions_are_independent(reg, settings) -> None:
    """Review Focus 3: the client opens SERVER_SER, then SERVER_GAME."""
    peers: list[str] = []

    def on_srvinfo(session: Session, req):
        peers.append(session.peer)
        session.data["server_id"] = req.server_id
        return reg.message_class("QuerySrvInfoRes")(
            district=1, addr=f"127.0.0.1:{session.bound_port}"
        )

    def on_protocol(session: Session, req):
        assert "server_id" not in session.data, "sessions must not share state"
        return reg.message_class("ProtocolRes")(issue_required=req.issue + ":x")

    async def scenario() -> None:
        server = Server(reg, settings, {(194, 2001): on_srvinfo, (3, 2005): on_protocol})
        task, port = await _run_server(server)
        a = await Client.connect(port)
        b = await Client.connect(port)
        await a.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await a.recv()).cmd == 2002
        await b.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        assert (await b.recv()).cmd == 2006
        # connection a is still alive and still has its own state
        await a.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await a.recv()).cmd == 2002
        await a.close()
        await b.close()
        await _stop(task)

    asyncio.run(scenario())
    assert len(peers) == 2


def test_handler_exception_answers_status_one_and_keeps_the_connection(reg, settings) -> None:
    def boom(session: Session, req):
        raise RuntimeError("deliberate")

    async def scenario() -> None:
        server = Server(reg, settings, {(5, 2005): boom})
        task, port = await _run_server(server)
        client = await Client.connect(port)
        await client.send(5, 2005)
        frame = await client.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.status == 1
        # still usable
        await client.send(151, 2041)
        assert (await client.recv()).cmd == 2042
        await client.close()
        await _stop(task)

    asyncio.run(scenario())


def test_two_frames_in_one_write_are_both_handled(reg, settings) -> None:
    async def scenario() -> None:
        server = Server(reg, settings, {})
        task, port = await _run_server(server)
        client = await Client.connect(port)
        client.writer.write(
            framing.encode(151, 2041, 0, b"") + framing.encode(153, 2001, 0, b"")
        )
        await client.writer.drain()
        first = await client.recv()
        second = await client.recv()
        assert {first.cmd, second.cmd} == {2042, 2002}
        await client.close()
        await _stop(task)

    asyncio.run(scenario())
```

A handler that returns `None` means "nothing to send"; the dispatcher must accept that and stay quiet.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `py -3.14 -m pytest -q tests/test_server_core.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'server.net.server'`.

- [ ] **Step 5: Write `server/net/server.py`**

```python
"""asyncio TCP server: one Session per connection, dispatch by (service, cmd)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from google.protobuf.descriptor import FieldDescriptor

from server.net import framing, msgmap
from server.net.registry import Registry
from server.settings import Settings

log = logging.getLogger("loa.net")

Handler = Callable[["Session", object], object | None]

_DEFAULTS = {
    FieldDescriptor.TYPE_DOUBLE: 0.0, FieldDescriptor.TYPE_FLOAT: 0.0,
    FieldDescriptor.TYPE_INT64: 0, FieldDescriptor.TYPE_UINT64: 0,
    FieldDescriptor.TYPE_INT32: 0, FieldDescriptor.TYPE_FIXED64: 0,
    FieldDescriptor.TYPE_FIXED32: 0, FieldDescriptor.TYPE_BOOL: False,
    FieldDescriptor.TYPE_STRING: "", FieldDescriptor.TYPE_BYTES: b"",
    FieldDescriptor.TYPE_UINT32: 0, FieldDescriptor.TYPE_SFIXED32: 0,
    FieldDescriptor.TYPE_SFIXED64: 0, FieldDescriptor.TYPE_SINT32: 0,
    FieldDescriptor.TYPE_SINT64: 0,
}


def fill_required(msg) -> None:
    """Set every unset proto2 required field, recursing into sub-messages."""
    for fd in msg.DESCRIPTOR.fields:
        # protobuf 7.x dropped FieldDescriptor.label; is_repeated and
        # is_required are the supported accessors. Verified on 7.36.2.
        if fd.is_repeated:
            continue
        if fd.type == FieldDescriptor.TYPE_MESSAGE:
            if fd.is_required or msg.HasField(fd.name):
                fill_required(getattr(msg, fd.name))
            continue
        if not fd.is_required or msg.HasField(fd.name):
            continue
        if fd.type == FieldDescriptor.TYPE_ENUM:
            setattr(msg, fd.name, fd.enum_type.values[0].number)
        else:
            setattr(msg, fd.name, _DEFAULTS[fd.type])


def _has_status(msg) -> bool:
    return any(fd.name == "status" for fd in msg.DESCRIPTOR.fields)


def stub_response(registry: Registry, service: int, cmd: int, status: int = 0):
    key = msgmap.res_key(registry.ids, service, cmd)
    if key is None:
        return None
    cls = registry.class_for(*key)
    if cls is None:
        return None
    msg = cls()
    fill_required(msg)
    if _has_status(msg):
        msg.status = status
    return msg
```

Second half of `server/net/server.py`:

```python
@dataclass
class Session:
    writer: asyncio.StreamWriter
    peer: str
    bound_port: int  # the port this server is really listening on (ephemeral in tests)
    player_id: int | None = None
    data: dict[str, object] = field(default_factory=dict)

    async def send(self, service: int, cmd: int, msg, status: int = 0) -> None:
        body = msg.SerializeToString()
        self.writer.write(framing.encode(service, cmd, status, body))
        await self.writer.drain()
        log.debug("sent %d_%d, %d bytes", service, cmd, len(body))


class Server:
    def __init__(
        self,
        registry: Registry,
        settings: Settings,
        handlers: dict[tuple[int, int], Handler],
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.handlers = handlers
        self.port = settings.port
        self.sent_unknown: set[tuple[int, int]] = set()
        self._logged_unknown: set[tuple[int, int]] = set()

    async def serve(self, ready: asyncio.Event | None = None) -> None:
        srv = await asyncio.start_server(
            self._on_client, self.settings.host, self.settings.port
        )
        self.port = srv.sockets[0].getsockname()[1]
        log.info("listening on %s:%d", self.settings.host, self.port)
        if ready is not None:
            ready.set()
        async with srv:
            await srv.serve_forever()

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = "%s:%d" % writer.get_extra_info("peername")[:2]
        session = Session(writer=writer, peer=peer, bound_port=self.port)
        log.info("connection from %s", peer)
        buf = b""
        try:
            while chunk := await reader.read(65536):
                buf += chunk
                while (decoded := framing.decode(buf)) is not None:
                    frame, buf = decoded
                    await self._on_frame(session, frame)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            log.info("connection closed %s", peer)
            writer.close()

    async def _on_frame(self, session: Session, frame: framing.Frame) -> None:
        key = (frame.service, frame.cmd)
        name = self.registry.name_for(*key)
        if name is None:
            if key not in self._logged_unknown:
                self._logged_unknown.add(key)
                log.warning("frame %d_%d is not in msgIDMap, ignoring", *key)
            return

        req_cls = self.registry.message_class(name)
        req = req_cls()
        req.ParseFromString(frame.body)

        handler = self.handlers.get(key)
        if handler is None:
            if key not in self._logged_unknown:
                self._logged_unknown.add(key)
                log.info("no handler for %d_%d %s, answering a zero stub", *key, name)
            res = stub_response(self.registry, *key)
            if res is not None:
                self.sent_unknown.add(key)
                await self._reply(session, key, res)
            return

        try:
            res = handler(session, req)
        except Exception:
            log.exception("handler %d_%d %s failed on %r", *key, name, str(req)[:500])
            res = stub_response(self.registry, *key, status=1)
        if res is not None:
            await self._reply(session, key, res)

    async def _reply(self, session: Session, key: tuple[int, int], res) -> None:
        res_key = msgmap.res_key(self.registry.ids, *key)
        if res_key is None:
            log.warning("handler for %d_%d produced a response but no Res id exists", *key)
            return
        fill_required(res)
        await session.send(res_key[0], res_key[1], res)
```

`_reply` calls `fill_required` on every outgoing message, including the ones real handlers build, so Review Focus 1 cannot bite even if a handler forgets a field.

- [ ] **Step 6: Write `server/__main__.py`**

Handlers from Tasks 13 and 14 do not exist yet, so this entry point starts with an empty handler map and is extended in those tasks. It must already run.

```python
"""py -3.14 -m server"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from server.net.registry import Registry
from server.net.server import Server
from server.settings import load


def build_handlers(registry: Registry, settings) -> dict:
    handlers: dict = {}
    return handlers


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )
    settings = load(Path("settings.toml"))
    registry = Registry.load(settings.stock_dir)
    server = Server(registry, settings, build_handlers(registry, settings))
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The log timestamp format is `%d-%m-%Y %H:%M:%S`, matching the house date rule for anything a human reads.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_server_core.py --basetemp=C:\tmp\pytest-loa`
Expected: `10 passed`.

- [ ] **Step 8: Start the server once by hand**

Run: `py -3.14 -m server`
Expected: a single line like `20-10-2026 21:14:03 INFO    loa.net listening on 192.168.1.50:8112`. Stop it with Ctrl+C.

- [ ] **Step 9: Commit**

```bash
git add server/net/server.py server/__main__.py tests/test_server_core.py
git commit -m "feat(server): asyncio core, per-connection sessions and the zero-stub policy"
```

---

### Task 13: Player database and the login module

**Files:**
- Create: `server/db.py`, `server/modules/__init__.py`, `server/modules/login.py`
- Modify: `server/__main__.py` (`build_handlers` registers the login handlers)
- Test: `tests/test_db.py`, `tests/test_login.py`

**Interfaces:**
- Consumes: `server.net.server.Session`, `server.net.registry.Registry`, `server.settings.Settings`.
- Produces:
  - `server.db.connect(path: Path) -> sqlite3.Connection` (creates the parent directory, sets `row_factory = sqlite3.Row`, runs the schema, returns the connection).
  - `server.db.SCHEMA: str`.
  - `server.db.find_player(conn, username: str) -> sqlite3.Row | None`.
  - `server.db.create_player(conn, username: str, nickname: str, guide_id: int) -> int`, returning the new player id, committing the insert.
  - `server.modules.login.STATUS_OK = 0` and `server.modules.login.STATUS_NO_ROLE = 327682`.
  - `server.modules.login.handlers(registry, settings, conn) -> dict[tuple[int, int], Handler]`, returning handlers for `(194, 2001)`, `(3, 2005)`, `(3, 2015)`, `(3, 2001)`, `(3, 2003)`, `(3, 2009)`.

**Decisions this task locks in, each traced to the Lua:**
- `QuerySrvInfoRes.district = 1` and `addr = f"{settings.host}:{session.bound_port}"` (the live bound port carried on the `Session`, so ephemeral test ports and the Task 15 fake client work). `GameLoginScene:querySrvInfoRes` splits `addr` on a colon and rejects a port of 0 or less, so both halves must be present.
- `ProtocolRes.issue_required = f"{req.issue}:0"`. `checkServerVersion` splits on a colon and reads `serverData[1]`, so the string must contain one; with `CONFIG_DEVELOP == 1` neither half is compared.
- `QuerySrvStateRes.state = 0` means "log in normally"; the inline Lua handler returns immediately on 0.
- First `LoginReq` for an unknown username answers `status = STATUS_NO_ROLE` (327682). That is what makes the client send `GameplayReq`, which is this game's character creation. Every later `LoginReq` answers `status = STATUS_OK`.
- Nothing on the wire carries a character name: `GameplayReq` has exactly the `LoginReq` field set (`username`, `token`, `datetime`, `reserved`, `device`, `IMEI`, `language`, `args`). The server therefore names the character after the account, `settings.username`.
- `time_zone_offset` is the PC offset from UTC in seconds; `g_timeManager:setTime(timestamp, offset)` consumes it.

- [ ] **Step 1: Write the failing test `tests/test_db.py`**

```python
from pathlib import Path

from server.db import connect, create_player, find_player


def test_connect_creates_the_file_and_the_tables(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "player.db"
    conn = connect(db)
    assert db.exists()
    names = {
        row["name"]
        for row in conn.execute("select name from sqlite_master where type='table'")
    }
    assert {"players", "heroes", "angels", "items"} <= names


def test_create_and_find_player(tmp_path: Path) -> None:
    conn = connect(tmp_path / "player.db")
    assert find_player(conn, "stefan") is None

    pid = create_player(conn, "stefan", "Stefan", guide_id=0)

    row = find_player(conn, "stefan")
    assert row is not None
    assert row["id"] == pid
    assert row["username"] == "stefan"
    assert row["nickname"] == "Stefan"
    assert row["level"] == 1
    assert row["guide_id"] == 0
    assert row["created_at"] is not None


def test_create_player_is_rejected_twice(tmp_path: Path) -> None:
    import sqlite3

    conn = connect(tmp_path / "player.db")
    create_player(conn, "stefan", "Stefan", guide_id=0)
    try:
        create_player(conn, "stefan", "Stefan", guide_id=0)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("username must be unique")
```

- [ ] **Step 2: Write `server/db.py`**

```python
"""The single-player SQLite store. No ORM, one connection, per-request commits."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    nickname   TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    gold       INTEGER NOT NULL DEFAULT 0,
    diamond    INTEGER NOT NULL DEFAULT 0,
    vip        INTEGER NOT NULL DEFAULT 0,
    energy     INTEGER NOT NULL DEFAULT 60,
    max_energy INTEGER NOT NULL DEFAULT 60,
    avatar     INTEGER NOT NULL DEFAULT 0,
    guide_id   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS heroes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry     INTEGER NOT NULL,
    star      INTEGER NOT NULL DEFAULT 1,
    level     INTEGER NOT NULL DEFAULT 1,
    xp        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS angels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    angel_entry INTEGER NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    exp         INTEGER NOT NULL DEFAULT 0,
    star        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry     INTEGER NOT NULL,
    amount    INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def find_player(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM players WHERE username = ?", (username,)
    ).fetchone()


def create_player(
    conn: sqlite3.Connection, username: str, nickname: str, guide_id: int
) -> int:
    cur = conn.execute(
        "INSERT INTO players (username, nickname, guide_id, created_at)"
        " VALUES (?, ?, ?, ?)",
        (username, nickname, guide_id, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)
```

`created_at` is stored ISO, per the house rule; anything that shows it to a human reformats to `dd-mm-yyyy`.

- [ ] **Step 3: Run the db test to verify it passes**

Run: `py -3.14 -m pytest -q tests/test_db.py --basetemp=C:\tmp\pytest-loa`
Expected: `3 passed`.

- [ ] **Step 4: Write the failing test `tests/test_login.py`**

```python
import asyncio
from pathlib import Path

import pytest

from server.db import connect, find_player
from server.net import framing
from server.net.registry import Registry
from server.net.server import Server
from server.modules import login
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)


def _login_body(reg: Registry, name: str, username: str = "stefan") -> bytes:
    return reg.message_class(name)(
        username=username, token="local", datetime=1,
        device="", IMEI="LOA-HOME-0001", args=["1"],
    ).SerializeToString()


def test_srvinfo_answers_host_and_port(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(reg, settings, login.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(194, 2001, bytes.fromhex("0a0131"))
        frame = await c.recv()
        res = reg.message_class("QuerySrvInfoRes")()
        res.ParseFromString(frame.body)
        assert res.district == 1
        assert res.addr == f"127.0.0.1:{port}"  # the live port, not settings.port
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_protocol_res_carries_a_colon(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(reg, settings, login.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        frame = await c.recv()
        res = reg.message_class("ProtocolRes")()
        res.ParseFromString(frame.body)
        assert res.issue_required == "1.0.0.5:0"
        assert len(res.issue_required.split(":")) == 2
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_first_login_says_no_role_then_gameplay_creates_the_player(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(reg, settings, login.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)

        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2002)
        res = reg.message_class("LoginRes")()
        res.ParseFromString(frame.body)
        assert res.status == login.STATUS_NO_ROLE
        assert find_player(conn, "stefan") is None

        await c.send(3, 2003, _login_body(reg, "GameplayReq"))
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2004)
        res2 = reg.message_class("GameplayRes")()
        res2.ParseFromString(frame.body)
        assert res2.status == login.STATUS_OK
        assert res2.timestamp > 0
        row = find_player(conn, "stefan")
        assert row is not None and row["nickname"] == "stefan"

        await c.send(3, 2001, _login_body(reg, "LoginReq"))
        frame = await c.recv()
        res3 = reg.message_class("LoginRes")()
        res3.ParseFromString(frame.body)
        assert res3.status == login.STATUS_OK
        assert res3.session > 0

        await c.close()
        await _stop(task)

    asyncio.run(scenario())
```

Append the remaining two tests to the same file:

```python
def test_srvinfo_on_first_socket_then_login_on_second(reg, settings) -> None:
    """Review Focus 3, with the real handlers: the client uses two sockets."""
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(reg, settings, login.handlers(reg, settings, conn))
        task, port = await _run_server(server)

        ser = await Client.connect(port)
        await ser.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await ser.recv()).cmd == 2002

        game = await Client.connect(port)
        await game.send(3, 2005, bytes.fromhex("0a07312e302e302e35"))
        assert (await game.recv()).cmd == 2006
        await game.send(3, 2015)
        assert (await game.recv()).cmd == 2016
        await game.send(3, 2001, _login_body(reg, "LoginReq"))
        assert (await game.recv()).cmd == 2002

        # the first socket is still open and still answering
        await ser.send(194, 2001, bytes.fromhex("0a0131"))
        assert (await ser.recv()).cmd == 2002

        await ser.close()
        await game.close()
        await _stop(task)

    asyncio.run(scenario())


def test_heartbeat_echoes_a_time(reg, settings) -> None:
    conn = connect(settings.db_path)

    async def scenario() -> None:
        server = Server(reg, settings, login.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)
        body = reg.message_class("HeartbeatReq")(time=1).SerializeToString()
        await c.send(3, 2009, body)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (3, 2010)
        res = reg.message_class("HeartbeatRes")()
        res.ParseFromString(frame.body)
        assert res.status == 0
        assert res.time > 1_700_000_000
        await c.close()
        await _stop(task)

    asyncio.run(scenario())
```

- [ ] **Step 5: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_login.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'server.modules'`.

- [ ] **Step 6: Write `server/modules/login.py` plus an empty `server/modules/__init__.py`**

```python
"""Login and session handlers: 194_2001, 3_2005, 3_2015, 3_2001, 3_2003, 3_2009."""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import datetime

from server import db
from server.net.registry import Registry
from server.net.server import Handler, Session
from server.settings import Settings

log = logging.getLogger("loa.login")

STATUS_OK = 0
# LoginSocketData:loginReceiveHdr branches on exactly this value to mean
# "this account has no character yet", and answers with GameplayReq.
STATUS_NO_ROLE = 327682


def _tz_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return 0 if offset is None else int(offset.total_seconds())


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection
) -> dict[tuple[int, int], Handler]:
    def srv_info(session: Session, req):
        log.info("server info asked for server_id=%r", req.server_id)
        # Live port from the Session, never settings.port: tests bind port 0 and
        # the fake client of Task 15 really dials this address.
        return registry.message_class("QuerySrvInfoRes")(
            district=1, addr=f"{settings.host}:{session.bound_port}"
        )

    def protocol(session: Session, req):
        # CONFIG_DEVELOP=1 makes the client ignore both halves; it only splits
        # on the colon, so the colon is the whole contract.
        return registry.message_class("ProtocolRes")(
            issue_required=f"{req.issue}:0"
        )

    def srv_state(session: Session, req):
        return registry.message_class("QuerySrvStateRes")(
            state=0, time_zone_offset=_tz_offset_seconds()
        )

    def _session_fields(cls_name: str, status: int, token: str):
        return registry.message_class(cls_name)(
            status=status,
            token=token,
            session=random.randrange(1, 2**31),
            time_zone_offset=_tz_offset_seconds(),
            timestamp=int(time.time()),
        )

    def login(session: Session, req):
        row = db.find_player(conn, req.username)
        if row is None:
            log.info("no character for %r yet, asking the client to create one",
                     req.username)
            return registry.message_class("LoginRes")(status=STATUS_NO_ROLE)
        session.player_id = int(row["id"])
        log.info("login ok, player id %d", session.player_id)
        return _session_fields("LoginRes", STATUS_OK, req.token)

    def gameplay(session: Session, req):
        row = db.find_player(conn, req.username)
        if row is None:
            player_id = db.create_player(
                conn, req.username, req.username, settings.guide_id
            )
            log.info("created character %r as player id %d", req.username, player_id)
        else:
            player_id = int(row["id"])
        session.player_id = player_id
        return _session_fields("GameplayRes", STATUS_OK, req.token)

    def heartbeat(session: Session, req):
        return registry.message_class("HeartbeatRes")(
            status=STATUS_OK, time=int(time.time())
        )

    return {
        (194, 2001): srv_info,
        (3, 2005): protocol,
        (3, 2015): srv_state,
        (3, 2001): login,
        (3, 2003): gameplay,
        (3, 2009): heartbeat,
    }
```

- [ ] **Step 7: Wire the handlers into `server/__main__.py`**

Replace `build_handlers` with:

```python
def build_handlers(registry: Registry, settings) -> dict:
    conn = db.connect(settings.db_path)
    handlers: dict = {}
    handlers.update(login.handlers(registry, settings, conn))
    return handlers
```

and add the imports `from server import db` and `from server.modules import login`.

- [ ] **Step 8: Run the whole suite to verify it passes**

Run: `py -3.14 -m pytest -q --basetemp=C:\tmp\pytest-loa`
Expected: every test passes, including the five new ones in `tests/test_login.py`.

- [ ] **Step 9: Commit**

```bash
git add server/db.py server/modules/__init__.py server/modules/login.py \
        server/__main__.py tests/test_db.py tests/test_login.py
git commit -m "feat(server): player database and the login module through character creation"
```

---

### Task 14: Player module, QueryMyselfRes and the main-city burst

**Files:**
- Create: `server/modules/player.py`
- Modify: `server/__main__.py` (register the player handlers)
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: `server.db`, `server.net.registry.Registry`, `server.net.server.Session/Handler/fill_required`, `server.settings.Settings`.
- Produces:
  - `server.modules.player.build_client_player(registry, row) -> ClientPlayer instance`
  - `server.modules.player.build_daily_stats(registry) -> ClientDailyStats instance`
  - `server.modules.player.build_query_myself_res(registry, row) -> QueryMyselfRes instance`
  - `server.modules.player.handlers(registry, settings, conn) -> dict[tuple[int, int], Handler]`, covering `(5, 2005)` and the five main-city ids `(5, 2317)`, `(5, 2801)`, `(5, 2943)`, `(153, 2001)`, `(151, 2041)`.

**What QueryMyselfRes must contain, and why**, from `RoleData:updateData` and `ClientPlayer:updateData`:
- `status = 0`.
- `player`: all 30 required `ClientPlayer` fields plus `nobility_level` and `nobility_exp`, which are optional in the proto but concatenated into a `print` by the Lua. Set `guild_id = 0` too, since `ClientPlayer:updateData` reads it with an `or 0` fallback and it costs nothing.
- `stats`: all 19 required `ClientDailyStats` fields. `deadline` is the end of today as a unix timestamp.
- `gold_trails`: present, even though both its fields are optional, because `RoleData:updateData` does `local gold_trails = d.gold_trails` and then `gold_trails.prize` without a nil check.
- `heroes`, `inventory`, `levels`, `angels`, `chapters`, `events`: empty repeated fields are fine; the Lua only takes their length.
- `guild = 0`, `mail_new = 0`.
- Everything else stays unset. The Lua guards each of those with `if d.x then`.

**The five main-city messages** are answered with the zero stub, but explicitly rather than through the unknown path, so the log stays quiet and the shapes are pinned by a test: `GameReadyRes` (no fields), `QueryMyPushMessageRes` (empty `message_list`), `QueryBtCardRecordRes` (empty `btCards`), `MagicStateRes` (`match_state = 99`, which `RPGGame` pre-sets as "off season"), `TounamentQuerySeasonStateRes` (`season_state = 0`, `season_state_end_time = 0`).

- [ ] **Step 1: Write the failing test `tests/test_player.py`**

```python
import asyncio
from pathlib import Path

import pytest

from server.db import connect, create_player, find_player
from server.net.registry import Registry
from server.net.server import Server
from server.modules import player
from server.settings import Settings
from tests.test_server_core import Client, _run_server, _stop

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)


@pytest.fixture
def row(settings: Settings):
    conn = connect(settings.db_path)
    create_player(conn, "stefan", "stefan", guide_id=0)
    return conn, find_player(conn, "stefan")


def test_query_myself_res_serializes(reg, row) -> None:
    """Review Focus 1."""
    _, r = row
    res = player.build_query_myself_res(reg, r)
    raw = res.SerializeToString()
    assert raw  # non-empty
    parsed = reg.message_class("QueryMyselfRes")()
    parsed.ParseFromString(raw)
    assert parsed.status == 0
    assert parsed.player.username == "stefan"
    assert parsed.player.nickname == "stefan"
    assert parsed.player.level == 1
    assert parsed.HasField("stats")
    assert parsed.HasField("gold_trails")
    assert len(parsed.heroes) == 0
    assert len(parsed.inventory) == 0
    assert len(parsed.levels) == 0


def test_player_sets_every_field_lua_concatenates(reg, row) -> None:
    """Review Focus 2: ClientPlayer:updateData concatenates nobility_level."""
    _, r = row
    p = player.build_client_player(reg, r)
    assert p.HasField("nobility_level")
    assert p.HasField("nobility_exp")
    assert p.HasField("guild_id")


def test_every_required_client_player_field_is_set(reg, row) -> None:
    _, r = row
    p = player.build_client_player(reg, r)
    missing = [
        fd.name for fd in p.DESCRIPTOR.fields if fd.is_required and not p.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in p.DESCRIPTOR.fields if fd.is_required]) == 30


def test_every_required_daily_stats_field_is_set(reg) -> None:
    s = player.build_daily_stats(reg)
    missing = [
        fd.name for fd in s.DESCRIPTOR.fields if fd.is_required and not s.HasField(fd.name)
    ]
    assert missing == []
    assert len([fd for fd in s.DESCRIPTOR.fields if fd.is_required]) == 19


def test_query_myself_over_a_socket(reg, settings, row) -> None:
    conn, _ = row

    async def scenario() -> None:
        server = Server(reg, settings, player.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)
        await c.send(5, 2005)
        frame = await c.recv()
        assert (frame.service, frame.cmd) == (5, 2006)
        res = reg.message_class("QueryMyselfRes")()
        res.ParseFromString(frame.body)
        assert res.player.username == "stefan"
        await c.close()
        await _stop(task)

    asyncio.run(scenario())


def test_the_five_main_city_messages_are_answered(reg, settings, row) -> None:
    conn, _ = row
    expected = {(5, 2317): 2318, (5, 2801): 2802, (5, 2943): 2944,
                (153, 2001): 2002, (151, 2041): 2042}

    async def scenario() -> None:
        server = Server(reg, settings, player.handlers(reg, settings, conn))
        task, port = await _run_server(server)
        c = await Client.connect(port)
        for (service, cmd), res_cmd in expected.items():
            await c.send(service, cmd)
            frame = await c.recv()
            assert (frame.service, frame.cmd) == (service, res_cmd)
        assert server.sent_unknown == set()
        await c.close()
        await _stop(task)

    asyncio.run(scenario())
```

Note on `test_query_myself_over_a_socket`: no login happened on that socket, so `session.player_id` is `None`. The handler therefore falls back to `db.find_player(conn, settings.username)`. That is not a shortcut for the test: this is a single-player server, the account name is fixed in `settings.toml`, and the client can legitimately send `5_2005` on a reconnect before any `3_2001`.

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_player.py --basetemp=C:\tmp\pytest-loa`
Expected: `ImportError: cannot import name 'player' from 'server.modules'`.

- [ ] **Step 3: Write `server/modules/player.py`**

```python
"""QueryMyselfRes and the main-city burst."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta

from server import db
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.player")

# RPGGame sets g_roleData.cspvpState = 99 as "off season" before it asks.
MAGIC_STATE_OFF_SEASON = 99


def _end_of_today() -> int:
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(tomorrow.timestamp())


def build_client_player(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("ClientPlayer")(
        id=int(row["id"]),
        username=row["username"],
        nickname=row["nickname"],
        level=int(row["level"]),
        xp=int(row["xp"]),
        gold=int(row["gold"]),
        diamond=int(row["diamond"]),
        vip=int(row["vip"]),
        energy=int(row["energy"]),
        max_energy=int(row["max_energy"]),
        avatar=int(row["avatar"]),
        guide_id=int(row["guide_id"]),
    )
    # Optional in the proto, but ClientPlayer:updateData concatenates these
    # into a print, so an absent value kills the Lua VM right after login.
    msg.nobility_level = 0
    msg.nobility_exp = 0
    msg.guild_id = 0
    # Everything else required gets the proto2 zero.
    fill_required(msg)
    return msg


def build_daily_stats(registry: Registry):
    msg = registry.message_class("ClientDailyStats")(deadline=_end_of_today())
    fill_required(msg)
    return msg


def build_query_myself_res(registry: Registry, row: sqlite3.Row):
    msg = registry.message_class("QueryMyselfRes")(status=0, guild=0, mail_new=0)
    msg.player.CopyFrom(build_client_player(registry, row))
    msg.stats.CopyFrom(build_daily_stats(registry))
    # RoleData:updateData reads d.gold_trails.prize with no nil check, so the
    # sub-message must be present even though both its fields are optional.
    msg.gold_trails.SetInParent()
    fill_required(msg)
    return msg


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection
) -> dict[tuple[int, int], Handler]:
    def _row(session: Session):
        if session.player_id is not None:
            return conn.execute(
                "SELECT * FROM players WHERE id = ?", (session.player_id,)
            ).fetchone()
        return db.find_player(conn, settings.username)

    def query_myself(session: Session, req):
        row = _row(session)
        if row is None:
            log.warning("5_2005 before any character exists, answering status 1")
            res = registry.message_class("QueryMyselfRes")(status=1)
            fill_required(res)
            return res
        session.player_id = int(row["id"])
        log.info("sending QueryMyselfRes for player id %d", session.player_id)
        return build_query_myself_res(registry, row)

    def game_ready(session: Session, req):
        return registry.message_class("GameReadyRes")()

    def push_messages(session: Session, req):
        return registry.message_class("QueryMyPushMessageRes")()

    def bt_cards(session: Session, req):
        return registry.message_class("QueryBtCardRecordRes")()

    def magic_state(session: Session, req):
        return registry.message_class("MagicStateRes")(
            match_state=MAGIC_STATE_OFF_SEASON
        )

    def season_state(session: Session, req):
        return registry.message_class("TounamentQuerySeasonStateRes")(
            season_state=0, season_state_end_time=0
        )

    return {
        (5, 2005): query_myself,
        (5, 2317): game_ready,
        (5, 2801): push_messages,
        (5, 2943): bt_cards,
        (153, 2001): magic_state,
        (151, 2041): season_state,
    }
```

- [ ] **Step 4: Register the player handlers in `server/__main__.py`**

```python
    handlers.update(player.handlers(registry, settings, conn))
```

after the `login.handlers(...)` line, and add `from server.modules import login, player`.

- [ ] **Step 5: Run the whole suite to verify it passes**

Run: `py -3.14 -m pytest -q --basetemp=C:\tmp\pytest-loa`
Expected: every test passes, including the six in `tests/test_player.py`.

- [ ] **Step 6: Commit**

```bash
git add server/modules/player.py server/__main__.py tests/test_player.py
git commit -m "feat(server): QueryMyselfRes for a fresh player and the main-city stubs"
```

---

### Task 15: End-to-end fake client, then the phone test

**Files:**
- Create: `tools/fake_client.py`
- Test: `tests/test_fake_client.py`, then the HUMAN phone pass that closes milestone 1

**Interfaces:**
- Consumes: everything above.
- Produces: `tools.fake_client.replay(host: str, port: int, username: str, registry: Registry) -> list[tuple[int, int]]`, the list of `(service, cmd)` pairs the server answered with, in order. A coroutine; `main()` wraps it in `asyncio.run`.

**The burst it replays**, exactly the order the real client uses:
1. socket A: `194_2001 QuerySrvInfoReq{server_id="1"}`, expect `194_2002`, read `addr`.
2. socket B to that `addr`: `3_2005 ProtocolReq{issue="1.0.0.5"}`, expect `3_2006`.
3. socket B: `3_2015 QuerySrvStateReq{}`, expect `3_2016`.
4. socket B: `3_2001 LoginReq{username, token="local", datetime, device, IMEI, args=["1"]}`, expect `3_2002`. If `status == 327682`, send `3_2003 GameplayReq` with the same body and expect `3_2004`.
5. socket B: `5_2005 QueryMyselfReq{}`, expect `5_2006`; parse it and assert `player.username` matches and `player.nobility_level` is present.
6. socket B: `5_2317`, `151_2041`, `5_2801`, `153_2001`, `5_2943`, expecting each paired `*Res`.
7. socket B: `3_2009 HeartbeatReq{time}`, expect `3_2010`.

- [ ] **Step 1: Write the failing test `tests/test_fake_client.py`**

```python
import asyncio
from pathlib import Path

import pytest

from server import db
from server.net.registry import Registry
from server.net.server import Server
from server.modules import login, player
from server.settings import Settings
from tests.test_server_core import _run_server, _stop
from tools.fake_client import replay

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


def test_full_login_burst_against_a_live_server(reg, tmp_path: Path) -> None:
    settings = Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)
    conn = db.connect(settings.db_path)

    async def scenario() -> list[tuple[int, int]]:
        handlers = {}
        handlers.update(login.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))
        server = Server(reg, settings, handlers)
        task, port = await _run_server(server)
        got = await replay("127.0.0.1", port, "stefan", reg)
        assert server.sent_unknown == set()
        await _stop(task)
        return got

    answered = asyncio.run(scenario())

    assert answered == [
        (194, 2002),
        (3, 2006),
        (3, 2016),
        (3, 2002),   # status 327682, no character yet
        (3, 2004),   # character created
        (5, 2006),
        (5, 2318),
        (151, 2042),
        (5, 2802),
        (153, 2002),
        (5, 2944),
        (3, 2010),
    ]
    assert db.find_player(conn, "stefan") is not None


def test_second_run_skips_character_creation(reg, tmp_path: Path) -> None:
    settings = Settings(STOCK, tmp_path / "player.db", "127.0.0.1", 0, "stefan", 0)
    conn = db.connect(settings.db_path)

    async def scenario() -> list[tuple[int, int]]:
        handlers = {}
        handlers.update(login.handlers(reg, settings, conn))
        handlers.update(player.handlers(reg, settings, conn))
        server = Server(reg, settings, handlers)
        task, port = await _run_server(server)
        await replay("127.0.0.1", port, "stefan", reg)
        got = await replay("127.0.0.1", port, "stefan", reg)
        await _stop(task)
        return got

    answered = asyncio.run(scenario())
    assert (3, 2004) not in answered
    assert answered[3] == (3, 2002)
    assert answered[4] == (5, 2006)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -3.14 -m pytest -q tests/test_fake_client.py --basetemp=C:\tmp\pytest-loa`
Expected: `ModuleNotFoundError: No module named 'tools.fake_client'`.

- [ ] **Step 3: Write `tools/fake_client.py`**

```python
"""Replay the client login burst against a running server.

py -3.14 tools/fake_client.py            # uses settings.toml
py -3.14 tools/fake_client.py --port 8112
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from server.net import framing
from server.net.registry import Registry
from server.settings import load as load_settings

GAME_VERSION = "1.0.0.5"


class Conn:
    def __init__(self, reader, writer) -> None:
        self.reader = reader
        self.writer = writer
        self.buf = b""

    @classmethod
    async def open(cls, host: str, port: int) -> "Conn":
        reader, writer = await asyncio.open_connection(host, port)
        return cls(reader, writer)

    async def call(self, service: int, cmd: int, body: bytes = b"") -> framing.Frame:
        self.writer.write(framing.encode(service, cmd, 0, body))
        await self.writer.drain()
        while True:
            decoded = framing.decode(self.buf)
            if decoded is not None:
                frame, self.buf = decoded
                return frame
            chunk = await asyncio.wait_for(self.reader.read(65536), 10)
            if not chunk:
                raise RuntimeError(f"server closed after {service}_{cmd}")
            self.buf += chunk

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


def _login_body(reg: Registry, name: str, username: str) -> bytes:
    return reg.message_class(name)(
        username=username,
        token="local",
        datetime=int(time.time()),
        device="",
        IMEI="LOA-HOME-0001",
        args=["1"],
    ).SerializeToString()


async def replay(
    host: str, port: int, username: str, reg: Registry
) -> list[tuple[int, int]]:
    answered: list[tuple[int, int]] = []

    ser = await Conn.open(host, port)
    req = reg.message_class("QuerySrvInfoReq")(server_id="1")
    frame = await ser.call(194, 2001, req.SerializeToString())
    answered.append((frame.service, frame.cmd))
    srv = reg.message_class("QuerySrvInfoRes")()
    srv.ParseFromString(frame.body)
    await ser.close()

    game_host, _, game_port = srv.addr.rpartition(":")
    game = await Conn.open(game_host, int(game_port))

    body = reg.message_class("ProtocolReq")(issue=GAME_VERSION).SerializeToString()
    frame = await game.call(3, 2005, body)
    answered.append((frame.service, frame.cmd))

    frame = await game.call(3, 2015)
    answered.append((frame.service, frame.cmd))

    frame = await game.call(3, 2001, _login_body(reg, "LoginReq", username))
    answered.append((frame.service, frame.cmd))
    res = reg.message_class("LoginRes")()
    res.ParseFromString(frame.body)
    if res.status == 327682:
        frame = await game.call(3, 2003, _login_body(reg, "GameplayReq", username))
        answered.append((frame.service, frame.cmd))

    frame = await game.call(5, 2005)
    answered.append((frame.service, frame.cmd))
    me = reg.message_class("QueryMyselfRes")()
    me.ParseFromString(frame.body)
    assert me.player.username == username, me.player.username
    assert me.player.HasField("nobility_level")
    assert me.HasField("gold_trails")
    print(f"player {me.player.nickname!r} level {me.player.level}")

    for service, cmd in ((5, 2317), (151, 2041), (5, 2801), (153, 2001), (5, 2943)):
        frame = await game.call(service, cmd)
        answered.append((frame.service, frame.cmd))

    hb = reg.message_class("HeartbeatReq")(time=int(time.time())).SerializeToString()
    frame = await game.call(3, 2009, hb)
    answered.append((frame.service, frame.cmd))

    await game.close()
    return answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    s = load_settings(args.settings)
    reg = Registry.load(s.stock_dir)
    answered = asyncio.run(
        replay(args.host or s.host, args.port or s.port, s.username, reg)
    )
    for service, cmd in answered:
        print(f"answered {service}_{cmd} {reg.name_for(service, cmd)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `py -3.14 -m pytest -q tests/test_fake_client.py --basetemp=C:\tmp\pytest-loa`
Expected: `2 passed`.

- [ ] **Step 5: Run the whole suite and the real server plus fake client**

```bash
py -3.14 -m pytest -q --basetemp=C:\tmp\pytest-loa
rm -f data/player.db
py -3.14 -m server &
sleep 2
py -3.14 tools/fake_client.py
```

Expected: a green suite; the server log showing the full burst with no traceback and no `no handler for` line; the fake client printing `player 'stefan' level 1` and twelve `answered ...` lines. Stop the server, then run the fake client once more against a fresh server to confirm the second login skips `3_2004`.

- [ ] **Step 6: Rebuild and re-sign the APK against the final `settings.toml`**

Only needed if `[net] host` changed since Task 7.

```bash
py -3.14 client/build_assets.py
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
cd client/android && ./gradlew.bat --no-daemon :app:assembleRelease
cp app/build/outputs/apk/release/app-release.apk /c/Users/Stefan.Nasev/Downloads/LOA-private-release.apk
```

- [ ] **Step 7: HUMAN acceptance pass, the milestone 1 gate**

Start the server and leave the log visible: `py -3.14 -m server`. Then hand Stefan this checklist, which is the brief definition of done, item for item. Do not claim milestone 1 before every box is ticked by him.

1. Install `LOA-private-release.apk` on the Galaxy S20 Ultra (the stock LOA app can be uninstalled; it is not needed again).
2. Open it. Expected: no permission prompts beyond what Android grants silently; the game reaches its login scene showing the server name `Home`.
3. Tap the Start-game button. Expected: the connecting tip appears and then clears.
4. Expected: a character is created and the main city appears with his character on screen.
5. The server log shows, in order: `connection from <phone-ip>`, `server info asked for server_id='1'`, a second `connection from <phone-ip>`, `no character for 'stefan' yet`, `created character 'stefan' as player id 1`, `sending QueryMyselfRes for player id 1`, and then heartbeats roughly every 30 seconds. No traceback anywhere.
6. Close and reopen the app. Expected: it goes straight to the main city, the log shows `login ok, player id 1` and no second `created character` line.

If the main city does not appear but the log shows `sending QueryMyselfRes`, the client got the data and failed afterwards: capture `adb logcat` if a cable is available, otherwise the first thing to try is `[player] guide_id = 14302` in `settings.toml` plus a server restart, since the new-player guide is the only scripted gate between `QueryMyselfRes` and the city. Record whatever happened and the fix in `docs/dev-loop.md`.

- [ ] **Step 8: Commit**

```bash
git add tools/fake_client.py tests/test_fake_client.py
git commit -m "feat(tools): fake client replaying the full login burst end to end"
```

---

## Risks

1. **The framing is unknown until Task 10.** Tasks 11 to 15 cannot be written against a guessed header, and this plan deliberately does not guess one. If the capture produces nothing, the blocker is in Tasks 6 to 9, not in the server. Mitigation: the first frame has a fully known 3-byte body and known service and cmd values, 194 and 2001, which over-determines the layout.
2. **The engine may want a Java behaviour we have not seen.** `libgame.so` is unstripped, so a crash log names the missing `FindClass` or method directly. Mitigation: `verify_natives` in Task 4 proves every exported native has a Java declaration before the first install, and Task 9 reads logcat.
3. **The new-player guide may block the main city.** `NewGuideManager` is driven entirely by `player.guide_id`, which the server controls through `settings.toml`. Mitigation: the verified value 14302 is in the config comment and in the Task 15 fallback.
4. **A 450 to 500 MB APK.** Install over USB or by file manager is slow and the Gradle packaging step takes minutes. Mitigation: `noCompress` on the bulk extensions. Not mitigated: the size itself, which is inherent to shipping the stock art.
5. **AGP and Gradle version pairing.** Gradle 9.3.1 is the only cached distribution and the matching AGP may not resolve offline. Mitigation: exactly one documented fallback pair, Gradle 8.13 with AGP 8.9.2, and a note in `docs/dev-loop.md`. No third attempt.
6. **QueryMyselfRes with empty `heroes` may surprise the main-city UI.** The Lua only reads the lengths, so the plan ships it empty. If the city renders but the hero lineup crashes, the smallest fix is seeding one row in `heroes` from `res/data/split/hero_info.db` and extending `build_query_myself_res`. That is a Plan B change, not a Plan A one: record it, do not improvise it mid-task.
7. **Two sockets, one of which the client abandons.** `MMNetManager:onConnectFailed` and `onConnectBroken` both return early for `SERVER_SER`, so the client tolerates the first socket dying. The server must not assume it stays open and must not tie player state to it. Covered by the Review Focus 3 tests.
8. **The `settings.toml` host must be the LAN address, not 127.0.0.1.** It is baked into the APK by Task 7 and returned in `QuerySrvInfoRes.addr` by Task 13, so a wrong value means a client that cannot connect and a capture that stays empty. Mitigation: Task 7 step 6 greps the generated Lua for the IP.

## Out of scope for Plan A

Do not add any of these, even if a test seems to want them:

- Campaign, `LevelIntoReq` and `LevelOutReq`, drops, XP. Milestone 2.
- Heroes, angels, gear, runes, summons. Milestone 3.
- Sign-in, shop, mail, dailies. Milestone 4.
- `server/config/`, the read-only accessors over `res/data/split/*.db`. Plan A opens exactly one config DB, `new_player_guide_info.db`, and only to document the value 14302.
- The English localisation pipeline under `localise/` and the `Language_en.lua` swap. Spec 3.3, Plan C.
- Arena, guild, cross-server, events, chat, friends, payments, anti-cheat, multi-account.
- Any public exposure of the server, TLS, or authentication beyond the fixed account name.
- An arm64 build, an app bundle, Play Store metadata, an app icon.
- Docker. The spec says it is not required for one player on a LAN.
- Reusing the stock dex, manifest or channel SDK native libraries. Only `libgame.so`, `assets/res`, `assets/scripts` and `assets/fonts` come out of the stock APK.
- `git push`.

## Self-review

**1. Spec coverage.** Spec 3.1 runtime, protocol layer, player state, the `login` and `player` modules, the unknown-message policy and the heartbeat are Tasks 2, 11, 12, 13, 14. Spec 3.1 `server/config/` is explicitly deferred, because Plan A needs no config lookups. Spec 3.2 is Tasks 4, 5, 6, 7, 8, and it covers all five Lua patch groups: group 1 server list is patch 4; group 2 SDK login is patches 7 and 8 plus the constant device id in the Task 5 stub; group 3 `CONFIG_DEVELOP` is patch 1, and `DEBUG_LOG` needs no patch because `config.lua` line 23 already sets it to 0 on every non-Windows target; group 4 hot-update skip is patch 2, with patch 3 covering the same class of blocker one layer up, which the spec did not know about because it did not know `getGmActivity` gates the login scene behind a dead CDN; group 5 English tables are Plan C. Spec 3.4 is Tasks 2, 3, 15. Spec 5.1 is Tasks 3, 10, 11. Spec 5.2 is Tasks 6 to 9. Spec 5.3 milestone 1 is Task 15. Spec 6 error handling is Task 12. Spec 7 testing runs through every task, with the scripted fake client in Task 15. Nothing in the in-scope sections is unclaimed.

**2. Placeholder scan.** Two placeholders remain on purpose, both flagged in their own task: `CAPTURED_HEX = "REPLACE_ME_WITH_THE_CAPTURED_FIRST_FRAME"` in `tests/test_framing.py` and four `REPLACE_ME` markers in `server/net/framing.py`. They exist because the header layout is genuinely unknown until Task 10 writes `docs/protocol.md`, and Task 11 states in its Interfaces block that the doc is the only permitted source. Every other step carries real code, a real command and a real expected output. No "add error handling", no "similar to Task N", no reference to an undefined type.

**3. Type consistency.** `Registry.message_class`, `name_for`, `class_for` and `ids` keep those names in Tasks 12, 13, 14, 15. `msgmap.res_key(ids, service, cmd)` keeps its signature in Tasks 2 and 12. `framing.encode(service, cmd, status, body)` and `framing.decode(buf)` returning either `None` or `(Frame, rest)` are used identically in Tasks 11, 12, 15 and in the test `Client` helper. `Session.peer`, `Session.player_id`, `Session.data` and `Session.send` match between Task 12 and every user. `fill_required` is defined in Task 12 and imported by Task 14. `handlers(registry, settings, conn)` has the same shape in `login` and `player`, which is what lets `build_handlers` call `.update()` on both. `db.connect`, `db.find_player` and `db.create_player` match between Tasks 13 and 14. The test helpers `Client`, `_run_server` and `_stop` are defined once, in `tests/test_server_core.py`, and imported from there by Tasks 13, 14 and 15.

**4. Review Focus coverage.** Item 1, required fields: `test_every_stub_res_serializes` and `test_query_myself_res_serializes`, backed by `_reply` calling `fill_required` on every outgoing message. Item 2, `nobility_level`: `test_player_sets_every_field_lua_concatenates`, plus an assertion inside `tools/fake_client.py`. Item 3, two connections: `test_two_concurrent_sessions_are_independent` and `test_srvinfo_on_first_socket_then_login_on_second`, and `fake_client.replay` opens two sockets for real. Item 4, partial and coalesced frames: `test_decode_partial_returns_none`, `test_decode_two_frames_in_one_buffer`, `test_two_frames_in_one_write_are_both_handled`. Item 5, ids with no paired Res: `test_stub_response_is_none_without_a_paired_res` and `test_unknown_id_without_res_sends_nothing`.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-20-plan-a-boot-to-main-city.md`. Please review the plan.

Recommended execution approach: **subagent-driven**. Fifteen tasks, several of which hand a named interface to the next one (the registry to the handlers, the captured header to the framing, the patch table to the APK build), and two of which gate on a human with a phone. A mistake that ships here costs a 500 MB rebuild and another round trip through Stefan, so a fresh reviewer per task earns its context. Tasks 2, 3 and 4 have disjoint file sets and can run in parallel after Task 1; Tasks 10 and 11 must be strictly sequential and must not start before Task 9 reports.
