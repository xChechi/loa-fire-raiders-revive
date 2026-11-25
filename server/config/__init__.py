"""Read-only typed lookups over the client config tables (spec 3.1).

The stock .db files under .stock/assets/res/data/split are the single source of
truth for game data; nothing is copied or converted. Every connection is opened
mode=ro, one per .db file, lazily, and kept for the process lifetime.

Table and column names interpolated into the SQL below are literals from this
module, never request data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SPLIT_RELPATH = Path("assets/res/data/split")

# DataManager.DROP_BASE_SPLIT, DataManager.lua:14. Groups at or above this id
# live in drop_base_2.db, table drop_base_2, whose columns are TEXT.
DROP_BASE_SPLIT = 10_000_000


class Config:
    def __init__(self, split_dir: Path) -> None:
        self.split_dir = Path(split_dir)
        self._conns: dict[str, sqlite3.Connection] = {}

    @classmethod
    def load(cls, stock_dir: Path) -> "Config":
        return cls(Path(stock_dir) / SPLIT_RELPATH)

    def conn(self, db_name: str) -> sqlite3.Connection:
        cached = self._conns.get(db_name)
        if cached is None:
            path = (self.split_dir / f"{db_name}.db").resolve()
            # A sqlite URI needs forward slashes even on Windows.
            cached = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            cached.row_factory = sqlite3.Row
            self._conns[db_name] = cached
        return cached

    def close(self) -> None:
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()

    def _one(self, db: str, table: str, column: str, value):
        return self.conn(db).execute(
            f"SELECT * FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()

    def _all(self, db: str, table: str, where: str, params: tuple) -> list:
        return list(self.conn(db).execute(f"SELECT * FROM {table} {where}", params))

    # --- stages and chapters ------------------------------------------------
    def stage(self, entry: int):
        return self._one("stage_info", "stage_info", "entry", int(entry))

    def stages_in_chapter(self, chapter: int) -> list:
        return self._all(
            "stage_info", "stage_info",
            "WHERE chapter = ? ORDER BY CAST(idx AS INTEGER)", (int(chapter),),
        )

    def chapter(self, entry: int):
        return self._one("chapter_info", "chapter_info", "entry", int(entry))

    def chapters_of_type(self, type_: int = 1) -> list:
        return self._all(
            "chapter_info", "chapter_info",
            "WHERE type = ? ORDER BY CAST(idx AS INTEGER)", (int(type_),),
        )

    def first_stage(self, chapter_type: int = 1) -> int:
        """LevelManager.comEntryTable[1][1]: first stage of the first chapter."""
        chapters = self.chapters_of_type(chapter_type)
        return int(self.stages_in_chapter(int(chapters[0]["entry"]))[0]["entry"])

    def next_stage(self, entry: int) -> int:
        """LevelManager:readStageInfo nextLevel: the next idx in this chapter,
        else the first stage of the next chapter of the same type, else itself.
        """
        row = self.stage(entry)
        if row is None:
            return int(entry)
        chapter_entry = int(row["chapter"])
        siblings = [int(r["entry"]) for r in self.stages_in_chapter(chapter_entry)]
        here = siblings.index(int(entry))
        if here + 1 < len(siblings):
            return siblings[here + 1]
        chapter_row = self.chapter(chapter_entry)
        if chapter_row is None:
            return int(entry)
        entries = [int(c["entry"]) for c in self.chapters_of_type(int(chapter_row["type"]))]
        at = entries.index(chapter_entry)
        for following in entries[at + 1:]:
            stages = self.stages_in_chapter(following)
            if stages:
                return int(stages[0]["entry"])
        return int(entry)

    # --- heroes -------------------------------------------------------------
    def hero(self, entry: int):
        return self._one("hero_info", "hero_info", "entry", int(entry))

    def hero_qualities(self, hero: int) -> list:
        return self._all(
            "hero_quality", "hero_quality",
            "WHERE hero = ? ORDER BY CAST(quality AS INTEGER)", (int(hero),),
        )

    def hero_growth(self, hero: int, star: int):
        rows = self._all(
            "hero_growth", "hero_growth", "WHERE hero = ? AND star = ?",
            (int(hero), int(star)),
        )
        return rows[0] if rows else None

    def npc(self, entry: int):
        return self._one("npc_info", "npc_info", "entry", int(entry))

    def hero_quality_row(self, hero: int, quality: int):
        """None when the (hero, quality) row is missing; hero.quality_row_for
        keeps its own fallback to the lowest quality."""
        rows = self._all(
            "hero_quality", "hero_quality", "WHERE hero = ? AND quality = ?",
            (int(hero), int(quality)),
        )
        return rows[0] if rows else None

    # --- skills and function unlocks (Wave 2) --------------------------------
    def spell(self, entry: int):
        return self._one("spell_info", "spell_info", "entry", int(entry))

    def spell_level_up(self, level: int):
        """spell0..spell3: the highest skill level a hero of this level may
        reach (RoleSkillRender.lua:236-263)."""
        return self._one("spell_level_up", "spell_level_up", "level", int(level))

    def function_unlock(self, entry: int) -> int:
        """function.unlock_level, the player level a feature opens at
        (FunctionType:checkIsOpend, FunctionType.lua:1152-1180). `function`
        is an SQL keyword, hence the brackets."""
        row = self._one("functions", "[function]", "entry", int(entry))
        if row is None:
            raise KeyError(f"function has no row for {entry}")
        return int(row["unlock_level"] or 0)

    # --- training (Wave 2) ---------------------------------------------------
    def train_slots(self) -> list:
        return self._all("train_info", "train_info", "ORDER BY entry", ())

    def train_quality(self, train: int, quality: int):
        rows = self._all(
            "train_quality", "train_quality", "WHERE train = ? AND quality = ?",
            (int(train), int(quality)),
        )
        return rows[0] if rows else None

    def train_level_xp(self, level: int, quality: int):
        """Keyed by player level and slot quality (TrainUI.lua:646-656)."""
        rows = self._all(
            "train_level_xp", "train_level_xp", "WHERE level = ? AND quality = ?",
            (int(level), int(quality)),
        )
        return rows[0] if rows else None

    # --- angels -------------------------------------------------------------
    # AngelManager.lua:79,295 only ever count angel_info rows whose
    # activation_item_num is not 0, so the same filter applies here.
    def angel_by_star(self, angel_entry: int, star: int):
        rows = self._all(
            "angel_info", "angel_info",
            "WHERE angel_entry = ? AND star = ? AND activation_item_num != 0"
            " ORDER BY entry",
            (int(angel_entry), int(star)),
        )
        return rows[0] if rows else None

    def angel_star1_rows(self) -> list:
        """The roster AngelManager:parseAngel builds (AngelManager.lua:75-84)."""
        return self._all(
            "angel_info", "angel_info",
            "WHERE star = 1 AND activation_item_num != 0 ORDER BY entry", (),
        )

    # --- gear crafting ------------------------------------------------------
    def item_composite(self, item_id: int):
        return self._one("item_composite", "item_composite", "item_id", int(item_id))

    # --- achievements -------------------------------------------------------
    def events_catalog(self, catalog: int) -> list:
        return self._all(
            "event_info", "event_info", "WHERE catalog = ? ORDER BY entry",
            (int(catalog),),
        )

    def event(self, entry: int):
        return self._one("event_info", "event_info", "entry", int(entry))

    def event_children(self, parent: int) -> list:
        return self._all(
            "event_info", "event_info", "WHERE parent = ? ORDER BY entry",
            (int(parent),),
        )

    # --- sign-in ------------------------------------------------------------
    def checkin_months(self) -> list[int]:
        return [
            int(r["month"])
            for r in self.conn("checkin").execute(
                "SELECT DISTINCT month FROM checkin ORDER BY month"
            )
        ]

    def checkin_rows(self, month: int) -> list:
        return self._all(
            "checkin", "checkin", "WHERE month = ? ORDER BY idx", (int(month),)
        )

    def check_award(self, award_id: int):
        # check_award stores every column as TEXT.
        return self._one("check_award", "check_award", "id", str(int(award_id)))

    def checkin_extreme(self, day: int):
        return self._one(
            "checkin_extreme_info", "checkin_extreme_info", "day", int(day)
        )

    # --- mail, stores, purchases --------------------------------------------
    def mail_template(self, entry: int):
        return self._one("mail_info", "mail_info", "entry", int(entry))

    def store(self, entry: int):
        return self._one("store_info", "store_info", "entry", int(entry))

    def merchandise(self, store: int) -> list:
        return self._all(
            "merchandise_info", "merchandise_info", "WHERE store = ? ORDER BY entry",
            (int(store),),
        )

    def buy_gold_cost(self, times: int) -> int | None:
        row = self._one("buy_gold_cost", "buy_gold_cost", "times", int(times))
        return None if row is None else int(row["cost"])

    def vip_value(self, entry: int, vip: int) -> str | None:
        """vip_info stores each VIP level in its own TEXT column vip0..vipN."""
        row = self._one("vip_info", "vip_info", "entry", int(entry))
        return None if row is None else str(row[f"vip{int(vip)}"])

    def item_buy(self, refer: int):
        return self._one("item_buy_info", "item_buy_info", "refer", int(refer))

    # --- items, levels, variables, text -------------------------------------
    def item(self, entry: int):
        # item_info stores every column as TEXT.
        return self._one("item_info", "item_info", "entry", str(int(entry)))

    def xp_for_level(self, lvl: int):
        return self._one("xp_for_level", "xp_for_level", "lvl", int(lvl))

    def variable(self, key: str):
        row = self._one("variables", "variables", "key", key)
        return None if row is None else str(row["value"])

    def variable_int(self, key: str, default: int) -> int:
        raw = self.variable(key)
        if raw is None or raw == "":
            return default
        return int(float(raw))

    def gacha(self, entry: int):
        return self._one("gacha_info", "gacha_info", "entry", int(entry))

    def gachas(self) -> list:
        return self._all("gacha_info", "gacha_info", "ORDER BY entry", ())

    def guide(self, gid: int):
        return self._one("new_player_guide_info", "new_player_guide_info", "id", int(gid))

    def language(self, status: int):
        row = self._one("language", "language", "id", int(status))
        return None if row is None else str(row["content"])

    # --- drops --------------------------------------------------------------
    def drop_groups(self, drop_id: int) -> list:
        """DataManager:getDropBaseAry step 1: a drop id to its groups."""
        return self._all(
            "drop_group", "drop_group",
            "WHERE drop_id = ? ORDER BY drop_group_id", (int(drop_id),),
        )

    def drop_rows(self, drop_group_id: int) -> list[dict[str, int]]:
        """Step 2, with the drop_base_2 split. drop_base_2 stores TEXT, so both
        the parameter and every value are cast."""
        group = int(drop_group_id)
        db = table = "drop_base"
        param = group
        if group >= DROP_BASE_SPLIT:
            db = table = "drop_base_2"
            param = str(group)
        rows = self.conn(db).execute(
            f"SELECT drop_type, item_id, amount, weight FROM {table} "
            "WHERE drop_group_id = ? ORDER BY CAST(drop_base_id AS INTEGER)",
            (param,),
        )
        return [
            {
                "drop_type": int(r["drop_type"]),
                "item_id": int(r["item_id"]),
                "amount": int(r["amount"]),
                "weight": int(r["weight"]),
            }
            for r in rows
        ]
