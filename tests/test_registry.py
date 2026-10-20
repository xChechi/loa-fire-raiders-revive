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
