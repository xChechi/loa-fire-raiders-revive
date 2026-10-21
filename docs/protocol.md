# Wire protocol

Everything here is read off bytes that a real client sent or accepted on 21-10-2026.
Nothing in this file is inferred from another game, from the proto names or from what a
header "usually" looks like. Where the capture did not settle a field it says so under
[Open questions](#open-questions) instead of guessing.

## Capture

| | |
|---|---|
| Date | 21-10-2026 |
| Device | AVD `LOA_API30` (`emulator-5554`), Android 11, our `bg.stefan.loa` build |
| Client address | `10.0.2.2:8112`, the emulator's alias for this PC |
| Listener | `tools/capture_server.py --host 0.0.0.0 --port 8112`, then the Task 10 probe |
| Logs | `captures/capture.log`, `.superpowers/sdd/2026-10-20-plan-a-boot-to-main-city/probe-*.log` (both gitignored) |

**Provenance.** The request bytes below were captured on 21-10-2026 during **Task 9c**,
by `tools/capture_server.py --host 0.0.0.0 --port 8112`, while that task was driving the
client to the login scene; they were written to
`.superpowers/sdd/2026-10-20-plan-a-boot-to-main-city/capture-9c.log` and are reused
here, copied verbatim to `captures/capture.log` for the record. Step 1 of the Task 10
brief — start the capture listener and tap Start-game — was **not re-run**, because that
capture already existed and the probe below re-observed the same 27 bytes six more times.
`--host 0.0.0.0` is deliberate in both tools: the `settings.toml` `[net] host`
`10.0.2.2` is a client-side alias that this PC cannot bind.

**Frame 1 — the client's first packet, `194_2001 QuerySrvInfoReq{server_id="1"}`.** 27
bytes, captured three times identically by `capture_server.py` in Task 9c and six more
times by the Task 10 probe, byte for byte the same every time:

```
00000000  03 00 00 00 00 00 01 00  c2 00 d1 07 00 00 00 00  |................|
00000010  00 00 00 00 00 00 00 00  0a 01 31                 |..........1|
```

Pinned by the client's own log line `发送的 service 为 = 194 cmd 为 = 2001` and by
`msgIDMap.lua` (`id_194_2001 = "QuerySrvInfoReq"`): `0x00c2` = 194 and `0x07d1` = 2001
appear at offsets 8 and 10, little-endian, and the 3-byte protobuf body is the whole
tail.

**Frames 2 and 3 — the second connection,** which only exists because the probe answered
frame 1 (see [Response layout](#response-layout-verified-live)). `3_2005
ProtocolReq{issue="1.0.0.5"}` and `3_2015 QuerySrvStateReq{}`, two separate TCP segments:

```
00000000  09 00 00 00 01 00 01 00  03 00 d5 07 00 00 00 00  |................|
00000010  00 00 00 00 00 00 00 00  0a 07 31 2e 30 2e 30 2e  |..........1.0.0.|
00000020  35                                                |5|

00000000  00 00 00 00 01 00 01 00  03 00 df 07 00 00 00 00  |................|
00000010  00 00 00 00 00 00 00 00                           |........|
```

These two carry the whole framing argument on their own: the second is 24 bytes with
nothing after it, so the header is exactly 24 bytes and the leading `00 00 00 00` is a
body length that counts the body alone.

## Header

`HEADER_SIZE = 24`

| offset | size | type | endianness | meaning | observed value |
|---|---|---|---|---|---|
| 0 | 4 | uint32 | little | body length, **body only**, header excluded | `3` (`194_2001`), `9` (`3_2005`), `0` (`3_2015`), `17` (our `194_2002`) |
| 4 | 2 | uint16 | little | district | `0` on the first connection, then whatever `QuerySrvInfoRes.district` said: `1` and `7` in two probe runs |
| 6 | 2 | uint16 | little | **unknown**, constant `1` | `1` in every frame seen in either direction |
| 8 | 2 | uint16 | little | service | `194`, `3` |
| 10 | 2 | uint16 | little | cmd | `2001`, `2002`, `2005`, `2015` |
| 12 | 12 | bytes | — | **unknown**, always zero; ignored on the way in | twelve `00` in every frame |

**Why offset 4 is the district and not a flag.** The client calls
`MMMsgProcessHandler:getInstance():setCurDistrict(0)` before it opens the first
connection (`GameLoginScene.lua:1098`) and `setCurDistrict(toint(rs.district))` when the
server's `194_2002` arrives (`GameLoginScene.lua:1154`). The probe put `district = 1` in
the response body and every later client frame carried `01 00` at offset 4; a second run
put `district = 7` in the body and every later frame carried `07 00`. The value is the
one the server chose, at the offset that was `00 00` before the server chose it.

**Why the length field counts the body only.** `3_2015 QuerySrvStateReq` has an empty
body, and its frame is 24 bytes with `00 00 00 00` in the length field. A frame length
would have read `24`.

**Why offsets 12 to 23 are ignored on the way in.** Three probe runs put the non-zero
word `02 00 05 00` at offset 12, then 16, then 20, in a response that was otherwise
identical. In all three the client parsed the response, logged
`获取服务器群组信息成功` and opened the second connection — so no 4-byte window inside
those twelve bytes changes how an incoming frame is accepted. The server still writes
zeros there, because that is the only value the client has ever been observed to send.

## Worked example

The captured `194_2001` frame split at `HEADER_SIZE`:

```
header  03 00 00 00   00 00   01 00   c2 00   d1 07   00 00 00 00 00 00 00 00 00 00 00 00
        |length=3 |   |dist|  |  1  |  |194 |  |2001|  |------------ 12 zero bytes --------|
body    0a 01 31
```

Body: `0a` = field 1, wire type 2 (length-delimited); `01` = one byte of payload; `31` =
`"1"`. That is `QuerySrvInfoReq{server_id = "1"}`, which is what the patched one-entry
server list in the APK holds.

## Response layout verified live

The response header is the **mirror of the request header**: same 24 bytes, same field
order, same endianness, with the server's own service, cmd, body length and district.
Nothing about the request direction had to be changed for the client to accept it.

Verified on 21-10-2026 by `probe_srvinfo.py`, which answered the captured `194_2001` with
`194_2002 QuerySrvInfoRes{district = 1, addr = "10.0.2.2:8112"}` — body serialized from
the client's own descriptor set through `server.net.registry`, not hand-typed. The 41
bytes that the client accepted, verbatim:

```
00000000  11 00 00 00 00 00 01 00  c2 00 d2 07 00 00 00 00  |................|
00000010  00 00 00 00 00 00 00 00  08 01 12 0d 31 30 2e 30  |............10.0|
00000020  2e 32 2e 32 3a 38 31 31  32                       |.2.2:8112|
```

`0x11` = 17 = body length; `00 00` district (the server's first frame is still district
0); `01 00` the constant; `0x00c2` = 194; `0x07d2` = 2002; twelve zeros; then the
17-byte body `08 01 12 0d 31 30 ...` = `{district: 1, addr: "10.0.2.2:8112"}`.

What the client did with it, from logcat, 35 ms after the bytes went out:

```
[1097.9774] -     "addr"     = "10.0.2.2:8112"
[1097.9774] -     "district" = 1
[1097.9778] [MMMsgDispatcher:onNetMessage] key=194_2002, msg=table: 0xb78caef8, len=17
[1097.9779] 获取服务器群组信息成功                     <- querySrvInfoRes passed rs.status == 0
[1097.9818] socket 准备连接的真实地址为 .. 10.0.2.2 :8112
[1098.0115] socket 连接成功                           <- second connection up
[1098.0176] 发送的 service 为 = 3 cmd 为 = 2005        <- ProtocolReq on it
[1098.0184] 发送的 service 为 = 3 cmd 为 = 2015
```

This layout was the **first one tried and it worked**; no variant was needed to get the
client past `194_2002`. Four further runs varied one header field each, purely to find
out which bytes the client actually reads — results in the table above and under
[Open questions](#open-questions). Every attempt is in the table below.

| run | header bytes 0..23 of the response | client reaction |
|---|---|---|
| mirror | `11000000 0000 0100 c200 d207 00×12` | accepted, second connection opened, `3_2005` sent |
| status@12 | `11000000 0000 0100 c200 d207 02000500 00×8` | accepted, identical behaviour |
| status@16 | `11000000 0000 0100 c200 d207 00000000 02000500 00000000` | accepted, identical behaviour |
| status@20 | `11000000 0000 0100 c200 d207 00×8 02000500` | accepted, identical behaviour |
| district@4 | `11000000 0100 0100 c200 d207 00×12` | accepted, identical behaviour. Proves nothing about where the client takes its district from — the body said `1` here too — only that a non-zero inbound offset 4 is not rejected |
| body district=7 | `11000000 0000 0100 c200 d207 00×12`, body `{district: 7, addr: ...}` | accepted; every later client frame carried `07 00` at offset 4 |

The run that proves the district comes from the **body** is `mirror`: its header carried
`00 00` at offset 4 while its body said `district = 1`, and the client's later frames
carried `01 00`. `body district=7` repeats that with a second value. The `district@4` run
only shows that the inbound offset-4 value is not validated.

## The second connection

The frame the server answers on the first connection is a redirect, not a session. The
client keeps the first socket open, reads `addr` out of `QuerySrvInfoRes`, and opens a
**second** TCP connection to that address — in this build the very same host and port —
and everything after that is the game session: `3_2005 ProtocolReq{issue="1.0.0.5"}`,
then `3_2015 QuerySrvStateReq{}`, then the login exchange that `LoginSocketData` drives,
all on connection 2 (`connIndex` 1, `SERVER_GAME`), while connection 1 (`connIndex` 999,
`SERVER_SER`) sits idle and is never written to again. A server that answers only the
first connection gets the client as far as the "正在获取服务器数据请稍候" loading screen
and no further.

## Encode rule

When the server sends a response it writes, in this order:

- **offset 0, length:** the byte count of the serialized protobuf body, little-endian
  uint32, the header's own 24 bytes excluded. Zero for a message with an empty body.
- **offset 4, district:** the district this connection belongs to, little-endian uint16.
  The client takes its district from the body of `194_2002`, not from this field, so the
  server writes `0` until it has told the client a district, and that district afterwards.
- **offset 6, the constant:** `1`, little-endian uint16. This is what the client puts
  there in every frame and what it accepted in every response; the server mirrors it.
- **offset 8, service** and **offset 10, cmd:** the `(service, cmd)` of the message being
  sent, little-endian uint16 each, as keyed in `msgIDMap.lua` — for a reply to a `Req`,
  the paired `Res`, which is `cmd + 1` (`msgmap.res_key`).
- **offsets 12 to 23:** twelve zero bytes.
- **no status field:** the server writes nothing for status. It cannot: no header byte it
  is able to set reaches the client's `status`, see below. Every response the client
  accepted came out as `status == 0`, which is what every success path needs.
- **no sequence number, no magic, no checksum:** nothing in any captured frame varies in
  a way that would hold one, and the client accepted responses whose every byte outside
  length / service / cmd was either mirrored or deliberately wrong.

Then the serialized body, immediately after byte 23, with no padding and no terminator.

## Contract for `server/net/framing.py`

Controller ruling for Task 11, reconciling the plan's API with the header this capture
found. Verbatim:

> The header has no status slot; Task 11 keeps the planned API for interface stability
> with Tasks 12-15: `Frame(service, cmd, status, body)` where decode sets `status = 0`
> always and additionally exposes `district` (the u16 at offset 4) as a Frame field;
> `encode(service, cmd, status, body, district=0)` ignores `status` on the wire, writes
> the 24-byte header as documented (length = body length only, LE u32; offset 4 =
> district; offset 6 = constant 1; offsets 8/10 = service/cmd LE u16; 12 zero bytes).
> Status semantics live in the protobuf body (`*Res.status`), which Task 13 sets.
> HEADER_SIZE = 24.

## Open questions

1. **Where `status` comes from — the important one.** Every message the client dispatches
   carries a `status` that Lua reads as `rs.status` and gates on
   (`GameLoginScene:querySrvInfoRes` returns early unless it is `0`; `LoginSocketData`
   compares it against `327682` to mean "this account has no character"). It is produced
   by the native `MMMsgProcessHandler`, not by Lua, and it is not a body field. Four
   probe runs put a non-zero value at every 4-byte window of offsets 12 to 23 and at
   offset 4, and the client's `status` stayed `0` in all of them. So no header offset the
   server can currently set produces a non-zero status, and the offset that does is
   **unknown**. Harmless for every success path. It becomes a blocker the first time the
   server needs to *signal an error* to the client, `327682` included — that is the
   moment to disassemble `libgame.so`'s `MMMsgProcessHandler` rather than probe further.
   How the server code lives with this is settled above in
   [Contract for `server/net/framing.py`](#contract-for-servernetframingpy): `status`
   stays in the API, never reaches the wire, and the error semantics the handlers need
   go in the protobuf body's own `status` field.
2. **The constant `1` at offset 6.** Present in every frame in both directions and
   accepted by the client in every response, but never sent as anything other than `1`,
   so what it means — protocol version, compression flag, connection kind — is unknown.
   The server mirrors `1`.
3. **The twelve zero bytes at offsets 12 to 23.** Proven ignored on the way in (three
   probe runs), never non-zero on the way out. Their meaning is unknown; they may well be
   a field the stock server fills and this client never reads.
4. **Message coalescing and partial reads.** The client sent `3_2005` and `3_2015` as two
   separate TCP segments and read our single 41-byte response in one piece. Whether it
   handles two frames in one segment, or one frame split across segments, is untested.
   The server should still frame strictly by the length field rather than assume one
   frame per `recv`.
5. **Anything beyond `194_2002`.** The probe never answered `3_2005`, so nothing is known
   yet about what the client expects on the game connection beyond the fact that it sends
   those two messages and then waits.

## Client behaviour when the server says nothing

`GameLoginScene:loginClickHdr2` schedules a 7-second timeout before it connects
(`GameLoginScene.lua:1071-1092`). With a listener that captures and never replies — Task
9c, `tools/capture_server.py` — the client connects, sends `194_2001`, and 7 seconds
later logs `手动断开服务器`, floats the yellow banner `登录超时，请稍候再试!` ("login
timed out, try again later"), drops both sockets and re-enables the Start-game button, so
the next tap retries cleanly.

That timeout covers the `194_2002` exchange only: `querySrvInfoRes` cancels it as its
first act. On the second connection there is no equivalent deadline — with the probe's
sockets closed under it, the client sat on the "正在获取服务器数据请稍候" loading screen
indefinitely rather than reporting an error.
