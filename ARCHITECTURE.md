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
{"cmd":"move","dx":1,"dy":0}        // one tile step, orthogonal or diagonal (bump = attack)
{"cmd":"attack","target_id":13}     // explicit adjacent melee
{"cmd":"talk","npc_id":1,"text":"…"}// unchanged (Layer 2)
{"cmd":"say","text":"…"}            // unchanged
{"cmd":"look"}                      // resends zone_state
{"cmd":"map"}                       // request the zone-graph (Phase 2)
{"cmd":"inventory"}                 // request the inventory (Phase 3)
{"cmd":"pickup","item_id":5}        // item_id optional → item on your tile
{"cmd":"drop","item_id":5}          // onto your tile
{"cmd":"equip","item_id":5}         // / {"cmd":"unequip","item_id":5}
{"cmd":"spells"}                    // request the spellbook (Phase 4)
{"cmd":"cast","spell_id":"firebolt","x":9,"y":6}  // x/y omitted for self spells
{"cmd":"sheet"}                     // request the character sheet

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
// Phase 3: ground items ride zone_state ("items":[…]); inventory is personal.
{"event":"zone_state", …, "items":[{"id":5,"name":"Iron Sword","glyph":"⚔️","x":2,"y":1}]}
{"event":"inventory","items":[{"id":5,"name":"Iron Sword","glyph":"⚔️","type":"weapon",
 "equip_slot":"weapon","equipped":true,"attack_bonus":1,"defense_bonus":0,"damage_bonus":2}]}
{"event":"item_dropped","id":5,"name":"Iron Sword","glyph":"⚔️","x":3,"y":3}
{"event":"item_taken","id":5,"by":"Bryan"}
// Phase 4: classes/spells/mana. zone_state.you carries mana/max_mana; spellbook
// + stats are personal; spell_cast is the VFX broadcast; damage rides `combat`.
{"event":"spellbook","char_class":"mage",
 "spells":[{"id":"firebolt","name":"Firebolt","glyph":"🔥","cost":3,"cooldown":1.0,
            "range":6,"shape":"bolt","radius":0}]}
{"event":"spell_cast","caster_id":7,"spell":"firebolt","glyph":"🔥","fx":"bolt",
 "x0":3,"y0":4,"x":9,"y":6,"radius":0}
{"event":"stats","player_id":7,"mana":24,"max_mana":30}   // hp/max_hp too when healed
// Character sheet: identity, abilities+mods, skills, and worn gear by slot.
{"event":"character_sheet","name":"Bryan","char_class":"warrior","class_name":"Warrior",
 "gender":"male","level":1,"experience":0,"hp":10,"max_hp":10,"mana":0,"max_mana":0,
 "abilities":{"str":15,…},"modifiers":{"str":2,…},"skills":{"Melee":3,…},
 "equipment":{"head":[{"id":9,"name":"Steel Helm","glyph":"⛑️"}]},
 "slots":["head","torso","upper_arms","lower_arms","hands","pelvis","upper_legs","lower_legs","feet"]}
// Phase 5: portraits. zone_state.you + each entity + character_sheet carry a
// nullable portrait_url; a `portrait` event announces a just-generated image so
// open windows swap the glyph placeholder live.
{"event":"portrait","kind":"npc","id":3,"url":"/static/portraits/ab12cd34ef567890.png"}
```

**Portraits (Phase 5, Layer 2).** `novita_integration.py` mirrors
`deepseek_integration.py` (config from env, async client, graceful "not
configured" path) but talks to Novita's text-to-image HTTP API with `httpx`
(POST `/v3/async/txt2img` → poll `/v3/async/task-result` → download `image_url`).
Models are **per-purpose** via `portraits.STYLES` (each purpose → model + image
size + prompt suffix; swap via `.env`, no code change): `portrait` uses
**ZavyChromaXL** at 1024² (painterly fantasy busts); `token` uses **SDXL Unstable
Diffusers** at 768² for **overhead map tokens** (top-down) — players + NPCs +
items each get a generate-once token (`token_url` on Npc/Player/Item), rendered
circular-clipped on the tile in place of the emoji glyph (emoji fallback). The
generic seam is `portraits.ensure_image(purpose, kind, subject_id)` (kind ∈
npc/player/item) with `ensure_portrait`/`ensure_token` wrappers; a `token` WS
event + `token_url` snapshot fields mirror the `portrait` ones.
`portraits.py` is a **generate-once store**: a prompt is hashed
(`sha256(prompt)[:16]`), the PNG is written to `static/portraits/{hash}.png`
(served by the `/static` mount, gitignored), and a nullable `portrait_url` is
persisted on `Player` + `Npc`. An in-memory in-flight set + a
`PORTRAIT_MAX_CONCURRENT` semaphore bound calls; identical prompts dedup to one
file, so **N subjects = N API calls ever**. `ensure_portrait` is fire-and-forget
(returns the url if known / adopts an existing file / else spawns an async job →
writes file → sets `portrait_url` → broadcasts `portrait`), triggered on connect,
zone entry, first `talk`, and first `sheet`. The player prompt folds in the
free-form `appearance` field, so editing it (`set_appearance`) re-keys the hash
and a fresh portrait generates. Dark by default: with no
`NOVITA_API_KEY` the manager is disabled and every subject falls back to its
emoji glyph (exactly how DeepSeek-off degrades). Additive `migrate_phase5.py`.

**PvP:** **intentional only** — bumping a player just blocks; you strike them with
the **target+attack** action or `attack {target_id}`. `combat.resolve_pvp_attack`
rolls with both sides' gear and routes a kill through the shared `damage_player`
(broadcast + respawn + grace), **except in `config.PVP_SAFE_ROOM_IDS`** (the Foyer
by default — a truce zone). Targeting (**T**) cycles hostile mobs *and* players.
The client shows a **hover label** with the token's name. **Pickups skip immovable
items** (`world.grabbable_at`) so an item resting on a chest/furniture stays
retrievable.

**Currency** (`currency.py`): a base-10 coin wallet — `Player.coins` is a single
**copper** integer; `10cp=1sp, 10sp=1gp, 10gp=1pp` derived for display
(`currency.short`/`breakdown`). A coin pile (`item_type:"coins"`, `value` copper)
**collects into the wallet** on pickup (consumed); **gems** (`item_type:"gem"`)
are valued carried items (`Item.value`), not spendable currency. `coins` rides
`zone_state.you` + `character_sheet`; a `wallet` event updates the purse; the
inventory carries each item's `value`. `migrate_currency.py`. **Economy loop:**
slain mobs drop coins/gems on their tile (`loot.py` tables, on the NPC-death
paths); a **vendor** NPC (`shops.py` stock, e.g. the Innkeeper — `entity.vendor`
flag) trades via `shop`/`buy`/`sell` WS cmds (a `shop` event lists wares + your
sellables); admins grant coins (`POST /admin/characters/{id}/coins`).

**XP & leveling** (`leveling.py`): a triangular XP curve (`xp_to_reach` /
`level_for_xp` / `progress`). Slaying a mob grants the killer XP (`xp_for_kill`,
scaled by mob max-HP) via `PlayerService.award_xp`, which levels the character up
(+HP +CON-mod per level, +mana for casters, healed to full) and fires `xp` /
`level_up` / `stats` events. `character_sheet` carries `xp_into`/`xp_needed`; the
sheet draws an XP bar and a level-up gold-flashes the token. The `level` /
`experience` columns predate this — no migration.

**Consumable potions** (`potions.py`): an `item_type:"potion"` item; the `use`
WS cmd applies an instant effect (heal HP / restore mana / full restore, keyed
by item name) and consumes it, pushing `stats` + `inventory` + a flavor line.
Unknown potions are inert (not wasted). The Innkeeper sells Healing/Greater/Mana;
one Healing Draught is seeded in the Cellar. Client: a **drink** button on potions
(+ `use`/`drink` text verb).

**Status-effect layer** (`effects.py`, handoff-08): in-memory timed effects keyed
by an **entity key** `"player:{id}"`/`"npc:{id}"` (`effects.eid`) — buffs *and*
debuffs, on players *and* NPCs. Each effect carries flat combat deltas
(atk/dmg/defn), a movement `haste` factor, an optional **damage-over-time** (`dot`
every `dot_interval`s, attributed to its `source` so a DoT kill drops loot +
awards XP), and `harm`/`gear` flags. `effects.bonuses`/`haste_factor` read the
LIVE set and fold into **all** the melee resolvers (player, PvP, *and the mob's
own attack* — a Weaken lowers a mob's hits) + the move cooldown. The fast combat
tick drains `effects.due_dots()` through the shared `combat.damage_npc`/
`damage_player` paths (`game_loop._apply_dots`); the slow tick `sweep`s expiries
(player keys → an `effects` event + "… fades"; npc keys → an `entity_effects`
broadcast). Effects clear on death (`effects.clear` for mobs;
`clear_expirable` on respawn keeps gear).

- **Buff potions** (`potions.py`, `buff` kind): Strength/Stoneskin/Haste — unchanged.
- **Debuffs** (`debuffs.py`): Weaken (−atk/−dmg), Poison (a DoT), Slow (haste×2 =
  slower). A **venomous** mob (`VENOM_BY_TYPE` keyed by `npc_type`, e.g. the
  Cave Spider) poisons the player it bites in `resolve_mob_attack`.
- **Spell buffs/debuffs** (`spells.py` `effect.kind` ∈ `buff`/`debuff`, resolved
  in `casting.resolve_cast`): **Bless** (self +atk/+def), **Slow** (debuff bolt),
  **Venom Bolt** (damage + poison). A debuff is applied to each *surviving* npc
  target with the caster as source; a self-buff pushes an `effects` event.
- **Gear effects** (`gear_effects.py`): worn gear grants a **non-expiring**
  (`gear=True`) effect — **Ring of Haste** (haste), **Band of Might** (+atk/+dmg).
  `gear_effects.sync(pid)` rebuilds them from the worn set on equip / unequip /
  connect (so they survive a reconnect); `sweep` skips gear.
- **WS/client:** `zone_state` entities and `you` carry a compact
  `effects:[{name,glyph,remaining,harm,gear}]`; an `entity_effects {id,effects}`
  event updates a mob's. The client renders effect **chips** in the Status panel
  (red = debuff, blue ◆ = gear) and **icons over the token** (tinted; flash on
  apply — gold buff / green debuff).

**Traps & environments** (handoff-09): a general per-tile **feature layer** keeps
`Room.tiles` purely geometric. A `RoomFeature(room_id, x, y, kind, glyph, config)`
row (`config` = JSON, like `Player.skills`) loads into `RoomNode.features`;
`world.feature_at`/`feature_near`/`features_payload` query it, and it rides
`zone_state.features` (client draws a glyph overlay). `migrate_features.py`
(idempotent) creates the table + adds `rooms.room_type`/`rooms.is_safe` +
`npcs.wanders`. Kinds:

- **Traps / hazards** (`features.py`): firing on entry (the player `move` handler
  and the mob AI step both call `features.on_enter`). A trap deals `damage`
  (via the shared `combat.damage_player`/`damage_npc`, by_type `"trap"` → no XP)
  and/or applies a `debuff` (e.g. Poison); `radius>0` makes it **AoE**
  (`tiles_in_radius`); `one_shot` fires once (in-memory `_sprung`).
- **AoE objects** — a **powder keg** (`kind:"keg"`): the `trigger` WS cmd ignites
  a keg on/adjacent to you → a radius blast → the keg is consumed (`feature_removed`).
- **Signs** (`kind:"sign"`): the `read` WS cmd → a `sign {title,text}` event.
- **Spawners** (`kind:"spawner"`): a spawner tick (`game_loop._spawn_tick`)
  repopulates its `radius` up to `max_active` on its `interval`, creating fresh
  NPC rows from an inline `template` (`world.spawn_npc_from_template`). Spawned
  mobs are flagged `spawned` (so they don't auto-respawn — the spawner manages
  population) and their dead rows are reaped on the next tick.
- **Wandering mobs** (`npcs.wanders`): a non-aggroed wandering mob ambles one tile
  on `MOB_WANDER_COOLDOWN_SECONDS` within `MOB_WANDER_LEASH` of home
  (`world.wander_candidates`); it still aggros on sight.
- **Room types** (`rooms.room_type`/`is_safe`): a **sanctuary** (`is_safe`) refuses
  PvP (`resolve_pvp_attack`) *and* suppresses mob aggro (the combat tick acquires
  no targets there); `PVP_SAFE_ROOM_IDS` now falls back to flagged rooms. A
  **tavern** (`room_type:"tavern"`) supports the `rest` WS cmd — full HP/mana
  recovery when no hostiles are present. The Foyer is seeded as a tavern+sanctuary.

New WS: `read`/`trigger`/`rest` (client→server); `sign`/`feature_triggered`/
`feature_removed`/`entity_effects` (server→client). Demo content (seed): a Foyer
sign, a Cellar poison-gas AoE trap + powder keg, a Great-Hall Cave-Bat spawner, a
wandering Caretaker, and a new **Fireball** AoE spell (Mage).

**Class-gear chest:** an immovable `item_type:"chest"` item (the Old Chest in the
Great Hall) grants the **opener's class starting kit** (`classes.starting_gear`)
on the `open` WS command (**O** key when on/adjacent) — created in the pack and
auto-equipped — **once per character** (`Player.opened_chests` JSON, set by
`ItemService.open_chest`; `migrate_chest.py`).

Equipment slots: `weapon`, `ring`×2, `amulet`, and the **15 body slots** —
`head`/`torso`/`pelvis` plus independent left/right for each limb
(`{left,right}_upper_arm`/`_lower_arm`/`_hand`/`_upper_leg`/`_lower_leg`/`_foot`)
— driving the character-sheet paperdoll. `Player` carries `char_class`/`mana`/
`race` (`races.py`, a small ability nudge)/`gender`/`skills` (a JSON `{skill:
rank}` dict from `skills.py`)/`appearance` (free-form looks/bio, set at creation
and editable from the sheet via the `set_appearance` WS cmd; it feeds the
portrait prompt, so editing it clears `portrait_url` and regenerates). Character **creation is its own gate screen** (not
the character-select list). Legacy single limb slots migrate to their left side.

## Graphical overhaul — two-tier tiled world (Phase 1)

BGID is being reshaped into an **overhead, real-time roguelike** while keeping
the LLM social layer. Two tiers share one world view (see
`docs/handoff-01-graphical-overhaul-master.md`):

- **Structured tiles** (`tiles.py`, handoff-11 Slice A): authoring stays a terse
  glyph grid (`Room.tiles`), but each glyph **resolves through a data-driven
  registry** into `{name, walkable, transparent, transition}`. The three tile
  predicates — `_is_walkable_grid`, `_is_transparent`, and `transition_for_tile`'s
  kind switch — read the registry (an **unknown glyph fails safe** as a solid,
  opaque wall); `BLOCKING`/`SIGHT_BLOCKING`/`TRANSITION_TILES` are derived views.
  `zone_state.tiles` ships a compact `tiledefs` map of the glyphs present, so the
  client derives its FOV/`isTransparent` rule from data — a new tile type behaves
  correctly with no engine or client change. This is also the designer's palette
  source + the first registry slated to move to the config layer (handoff-10 §1).
- **Author-time map generator** (`mapgen.py`, handoff-11 Slice D): imported by
  the designer/CLI, **never by the live sim**. `generate(kind, w, h, params, seed)`
  → glyph rows (geometry only) for `cave` (cellular automata) and `rooms` (BSP +
  L-corridors); deterministic per seed, border-walled, and run through a
  largest-connected-component pass so the floor is always connected. `validate()`
  (rectangular, registry-only glyphs, connected floor) is the shared check the
  designer reuses alongside its spawn/exit rules. Output bakes one-way to static
  `Room.tiles` — after that it's hand-editing.
- **Levels & z-floors** (`models.Level`, `Room.level_id`/`Room.z`, handoff-11
  Slice B): a **level** is a named area (the Manor); its floors are the Rooms
  sharing a `level_id`, indexed by signed `z` (0 ground, −1 cellar). *Within* a
  level, floors link by **stairs** (the existing `up`/`down` transitions — same
  `level_id`, adjacent `z`); *between* levels, an exit crossing `level_id` is an
  **entrance** (the generalized room-graph). The runtime is unchanged — vertical
  movement already worked; this is grouping metadata. `RoomNode` caches
  `level_id`/`z`; `world.levels` maps id→name; `world_map` ships rooms (with
  `level_name`/`z`), `levels`, and per-exit `entrance` flags; `zone_state.room`
  carries `level_id`/`level_name`/`z`. The overview labels each chamber with its
  level + floor and shows a **floor-stack** widget for the current level.
  Additive `migrate_maps.py`; seed authors the Manor (Foyer z0 + Cellar z−1) with
  the Great Hall as its own level (an entrance).
- **Layer 1 — the dungeon (no LLM):** each room is now an overhead **tile grid**
  (`Room.width/height/tiles/spawn_x/spawn_y`; glyphs `#` wall, `.` floor, `+`
  door — see the tile registry above). `WorldState` tracks live tile positions (`RoomNode.player_pos` /
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

**Client** (`static/index.html` + vendored `static/vendor/rot.min.js`,
`rough.min.js`): the tile world renders as a **hand-drawn ink-on-graph-paper
dungeon map** (Phase 6 — `rough.js` sketchy cross-hatched walls, ink room
outline, arc doorways, compass rose; the static map is cached to an offscreen
layer so spell-FX frames don't re-randomise). `ROT.FOV.PreciseShadowcasting`
still drives fog-of-war (visible = full ink, remembered = faded). Entities/items
are emoji **tokens** on paper discs, animated by a `requestAnimationFrame` loop
(`paint()` blits the cached map; `draw()` owns FOV + the cache): eased movement
slides, floating combat numbers, hit-flash, attacker lunge, and death fade — the
loop runs only while something is animating. A damaged entity (hp < max) shows a
**percentage health bar** over its head (green → yellow → red by 50% HP); live HP
rides `combat` events + `zone_state`. **Adaptive camera** (handoff-11 Slice C,
`static/camera.js` — pure, unit-tested in `test_camera.js`): a floor that fits the
panel at a readable tile size renders **static** (whole grid, as before); a larger
floor switches to a **player-centered follow camera** at a fixed cell — the cached
ink layer still renders the *whole* floor once, and `paint()` blits the camera
sub-rect + translates the token layer by the camera offset (no re-hatch → no
shimmer); the minimap shows the whole floor with the camera window outlined, and
click/hover map back through the offset. The **M** overview redraws as a `map.jpg`-
style floor plan (numbered chambers, locked exits, cartouche, compass). A Layer-2
dialogue window (right) and combat-log/stats strip complete the layout. Movement
is WASD/arrow keys; bump a foe to attack. (Renderer evolved: Phase 1 used rot.js
`Display` with emoji tiles → a custom dark-vellum 2D-canvas → the Phase-6
cartographic look; rot.js is kept only for FOV math.)

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

4b. ✅ **Admin console** — `/admin/*` (admin-gated): `GET /admin/accounts` (every
   account + its characters), `PATCH /admin/accounts/{id}` (promote/demote `role`,
   activate/ban `is_active` — `is_active` already gates login; self-lockout
   blocked), `DELETE /admin/accounts/{id}` (cascades characters), `DELETE
   /admin/characters/{id}`. The client header shows an **Admin** link to admins
   only, opening an overlay to manage accounts/characters.

   **World authoring** (handoff-10 §3): admin-gated CRUD over live content —
   `PUT/DELETE /rooms/{id}` (name/desc + tile grid + room type), `PUT/DELETE
   /npcs/{id}` (combat & AI flags, glyph, home, abilities), `GET/POST
   /rooms/{id}/features` + `PUT/DELETE /features/{id}` (the `RoomFeature` layer:
   traps/signs/spawners/kegs), and `POST /admin/world/reload`. Every write calls
   `world.reload()` (resyncs the in-memory world, preserving online players). The
   admin overlay is now **tabbed** (`#admintabs`): an **Accounts** tab + a
   **Monsters** tab (list/create/edit/delete NPCs with a per-NPC form) + a
   **Reload world** button.

   **Map designer** (handoff-10 §2, built against the handoff-11 maps model): an
   admin-only `#designerview` overlay (launched from the admin console) — a canvas
   editor that paints tiles from a **palette** (`GET /tiles`, the `tiles.py`
   registry), sets the **spawn**, edits room **properties** (name/desc/size/
   `room_type`/`is_safe`/`level_id`/`z`), manages **exits** and **RoomFeatures**
   (traps/signs/spawners/kegs) via the CRUD above, and runs the **generator**
   (`POST /admin/mapgen` → `mapgen.py`, cave/rooms). **Save** writes the grid +
   meta via `PUT /rooms/{id}` (creating the row first for a new room) and
   `world.reload()`s. Levels come from `GET /levels` (+ `POST /levels` to create).
   *(Deferred: drag-placing items/NPCs on tiles — use the Monsters editor + an
   NPC's home tile; and re-skinning the editor with the hand-drawn renderer.)*

   **Content config layer** (handoff-10 §1, `content.py` + `models.Content`): the
   authored code registries become **editable data without a restart**. Each
   registry module (`spells`, `potions`, `debuffs`, `gear_effects`) keeps its
   Python dict as the **defaults** and registers an applier; the live registry is
   `{**defaults, **overrides}`, where overrides are JSON rows in the `content`
   table (`kind`/`key`/`data`). An empty store = pure defaults (additive, safe to
   wipe; `migrate_content.py` just creates the table). Admin endpoints
   `GET /admin/content[/{kind}]`, `PUT/DELETE /admin/content/{kind}/{key}`
   validate on write (per-kind schema) and **hot-reload** the module global, so an
   edit reaches combat/casting immediately; deleting an override reverts to the
   code default. A **Content** tab in the admin console edits entries as JSON.
   Startup `content.reload_all()`s; tests reset to defaults between cases.
   Registries on the layer: `spells`, `potions`, `debuffs`, `gear`, **`classes`,
   and `races`** — the class/race appliers also recompute `SELECTABLE`, and public
   `GET /classes`/`GET /races` feed the character-creation gate (which loads them
   dynamically), so a class/race added in the editor is immediately offered to
   players; the `wanderer`/`human` fallbacks are never-deletable code defaults so
   no character is orphaned. The **Content** tab lists every registered kind.
   *(Deferred to the same pattern: the import-frozen `tiles` set — needs `world`
   to re-derive its walk/sight sets on reload — and per-field form editors.)*

5. ✅ **Room graph** (`models.RoomExit`, `directions.py`) — directed exits with
   locks/keys; direction-based, lock-aware movement (WS + `/action`); exits in
   room_state/`/state`; exit-management API. **Consumable shared unlock:** using
   a key to pass a locked door **destroys the key** (`ItemService.destroy`) and
   opens the door for *everyone* for `DOOR_UNLOCK_SECONDS` (a single in-memory
   timer, `world.door_unlocks`); the slow tick (`_relock_doors`) re-locks it and
   respawns the key at its recorded home tile (`world.key_home`, armed at load).
   A restart reverts an open door to locked (timers aren't persisted) and recovers
   a mid-crumble key to its home (`world._arm_doors`).

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

8. ✅ **Inventory & equipment** (Phase 3) — items gained tile positions (ground
   items ride `zone_state.items` and render on the map); pickup (**G** / `get`)
   and drop onto tiles; equip slots (weapon, armor, ring ×2, amulet) with
   per-slot limits (`services.SLOT_LIMITS`, equipping a full slot swaps the
   oldest); item `attack_bonus`/`defense_bonus`/`damage_bonus` feed the D20
   resolver via `ItemService.equipment_bonuses` (the single seam combat reads);
   inventory overlay (**I**) + worn summary. New `items` columns (additive
   migration, `migrate_phase3.py`); the Cellar is re-locked behind the now-
   grabbable Rusty Key. See `docs/handoff-04-phase3-inventory-equipment.md`.

9. ✅ **Classes, spells & mana** (Phase 4) — characters pick a **class**
   (Warrior/Mage/Cleric/Rogue + a `wanderer` migration fallback) at creation,
   stamping abilities/glyph/mana from `classes.py`. A data-driven spell registry
   (`spells.py`) with mana cost + per-`(player,spell)` cooldown; `cast` resolves
   `self`/`bolt`/`blast` via new `world.line_of_sight` (Bresenham,
   `SIGHT_BLOCKING`) + `world.tiles_in_radius` — the first **ranged & AoE** on
   the grid. Spells auto-hit (range/LOS is the counterplay) and reuse the shared
   `combat.damage_npc`/`damage_player` death/respawn paths. Mana regenerates on
   the regen tick per class. New `players` columns (`char_class`/`mana`/
   `max_mana`, additive `migrate_phase4.py`); client mana bar, quickslot bar
   (keys 1–9), click-to-target, `spell_cast` VFX, class picker.
   See `docs/handoff-05-phase4-classes-spells-mana.md`.

### Future
- Per-NPC conversation memory across `talk` turns.
- Richer combat (initiative, abilities, NpcReaction-driven aggro) and a real
  NPC AI tick (wandering, hostiles engaging on sight).

### Out of scope here (tracked separately)
- Reactions endpoint (`/npcs/{id}/reaction/...`) the CLIs expect (P1).
- `pytest-asyncio` test harness (P1).
- Config/seed cleanup, committed cruft (P2).
