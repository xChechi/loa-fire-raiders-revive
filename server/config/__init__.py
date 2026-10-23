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
