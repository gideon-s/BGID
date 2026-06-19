# Handoff 09 — Traps & environments

**Status:** ready to build (independent slices) · **Depends on:** the live world
(tiled rooms, NPC AI, combat, the status-effect layer). **Goal:** make zones feel
*alive and dangerous* beyond hand-placed mobs — **traps & hazard tiles**,
**interactive props (signs, etc.)**, **monster spawners**, **wandering mobs**, and
**room types (safe zones / sanctuaries, taverns)**. Each section is an independent
slice; pick any order (suggested order in §8).

> Read `world.py` (tile palette + `RoomNode`/`try_step`), `game_loop.py`
> (`_combat_tick_once` mob AI), and the move handler in `main.py` first.

---

## 0. What exists now (the seams)

- **Tiles** (`world.py`): a small glyph palette — `#` wall, `.` floor, `+` door,
  `o` pillar, `~` water, `:` rubble, `>`/`<` stairs. `BLOCKING = {#, o, ~}`,
  `SIGHT_BLOCKING = {#, o}`, `TRANSITION_TILES = {+, >, <}`. A room's layout is the
  `Room.tiles` Text column (one row per line); the client renders it in
  `renderMapLayer()`.
- **Movement** routes through `world.try_step(kind, id, room, dx, dy)` → MOVED /
  ATTACK / BLOCKED; the `move` WS handler in `main.py` acts on the result (and runs
  zone transitions on `>`/`<`/`+`). **This is the choke point to fire a trap on entry.**
- **Mob AI** (`game_loop._combat_tick_once`): hostile NPCs (`world.hostile_mobs`)
  aggro a player within `aggro_radius`, path toward, and melee. **Non-hostile NPCs are
  stationary — there is no wandering.** Slain mobs respawn at `home_x/home_y` after
  `MOB_RESPAWN_SECONDS`. NPC fields: `is_hostile`, `aggro_radius`, `combat_enabled`,
  `home_x/y`, `glyph`, abilities, hp.
- **Props**: items can be **immovable** (`is_movable=False`, e.g. the Sturdy Stool /
  Old Chest). The chest uses a custom `open` WS cmd resolved via `world.chest_near`.
  This is the template for new interactive props.
- **Safe zone**: `config.PVP_SAFE_ROOM_IDS` (the Foyer) blocks PvP only.

---

## 1. Traps & hazard tiles

New tile glyphs that *do something* when an entity enters or stands on them.

- **Add glyphs** to `world.py`: e.g. `TRAP = "^"`, `HAZARD = "≈"` (lava/spikes). Decide
  walkability (a trap is walkable; a permanent hazard like lava could be BLOCKING or
  walkable-with-damage). Update the walkable/sight sets accordingly and **render them**
  in `renderMapLayer()` (a sketchy ink "^" / a hatched danger fill) + the minimap.
- **Trigger on entry**: in the `move` handler, after a `MOVED` result, check the new
  tile — if it's a trap/hazard, apply an effect to the player via the shared
  `combat.damage_player` (instant damage) and/or `effects.apply_effect` (a DoT / a
  debuff — "caught in spikes", "burning"). Mobs stepping on traps should take it too
  (apply in `try_step`/the mob AI path for symmetry — optional).
- **Hidden vs telegraphed**: MVP = **telegraphed** (drawn, everyone sees them — a
  tactical-positioning hazard). Stretch = **hidden** traps revealed by a detection
  roll (per-room `revealed` set; a Survival/Perception skill check on approach), and
  **one-shot** traps (a `sprung` set so a spike trap fires once).
- **Authoring**: traps live in `Room.tiles` like any glyph — no schema change for the
  tile itself. Per-trap data (damage, effect) can be a small `traps.py` registry keyed
  by glyph, or (richer) a `RoomFeature` row (see §3) for per-tile config.

**Acceptance:** stepping onto a `^` tile deals damage (a floating number) / applies a
DoT; the tile is drawn distinctly; a one-shot trap fires once.

## 2. Interactive props — signs & readables

A readable/usable object you interact with (the chest is the pattern).

- **Signs**: an immovable `item_type:"sign"` item carrying its text in `description`.
  A `read` WS cmd (mirror `open`/`world.chest_near` → a `world.prop_near(room,x,y,type)`
  helper) returns the text as an `info`/a dedicated `sign` event the client shows in a
  small popup. The client shows a **read** button on adjacent sign props + an `R`-style
  affordance / `read` text verb (mirror the chest's `open`/O).
- Generalize: a `prop` concept covers signs, levers (toggle a door/trap), fountains
  (drink → heal), altars (buff). Keep them as `is_movable=False` items with an
  `item_type` + an interaction handler, so they ride the existing ground-item rendering
  + token generation.

**Acceptance:** walking up to a sign and reading it shows its text; props render with
their glyph/token and aren't pick-up-able.

## 3. Monster spawners

A source that keeps an area populated (vs today's fixed, hand-placed mobs).

- **Model**: a spawner references a **mob template** + `interval`, `max_active`, and a
  spawn radius/tile. Two viable shapes:
  - **NPC-as-spawner**: an `npc_type:"spawner"` NPC (immobile, non-combat, a glyph like
    a nest/portal) with spawner config in new columns or a `spawners.py` registry keyed
    by the template name.
  - **Room/feature-driven**: a `RoomFeature` table `(room_id, x, y, kind, config JSON)`
    — a general "things attached to a tile" table that also serves §1 trap config and
    §2 prop config. Cleaner long-term; one additive migration.
- **Tick**: in the combat tick (or a dedicated spawner tick), for each spawner with
  `live_count < max_active` and `now >= next_spawn`, spawn a mob at a free tile in
  radius. **Reuse the NPC machinery**: either create a fresh `Npc` row (and `world`
  registers it like a normal mob — broadcast `entity_spawned`) or maintain a **pool**
  of pre-made NPC rows the spawner revives (avoids unbounded row growth). Track
  spawner→children so `live_count` decrements on a child's death.
- Spawned mobs use the normal hostile AI (§0) + loot/XP on death.

**Acceptance:** a spawner repopulates its area up to its cap on a timer; clearing the
area triggers fresh spawns after the interval; spawned mobs aggro/loot/grant XP normally.

## 4. Wandering mobs

Idle movement so non-aggroed mobs don't stand like statues.

- Add a **`wanders`** flag to NPCs (a column, additive migration — or derive from
  `npc_type`). In `_combat_tick_once`, for a hostile-or-neutral mob that is **not
  aggroed** and `wanders`: on a per-mob wander cooldown (a new `MOB_WANDER_COOLDOWN`,
  slower than the chase cadence), step to a random adjacent walkable, unoccupied tile
  (bounded near its `home` so it doesn't drift across the zone — a leash radius).
- Keep it cheap (DB-free, like the existing AI). Broadcast `entity_moved` as usual;
  the client already tweens it. A wandering mob that sees a player still aggros (the
  existing path takes over).

**Acceptance:** neutral/idle mobs amble around their home tile; they still aggro on
sight; movement is smooth (rides the existing tween).

## 5. Room types — safe zones / sanctuaries & taverns

Per-room behavior beyond geometry.

- **Schema**: add `Room.room_type` (e.g. `dungeon`/`town`/`tavern`/`sanctuary`) and/or a
  `flags`/`is_safe` column (one additive migration). Load into `RoomNode`.
- **Sanctuary**: extends today's `PVP_SAFE_ROOM_IDS` to a per-room flag AND suppresses
  **mob aggro** (mobs don't acquire targets in a sanctuary — check in
  `nearest_player_within`/the aggro step) and optionally slow **out-of-combat regen**.
  Make `PVP_SAFE_ROOM_IDS` fall back to "rooms flagged safe" so it's data-driven.
- **Tavern**: a room (the Foyer/an inn) with a **`rest`** WS cmd — while resting (and
  out of combat) the player recovers HP/mana faster, or a flat heal for a coin fee paid
  to the Innkeeper (ties to the economy). The Innkeeper vendor already lives here.
  Ambient flavor (a `room.description`, later sound/portrait).

**Acceptance:** a sanctuary blocks PvP *and* mob aggro and reads as safe; `rest` in a
tavern restores the player (free trickle or a paid full-heal).

---

## 6. Cross-cutting: a `RoomFeature` table?

§1 (per-trap data), §2 (prop config), and §3 (spawners) all want **per-tile attached
data**. Strongly consider one additive table early:

    RoomFeature(id, room_id, x, y, kind, config: JSON)   # kind ∈ trap|sign|spawner|portal|…

It generalizes "stuff on a tile that isn't a plain item/npc", keeps `Room.tiles` purely
geometric, loads into `RoomNode.features`, and is exactly what the **map designer**
(handoff-10) will read/write. If you build it, §1–3 become config in this table rather
than bespoke registries.

## 7. Tests & DoD

- Trap entry deals damage/DoT (drive the `move` path; assert `combat`/`stats`); one-shot
  fires once.
- Sign `read` returns the text; prop isn't grabbable.
- Spawner spawns up to the cap on a forced tick and respects it; child death frees a slot.
- Wandering mob moves on a forced tick within its leash; still aggros on sight.
- Sanctuary blocks PvP + mob aggro; tavern `rest` restores.
- Keep the suite green; additive migrations only (no destructive schema changes).
  `ARCHITECTURE.md` + memory updated on ship.

## 8. Build order (suggested)

1. **§6 `RoomFeature`** (if adopting it) — unblocks 1–3 cleanly.
2. **§4 wandering** (small, high life-to-effort) + **§1 traps** (telegraphed first).
3. **§3 spawners**.
4. **§5 room types** (sanctuary + tavern `rest`).
5. **§2 props/signs** + the hidden-trap stretch.
