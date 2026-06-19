# Handoff 10 — Authoring tool suite (map designer + content editors)

**Status:** design / phased build · **Depends on:** the admin layer (account/character
console + admin-gated REST CRUD), the world model, and the content registries.
**Goal:** give admins **in-browser authoring tools** instead of editing seed code:
a **map designer**, and editors for the **monster list, spells & effects, magic items,
classes, and races**. The big architectural lever is **moving code registries to a
data/config layer** so they're editable at runtime (§1).

> ⚠️ **The map designer (§2) is gated on a maps-model decision.** Bryan wants to change
> how maps work; settle that first (see "Maps — discussion" at the bottom) so the
> designer is built against the *new* model, not retro-fitted.

---

## 0. What exists now (the seams)

- **Admin auth + UI**: `get_current_admin`, the `/admin/*` account/character endpoints,
  and the **admin overlay** in `static/index.html` (`#adminview`, `renderAdmin`) — the
  pattern + home for new tool panels (or a dedicated `/admin` page).
- **World data is DB-backed with admin REST CRUD**: `POST/PUT/DELETE /players`,
  `POST /rooms`, `POST /rooms/{id}/exits`, `DELETE …/exits/{dir}`, `POST /items`,
  `POST /npcs` (all `Depends(get_current_admin)`). `Room` carries
  `name/description/width/height/tiles/spawn_x/spawn_y`; `Npc`/`Item` are full rows.
  After edits, `world.reload()` resyncs the in-memory world (preserving online players).
  **Missing for a designer:** `GET /rooms` list, `PUT /rooms/{id}` (edit tiles/name),
  room/feature deletion, and a "reload world" trigger.
- **Content registries are CODE** (Python dicts, not DB): `classes.py`, `races.py`,
  `spells.py`, `skills.py`, `shops.py`, `loot.py`, `potions.py`, `effects.py`. The game
  reads them directly at runtime. **A tool can't edit these without a data layer (§1).**

---

## 1. The lever — registries: code → data/config

To edit spells/classes/races/items/effects from a UI, the game must read them from
**data**, not hard-coded dicts. Recommended:

- **A config layer**: each registry becomes a JSON document (a `content/` dir, or DB
  rows in a `Content(kind, key, data JSON)` table). The existing modules become thin
  loaders: `spells.SPELLS = load("spells")`, with the authored Python kept as the
  **default/seed** that populates the store on first run (idempotent, like `seed.py`).
- **Editing** = write the JSON/row + hot-reload the registry (a `reload_content(kind)`
  call, admin-triggered) so changes apply without a restart. Validate on write
  (schema per kind) so a bad spell can't crash combat.
- **Why phased:** do this **per registry, lowest-risk first** (items/potions/loot →
  spells/effects → classes/races, which touch character creation + migration defaults).
  Things already DB-backed (rooms/npcs/items rows) need *no* config layer — only the
  designer UI + a few endpoints.

This is the prerequisite for §4–6; §2–3 mostly need UI + endpoints over existing DB rows.

## 2. Map designer  ⚠️ (gated on the maps discussion)

A canvas tool to author a zone: paint tiles, set the spawn, place exits/items/npcs/
features, edit name/description — saving to the DB and live-reloading the world.

- **UI** (admin-only, likely its own `/admin/map` page given the canvas size): a tile
  **palette** (wall/floor/door/pillar/water/rubble/stairs + any new trap/hazard glyphs
  from handoff-09) you paint into a grid; tools to set the **spawn tile**, draw
  **exits** (pick a border tile/stairs → target room + lock/key), drop **items/NPCs/
  spawners** (from the monster/item lists, §3/§5), and edit the room **name/description**.
  Render with the *same* hand-drawn renderer so authoring looks like play.
- **Backend**: `GET /rooms` (list), `PUT /rooms/{id}` (name/desc/width/height/tiles/
  spawn), create/delete rooms, place/move/remove items+npcs at tiles, exits CRUD (mostly
  exists), and a `POST /admin/world/reload` → `world.reload()`. Plus `RoomFeature` CRUD
  if handoff-09 §6 lands (traps/signs/spawners are features).
- **Validation**: rectangular rows, a reachable spawn, exits aligned to a border/stairs,
  no orphaned locks. Reuse `world._load_tiles` rules.

**Why gated:** the designer's whole UX is the tile model. If maps change (bigger zones?
layers? a seamless world vs discrete rooms? procedural rooms? off-grid features?), the
palette, the grid, exits, and the renderer all change. **Decide the maps model before
building this** — see the discussion prompt below.

## 3. Monster list (NPC authoring)

NPCs are already DB rows; this is a list + editor UI over them (+ a few endpoints).

- A table of NPCs (name, type, room, hostile/aggro/combat, hp, abilities, glyph,
  home, loot table, vendor stock if any) with create/edit/delete; place on a tile via
  the map designer. Surface the **loot table** (`loot.py`) and **AI flags**
  (`wanders` from handoff-09) here. If §1 lands, the loot table becomes editable data.
- Endpoints: `GET /npcs`, `PUT /npcs/{id}`, `DELETE /npcs/{id}` (+ the existing POST),
  then `world.reload()`.

## 4. Spells & effects editor

Needs §1 (spells/effects → data). Editor over `spells.py` (name, glyph, cost, cooldown,
range, shape self/bolt/blast, effect kind damage/heal/**buff/debuff** + dice/mod/params)
and `effects.py` templates (atk/dmg/defn/haste/dot/duration). Validate against the
casting engine's expectations so a saved spell is castable. Live-reload.

## 5. Magic items editor

Mostly DB (items are rows) + a **templates** notion for shop/loot/chest gear. Editor for
item templates (name, glyph, type, equip_slot, bonuses, value, effect-granting fields
from handoff-08 §3) feeding `shops.py`/`classes.starting_gear`/loot — those registries
move to data (§1). Generated **tokens** (Phase 5/6) regenerate when a template changes.

## 6. Classes & races editor

Highest-risk (touches character creation + the migration defaults). Needs §1. Editor over
`classes.py` (abilities, glyph, mana, spells, `starting_gear`, skills) and `races.py`
(ability nudges). Guard: don't let an edit orphan existing characters' `char_class`/
`race`; keep the `wanderer`/migration fallbacks.

## 7. Tests & DoD

- Endpoint CRUD + auth (admin-only, mirror `test_admin.py`); `world.reload()` reflects
  edits without dropping online players.
- For §1: a registry round-trips through the config store and hot-reloads; an invalid
  document is rejected (no crash).
- Map designer: a saved layout validates + loads (reuse `world._load_tiles`).
- Suite green; additive migrations only. `ARCHITECTURE.md` + memory updated on ship.

## 8. Build order (suggested)

1. **§3 monster list** + the missing `GET/PUT/DELETE` room/npc endpoints + `world.reload`
   trigger — quick wins over existing DB rows, and they back the designer.
2. **Maps discussion → decide the model** (blocks §2).
3. **§2 map designer** against the agreed model.
4. **§1 config layer**, then **§4 spells/effects → §5 items → §6 classes/races** editors,
   lowest-risk first.

---

## Maps — discussion prompt (decide before §2)

Today: the world is **discrete tiled rooms** (a `Room.tiles` string per zone, small
hand-authored grids) connected by a **room-graph** of directed `RoomExit`s (doors on
borders, stairs up/down); you see one zone at a time with fog-of-war, and the M-overview
shows the zone graph. Tiles are a 8-glyph palette; the look is the hand-drawn renderer.

Open questions for the change Bryan wants (answers reshape §2):
- **Zone size & shape** — stay with small per-room grids, or larger / variable / irregular?
- **One world vs rooms** — keep discrete zones with transitions, or a seamless contiguous
  map (shared coordinates, scrolling camera)?
- **Authoring source** — hand-painted (the designer), procedural generation, or both
  (authored landmarks + procedural fill)?
- **Layers / features** — multi-floor (the stairs already hint at this), off-grid props,
  decorative vs collision layers?
- **Palette** — extend the glyph set (traps/hazards/biomes) or move to per-tile data?

Bring these to the table; the answers set the map model, then the designer is built once,
against the right thing.
