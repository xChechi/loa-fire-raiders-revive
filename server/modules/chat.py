"""Chat: 11_2005 QueryTalkDataReq, 11_2009 QueryHistoryTalkReq.

Both are asked when the main city opens. A zero stub of QueryTalkDataRes has
an empty `data`, and ChatRoom:dealWithQueryTalkDataRes indexes
msg.data[1].talkTimes with no nil check (ChatRoom.lua:1161-1166): that is the
known 11_2006 Lua error. One world-channel TalkData fixes it; data[2] would be
the guild channel, which this server has none of.

QueryHistoryTalkRes echoes the channel it was asked for, and an empty
`speaks` just draws no lines (ChatRoom.lua:985-991, GameMainChatPanel.lua:
194-197). A single player has nobody to talk to, so both answers stay empty.
"""

from __future__ import annotations

import sqlite3

from server.config import Config
from server.net.registry import Registry
from server.net.server import Handler, Session, fill_required
from server.settings import Settings

STATUS_OK = 0
WORLD_CHANNEL = 0


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    def query_talk_data(session: Session, req):
        res = registry.message_class("QueryTalkDataRes")(
            status=STATUS_OK, ignoreLevel=0
        )
        res.data.add(channel=WORLD_CHANNEL, talkTimes=0, timeLimit=0)
        fill_required(res)
        return res

    def query_history_talk(session: Session, req):
        res = registry.message_class("QueryHistoryTalkRes")(
            status=STATUS_OK, channel=req.channel
        )
        fill_required(res)
        return res

    return {(11, 2005): query_talk_data, (11, 2009): query_history_talk}
