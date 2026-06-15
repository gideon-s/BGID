# Handoff 03 — Phase 2: Zones & the Map

**Status:** ready to build · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phase 1 (shipped). **Goal:** turn the single tiled room into a navigable
multi-zone world — walk through doors/stairs between tiled zones, with a minimap
of the current zone and an overview map of the zone graph.

> Read master §3 (current architecture, now Phase-1-updated) and the Phase 1
> handoff first. Phase 1 left the **room-graph (`RoomExit`, `directions.py`) and
> REST `/action` movement intact underneath** specifically so Phase 2 can wire
> doors to it. We reuse it; we don't rebuild it.

---

## 1. The slice (acceptance demo)

1. Spawn in the tiled **Foyer**. Walk onto the **north doorway** → arrive in the
   tiled **Great Hall** (fresh `zone_state`); others in each zone see you
   leave/arrive.
2. Walk back **south** → Foyer.
3. Step onto the **Cellar stairs (`>`)** → blocked unless you carry the **Rusty
   Key**; with the key, descend to the **Cellar**; the **up stairs (`<`)** return
   you to the Foyer.
4. A **minimap** panel shows the current zone with explored tiles; pressing **M**
   (or a button) shows the **zone-graph overview** — visited rooms as nodes,
   exits as edges, the current room highlighted, locked exits marked.

If all four work and presence is correct across zones, Phase 2 is done.

---

## 2. In scope / out

**In:** tile layouts for every seeded room; door-tile (cardinal) + stair-tile
(up/down) transitions; lock/key enforcement on transitions; per-zone explored
memory; current-zone minimap; zone-graph map overlay; multiplayer presence
across zones; tests; in-place migration + deploy.

**Out (later):** procedural generation (never — authored world); persisting live
`(x,y)` across reconnects; inventory/equipment (P3); spells/classes (P4);
portraits (P5); new mobs (the Cellar Rat stays in the Foyer for now).

---

## 3. Tile palette additions (`world.py` + client)

Phase 1 added `#`/`.`/`+`/`o`/`~`/`:`. Phase 2 adds **stairs**:

- `>` stairs down, `<` stairs up. **Walkable, transparent.** Rendered as gold
  chevrons. No new DB column — they're just layout glyphs.
- The door `+` becomes **functional**: a door on a room *border* maps to that
  border's cardinal exit.

No schema change: transitions ride the existing `RoomExit` rows
(direction → to_room, `is_locked`, `key_item_id`).

---

## 4. Transition model (`world.py` + `main.py`)

- `world.transition_for_tile(room_id, x, y) -> exit | None`:
  - `<` → `up`, `>` → `down`.
  - `+` on the top row → `north`, bottom row → `south`, left col → `west`,
    right col → `east`.
  - Returns `RoomNode.exits[direction]` (or None — a border door with no exit is
    decorative).
- In the WS `move` handler, when `try_step` returns **MOVED**, check
  `transition_for_tile` at the new tile. If it yields an exit:
  - **Lock:** if `is_locked` and the player doesn't hold `key_item_id` → soft
    `error`, remain in place (don't consume the step visually — they're standing
    on the threshold).
  - Else **transition**: `world.move_player(pid, to_room)` (room-graph + DB
    write-through), `place at arrival tile`, move WS room subscription, broadcast
    `entity_left` (old zone) + `entity_spawned` (new zone), send `zone_state`
    (new zone) to the mover.
- **Arrival tile:** the destination's transition tile whose exit points *back*
  (reverse direction) — stand on the floor just inside it; else the destination
  `spawn`. Implement `world.arrival_tile(dest_room, from_direction)`.

---

## 5. World migration (`seed.py` + in-place deploy)

Author tiled layouts for **Great Hall** and **Cellar**, aligning door/stair tiles
to the seeded exits:

- Foyer **north** door ↔ Great Hall **south** door (open).
- Foyer **`>`** stairs ↔ Cellar **`<`** stairs (the locked down/up pair; Rusty
  Key). Re-author the Foyer so its transition tiles sit on the correct walls
  (the Phase-1 decorative south doors get repurposed/removed).
- Keep NPC/spawn tiles on open floor. Cellar Rat stays in the Foyer.

Deploy is an **in-place tile update** of the seeded rooms (as we did shipping the
shaped Foyer) — **no reseed, accounts preserved.** Schema is unchanged.

---

## 6. Map + minimap (client)

- **Per-zone explored memory:** `S.exploredByRoom[roomId]`; on `zone_state`, swap
  to that room's set instead of wiping — returning to a zone shows what you'd
  seen.
- **Minimap:** a small always-on canvas in the panel rendering the current zone's
  explored tiles + entities (reuse the wall-tracer at small scale, or a
  simplified block renderer).
- **Overview map (press `M`):** the **zone graph** — visited rooms as nodes,
  exits as edges (locked marked), current room highlighted. Reveal nodes as
  visited. A simple force-free layout (BFS from start, grid placement) is fine.

---

## 7. Server data for the map (`main.py`)

- New server→client event **`world_map`**, sent once on connect (after the first
  `zone_state`): `{rooms:[{id,name}], exits:[{from,to,dir,locked}]}`, derived from
  `world.rooms`/`exits`. The client builds the graph and reveals nodes as the
  player visits them.

---

## 8. WS protocol delta

Reuse `zone_state` / `entity_left` / `entity_spawned`. **Add** `world_map`
(server→client, on connect). `move {dx,dy}` is unchanged — a zone transition is
the server-side consequence of stepping onto a transition tile.

---

## 9. Tests

- `transition_for_tile` mapping: border doors→cardinals, `<`/`>`→up/down,
  interior door→None.
- Stepping onto a door moves zones: mover gets `zone_state` for the new room;
  old zone gets `entity_left`, new zone `entity_spawned`. Arrival tile correct.
- Locked stairs blocked without the key; allowed holding it.
- Per-zone explored retained on return (client logic — unit-test the data model
  if practical, else manual).
- `world_map` shape.
- Keep auth / combat / rate-limit / Phase-1 tile tests green.

---

## 10. Deploy

- **No schema change**, **no reseed** — update the seeded rooms' `tiles` (+ any
  spawn) in place on the box, then restart (`world.load()` picks them up). One
  worker. Accounts preserved.

---

## 11. Definition of done

- The four acceptance steps work over `wss://`.
- Full suite green (new transition/map tests + Phase-1 tests).
- Docs: tick master §5 Phase 2; note `world_map` + stair tiles in
  `ARCHITECTURE.md`.

---

## 12. Build order (suggested)

1. **Spine:** stair tiles + `transition_for_tile`/`arrival_tile` + WS transition
   on step + locks + tiled Great Hall/Cellar + tests + deploy. *(zones navigable)*
2. **Map:** per-zone explored, minimap, `world_map` event, overview overlay +
   tests + deploy. *(the map)*
