"""5_2121 GachaInfoReq and 5_2123 GachaReq: the two summons the guide points at."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, find_player, heroes_of, items_of
from server.modules import gacha
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        stock_dir=STOCK, db_path=tmp_path / "player.db", host="127.0.0.1",
        bind="127.0.0.1", port=0, username="stefan", guide_id=0,
    )


@pytest.fixture
def world(settings, cfg, reg):
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    handlers = gacha.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def test_gacha_info_lists_every_configured_banner(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2121)](session, reg.message_class("GachaInfoReq")())
    assert res.status == 0
    assert [g.gacha for g in res.gachaInfos] == [
        1200000, 1300000, 2400000, 2500000, 3000000
    ]
    assert all(g.cooldown == 0 for g in res.gachaInfos)
    assert [g.freetimes for g in res.gachaInfos] == [0, 0, 1, 0, 0]
    assert res.gold_gacha == 0 and res.diamond_gacha == 0
    res.SerializeToString()


def test_gacha_info_has_no_daily_or_weekly_soul_data(reg, cfg, world) -> None:
    """Plan open question F: todays stays empty and week is 0 in Plan B1."""
    _, _, handlers, session = world
    res = handlers[(5, 2121)](session, reg.message_class("GachaInfoReq")())
    assert list(res.todays) == []
    assert res.week == 0


def test_gacha_res_always_has_at_least_one_item(reg, cfg, world) -> None:
    """Review Focus 5: TavernUI feeds msg.items to g_tools:randomTable."""
    conn, pid, handlers, session = world
    for _ in range(20):
        res = handlers[(5, 2123)](
            session, reg.message_class("GachaReq")(gacha=1200000)
        )
        assert res.status == 0
        assert len(res.items) >= 1
        res.SerializeToString()


def test_a_seeded_draw_is_deterministic(reg, cfg, settings) -> None:
    """Randomness is injectable exactly like the Task 10 roller."""
    conn = connect(settings.db_path)
    pid = create_player(
        conn, "stefan", "stefan", guide_id=0, gold=1280000, diamond=18888
    )
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid

    def draw(seed: int):
        handlers = gacha.handlers(
            reg, settings, conn, cfg, rng=random.Random(seed)
        )
        res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
        return [(e.category, e.refer, e.amount) for e in res.items]

    first = draw(7)
    assert first == draw(7)
    assert len(first) == 1


def test_a_gold_draw_costs_the_configured_gold(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    row = find_player(conn, "stefan")
    assert int(row["gold"]) == 1280000 - 20000


def test_a_diamond_draw_costs_the_configured_diamonds(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=2400000))
    row = find_player(conn, "stefan")
    assert int(row["diamond"]) == 18888 - 2000


def test_too_little_gold_is_refused_with_the_client_status(reg, cfg, settings) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=10, diamond=0)
    handlers = gacha.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert res.status == 327937                     # language.db 金币不足
    assert len(res.items) == 0
    assert int(find_player(conn, "stefan")["gold"]) == 10


def test_too_few_diamonds_is_refused_with_the_client_status(
    reg, cfg, settings
) -> None:
    conn = connect(settings.db_path)
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=0, diamond=10)
    handlers = gacha.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=2400000))
    assert res.status == 327938                     # language.db 钻石不足
    assert len(res.items) == 0
    assert int(find_player(conn, "stefan")["diamond"]) == 10


def test_an_unknown_banner_is_refused(reg, cfg, world) -> None:
    _, _, handlers, session = world
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=42))
    assert res.status != 0


def test_a_banner_with_no_pool_is_refused_and_costs_nothing(reg, cfg, world) -> None:
    """3000000 has drop_id 0: nothing can be rolled, and an empty items list
    with status 0 would crash g_tools:randomTable, so the draw is refused."""
    conn, pid, handlers, session = world
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=3000000))
    assert res.status == 327681                     # language.db 系统内部错误
    assert len(res.items) == 0
    assert int(find_player(conn, "stefan")["diamond"]) == 18888


def test_a_drawn_hero_is_persisted_and_pushed(reg, cfg, world, monkeypatch) -> None:
    """A type-30 drop is a hero: it lands in the heroes table and the client is
    told through 5_2012 AddHeroNotify, which RoleData:getHero consumes."""
    conn, pid, handlers, session = world
    from server.modules import drops as drops_mod

    monkeypatch.setattr(
        drops_mod, "roll", lambda cfg_, drop_id, rng=None: [drops_mod.Drop(30, 101000, 1)]
    )
    res = handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert [(e.category, e.refer) for e in res.items] == [(30, 101000)]
    assert [int(h["entry"]) for h in heroes_of(conn, pid)] == [101000]
    assert [(s, c) for (s, c, _m) in session.outbox] == [(5, 2012), (5, 2008)]


def test_a_drawn_item_lands_in_the_bag_and_is_pushed(reg, cfg, world, monkeypatch) -> None:
    conn, pid, handlers, session = world
    from server.modules import drops as drops_mod

    monkeypatch.setattr(
        drops_mod, "roll", lambda cfg_, drop_id, rng=None: [drops_mod.Drop(20, 1100, 20)]
    )
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    assert {int(i["entry"]): int(i["amount"]) for i in items_of(conn, pid)} == {1100: 20}
    idents = [m.ident for (_s, _c, m) in session.outbox if _c == 2008]
    assert 4 in idents and 1 in idents


def test_the_player_notify_carries_the_absolute_balance(reg, cfg, world) -> None:
    """notify.player_changed gets the post-cost absolute gold, not a delta."""
    conn, pid, handlers, session = world
    handlers[(5, 2123)](session, reg.message_class("GachaReq")(gacha=1200000))
    player_notify = [m for (_s, c, m) in session.outbox if c == 2008 and m.ident == 1]
    assert len(player_notify) == 1
    row = find_player(conn, "stefan")
    assert int(player_notify[0].data[0]) == int(row["gold"])
    assert int(player_notify[0].data[1]) == int(row["diamond"])
