"""Wire framing. Every constant here comes from docs/protocol.md.

Do not edit the numbers from memory or from a plan; re-read the capture.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# --- from docs/protocol.md, section "Header" -------------------------------
# length (u32 LE), district (u16), the constant 1 (u16), service (u16),
# cmd (u16), then twelve zero bytes that the client ignores on the way in.
_HEADER = struct.Struct("<IHHHH12x")
HEADER_SIZE = _HEADER.size
# The length field counts the body alone: 3_2015 QuerySrvStateReq has an empty
# body and arrives as 24 bytes with 00 00 00 00 in the length field.
_LENGTH_INCLUDES_HEADER = False
# Offset 6 is an unknown field, constant 1 in every frame in either direction.
_CONSTANT = 1
# The length field is four bytes wide, so a corrupt or hostile header can ask the
# server to buffer up to 4 GiB. The largest real frame in the capture is 169
# bytes; 1 MiB is far beyond anything this protocol carries, and a length above
# it is a protocol violation rather than a short read.
MAX_BODY = 1 << 20
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    service: int
    cmd: int
    status: int
    body: bytes
    district: int = 0


def encode(service: int, cmd: int, status: int, body: bytes, district: int = 0) -> bytes:
    """Build a frame. ``status`` is accepted for API stability and never sent.

    The header has no status slot (docs/protocol.md, "Encode rule" and open
    question 1); status semantics live in the protobuf body's own field.
    """
    length = len(body) + (HEADER_SIZE if _LENGTH_INCLUDES_HEADER else 0)
    header = _HEADER.pack(length, district, _CONSTANT, service, cmd)
    return header + body


def decode(buf: bytes) -> tuple[Frame, bytes] | None:
    if len(buf) < HEADER_SIZE:
        return None
    length, district, _constant, service, cmd = _HEADER.unpack_from(buf, 0)
    body_len = length - HEADER_SIZE if _LENGTH_INCLUDES_HEADER else length
    if body_len < 0:
        raise ValueError(f"negative body length {body_len} in frame header")
    if body_len > MAX_BODY:
        raise ValueError(f"body length {body_len} in frame header exceeds {MAX_BODY}")
    end = HEADER_SIZE + body_len
    if len(buf) < end:
        return None
    # No header byte carries a status, so an incoming frame is always status 0.
    frame = Frame(service, cmd, 0, buf[HEADER_SIZE:end], district)
    return frame, buf[end:]
