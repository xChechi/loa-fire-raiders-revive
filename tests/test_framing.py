import pytest

from server.net.framing import HEADER_SIZE, MAX_BODY, Frame, decode, encode

# From docs/protocol.md, section "Capture". The frame the client sends first:
# 194_2001 QuerySrvInfoReq{server_id="1"}, body 0a0131.
CAPTURED_HEX = "0300000000000100c200d1070000000000000000000000000a0131"

# From docs/protocol.md, section "Response layout verified live": the 41 bytes of
# 194_2002 QuerySrvInfoRes{district=1, addr="10.0.2.2:8112"} that the real client
# accepted on 21-10-2026.
CAPTURED_RESPONSE_HEX = (
    "1100000000000100c200d2070000000000000000000000000801120d31302e302e322e323a38313132"
)


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
    assert frame == Frame(
        service=3, cmd=2002, status=0, body=bytes.fromhex("08001001"), district=0
    )


def test_encode_matches_the_captured_header_shape() -> None:
    captured = bytes.fromhex(CAPTURED_HEX)
    mine = encode(194, 2001, 0, bytes.fromhex("0a0131"))
    assert len(mine) == len(captured)
    # The captured request carries district 0 and the constant 1, which is exactly
    # what encode writes, so the two frames agree byte for byte.
    assert mine == captured


def test_encode_reproduces_the_verified_response_frame() -> None:
    body = bytes.fromhex("0801120d31302e302e322e323a38313132")
    raw = encode(194, 2002, 0, body)
    assert raw == bytes.fromhex(CAPTURED_RESPONSE_HEX)
    frame, rest = decode(raw)
    assert rest == b""
    assert (frame.service, frame.cmd, frame.district) == (194, 2002, 0)
    assert frame.body == body
    assert len(raw) == HEADER_SIZE + 17


def test_encode_ignores_status() -> None:
    # docs/protocol.md "Encode rule": the server writes nothing for status; status
    # semantics live in the protobuf body. So status must not change the bytes.
    body = bytes.fromhex("0a0131")
    assert encode(194, 2001, 5, body) == encode(194, 2001, 0, body)


def test_decode_always_reports_status_zero() -> None:
    frame, _ = decode(encode(194, 2001, 5, bytes.fromhex("0a0131")))
    assert frame.status == 0


def test_decode_exposes_the_district() -> None:
    # Offset 4 is the district (docs/protocol.md "Header"): the client's own frames
    # carried 07 00 there after a response body said district = 7.
    raw = bytes.fromhex("00000000" + "0700" + "0100" + "0300" + "df07" + "00" * 12)
    frame, rest = decode(raw)
    assert rest == b""
    assert frame.district == 7
    assert (frame.service, frame.cmd, frame.body) == (3, 2015, b"")
    assert encode(3, 2015, 0, b"", district=7) == raw


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


def _header_with_length(length: int) -> bytes:
    """A 3_2015 header claiming ``length`` body bytes, with no body behind it."""
    return (
        length.to_bytes(4, "little")
        + (0).to_bytes(2, "little")   # district
        + (1).to_bytes(2, "little")   # the constant at offset 6
        + (3).to_bytes(2, "little")   # service
        + (2015).to_bytes(2, "little")  # cmd
        + b"\x00" * 12
    )


def test_decode_rejects_a_body_longer_than_max_body() -> None:
    """A length field is 4 bytes; a bogus one must not make the server buffer 4 GiB.

    The largest real frame in the capture is 169 bytes, so 1 MiB is a decade of
    headroom and anything above it is a protocol violation.
    """
    with pytest.raises(ValueError):
        decode(_header_with_length(MAX_BODY + 1))
    with pytest.raises(ValueError):
        decode(_header_with_length(0xFFFFFFFF))


def test_decode_accepts_a_body_length_of_exactly_max_body() -> None:
    # at the limit it is a short read, not an error: None means "need more bytes"
    assert MAX_BODY == 1 << 20
    assert decode(_header_with_length(MAX_BODY)) is None
    frame, rest = decode(_header_with_length(MAX_BODY) + b"\x00" * MAX_BODY)
    assert rest == b""
    assert len(frame.body) == MAX_BODY


@pytest.mark.parametrize("service,cmd", [(0, 0), (255, 65535), (194, 2001)])
def test_encode_accepts_the_full_field_range(service: int, cmd: int) -> None:
    frame, _ = decode(encode(service, cmd, 0, b"x"))
    assert (frame.service, frame.cmd) == (service, cmd)
