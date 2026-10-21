# Brief for Plan B1 — "tutorial through to campaign chapter 1"

Read first: `docs/superpowers/specs/2026-10-20-loa-private-server-design.md` (approved, amended 21-10-2026),
sections 3.1 (modules `level`, `item` for drops, `hero` only as far as the tutorial needs), 4 ("Campaign stage"),
5.3 milestone 2. Then `docs/protocol.md`, `docs/dev-loop.md`, and the Plan A ledger
`.superpowers/sdd/2026-10-20-plan-a-boot-to-main-city/progress.md` (rulings and the Plan B items parked there).
Plan A is on master (40 commits, 98 tests): server core, login (3_2001 creates the character), player
(QueryMyselfRes for a fresh player, five main-city stubs), framing, fake client, own APK, emulator loop.

## Goal

Stefan (on the emulator `LOA_API30`, this PC; no phone this round) opens the game, the tutorial completes once and
never replays, he summons his first hero as the tutorial asks, fights the tutorial battle, then plays campaign
chapter 1 stage by stage: stars, XP, drops and stage unlocks persist across server restarts.

## Scope (in)

1. **Tutorial completion and persistence.** Trace `NewGuideManager` + `res/data/split/new_player_guide_info.db`
   (191 rows; `lua` column = story ids, `jump_id`, `is_over`; highest `is_over=1` id is 14302) to list every
   request the client sends during the guide from a fresh character until `is_over`. Implement `5_2041
   SaveGuideIdReq` (persist `guide_id` on the player row; `QueryMyselfRes.player.guide_id` already reads it) and
   every other message the guide path needs with real data, so the tutorial runs once. The guide's first fight uses
   `BattleFactoryGuide` with fixed random numbers; find out whether it still sends `LevelIntoReq`/`LevelOutReq`
   and what the server must answer.
2. **Hero summon as the tutorial demands** (`5_2121 GachaInfoReq`, `5_2123 GachaReq`, and whatever the summon UI
   queries): the minimum hero module — grant a hero (`ClientHero` with all 10 required fields, from `hero_info.db`
   + `hero_growth.db` + `hero_quality.db` values, never invented), persist heroes in `player.db`, return them in
   `QueryMyselfRes.heroes`. Hero level/star/gear upgrades are Plan B2; do not build them unless the tutorial blocks
   on one (if it does, the smallest real implementation, and say so).
3. **Campaign chapter 1** per spec section 4: `5_2201 LevelIntoReq` (validate unlock from `stage_info.db` /
   `chapter_info.db`, roll `urandom[64]` ints in 0..9999, pre-roll drops from `drop_group.db` + `drop_base.db` by
   the stage's drop ids, store them on the session), `5_2203 LevelOutReq` (trust `star`, grant XP from the stage
   row, hand out the stored drops into the inventory, unlock the next stage, persist; `ClientLevelXp` for owner,
   angel, heroes; `ClientFightResultFromServer` if the client needs it), `5_2209 LevelChapterPrizeReq`,
   `5_2205 LevelCleanReq` / `5_2207 LevelResetReq` (sweep/reset: implement if the chapter-1 UI exposes them, else
   stub with the right status), `QueryMyselfRes.levels` and `.chapters` populated from the player's progress.
   Energy: `LevelIntoReq` costs the stage's energy from `stage_info`; energy regenerates per
   `xp_for_level.db` (`levelup_recovery_energy`, and the regen interval the Lua expects); `max_energy` read from
   `xp_for_level` by level, not the frozen 60 (Plan A minor).
4. **Inventory and items**: `ClientStock`/`ClientItem` shapes from the proto; `player.db` tables for items and
   bag; drops land there; `QueryMyselfRes.inventory` returns them. Item use/sell are Plan B3 unless the campaign
   reward flow needs them.
5. **Plan A parked items**: `5_2944 QueryBtCardRecordRes` needs real data (the Lua does `#data` on an absent
   repeated field) — fill it from the table the Lua reads; the "answering a zero stub" log line fires when nothing
   is sent (fix the wording); `[net] bind` key in settings.toml with default `0.0.0.0`; `.gitattributes`
   `text eol=lf` for `gradlew` and the Lua patch sources; `MAX_BODY` already done.
6. **Config access layer** `server/config/` (spec 3.1): read-only typed lookups over `.stock/assets/res/data/split/*.db`
   (`stage(level)`, `chapter(id)`, `hero(entry)`, `drop_group(id)`, `drop_base(id)`, `xp_for_level(lvl)`), one
   connection per db file opened lazily, with tests that assert known rows (hero 100000 玫瑰骑士; stage 1-1's row).

## Scope (out)

Hero upgrades, gear, runes, angels beyond what QueryMyselfRes already carries, sign-in, shop, mail, arena,
guild, events, chat, English text, phone build, push.

## Facts and pointers

- Message ids are in `.stock/assets/res/utils/net/msgIDMap.lua`; message shapes in the registry
  (`server/net/registry.py`, loaded from `allProtos.pb`). Quote every message definition the plan relies on,
  verbatim from the registry (print the descriptor fields with a one-off script), never from memory.
- Client Lua to read for each flow: `scripts/app/game/manager/NewGuideManager.lua`,
  `scripts/app/game/view/ui/guide*`, `scripts/app/game/model/chapter*`, `scripts/app/game/view/ui/chapter*`,
  `scripts/app/game/view/scenes/battleScene/type/BattleFactoryLevel.lua` and `BattleFactoryGuide.lua`,
  `scripts/app/game/model/roleData/*.lua` (what `RoleData:updateData` reads from `levels`, `chapters`,
  `inventory`, `heroes`), `scripts/app/game/view/ui/gacha*` or wherever `5_2123` is sent.
- Status codes: in the proto body (`*Res.status`); 0 = ok. The client's error texts for non-zero codes are in
  `res/data/split/language.db` (`id` = status code, `content` = Chinese text) — use the real codes for "not enough
  energy", "stage locked" etc. (look them up by text, quote id and content).
- `urandom`: the guide battle hard-codes 64 floats scaled ×10000 (`BattleFactoryGuide.lua:73-75`); the server
  sends `repeated uint32 urandom` of 64 values in 0..9999 for a normal stage.
- Dev loop: `docs/dev-loop.md` (AVD `LOA_API30`, adb commands, screenshot, logcat filter). The acceptance run of
  each milestone is on the emulator by the implementer, screenshots named in the report; Stefan's own emulator
  pass is the gate. Server: `py -3.14 -m server`; settings host 10.0.2.2 stays.
- Plan A conventions to follow exactly: handler modules `handlers(registry, settings, conn) -> dict`, registered
  in `server/__main__.py:build_handlers`; `fill_required` for every emitted message; tests bind 127.0.0.1 port 0
  with `bind_host`; pytest `--basetemp=C:/tmp/pytest-loa`; `py -3.14`; no push; `.stock/` read-only; commit per
  task.

## Decisions (do not reopen)

- Battle results are trusted from the client (`LevelOutReq.star`); no server-side battle engine.
- Drops are rolled on `LevelIntoReq`, stored per session keyed by level, granted on `LevelOutReq` for the same
  level; a `LevelOutReq` without a matching `LevelIntoReq` is answered with the client's "stage locked" status.
- Player state in `data/player.db`; schema migrations are additive (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE
  ADD COLUMN` guarded), never a rebuild that loses the Plan A character.
- Config reads go through `server/config/`, never raw SQL in handlers.
- Tutorial must finish on a fresh character and must not replay after a restart: that is the definition of done
  for the first half; chapter 1 stage 1 to the chapter prize with persistence is the second half.

## Milestone definition of done

Fresh `player.db` → emulator: tutorial completes (screenshots at the summon, the battle, the city after), force-stop
and relaunch shows the city without the tutorial; campaign 探险 → chapter 1 → stage 1 fought and starred, energy
decreased, drops in the bag, next stage unlocked; server restart keeps all of it; `tools/fake_client.py` extended to
replay a stage fight; full suite green.
