# BGID Architecture

A hybrid, browser-based MUD: multiple players sharing a persistent world,
with LLM-driven (DeepSeek) NPCs that respond in character.

This document describes the target architecture and the incremental plan to
get there. It is a living document — update it as the design evolves.

## Goals & constraints

- **Browser clients** are the primary target → WebSockets for live gameplay.
- **LLM NPCs** take 2–5s to respond → NPC turns must be async and pushed, never
  blocking a connection or a request.
- **Hobby scale** (tens to low-hundreds of concurrent players) → a single
  FastAPI process with an in-memory world + asyncio is sufficient. Keep the
  pub/sub behind an interface so a Redis backend can slot in later if needed.

## Transport decision: WebSockets (for gameplay)

A MUD's defining requirement is **server-pushed, room-scoped events**: a player
must learn about others' actions in their room without polling. That needs a
persistent push channel. For browser clients, WebSockets is the conventional
and correct choice, and the project already has the connection primitive
(`websocket_manager.py`).

Raw TCP (telnet) would suit a terminal MUD; SSE+POST is a viable simpler
alternative if we ever drop bidirectional needs. Neither is the target today.

## REST vs. realtime split

**Rule of thumb:** if it changes the shared world or must notify others → WS.
If it's a player or admin managing data → REST.

| Concern | Channel |
| --- | --- |
| Join world, `look`, `move`, `say`, `talk` (NPC), `attack`, `take`/`drop` | **WebSocket** |
| Player/Room/NPC/Item CRUD, content authoring, seeding, character sheets, health | **REST** (existing) |
| Initial room snapshot on connect | WS, sent immediately after the socket opens |

We deliberately avoid full REST/WS parity: duplicated surface is duplicated
bugs. REST stays for setup/admin/CRUD (and powers `admin.py`); all live
gameplay flows over the socket.

## Components

```
┌─────────────────────────────────────────────────────┐
│  WorldState  (authoritative, in-memory)             │
│   rooms{ id -> {name, desc, npc_ids, item_ids,      │
│                 players:set} }                       │
│   player_locations{ player_id -> room_id }          │
│   loaded from DB at startup; moves write through    │
└───────────────┬─────────────────────────────────────┘
                │ mutated by
┌───────────────▼──────────┐   ┌──────────────────────┐
│ CommandDispatcher        │   │ NPCTurnManager (async)│
│  parse {cmd,args} -> fn  │──▶│  talk -> asyncio task │
│  move/say/look/attack/   │   │  -> DeepSeek (2-5s)   │
│  talk/take               │   │  -> push npc_said     │
└───────────────┬──────────┘   └──────────┬───────────┘
                │ emits events             │
┌───────────────▼─────────────────────────▼───────────┐
│ ConnectionManager  (websocket_manager.py)           │
│  player_id <-> socket;  broadcast_to_room(room,evt) │
└──────────────────────────────────────────────────────┘
```

- **WorldState** *(new — `world.py`)*: the live source of truth for who/what is
  where. The DB is for persistence and recovery, not live reads. Structural
  data (rooms, NPCs, items) is cached at load; player presence is tracked live;
  `reload()` resyncs after admin edits.
- **ConnectionManager** *(have — `websocket_manager.py`)*: socket registry, room
  subscriptions, `broadcast_to_room`, personal messages. Already capable.
- **CommandDispatcher** *(new)*: parses inbound WS messages and routes to
  handlers that mutate `WorldState` and emit events.
- **NPCTurnManager** *(new, wraps existing LLM path)*: runs the DeepSeek call as
  an async task and pushes the result into the room. Reuses
  `deepseek_integration` + `BaseLLMNPC`.
- **Game loop / tick** *(later)*: optional asyncio task for NPC wandering,
  combat rounds, regen, timed events.

The existing in-memory `ChatManager` (global/room/private routing) overlaps with
room-scoped broadcast; its routing idea folds into the dispatcher/world.

## Async NPC turn (the headline mechanic)

```
player → {"cmd":"talk","npc_id":1,"text":"who are you?"}
  dispatcher: ack + broadcast {"event":"npc_thinking","npc_id":1} to room
  asyncio.create_task(deepseek_call)          # non-blocking
  on done: broadcast {"event":"npc_said","npc_id":1,"text":"..."} to room
```

No socket blocks while an NPC "thinks"; other players keep acting; the
"Caretaker is thinking…" beat is good MUD texture.

## Message protocol (initial)

Client → server:

```json
{"cmd":"look"}
{"cmd":"move","dir":"north"}
{"cmd":"say","text":"hello"}
{"cmd":"talk","npc_id":1,"text":"who are you?"}
{"cmd":"attack","npc_id":3}
```

Server → client:

```json
{"event":"room_state","room":{...},"players":[...],"npcs":[...],"items":[...]}
{"event":"chat","from":"Bryan","text":"hello"}
{"event":"npc_thinking","npc_id":1}
{"event":"npc_said","npc_id":1,"name":"Caretaker","text":"..."}
{"event":"player_entered","player_id":2,"name":"Aria"}
{"event":"player_left","player_id":2,"name":"Aria"}
{"event":"error","detail":"..."}
```

### Tile protocol (Phase 1 — replaces the in-room movement messages)

The single-room tiled view uses a hard-cutover protocol (closed alpha, no
back-compat). `room_state` → `zone_state`; `move {dir}` → `move {dx,dy}`:

```json
// client → server
{"cmd":"move","dx":1,"dy":0}        // one orthogonal step (bump = attack)
{"cmd":"attack","target_id":13}     // explicit adjacent melee
{"cmd":"talk","npc_id":1,"text":"…"}// unchanged (Layer 2)
{"cmd":"say","text":"…"}            // unchanged
{"cmd":"look"}                      // resends zone_state
{"cmd":"map"}                       // request the zone-graph (Phase 2)

// server → client
{"event":"zone_state","room":{...},"tiles":{"w":12,"h":9,"grid":["############", …]},
 "you":{"id":7,"x":3,"y":4,"glyph":"🧙","hp":10,"max_hp":10},
 "entities":[{"id":13,"kind":"npc","name":"Cellar Rat","glyph":"🐀","x":9,"y":6,
              "hostile":true,"hp":8,"max_hp":8}, …]}
{"event":"entity_moved","id":13,"x":8,"y":6}
{"event":"entity_spawned","id":2,"kind":"player","name":"Aria","glyph":"🧙","x":3,"y":4}
{"event":"entity_died","id":13,"kind":"npc","name":"Cellar Rat","by":"Bryan"}
{"event":"entity_left","id":2,"name":"Aria"}
{"event":"combat","attacker":"Bryan","attacker_id":7,"target":"Cellar Rat","target_id":13,
 "hit":true,"damage":4,"target_hp":4,"target_max_hp":8}
{"event":"player_defeated","player_id":7,"name":"Bryan","by":"Cellar Rat"}
{"event":"respawn","room_id":1,"health":10}
// Phase 2: stepping onto a border door / stairs moves zones — server sends a
// fresh zone_state to the mover and entity_left/entity_spawned to the two zones.
{"event":"world_map","rooms":[{"id":1,"name":"Foyer"}],
 "exits":[{"from":1,"to":2,"dir":"north","locked":false}]}
```

## Graphical overhaul — two-tier tiled world (Phase 1)

BGID is being reshaped into an **overhead, real-time roguelike** while keeping
the LLM social layer. Two tiers share one world view (see
`docs/handoff-01-graphical-overhaul-master.md`):

- **Layer 1 — the dungeon (no LLM):** each room is now an overhead **tile grid**
  (`Room.width/height/tiles/spawn_x/spawn_y`; glyphs `#` wall, `.` floor, `+`
  door). `WorldState` tracks live tile positions (`RoomNode.player_pos` /
  `npc_pos`) and resolves all movement through one helper, `try_step` →
  `MOVED | BLOCKED | ATTACK` (bump-to-attack). Melee is adjacency-gated and
  single-strike. A **fast combat tick** (`game_loop._combat_loop`,
  `COMBAT_TICK_SECONDS≈0.3`, separate from the 15s regen tick) drives hostile
  mob AI: acquire nearest player in `aggro_radius`, `step_toward`, melee when
  adjacent. The hot tick is **DB-free for movement** (positions in memory).
- **Layer 2 — the story (LLM):** unchanged `talk`/`npc_said`, plus a throttled
  **smack-talk bridge** (`smack_talk.py`): Layer-1 combat events fan out to short
  in-character barbs, gated by a per-mob cooldown + a per-room global budget
  (`rate_limit.check_mob_chatter`), with a **canned-barb fallback** so combat
  stays playable and free when DeepSeek is off/throttled.

**Client** (`static/index.html` + vendored `static/vendor/rot.min.js`): a rot.js
`Display` renders the tiles with `ROT.FOV.PreciseShadowcasting` fog-of-war
(center), a Layer-2 dialogue sidebar (right), and a combat-log/stats/actions
strip (under the map). Movement is WASD/arrow keys; bump a foe to attack.

Phase 1 is scoped to a **single tiled room** (no zone-to-zone door transitions —
that's Phase 2). The room-graph (`RoomExit`, `directions.py`) and the REST
`/action` movement remain intact underneath for Phase 2 to build on.

## Persistence strategy

- Load full world from DB at startup.
- **Write-through** on durable mutations (player room changes, health, items).
- Ephemeral state (who is online, "thinking" flags, transient combat timers)
  lives only in memory.
- On clean shutdown, optionally flush. Crash recovery = reload from DB; online
  presence is naturally rebuilt as clients reconnect.

## Scale notes

Single process + asyncio + in-memory `WorldState` + WS handles the target load.
`broadcast_to_room` is the seam: keep it an interface so a Redis pub/sub backend
can replace the in-process version for multi-worker deployments — but only if
that day comes. Do not build it now.

## Incremental build plan

Each step keeps the app runnable.

1. ✅ **WorldState** (`world.py`) — load rooms/NPCs/items/player-locations from
   DB at startup; room snapshots; player presence; `move_player` write-through.
2. ✅ **Real `/ws` handler** — on connect, join the world and send `room_state`;
   `look` / `move` / `say` with room broadcast; presence enter/leave.
3. ✅ **NPC turns** (`npc_turns.py`) — `talk` runs the DeepSeek call as a
   fire-and-forget task and broadcasts `npc_thinking` / `npc_said` room-wide.
4. ✅ **Combat & tick** (`combat.py`, `game_loop.py`) — `attack` (turn-based,
   death/respawn, room-wide) and a periodic NPC-regen tick.

5. ✅ **Room graph** (`models.RoomExit`, `directions.py`) — directed exits with
   locks/keys; direction-based, lock-aware movement (WS + `/action`); exits in
   room_state/`/state`; exit-management API.

6. ✅ **Tiled combat slice** (graphical overhaul Phase 1) — rooms become overhead
   tile grids; per-tile movement + FOV; bump-to-attack melee; a real-time mob-AI
   combat tick (aggro/path/melee); LLM smack-talk with canned fallback; rot.js
   three-region client. Single room only — zones/doors are Phase 2. See
   `docs/handoff-02-phase1-tiled-combat-slice.md`.

7. ✅ **Zones & the map** (Phase 2) — stepping onto a border door (cardinal) or
   stairs (`>`/`<`, up/down) transitions between tiled zones, resolved against
   the existing room-graph exits (`world.transition_for_tile`/`arrival_tile`)
   with lock/key enforcement; all seeded rooms tiled; per-zone explored memory +
   a current-zone minimap; an on-demand overview map (`map` command → `world_map`
   event; zone graph with visited rooms + locked exits). See
   `docs/handoff-03-phase2-zones-and-map.md`.

### Future
- Per-NPC conversation memory across `talk` turns.
- Richer combat (initiative, abilities, NpcReaction-driven aggro) and a real
  NPC AI tick (wandering, hostiles engaging on sight).

### Out of scope here (tracked separately)
- Reactions endpoint (`/npcs/{id}/reaction/...`) the CLIs expect (P1).
- `pytest-asyncio` test harness (P1).
- Config/seed cleanup, committed cruft (P2).
