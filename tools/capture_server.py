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
        hexpart = f"{left:<23}  {right:<23}"
        ascii_part = "".join(chr(b) if b in _PRINTABLE else "." for b in chunk)
        lines.append(f"{offset + start:08x}  {hexpart}  |{ascii_part}|")
    return "\n".join(lines)


async def serve(
    host: str, port: int, log_path: Path, ready: asyncio.Event | None = None
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    conn_ids = count(1)
    log = log_path.open("a", encoding="utf-8", buffering=1)
    handlers: set[asyncio.Task[None]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn_id = next(conn_ids)
        peer = "%s:%d" % writer.get_extra_info("peername")[:2]
        offset = 0
        handlers.add(asyncio.current_task())
        _emit(log, f"conn#{conn_id} {peer} OPEN")
        try:
            while data := await reader.read(65536):
                _emit(log, f"conn#{conn_id} {peer} recv {len(data)} bytes")
                _emit_raw(log, hexdump(data, offset))
                offset += len(data)
        finally:
            handlers.discard(asyncio.current_task())
            _emit(log, f"conn#{conn_id} {peer} CLOSE after {offset} bytes")
            writer.close()

    try:
        server = await asyncio.start_server(handle, host, port)
        _emit(log, f"capture listening on {host}:{port}, writing {log_path}")
        if ready is not None:
            ready.set()
        try:
            # Not serve_forever(): on cancellation it awaits wait_closed(),
            # which drains the open connections and so never returns here.
            await asyncio.Event().wait()
        finally:
            # Never wait for the connections to drain: the client abandons a
            # socket without closing it, and an abandoned socket sends no EOF.
            server.close()
            for handler in list(handlers):
                handler.cancel()
            if handlers:
                await asyncio.gather(*handlers, return_exceptions=True)
    finally:
        log.close()


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
