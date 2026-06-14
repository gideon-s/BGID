# Handoff 02 — Phase 1: Tiled Combat Slice

**Status:** ready to build · **Depends on:** `handoff-01-graphical-overhaul-master.md`
**Goal:** one vertical slice that proves both tiers through a single loop.

> Read the master doc §3 (current architecture) and §4 (target) first. This phase
> is deliberately scoped to **a single room** — no zone-to-zone transitions (that's
> Phase 2). The point is to make tile movement + combat + LLM reactions feel good in
> one screen before scaling the world.

---

## 1. The slice (acceptance demo)

1. Log in, pick a character, spawn into the **tiled Foyer** — emoji floor/walls,
   fog-of-war that clears as you move (FOV).
2. On the map: one **non-combat NPC** (the Innkeeper, `🧑`) and one **hostile mob**
   (a Cellar Rat or Goblin, `🐀`/`👺`).
3. Move with **arrow keys / WASD**; fog reveals around you.
4. **Bump into the mob** → melee. The **combat strip under the map** logs hits,
   misses, damage, and HP. The mob **paths toward you on the tick** and hits back.
5. The mob **talks smack in the sidebar** on combat events ("Hold still, meat!") —
   an LLM line when DeepSeek is on, a **canned barb** when it's off/throttled.
6. **Kill the mob** → it vanishes from the map. **Talk to the Innkeeper** (Layer 2)
   → an LLM reply appears in the sidebar.

If all six happen and feel responsive, Phase 1 is done.

---

## 2. In scope / out of scope

**In:** one tiled room; per-tile movement w/ FOV; bump-to-attack melee; real-time
mob aggro + pathfinding + melee on a fast tick; mob smack-talk (LLM + canned
fallback); the three-region client layout; the WS protocol changes below; tests.

**Out (later phases):** zone transitions/doors (P2), map/minimap (P2), inventory &
equipment (P3), spells/mana/classes (P4), portraits (P5), sprites/procedural (P6),
ranged combat, persisting `(x,y)` across reconnects.

---

## 3. Data model changes (`models.py` + migration via wipe-reseed)

SQLite + no Alembic wiring → **wipe & reseed** (consistent with prior deploys).

- **Room:** add `width INT`, `height INT`, `tiles TEXT` (the layout, e.g. a
  newline-joined `#`/`.`/`+` string, parsed on load), `spawn_x INT`, `spawn_y INT`.
- **Npc:** add `home_x INT`, `home_y INT` (spawn/anchor tile), `aggro_radius INT`
  (default e.g. 6; 0 = passive), `glyph TEXT` (emoji), `is_hostile BOOL` (distinct
  from `combat_enabled`: hostile = initiates/aggros; the Innkeeper is
  `combat_enabled=False, is_hostile=False`).
- **Player:** `glyph` optional (default `🧙`). Do **not** persist live `(x,y)` this
  phase — spawn at the room's spawn tile on connect.
- Items keep `room_id`; tile position for ground items can default to spawn or a
  fixed tile (not central to this slice).

Update `seed.py`: give the Foyer a small authored layout (e.g. 12×9) with a wall
border + a door glyph (decorative for now), place the Innkeeper and one hostile mob
(reuse/clone the Caretaker as hostile, or add a "Cellar Rat") at fixed tiles.

---

## 4. World model changes (`world.py`)

- **`RoomNode`** gains: `width`, `height`, `tiles` (2D list or flat list + accessor),
  `npc_pos: Dict[int,(x,y)]`, `player_pos: Dict[int,(x,y)]`, plus the existing
  `npc_ids`/`players`. Load tiles + npc home positions in `load()`.
- **Helpers:**
  - `is_walkable(room_id, x, y)` — in-bounds, not a wall.
  - `occupant_at(room_id, x, y)` — entity id/kind on a tile, or None.
  - `place_player(player_id, room_id)` — set to spawn tile (replaces the room-only
    `enter_world` placement; keep room bookkeeping).
  - `try_step(entity_kind, id, dx, dy)` → result enum: `MOVED` (+new x,y),
    `BLOCKED`, or `ATTACK(target_id)` when the destination holds a hostile/valid
    target. Single source of truth for both players and mobs.
  - `neighbors`/`step_toward(room_id, from, to)` — BFS or greedy step for mob
    pathing (hand-rolled; no new dep). Cache nothing fancy; rooms are tiny.
- Keep DB write-through for durable state (room membership/hp), but **keep the live
  tick DB-free** — operate on in-memory positions.

---

## 5. Tick / real-time (`game_loop.py` + new combat tick)

- Add a **fast combat tick**, `COMBAT_TICK_SECONDS` (config, default `0.3`), separate
  from the existing 15s regen tick (keep regen as-is).
- Each combat tick, for each room with ≥1 online player:
  - For each hostile mob: find nearest player within `aggro_radius`. If adjacent →
    melee that player; else `step_toward` them (respecting walls/occupancy) and
    broadcast `entity_moved`.
  - Emit smack-talk per the policy in §7 (throttled).
- Keep the tick **cheap and exception-safe** (one slow/raised tick must not stall the
  loop or block player input — player moves are handled on the WS coroutine, not the
  tick).

---

## 6. WebSocket protocol changes (`main.py`)

This is a **hard cutover** (closed alpha — no back-compat needed). Replace the
room-graph movement protocol *within a room* with tile movement.

**Server → client events (new/changed):**
- `zone_state` (replaces `room_state` for this view):
  ```json
  {"event":"zone_state",
   "room":{"id":1,"name":"Foyer"},
   "tiles":{"w":12,"h":9,"grid":["############","#..........#", "..."]},
   "you":{"id":7,"x":3,"y":4,"glyph":"🧙","hp":10,"max_hp":10},
   "entities":[{"id":12,"kind":"npc","name":"Innkeeper","glyph":"🧑","x":8,"y":2,"hostile":false},
               {"id":13,"kind":"npc","name":"Cellar Rat","glyph":"🐀","x":9,"y":6,"hostile":true,"hp":8,"max_hp":8}]}
  ```
- `entity_moved` `{id, x, y}` — broadcast on any entity step.
- `entity_spawned` / `entity_died` `{id, ...}` — appear/disappear on the map.
- `combat` `{attacker_id, attacker, target_id, target, hit, damage, target_hp, target_max_hp}`
  (extend the existing combat event with ids/positions as needed).
- `you_died` / `respawn` — keep current respawn behavior (master §7: no permadeath).
- Layer 2 unchanged: `chat`, `npc_thinking`, `npc_said`, `error`.

**Client → server commands (new/changed):**
- `move` `{dx, dy}` — one orthogonal step (±1). Server validates via `try_step`:
  `MOVED` → broadcast `entity_moved`; `ATTACK` → resolve melee (bump-to-attack);
  `BLOCKED` → silent or a soft `error`. Enforce a per-player **move cooldown**
  (config `MOVE_COOLDOWN_SECONDS`, default `0.12`) to bound speed.
- `attack` `{target_id}` — explicit melee on an adjacent target (keep alongside
  bump-to-attack).
- `talk` `{npc_id, text}` — unchanged (Layer 2; explicit NPC conversation).
- `say` `{text}` — unchanged (sidebar emote/chat). Optional new `emote {text}`.
- Drop in-room `move {dir|room_id}` for this view (returns Phase 2 as door
  transitions between zones).

---

## 7. Combat + the smack-talk bridge

- **Melee:** reuse `combat.py`'s D20 resolver; gate on adjacency (Chebyshev distance
  1). Bump-to-attack and explicit `attack` both funnel through one path. Death →
  `entity_died` + remove from map; player death → existing respawn.
- **Smack-talk policy (Layer-1 event → Layer-2 line):** fire on these events, each
  with a **per-mob cooldown** (config `MOB_CHATTER_COOLDOWN_SECONDS`, default `8`):
  aggro acquired, mob lands a hit, mob takes a hit (low chance), mob below 30% HP,
  player below 30% HP. Also cap a **global chatter budget** (e.g. reuse a
  `rate_limit` window keyed `("mob_chatter", room_id)`), distinct from the
  player-`talk` budget.
- **Generation:** route through the `npc_turns`/`deepseek_integration` machinery with
  a combat-flavored system prompt. **Must fall back to a canned barb list** when
  DeepSeek is unconfigured/throttled (the slice has to work offline and free).
  Render as `npc_said` (optionally skip the `npc_thinking` indicator for barbs).

---

## 8. Client (`static/index.html` + `static/vendor/rot.js`)

- **Vendor rot.js** into `static/vendor/rot.min.js` (don't rely on a CDN; the box
  serves the game). Mount under `/static`.
- **Layout** (master §1 diagram): center = rot.js `Display` (emoji tiles, FOV/fog
  via `ROT.FOV.PreciseShadowcasting`); right sidebar = the existing event log,
  scoped to Layer-2 messages (chat/npc_said/emotes); under-map strip = combat log +
  stats (HP now; MP/level later) + action buttons (Attack, Talk).
- **Input:** Arrow keys/WASD → `move {dx,dy}` (bump-to-attack handled server-side);
  click a tile → optional rot.js path → step queue. Keep the command box for
  `say`/`talk` (Layer 2).
- **Rendering:** maintain a local entity map from `zone_state`/`entity_moved`; redraw
  the rot.js display each update; apply FOV so unseen tiles are dimmed/hidden.
- Preserve the auth/character-select gate and token-authed WS (`/ws/{id}?token=`).

---

## 9. Config knobs (new, in `config.py` + `.env.example`)

```
COMBAT_TICK_SECONDS=0.3        # mob AI cadence
MOVE_COOLDOWN_SECONDS=0.12     # per-player movement rate cap
MOB_CHATTER_COOLDOWN_SECONDS=8 # per-mob smack-talk cooldown
FOV_RADIUS=8                   # client view radius (if gated)
```

---

## 10. Tests

- **New (`test_tiles.py`):** `is_walkable`/`occupant_at`/bounds; `try_step` →
  MOVED/BLOCKED/ATTACK; bump-to-attack resolves combat; mob `step_toward` reduces
  distance and meleeing on adjacency; `zone_state` shape; smack-talk **fallback**
  fires with DeepSeek blank (no network); move cooldown enforced.
- **Rewrite:** `test_realtime.py`, `test_world.py`, `test_exits.py` move from the
  room-graph/`move {dir}` protocol to tiles/`move {dx,dy}`/`zone_state`. (Exits as
  door transitions return in Phase 2 — trim those assertions here.)
- **Keep green:** `test_auth.py`, `test_rate_limit.py`, `test_api.py` (adjust any
  `room_state`→`zone_state` expectations), `test_seed.py` (new Room columns).
- Target: full suite green before deploy.

---

## 11. Deploy notes

- No new backend dep (pathfinding hand-rolled). New static asset: `rot.min.js`.
- **Schema changed → wipe & reseed** on the box (as in prior deploys):
  `systemctl stop bgid-api` → `rm -f game.db*` → `sudo -u www-data ./.venv/bin/python
  seed.py` → `chown www-data:www-data game.db` → restart. (Bryan's account survives
  only if the `users` table is untouched — but a full reseed drops it; coordinate:
  either preserve `users`/`players` rows or have Bryan re-register as first =
  admin.) **Flag for Bryan before deploying.**
- Update flow otherwise unchanged (`git pull --ff-only` + restart, one worker).

---

## 12. Risks & mitigations

- **World-model rewrite ripples** (WS protocol, client, combat, tests) — biggest
  risk. Mitigated by scoping to **one room** + bump-to-attack + hard cutover.
- **Real-time AI on the event loop** — keep the tick DB-free, O(entities), and
  exception-safe; positions in memory only.
- **LLM cost/spam from mobs** — per-mob cooldown + global budget + canned fallback;
  Layer 1 stays LLM-free.
- **rot.js integration** — well-documented; vendor the single file; server stays
  authoritative so the client is "dumb renderer + input."
- **Reseed wipes accounts** — confirm with Bryan whether to preserve `users`/
  `players` or re-register.

---

## 13. Definition of done

- The six acceptance steps in §1 work over `wss://` on the box.
- Full test suite green (new tile tests + rewritten realtime/world tests + untouched
  auth/rate-limit).
- Docs: update master §5 phase list; note any protocol/config changes in
  `ARCHITECTURE.md` and `.env.example`.
