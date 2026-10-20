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
