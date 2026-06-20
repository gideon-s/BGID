# Handoff 11 — Maps overhaul: structured tiles, z-floors, levels & adaptive camera

**Status:** design locked / phased build · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phases 1–5 (live), and the **maps-model decision** that gated the map designer
(`handoff-10-tool-suite.md` §2) — now **settled** (see §1). **Goal:** evolve the
world from uniform small glyph-string rooms into a heterogeneous, vertical world:
**richer per-tile data**, **stacked z-floors** within a level, a **level graph**
that generalizes the room-graph, and an **adaptive camera** for large zones —
with **author-time procedural generation** (whole-floor, bake-to-tiles) feeding
the designer. This unblocks `handoff-10` §2.

> Read master §3 (current architecture) + §4 (target), `handoff-02` (the tile
> slice), `handoff-03` (zone transitions), and `handoff-07` (the hand-drawn
> renderer) first. The seams this builds on are listed in §2 with file refs.

---

## 0. Snapshot note (READ THIS before planning)

The code this handoff was written against is at roughly the **Phase-5 / tokens**
stage. Two handoffs marked "✅ SHIPPED 2026-06-19" are **not present in the
inspected tree**: `handoff-08` (status-effect extensions) and `handoff-09`
(traps & environments). Concretely missing: `features.py`, `debuffs.py`,
`gear_effects.py`, `migrate_features.py`, **a `RoomFeature` model**, and the
entity-keyed `effects.py` (it's still the player-only buff version —
`_active: Dict[int, …]`, no `eid`, no `dot`).

**Why it matters here:** the `RoomFeature` table (`handoff-09` §6) was going to be
the natural home for **per-tile attached data** and the thing the designer
reads/writes. In this snapshot it does not exist — so this handoff does **not**
assume it. If `08`/`09` are in fact live on another branch, Slice A gets cheaper
(reuse `RoomFeature` for the per-cell overlay in §4) and Slice D's feature CRUD is
already partly done. **Confirm the canonical snapshot before scheduling.**

---

## 1. The locked maps model (decisions — these are settled)

The map authoring discussion (`handoff-10`, "Maps — discussion prompt") is resolved:

- **Levels & floors.** A **level** is a named area (the Manor, the Caves). A
  level is a stack of **floors** indexed by a **signed integer z** (`0` ground,
  `-1` cellar, `+1` attic). Each floor is one tile grid. The cellar stops being
  "a room reached by a down-edge the overview draws as a line"; it becomes
  **floor `z=-1` of the same level**, and the overview **stacks floors**.
- **Shared coordinate frame, movement-only between floors.** Floors of a level
  share an `(x,y)` origin (so they overlay cleanly for authoring + the overview,
  and a stair at `(x,y,0)` lands at `(x,y,-1)`). **No cross-floor interaction** —
  no line of sight, no ranged, no falling. Only one floor is active/simulated per
  entity at a time. *Consequence:* the runtime cost is the same as independent
  grids; "shared coords" is an authoring/representation convenience, upgradable
  to true 3D later.
- **Two connection kinds.** *Between levels* = hand-placed **entrances**
  (village door → inn interior, cave mouth → sub-dungeon), each target with its
  own coordinate frame — this **is** the existing room-graph, generalized into a
  **level graph**. *Within a level* = the **floor stack**, linked by stairs.
- **Discrete vs. scrollable is just size.** A "small discrete room" is a level
  with one small floor; a "scrollable overworld" is a level with one large floor.
  **Same data structure**, different grid size + camera mode. The current world
  is the degenerate case (every level = one small floor). Big scrollable levels
  may hold entrances into smaller discrete interiors and sub-dungeons.
- **Adaptive camera.** Per-floor: a grid that fits the viewport renders **static**
  (as today); a grid that exceeds it switches to a **player-centered follow**
  camera. (Re-opens the camera-follow that Phase 6 slice 2 dropped.)
- **Richer per-tile data.** Tiles carry more than walkable/wall — terrain type,
  transparency, flags, variant — **driven by a tile registry** (§4), not
  hard-coded glyph sets.
- **Procedural generation = author-time, whole-floor, one-way bake.** The
  generator lives **inside the designer**, never in the live sim. It emits a tile
  grid that **bakes to static tiles**; from then on it's hand-editing. A re-roll
  is a fresh generate (the tool stashes seed + params so you can re-roll cheaply
  *before* you start editing). Three modes off one pipeline: hand-paint, fully
  procedural, generate-then-edit. **Entrances and stairs are hand-placed**
  (semantic links, never generated); generated output still passes the same
  validation as hand-painted.

---

## 2. Current code — the seams you build on (with refs)

- **Tiles are a single glyph per cell.** `Room.tiles` is a newline glyph string
  (`models.py:47`), parsed into `RoomNode.tiles: List[str]` by `_load_tiles`
  (`world.py:199`). Walkability/sight are **set-membership tests**:
  `BLOCKING`, `SIGHT_BLOCKING`, `TRANSITION_TILES` (`world.py:43–49`), read by
  `_is_walkable_grid` (`world.py:244`) and the transparency predicate
  (`world.py:460`). `zone_snapshot` ships the raw grid as
  `{"tiles":{"w","h","grid": node.tiles}}` (`world.py:692`, grid at `:738`).
  **These three predicates are nearly the entire behavioral surface of a tile.**
- **Vertical movement already exists.** `<`/`>` stairs map to `"up"`/`"down"`
  directions → `exits["up"/"down"]` → `to_room_id` in `transition_for_tile`
  (`world.py:583`, up/down at `:592`). The cellar is already a separate room
  reached by a down-exit. `arrival_tile` (`world.py:659`) + `move_player`
  (`world.py:783`) handle the landing. **Floor *movement* is built; only the
  grouping metadata (which rooms are one level, at which z) is missing.**
- **The room-graph is the level graph.** `RoomExit(from_room, to_room, direction,
  is_locked, key_item_id)` (`models.py:79`) + `RoomNode.exits` already model
  arbitrary directed connections. `drawOverview` (`static/index.html:1852`)
  renders the zone graph.
- **The snapshot is already size-agnostic.** It sends arbitrary `w`/`h` + grid;
  nothing server-side cares about zone size. **The size blocker is purely client.**
- **Client renderer.** `cell` (tile px) is sized to fit the *whole* grid into the
  `#map` panel with a 14px floor:
  `cell = max(14, floor(min((area.w-24)/S.w, (area.h-24)/S.h)))`
  (`static/index.html:582`); the canvas is `S.w*cell × S.h*cell`, `#map` is
  `overflow:hidden` + centered. The hand-drawn map is cached offscreen by
  `renderMapLayer(visible)` (`:629`), re-rendered only when `roomId:you.x,you.y`
  changes; `draw()` (`:768`) blits it then draws entities/items/FX. FOV is
  `ROT.FOV.PreciseShadowcasting(isTransparent)` (`:773`, `isTransparent` at `:573`,
  `tileAt` at `:566`). Minimap `drawMinimap` (`:886`). The `zone_state` handler is
  at `:1044`. **A big grid today shrinks to unreadable or clips — no scroll.**
- **Admin CRUD** over rooms/npcs/items/exits exists (`handoff-10` §0); the
  designer UI + a few endpoints (list rooms, edit tiles, world-reload) are the
  known gap.

---

## 3. Scope — four slices

**In:** (A) structured per-tile data via a tile registry; (B) levels + z-floors +
the stacked overview; (C) adaptive follow-camera; (D) the author-time whole-floor
generator contract (the full designer remains `handoff-10`). Additive migrations,
accounts preserved, one worker.

**Out / deferred:** true 3D / cross-floor interaction (LOS, ranged, falling);
runtime/instanced procedural (we chose author-time bake — the persistent shared
world is untouched); per-cell unique decoration beyond the registry (the sparse
overlay in §4 is sketched but deferred); seamless multi-room coordinate merging
(big *grids* yes, dissolving room boundaries no); NPC/mob awareness of z;
biome/auto-tiling art (Phase-6 territory). The full **map designer UI** stays in
`handoff-10` — this handoff delivers the model + the generator contract it needs.

Build A → B → C → D. **A is the only Phase-1-class risk; do it isolated, first.**

---

## 4. Slice A — structured per-tile data (the spine)

The goal is "a tile is a record, not a char," without a destructive rewrite of
every authored layout or `seed.py`.

**Approach (recommended): keep glyph-string authoring, resolve through a registry.**
Authoring stays a glyph grid (terse, reviewable, diffable — the world's whole
ethos), but each glyph **resolves through a new data-driven `tiles.py` registry**
(mirroring `classes.py`/`spells.py`) into a full tile def:

```python
# tiles.py (new — data-driven, the designer's palette source)
TILES = {
  "#": {"name":"wall",   "walkable":False, "transparent":False, "transition":None},
  ".": {"name":"floor",  "walkable":True,  "transparent":True,  "transition":None},
  "+": {"name":"door",   "walkable":True,  "transparent":True,  "transition":"door"},
  "o": {"name":"pillar", "walkable":False, "transparent":False, "transition":None},
  "~": {"name":"water",  "walkable":False, "transparent":True,  "transition":None},
  ":": {"name":"rubble", "walkable":True,  "transparent":True,  "transition":None},
  ">": {"name":"stairs_down","walkable":True,"transparent":True,"transition":"down"},
  "<": {"name":"stairs_up",  "walkable":True,"transparent":True,"transition":"up"},
  # New tile types are now data, not code — e.g.:
  ";": {"name":"tall_grass",  "walkable":True,  "transparent":False, "transition":None},
  "^": {"name":"rough",       "walkable":True,  "transparent":True,  "transition":None},
}
```

- `BLOCKING`/`SIGHT_BLOCKING`/`TRANSITION_TILES` (`world.py:43–49`) become
  **derived** from the registry, not literal sets:
  `walkable(g) = TILES[g]["walkable"]`, etc. The three predicates
  (`_is_walkable_grid` `:244`, transparency `:460`, `transition_for_tile`'s glyph
  switch `:592–604`) read the registry. Unknown glyph → safe default (wall/opaque).
- `_load_tiles` (`world.py:199`) is unchanged structurally (still splits the
  string into rows); it just validates each glyph against `TILES`.
- **Snapshot:** keep sending the glyph grid (`zone_snapshot` `:738`) **plus a
  compact `tiledefs` map** of the glyphs present → `{walkable,transparent,name}`,
  so the **client derives** its `isTransparent`/render rules from data instead of
  the hard-coded `t!=='#' && t!=='o'` (`static/index.html:573`). New tile types
  then render/behave correctly with **no client code change**.
- **Per-cell uniqueness (deferred):** if two cells with the same glyph must
  differ (this floor has moss, that one doesn't), add a **sparse overlay** later —
  a `{(x,y): {...}}` map per room (this is exactly what a `RoomFeature` table
  would back; see §0). Not needed for the four locked decisions; flagged so the
  registry choice doesn't paint us in.

**Alternative (heavier, only if per-cell data is needed now):** replace the glyph
string with a structured 2D array (`Room.tiles` → JSON grid of tile objects). More
powerful, but a destructive migration + rewrites `_load_tiles`, `seed.py`, every
authored layout, and the renderer's row iteration. **Recommend the registry path**
and add the sparse overlay if/when per-cell data is real.

**Data model / migration:** no `Room` change for the registry path (glyphs stay in
`Room.tiles`). New file `tiles.py` + a `tiles` registry seed-populate (idempotent,
like the other registries). If the config layer from `handoff-10` §1 is in play,
`tiles.py` is the **first, lowest-risk registry** to move to data.

**Tests (`test_tiles.py`, extend):**
- Registry sanity: every authored glyph in `seed.py` exists in `TILES`; defaults sane.
- `_is_walkable_grid` / transparency / `transition_for_tile` derive from the
  registry (add a new glyph → walkable/sight follow without touching the predicates).
- `zone_snapshot` carries `tiledefs` for the glyphs present.
- Keep all prior tile/zone/realtime tests green (they pin the existing glyphs).

---

## 5. Slice B — levels & z-floors

**Data model (`models.py` + migration):**

| change | type | meaning |
|--------|------|---------|
| `Level` table | `id, name, description` | groups floors into a named area |
| `Room.level_id` | `Integer` FK → `levels.id`, nullable | the level this floor belongs to |
| `Room.z` | `Integer` default `0` | signed floor index within the level |

Additive (`migrate_maps.py`, idempotent, guard on `PRAGMA table_info`). **Existing
rooms** get a per-room default `Level` (each room → its own single-floor level,
`z=0`) so the live world is **unchanged** — the degenerate case. Seed authors real
multi-floor levels (e.g. the Manor: Foyer `z=0`, Cellar `z=-1`).

**Runtime — mostly reuse:**
- Vertical movement already works (`transition_for_tile` up/down → `move_player`).
  A `"down"` exit now connects two rooms with the **same `level_id`** at adjacent
  `z`; its reverse `"up"` exit is the return (existing `directions.py` reverse
  mapping). Validate at seed/designer time that stair pairs stay within a level.
- An **entrance** is any exit whose endpoints have **different `level_id`** (or a
  door/portal). No engine change — it's the same `RoomExit`, reinterpreted.
- `RoomNode` caches `level_id` + `z` at load (additive fields).

**Overview (`drawOverview`, `static/index.html:1852`) — the visible work:**
- Group visited rooms by `level_id`; render the **level graph** (levels as nodes,
  entrances as edges, locked marked — today's behavior, one level deep).
- For the level you're in, render the **floor stack**: floors as stacked cards by
  `z` (highest on top), current floor highlighted, with a **flip-floors**
  affordance (PageUp/PageDn or click). The hand-drawn cartouche style from
  `handoff-07` carries over.

**WS protocol:** extend `world_map` (`handoff-03` §7) to carry `level_id`/`z` per
room so the client builds both tiers. `zone_state.room` gains `level_id`/`z`.
Keep the connect sequence stable (the Phase 2–5 rule).

**Tests (`test_zones.py`, extend):**
- Migration idempotency (mirror the Phase 3/4/charsheet migration tests).
- Floors of a level group by `level_id`; stair up/down stays intra-level; an
  entrance crosses `level_id`.
- `world_map`/`zone_state` carry `level_id`/`z`.

---

## 6. Slice C — adaptive camera (client only)

Self-contained; rides loosely on A (works on plain glyphs too). Re-introduces the
camera-follow dropped in Phase 6 slice 2.

- **Pick a mode per floor.** Compute viewport capacity in tiles at a *readable*
  fixed cell (target ~22–28px, floor ~18). If `S.w × S.h` fits → **static** (keep
  the current fit-to-panel behavior). Else → **follow**: fix `cell`, center a
  camera window `{camX, camY}` on the player, clamped to grid bounds.
- **Coordinate offset.** Replace `x*cell` / `y*cell` with `(x-camX)*cell` /
  `(y-camY)*cell` in `draw()` (`:768`), `drawToken`, `drawReticle`, `drawFx`, and
  the click→tile inverse (so targeting/click-to-move map through the camera).
- **Reuse the offscreen cache.** `renderMapLayer` still renders the **full** floor
  to `mapLayer` once per zone/FOV change; `draw()` **blits the camera sub-rect**
  instead of the whole layer. No per-frame re-hatching → no shimmer (preserves the
  `handoff-07` §1.4 rule). For very large floors, optionally cap `renderMapLayer`
  to a margin around the camera + FOV; not required for MVP.
- **Minimap** (`drawMinimap`, `:886`) keeps showing the whole floor (it's the
  "where am I in the zone" view) with a camera-window rectangle overlaid.
- FOV (`PreciseShadowcasting`) over the full grid is fine at moderate sizes; cap to
  a window only if a level gets pathologically large.

**Tests:** extract the camera-window math (mode pick + clamp + tile↔pixel) into a
pure function and unit-test it (fits → static; oversized → centered + edge-clamped;
inverse maps a click back to the right tile). Rendering itself stays manual/visual.

---

## 7. Slice D — author-time generator (contract; full tool → handoff-10)

The full **map designer** stays in `handoff-10` §2 (now unblocked: the model is
settled and Slice A gives it the tile **palette** via `tiles.py`). This handoff
specifies only the **generator** so the procedural decisions are captured:

- **New `mapgen.py`** (author-time only — imported by the designer/CLI, **never**
  by the live sim). `generate(kind, w, h, params, seed) -> tile_grid` (a list of
  glyph rows using `tiles.py` glyphs). MVP kinds: `"cave"` (cellular automata) and
  `"rooms"` (BSP rooms + corridors). Deterministic given a seed.
- **Whole-floor, one-way bake.** Output replaces a floor's `Room.tiles` wholesale.
  After bake it's plain tiles — hand-edit freely. **Re-roll = regenerate from
  scratch** (loses edits). The tool stashes `{kind, params, seed}` as optional
  level/room metadata so you can re-roll cheaply *until* you start editing.
- **Hand-placed semantics.** `mapgen` emits **geometry only**. Spawn, stairs,
  entrances, items, NPCs are placed by hand afterward; wiring into the level graph
  / floor stack is always an authoring act. Generated output runs the **same
  validation** as hand-painted (rectangular rows, reachable spawn, exits on a
  border/stairs, no orphaned locks — reuse the designer's validator / `_load_tiles`
  rules).
- **Modes fall out of one pipeline:** hand-paint = skip generate; fully procedural
  = generate-then-save; generate-then-edit = the full path.

**Tests (`test_mapgen.py`):** a generated grid is rectangular, uses only registry
glyphs, is fully connected (flood-fill from any floor reaches all floor), and is
deterministic for a fixed seed; the validator accepts it.

---

## 8. Migration & deploy

Same additive, accounts-preserved pattern as Phases 3–5 (one worker):

1. `git pull`.
2. `python migrate_maps.py` — idempotent `ALTER TABLE rooms ADD COLUMN level_id`,
   `ADD COLUMN z DEFAULT 0`, create `levels`, guarded by `PRAGMA table_info`.
   **Back up `game.db` first.** (No `Room.tiles` change — the registry path keeps
   glyph strings.)
3. `python seed.py` — populate the `tiles` registry (idempotent); assign existing
   rooms to per-room default levels (`z=0`); author any real multi-floor levels in
   place (in-place tile/level update, no reseed — the Phase 2/3 pattern).
4. `systemctl restart bgid-api` → `world.load()` picks up registry + level/z.

Existing characters and rooms are preserved; the live world is unchanged until you
author multi-floor levels and large grids. Note this in the deploy.

---

## 9. Tests & definition of done

- Per slice: the tests in §4–7. Keep the **full prior suite green** (watch the
  shared `test_bgid.db` — one pytest at a time, per the project rule). Additive
  migrations only; no destructive schema changes.
- Each slice is independently shippable and deployed before the next.
- Docs: tick master §5 with this work; document `tiles.py` + the `tiledefs`
  snapshot field, `Level`/`Room.level_id`/`Room.z`, the level-graph/floor-stack
  overview, the camera, and the `mapgen` contract in `ARCHITECTURE.md`; refresh
  the in-repo memory entry on ship. Update `handoff-10` to note its §2 gate is
  resolved by §1 here.

**Done when:** structured tiles drive walkability/sight/render from data; a level
with stacked floors navigates by stairs and reads as a stack in the overview; a
large floor scrolls with a player-centered camera while small floors stay static;
`mapgen` bakes a valid whole floor a fresh Mage can walk — all over `wss://`, full
suite green.

---

## 10. Build order (suggested)

1. **Slice A — structured tiles.** `tiles.py` registry, derive the three
   predicates, `tiledefs` in the snapshot + client read, tests. *Isolated, highest
   risk, no visible change.*
2. **Slice B — levels & z.** `migrate_maps.py`, `Level`/`level_id`/`z`, reuse the
   up/down transitions, the stacked overview + flip-floors, `world_map`/`zone_state`
   fields, tests. *The level graph comes along for free.*
3. **Slice C — adaptive camera.** Mode pick, camera offset, blit the sub-rect of
   the cached layer, minimap window, click inverse, tests.
4. **Slice D — generator.** `mapgen.py` (cave + rooms, seeded) + validation +
   tests; the full designer UI lands in `handoff-10` against this contract.
