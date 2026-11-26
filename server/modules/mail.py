"""Mail box: 5_2223 MailReceiveReq, 5_2225 MailCheckReq, 5_2227 MailCheckAllReq.

FunctionType.lua:680-688 opens the mail UI from MailReceiveRes.mails (unread)
and .checked_mails (read). EmailInfoPanel.lua:236,295 sends 5_2225 {id} when an
unread mail is opened, and EmailUI.lua:194-226 moves that id to the read list
on the answer. 5_2227 answers with the ids it paid (EmailUI.lua:231-262).

Text: the client merges each string into its own copy of the mail_info
template with MMTools:getResultTxt (EmailRenderBox.lua:93-105,
EmailInfoPanel.lua:107-152). A template with no "|" is shown as is, and each
"|" takes the next "|"-separated piece of the server string. So `sender` keeps
the template's sender_nickname (a required wire field, shown as is), `subject`
stays empty, and `body` carries only the fill-ins; sending the whole template
text would print it twice.

Lifetime: ClientMail.deadline is absolute epoch seconds (EmailRenderBox.lua:
127-129 counts the days left from it) and ClientMail.expires is the number of
days the mail is shown (the field comment, EmailRenderBox.lua:31). The stored
`expires` column is the absolute deadline, created + mail_info.expires days.
mail_info.deadline_days is 0 for template 99999, so it cannot be the lifetime.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time

from server import db
from server.config import Config
from server.modules import hero, item, notify
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

log = logging.getLogger("loa.mail")

STATUS_OK = 0
STATUS_NOT_FOUND = 330497          # language.db 邮件未找到
STATUS_ALREADY_CHECKED = 330498    # language.db 邮件已查看

DAY = 86400


def attachments_of(row: sqlite3.Row) -> list[tuple[int, int, int]]:
    return [(int(c), int(r), int(a)) for c, r, a in json.loads(row["attachments"])]


def deliver(
    conn: sqlite3.Connection, cfg: Config, pid: int, entry: int, attachments,
    now: int, body: str = "",
) -> int:
    """Store one mail built on mail_info(entry) and return its id. The caller
    queues notify.mail_arrived when a session is at hand."""
    template = cfg.mail_template(entry)
    if template is None:
        raise KeyError(f"mail_info has no row for mail {entry}")
    triples = [[int(c), int(r), int(a)] for c, r, a in attachments]
    cur = conn.execute(
        "INSERT INTO mails (player_id, entry, sender, subject, body, attachments,"
        " created, expires) VALUES (?, ?, ?, '', ?, ?, ?, ?)",
        (
            int(pid), int(entry), str(template["sender_nickname"] or ""), str(body),
            json.dumps(triples), int(now),
            int(now) + int(template["expires"] or 0) * DAY,
        ),
    )
    conn.commit()
    log.info("mail %d (template %d) delivered to player %d: %s",
             cur.lastrowid, entry, pid, triples)
    return int(cur.lastrowid)


def build_client_mail(registry: Registry, cfg: Config, row: sqlite3.Row):
    template = cfg.mail_template(int(row["entry"]))

    def _t(column: str) -> int:
        return int(template[column] or 0) if template is not None else 0

    msg = registry.message_class("ClientMail")(
        id=int(row["id"]),
        entry=int(row["entry"]),
        sender_nickname=str(row["sender"]),
        subject=str(row["subject"]),
        body=str(row["body"]),
        created=int(row["created"]),
        deadline=int(row["expires"]),
        expires=(int(row["expires"]) - int(row["created"])) // DAY,
        checked=int(row["checked"]),
        type=_t("type"),
        # EmailUI.lua:145,203 keeps a mail with priority != 0 in the unread list.
        priority=_t("priority"),
        icon=_t("icon"),
    )
    for category, refer, amount in attachments_of(row):
        msg.attachments.add(category=category, refer=refer, amount=amount)
    fill_required(msg)
    return msg


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def _pid(session: Session) -> int:
        if session.player_id is not None:
            return int(session.player_id)
        return int(db.find_player(conn, settings.username)["id"])

    def _live(pid: int, now: int) -> list[sqlite3.Row]:
        return list(conn.execute(
            "SELECT * FROM mails WHERE player_id = ? AND expires > ? ORDER BY id",
            (pid, now),
        ))

    def _pay(session: Session, pid: int, row: sqlite3.Row) -> None:
        """Pay one mail and mark it read. grant_prizes vets the whole list
        before it writes, so a raise leaves the mail unread and unpaid."""
        out = item.grant_prizes(conn, cfg, pid, attachments_of(row))
        conn.execute(
            "UPDATE mails SET checked = 1, claimed = 1 WHERE id = ?", (int(row["id"]),)
        )
        conn.commit()
        for hero_id in out["heroes"]:
            hero_row = conn.execute(
                "SELECT * FROM heroes WHERE id = ?", (hero_id,)
            ).fetchone()
            notify.hero_added(
                registry, session, hero.build_client_hero(registry, cfg, hero_row, conn=conn)
            )
        notify.items_changed(registry, session, out["items"])
        notify.player_changed(registry, session, {
            "gold": out["gold"], "diamond": out["diamond"], "energy": out["energy"],
        })
        item.announce(registry, session, out)

    def receive(session: Session, req):
        pid = _pid(session)
        res = registry.message_class("MailReceiveRes")(status=STATUS_OK)
        for row in _live(pid, int(time.time())):
            target = res.checked_mails if int(row["checked"]) else res.mails
            target.add().CopyFrom(build_client_mail(registry, cfg, row))
        fill_required(res)
        return res

    def check(session: Session, req):
        pid = _pid(session)
        mail_id = int(req.id)
        row = conn.execute(
            "SELECT * FROM mails WHERE id = ? AND player_id = ? AND expires > ?",
            (mail_id, pid, int(time.time())),
        ).fetchone()
        status = STATUS_OK
        if row is None:
            status = STATUS_NOT_FOUND
        elif int(row["checked"]):
            status = STATUS_ALREADY_CHECKED
        else:
            _pay(session, pid, row)
        if status:
            log.info("mail %d of player %d refused %d", mail_id, pid, status)
        res = registry.message_class("MailCheckRes")(status=status, id=mail_id)
        fill_required(res)
        return res

    def check_all(session: Session, req):
        pid = _pid(session)
        # The list is read once: an overflow mail created while paying is new
        # and waits for the next open.
        unread = [r for r in _live(pid, int(time.time())) if not int(r["checked"])]
        res = registry.message_class("MailCheckAllRes")()
        for row in unread:
            _pay(session, pid, row)
            res.attachments.append(int(row["id"]))
        fill_required(res)
        return res

    return {(5, 2223): receive, (5, 2225): check, (5, 2227): check_all}
