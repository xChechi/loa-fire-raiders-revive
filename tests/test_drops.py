"""Drop rolling over drop_group plus drop_base (DataManager:getDropBaseAry)."""

import random
from pathlib import Path

import pytest

from server.config import Config
from server.modules.drops import Drop, as_triples, roll, to_prize_entries
from server.net.registry import Registry

STOCK = Path(".stock")


@pytest.fixture(scope="module")
def cfg() -> Config:
    c = Config.load(STOCK)
    yield c
    c.close()


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load(STOCK)


class ScriptedRandom:
    """The two methods the roller uses, each reading from a scripted queue.

    randrange records the total it was handed, so a test can assert the weight
    sum the roller computed as well as the row it picked.
    """

    def __init__(self, randoms=(), randranges=()) -> None:
        self.randoms = list(randoms)
        self.randranges = list(randranges)
        self.totals: list[int] = []

    def random(self) -> float:
        return self.randoms.pop(0)

    def randrange(self, stop: int) -> int:
        self.totals.append(stop)
        return self.randranges.pop(0)


def test_a_certain_group_always_drops(cfg) -> None:
    # stage 1-1 visible_drops 10000 -> group 10001 at probability 1 -> item 10000 x2
    for seed in range(5):
        assert roll(cfg, 10000, random.Random(seed)) == [Drop(20, 10000, 2)]


def test_probability_is_respected(cfg) -> None:
    """invisible_drops 10005: groups at 0.2, 0.29 and 0.1, so 1000 rolls must
    land between a tenth and nine tenths of the maximum, never always or never."""
    rng = random.Random(7)
    counts = [len(roll(cfg, 10005, rng)) for _ in range(1000)]
    assert 0 in counts
    assert max(counts) >= 1
    assert sum(counts) < 3 * 1000
    # Seed 7 pinned: every group count occurs, and the hit total sits on the
    # 0.2 + 0.29 + 0.1 = 0.59 per roll expectation (590) rather than near 0 or 3000.
    # 621 and not 590 because group 5001 also draws a randrange for its 12 rows,
    # so the stream a pure probability model would see is not the stream here.
    assert sorted(set(counts)) == [0, 1, 2, 3]
    assert sum(counts) == 621


def test_probability_zero_never_drops_and_one_never_consumes_the_rng(cfg) -> None:
    """Group 10001 is at probability 1: it must not draw a random() at all, so
    an rng with an empty random() queue still rolls it."""
    rng = ScriptedRandom(randoms=(), randranges=(0,))
    assert roll(cfg, 10000, rng) == [Drop(20, 10000, 2)]
    # A draw of exactly the probability misses (>= is a miss), 0.0 always hits.
    assert roll(cfg, 10005, ScriptedRandom(randoms=(0.2, 0.29, 0.1))) == []
    hit_all = ScriptedRandom(randoms=(0.0, 0.0, 0.0), randranges=(0, 0, 0))
    assert roll(cfg, 10005, hit_all) == [
        Drop(20, 1050, 2), Drop(20, 1100, 3), Drop(20, 10000, 2)
    ]


def test_weighted_pick_inside_a_group(cfg) -> None:
    """Gacha 1200000 drop_id 190000: one group, 125 weighted rows, exactly one
    result per roll."""
    rng = random.Random(1)
    seen = set()
    for _ in range(200):
        drops = roll(cfg, 190000, rng)
        assert len(drops) == 1
        seen.add((drops[0].category, drops[0].refer))
    assert len(seen) > 1
    valid = {(r["drop_type"], r["item_id"]) for r in cfg.drop_rows(190000)}
    assert seen <= valid


def test_the_weight_boundaries_are_half_open(cfg) -> None:
    """Group 190000 weighs 9313 in total; the first rows weigh 81, 27, 9, 3.
    Cumulative edges: 0..80 -> row 1, 81..107 -> row 2, 9153..9312 -> row 125."""
    rows = cfg.drop_rows(190000)
    assert sum(r["weight"] for r in rows) == 9313

    for pick, expected in (
        (0, Drop(20, 1000, 1)),       # first unit of the first row
        (80, Drop(20, 1000, 1)),      # last unit of the first row
        (81, Drop(20, 1010, 1)),      # first unit of the second row
        (107, Drop(20, 1010, 1)),     # last unit of the second row
        (108, Drop(20, 1020, 1)),     # first unit of the third row
        (9152, Drop(20, 31110, 1)),   # last unit before the final row
        (9153, Drop(20, 31120, 1)),   # first unit of the final row
        (9312, Drop(20, 31120, 1)),   # last unit of the table
    ):
        rng = ScriptedRandom(randranges=(pick,))
        assert roll(cfg, 190000, rng) == [expected], f"pick {pick}"
        assert rng.totals == [9313]


def test_the_chapter_chest_is_deterministic(cfg) -> None:
    drops = roll(cfg, 600100, random.Random(0))
    assert drops == [
        Drop(9, 0, 600), Drop(20, 104000, 6), Drop(1, 0, 60000), Drop(20, 1100, 12)
    ]


def test_drop_base_2_groups_are_reached(cfg) -> None:
    drops = roll(cfg, 10000000, random.Random(0))
    assert Drop(9, 0, 1128) in drops
    assert Drop(1, 0, 600000) in drops


def test_an_unknown_drop_id_rolls_nothing(cfg) -> None:
    assert cfg.drop_groups(999999999) == []
    assert roll(cfg, 999999999, random.Random(0)) == []


def test_a_known_drop_id_whose_groups_all_miss_rolls_nothing(cfg) -> None:
    """13002 is a real drop id with two groups, at 0.2 and 0.3; seed 0 draws
    0.844 and 0.758, so both miss. (The plan called this id 'unknown'.)"""
    assert len(cfg.drop_groups(13002)) == 2
    assert roll(cfg, 13002, random.Random(0)) == []


def test_prize_entries_and_triples(reg, cfg) -> None:
    drops = [Drop(20, 10000, 2), Drop(1, 0, 516)]
    entries = to_prize_entries(reg, drops)
    assert [(e.category, e.refer, e.amount) for e in entries] == [
        (20, 10000, 2), (1, 0, 516)
    ]
    for entry in entries:
        entry.SerializeToString()
    assert as_triples(drops) == [(20, 10000, 2), (1, 0, 516)]
