"""Server-run activities with no data in the client answer "closed".

Anniversary, VIP gifts, open fund, recharge cards, first recharge, daily gift,
card master, money cat, turntables, flip cards, share, the 7-day open activity,
gift codes and the discount shop are all scheduled and filled by the original
server; the client ships none of their numbers. Every Req here is sent only
when the player taps an icon or a button (FunctionType.lua:1428-1437,
1661-1669; AnniversaryCtr.lua:46,189; DiscountShopUI.lua:250,578;
ExchangePanel.lua:100). A Res with a `status` answers 327974
活动尚未开启或已结束, which MMMsgDispatcher floats as text and does not pass
to the listener (MMMsgDispatcher.lua:107-131). A Res without `status` cannot
refuse, so it goes out empty, exactly like the zero stub it replaces.

blacklist_entries is plan open question O6: the payment-only and
server-scheduled functions LoginRes.blacklist hides
(RoleData:setFunctionBlackList, RoleData.lua:203-227, keeps disabled == 1).
W1 wires both into the server.
"""

from __future__ import annotations

import logging
import sqlite3

from server.config import Config
from server.net.registry import Registry
from server.net.server import Handler, Session, stub_response
from server.settings import Settings

log = logging.getLogger("loa.activity")

STATUS_CLOSED = 327974  # language.db 活动尚未开启或已结束

CLOSED_IDS: tuple[tuple[int, int], ...] = tuple(
    (5, cmd) for cmd in (
        2319, 2321, 2595, 2885,              # anniversary / wonderful activity
        2559, 2561, 2915,                    # VIP gifts, recharge
        2645, 2647,                          # open fund
        2945,                                # recharge card
        2329,                                # first recharge
        2167,                                # daily gift draw
        2749, 2751, 2753, 2755,              # card master
        2807, 2809,                          # money cat
        2819, 2821, 2947, 2949,              # turntables
        2895, 2897, 2899,                    # flip cards
        2901, 2905, 2907,                    # share
        2581, 2583,                          # 7-day open activity (W1b follow-up)
        2037,                                # gift-code exchange
        2643, 2649,                          # discount shop
    )
)

# functions.db entries, disabled = 1. 10410 (7-day login), 10600 (premium
# sign-in tab) and 10610 (7-day activity) stay visible on purpose.
BLACKLISTED_FUNCTIONS = (
    10100, 10101, 10102, 10103, 10220, 60010, 70010, 70020, 90010, 90050,
    90060, 90090, 90200, 90230, 90250, 90270, 90290, 90310, 90320, 90330,
    90340, 90360, 90370, 90380, 90390, 90400,
)


def blacklist_entries(cfg: Config) -> list[tuple[int, int]]:
    """(entry, disabled) pairs for LoginRes.blacklist. `cfg` is the W1 call
    signature; the list itself is the O6 product default, not table data."""
    return [(entry, 1) for entry in BLACKLISTED_FUNCTIONS]


def handlers(
    registry: Registry, settings: Settings, conn: sqlite3.Connection, cfg: Config
) -> dict[tuple[int, int], Handler]:
    logged: set[tuple[int, int]] = set()

    def make(key: tuple[int, int]) -> Handler:
        def closed(session: Session, req):
            if key not in logged:
                logged.add(key)
                log.info(
                    "%d_%d %s is a server-run activity: answering closed",
                    *key, registry.name_for(*key),
                )
            # stub_response sets status only where the Res has one, and runs
            # fill_required.
            return stub_response(registry, *key, status=STATUS_CLOSED)

        return closed

    return {key: make(key) for key in CLOSED_IDS}
