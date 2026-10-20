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
