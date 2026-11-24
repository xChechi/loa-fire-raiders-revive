"""Mail box: 5_2223 MailReceiveReq, 5_2225 MailCheckReq, 5_2227 MailCheckAllReq."""

import time
from pathlib import Path

import pytest

from server.config import Config
from server.db import connect, create_player, items_of
from server.modules import mail
from server.net.registry import Registry
from server.net.server import Session
from server.settings import Settings

STOCK = Path(".stock")
DAY = 86400


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
    pid = create_player(conn, "stefan", "stefan", guide_id=0, gold=100)
    handlers = mail.handlers(reg, settings, conn, cfg)
    session = Session(writer=None, peer="t", bound_port=0)
    session.player_id = pid
    return conn, pid, handlers, session


def test_deliver_uses_template_99999(cfg, world) -> None:
    """mail_info 99999 物品超限提醒: the sender comes from the template, the
    lifetime is the template's `expires` (7 days; its deadline_days is 0), and
    the body holds only the fill-in the client merges into the template's "|"
    (MMTools:getResultTxt, EmailInfoPanel.lua:131-134)."""
    conn, pid, _, _ = world
    template = cfg.mail_template(99999)
    now = 1_700_000_000
    mail_id = mail.deliver(conn, cfg, pid, 99999, [(20, 10000, 3)], now, body="X")
    row = conn.execute("SELECT * FROM mails WHERE id = ?", (mail_id,)).fetchone()
    assert int(row["player_id"]) == pid
    assert int(row["entry"]) == 99999
    assert row["sender"] == template["sender_nickname"]
    assert row["body"] == "X"
    assert int(row["created"]) == now
    assert int(row["expires"]) == now + int(template["expires"]) * DAY
    assert int(row["expires"]) > now
    assert int(row["checked"]) == 0 and int(row["claimed"]) == 0
    assert mail.attachments_of(row) == [(20, 10000, 3)]


def test_list_splits_checked_and_unchecked_and_hides_expired(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    now = int(time.time())
    unread = mail.deliver(conn, cfg, pid, 99999, [(1, 0, 50)], now)
    read = mail.deliver(conn, cfg, pid, 99999, [], now)
    conn.execute("UPDATE mails SET checked = 1 WHERE id = ?", (read,))
    conn.commit()
    mail.deliver(conn, cfg, pid, 99999, [(1, 0, 50)], now - 30 * DAY)
    res = handlers[(5, 2223)](session, reg.message_class("MailReceiveReq")())
    assert res.status == 0
    assert [m.id for m in res.mails] == [unread]
    assert [m.id for m in res.checked_mails] == [read]
    m = res.mails[0]
    assert m.entry == 99999
    assert m.checked == 0
    assert m.created == now
    assert m.deadline == now + 7 * DAY
    assert m.expires == 7
    assert m.priority == 0
    assert m.sender_nickname == cfg.mail_template(99999)["sender_nickname"]
    assert [(a.category, a.refer, a.amount) for a in m.attachments] == [(1, 0, 50)]
    res.SerializeToString()


def test_check_pays_attachments_once_330498_second_time(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    mail_id = mail.deliver(
        conn, cfg, pid, 99999, [(1, 0, 50), (20, 10000, 2)], int(time.time())
    )
    req = reg.message_class("MailCheckReq")(id=mail_id)
    res = handlers[(5, 2225)](session, req)
    assert res.status == 0
    assert res.id == mail_id
    gold = conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0]
    assert gold == 150
    assert [(int(r["entry"]), int(r["amount"])) for r in items_of(conn, pid)] == [
        (10000, 2)
    ]
    row = conn.execute("SELECT * FROM mails WHERE id = ?", (mail_id,)).fetchone()
    assert int(row["checked"]) == 1 and int(row["claimed"]) == 1
    assert session.outbox, "items and gold changes are pushed to the client"

    again = handlers[(5, 2225)](session, req)
    assert again.status == mail.STATUS_ALREADY_CHECKED == 330498
    gold = conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0]
    assert gold == 150

    missing = handlers[(5, 2225)](session, reg.message_class("MailCheckReq")(id=999))
    assert missing.status == mail.STATUS_NOT_FOUND == 330497
    res.SerializeToString()


def test_check_all_returns_ids(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    now = int(time.time())
    a = mail.deliver(conn, cfg, pid, 99999, [(1, 0, 10)], now)
    b = mail.deliver(conn, cfg, pid, 99999, [(1, 0, 20)], now)
    done = mail.deliver(conn, cfg, pid, 99999, [(1, 0, 1000)], now)
    conn.execute("UPDATE mails SET checked = 1 WHERE id = ?", (done,))
    conn.commit()
    res = handlers[(5, 2227)](session, reg.message_class("MailCheckAllReq")())
    assert list(res.attachments) == [a, b]
    assert list(res.overflows) == []
    gold = conn.execute("SELECT gold FROM players WHERE id = ?", (pid,)).fetchone()[0]
    assert gold == 130
    unchecked = conn.execute(
        "SELECT COUNT(*) FROM mails WHERE player_id = ? AND checked = 0", (pid,)
    ).fetchone()[0]
    assert unchecked == 0
    res.SerializeToString()


def test_an_xp_attachment_pushes_player_xp_and_the_level_up(reg, cfg, world) -> None:
    conn, pid, handlers, session = world
    need = int(cfg.xp_for_level(1)["player_xp_for_next_level"])
    mail_id = mail.deliver(conn, cfg, pid, 99999, [(11, 0, need + 1)], int(time.time()))
    res = handlers[(5, 2225)](session, reg.message_class("MailCheckReq")(id=mail_id))
    assert res.status == 0
    sent = [(s, c) for (s, c, _m) in session.outbox]
    assert (5, 2036) in sent
    level_up = next(m for (s, c, m) in session.outbox if c == 2036)
    assert (level_up.oldLevel, level_up.newLevel) == (1, 2)


def test_an_attachment_that_overflows_queues_the_new_mail_notify(reg, cfg, world) -> None:
    from server.db import grant_item

    conn, pid, handlers, session = world
    grant_item(conn, pid, 10000, int(cfg.item(10000)["stackable"]))
    mail_id = mail.deliver(conn, cfg, pid, 99999, [(20, 10000, 3)], int(time.time()))
    handlers[(5, 2225)](session, reg.message_class("MailCheckReq")(id=mail_id))
    assert 7 in [m.ident for (_s, c, m) in session.outbox if c == 2008]
