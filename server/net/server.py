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
            if fd.is_required:
                sub = getattr(msg, fd.name)
                # Reading a sub-message does not make it present: without
                # SetInParent a required sub-message with no required scalars
                # of its own (ArtifactMainRes.af_info) still fails to encode.
                sub.SetInParent()
                fill_required(sub)
            elif msg.HasField(fd.name):
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


@dataclass
class Session:
    writer: asyncio.StreamWriter
    peer: str
    bound_port: int  # the port this server is really listening on (ephemeral in tests)
    # Header offset 4: the client echoes the district the server assigned in
    # QuerySrvInfoRes, so the server echoes back what this connection sent.
    # It stays 0 until the client has been told a district (docs/protocol.md).
    district: int = 0
    player_id: int | None = None
    data: dict[str, object] = field(default_factory=dict)

    async def send(self, service: int, cmd: int, msg, status: int = 0) -> None:
        body = msg.SerializeToString()
        self.writer.write(framing.encode(service, cmd, status, body, self.district))
        await self.writer.drain()
        log.debug("sent %d_%d, %d bytes", service, cmd, len(body))


class Server:
    def __init__(
        self,
        registry: Registry,
        settings: Settings,
        handlers: dict[tuple[int, int], Handler],
        bind_host: str = "0.0.0.0",
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.handlers = handlers
        # settings.host is the client-side address baked into the APK
        # (10.0.2.2 for the emulator); the listening socket is separate.
        self.bind_host = bind_host
        self.port = settings.port
        self.sent_unknown: set[tuple[int, int]] = set()
        self._logged_unknown: set[tuple[int, int]] = set()

    async def serve(self, ready: asyncio.Event | None = None) -> None:
        srv = await asyncio.start_server(
            self._on_client, self.bind_host, self.settings.port
        )
        self.port = srv.sockets[0].getsockname()[1]
        log.info("listening on %s:%d", self.bind_host, self.port)
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
        if session.district == 0:
            # The first frame that names a district fixes it for this session.
            session.district = frame.district
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
