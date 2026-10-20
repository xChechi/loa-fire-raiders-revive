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
