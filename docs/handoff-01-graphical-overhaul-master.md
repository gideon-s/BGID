# Handoff 01 — Graphical Overhaul (Master)

**Status:** planning · **Owner:** Bryan (`gideon-s`) · **Created:** 2026-06-14
**Scope:** Transform BGID from a text MUD into an **overhead, real-time roguelike**
with a two-tier architecture, while preserving the LLM-driven social/narrative
layer that makes it distinctive.

This is the program-level doc. Each phase has (or will have) its own handoff with
an executable, fresh-session-sized spec. Phase 1 is `handoff-02-phase1-tiled-combat-slice.md`.

---

## 1. Vision

A "MUD with a chat client," rendered overhead in the spirit of classic crawl
roguelikes (emoji/tile icons), where two layers coexist in **one world view**:

- **Layer 1 — the dungeon (mechanical, deterministic, fast).** A real tile grid.
  Per-tile movement, fog-of-war/FOV, positional melee/ranged, inventory,
  equipment, spells/mana. **No LLM in this layer** — it's the classic crawl loop,
  so it's instant and free. This is where the map, minimap, combat, and stats live.
- **Layer 2 — the story (narrative, LLM, async).** The existing DeepSeek layer:
  NPC conversation, emotes, personality, "smack talk." Invoked on *events* and
  player intent, rate-limited, eventually with generated portraits.

**Why two tiers:** the LLM never sits in the combat hot path, so cost and latency
stay bounded to Layer 2 where they belong. Layer 1 is a fast, deterministic
simulation; Layer 2 is an async enrichment over the same world.

### Screen layout (one world, three regions)
```
┌───────────────────────────────┬──────────────────┐
│                               │  DIALOGUE / EMOTES │
│         TILE MAP              │  (Layer 2 sidebar) │
│      (overhead, FOV)          │  • npc_said        │
│                               │  • chat / emotes   │
│                               │  • portraits later │
├───────────────────────────────┤                    │
│  COMBAT LOG · STATS · ACTIONS │                    │
│  (Layer 1, under the map)     │                    │
└───────────────────────────────┴──────────────────┘
```

---

## 2. Locked decisions (from the design discussion)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Spatial model | **True tile-grid** — per-tile movement, walls, FOV, pathfinding (a `WorldState` rewrite). |
| D2 | World layout | **One world**, three regions: tile map (center), dialogue/emote sidebar (right), combat+stats (under map). |
| D3 | Time model | **Real-time with ticks.** Player movement is event-driven with a per-player cooldown; mobs path/act on a fast server tick. Not turn-based (multiplayer makes turn order ugly). |
| D4 | Rooms→grid | **Rooms become tiled zones.** Each existing room = one tile grid; exits = doors to adjacent zones. Room-graph stays as the macro map; minimap = current zone (explored), map = zone graph. |
| D5 | Renderer | **rot.js** (vendored into `static/vendor/`, not CDN — the box serves the game itself). Server stays authoritative; rot.js handles display + client FOV + click-path. |
| D6 | Tiles | **Emoji/ASCII first.** Sprite tilesets are a later upgrade. Portraits (Novita) are separate from map tiles. |
| D7 | Inventory | **Effectively infinite, no encumbrance** (no weight system — simplifies the model). |
| D8 | Authority | Server authoritative; single uvicorn worker (positions live in-memory in `WorldState`, same constraint as today). |
| D9 | First slice | A single tiled room: per-tile movement + FOV, bump-to-attack melee vs a hostile mob that paths toward you and **talks smack** (Layer 1 events → Layer 2 lines), plus one non-combat NPC. See Phase 1. |

---

## 3. Current architecture (the starting point)

Accurate as of 2026-06-14. A fresh session should read these files before changing them.

- **Stack:** FastAPI + uvicorn **(one worker only)**, SQLAlchemy + SQLite (`game.db`),
  in-memory authoritative `WorldState`. Auth is live (JWT + Argon2). LLM = DeepSeek.
- **World model (`world.py`):** a **room-graph**. `RoomNode{id,name,description,
  npc_ids,item_ids,players,exits}` where `exits` is `direction -> {to_room_id,
  description,is_locked,key_item_id}`. `player_locations: player_id -> room_id`.
  Moves write through to the DB. **There are no coordinates today** — this is the
  central thing Phase 1 changes.
- **Realtime (`main.py`):** `WebSocket /ws/{player_id}?token=<access>` (token-authed,
  ownership-checked). Commands: `look`, `say{text}`, `move{dir|room_id}`,
  `talk{npc_id,text}`, `attack{npc_id}`. Events: `room_state`, `player_entered`,
  `player_left`, `chat`, `npc_thinking`, `npc_said`, `combat`, `npc_defeated`,
  `player_defeated`, `respawn`, `error`.
- **Combat (`combat.py`):** `run_combat_round(player_id, room_id, npc_id)`, D20 off
  ability scores, death/respawn, `STARTING_ROOM_ID=1`. Non-combatants rejected.
- **Tick (`game_loop.py`):** one asyncio task, `TICK_SECONDS=15`, currently only
  regenerates damaged in-room NPCs. This is where real-time mob AI will hang.
- **LLM NPC (`npc_turns.py`, `deepseek_integration.py`):** `run_npc_turn(player_id,
  room_id, npc_id, text)` → broadcasts `npc_thinking` → DeepSeek → `npc_said`.
  `build_llm_npc`, `build_context`. Rate-limited via `rate_limit.py`.
- **Models (`models.py`):** `Room`, `RoomExit`, `Player`(+`AbilityScoresMixin`,
  `user_id`, `room_id`, hp/level/exp), `Npc`(+abilities, `npc_type`,
  `combat_enabled`, `is_friendly`, hp), `NpcReaction`, `Item`(`room_id`|`player_id`,
  type/flags), `User`, `RevokedToken`.
- **Client (`static/index.html`):** single file — text log + side panel, login →
  character-select gate, WS protocol above.
- **Deploy:** Hetzner `root@89.167.67.129`, `/var/www/bgid` (git clone, owned
  `www-data`), systemd `bgid-api` (`uvicorn main:app --workers 1`), nginx + TLS at
  `https://blackgoatsociety.com` and `theblackgoatsociety.com`. Update flow:
  `cd /var/www/bgid && sudo -u www-data git pull --ff-only && systemctl restart bgid-api`.
  `seed.py` is world-only (accounts own characters). One worker is mandatory.

---

## 4. Target architecture (what changes)

- **Tiled zones.** Each `Room` gains a tile grid (`width`, `height`, `tiles`).
  `RoomNode` holds the tilemap plus **entity positions** (`player_id -> (x,y)`,
  `npc_id -> (x,y)`). Tile types for MVP: `wall`, `floor`, `door`.
- **Movement.** Per-tile, validated against walls + occupancy. Event-driven
  (instant on keypress → WS → server resolves → broadcast `entity_moved`) with a
  per-player move cooldown to bound speed. **Bump-to-attack:** moving into a
  hostile's tile resolves melee instead of moving.
- **FOV/fog.** rot.js computes visibility client-side for rendering; server sends
  the (small) zone in full for MVP. Server-gated FOV is a later optimization.
- **Real-time mob AI.** A fast combat tick (config `COMBAT_TICK_SECONDS`, ~0.2–0.4s,
  separate from the 15s regen tick): hostile mobs acquire aggro in range, step
  toward the nearest player (server-side BFS/greedy), and melee when adjacent. Keep
  the hot tick **DB-free** (operate on in-memory positions; write through sparingly).
- **Combat.** Adjacency-gated melee reusing the D20 resolver. Ranged/spells land in
  later phases.
- **Layer-1 → Layer-2 bridge ("smack talk").** Combat/aggro events trigger
  *throttled* LLM lines via the `npc_turns` machinery, shown in the sidebar as
  `npc_said`. Must degrade to **canned barbs** when DeepSeek is off or throttled, so
  the game is playable and free by default. Per-mob cooldown + a global chatter
  budget (this LLM cost is mob-initiated, so it needs its own throttle distinct from
  the player-initiated `talk` budget).
- **Client.** rot.js tile renderer in the center; the existing chat log becomes the
  Layer-2 sidebar; a new combat/stats/actions strip sits under the map. Arrow/WASD
  move (bump to attack); optional click-to-path.

---

## 5. Phases (dependency-ordered)

> Order is by dependency, not strict priority. Portraits (Phase 5) are independent
> and can be pulled forward as a parallel track if desired.

- **Phase 1 — Tiled combat slice (the spine).** ✅ **Done** (branch
  `phase1-tiled-combat-slice`). Single tiled room, FOV, per-tile movement,
  bump-to-attack vs a hostile mob (Cellar Rat) that paths + talks smack, one
  non-combat NPC (Innkeeper), rot.js three-region client, real-time combat tick.
  Tile protocol + config knobs documented in `ARCHITECTURE.md` / `.env.example`;
  full test suite green (`test_tiles.py` + rewritten `test_realtime.py`).
  → `handoff-02-phase1-tiled-combat-slice.md`.
- **Phase 2 — Zones & the map.** ✅ **Done.** Tile-to-tile zone transitions via
  border doors (cardinal) and stairs (`>`/`<`, up/down), riding the existing
  room-graph exits with lock/key enforcement; all seeded rooms tiled; per-zone
  explored memory + current-zone minimap; on-demand overview map (zone graph,
  visited rooms, locked exits) via the `map` command / **M**. New tile glyphs
  `>`/`<`; new WS: `world_map`. → `handoff-03-phase2-zones-and-map.md`.
- **Phase 3 — Inventory & equipment.** ✅ **Done.** Effectively-infinite
  inventory; equipment slots (weapon, armor, ring ×2, amulet) with per-slot
  limits (full slot swaps oldest); item `attack_bonus`/`defense_bonus`/
  `damage_bonus` feeding the D20 combat resolver; ground items render on the map
  and are picked up (**G**/`get`) / dropped on tiles; inventory overlay (**I**).
  Additive `items` column migration; Cellar re-locked behind the grabbable Rusty
  Key. → `handoff-04-phase3-inventory-equipment.md`.
- **Phase 4 — Classes, spells, mana.** Character classes; spell list (data-driven);
  mana pool + costs/cooldowns; quickslot casting; ranged/AoE on the grid. *Spec
  ready* → `handoff-05-phase4-classes-spells-mana.md`.
- **Phase 5 — Portraits (Novita).** Generated character + mob portraits; portrait
  panel in the sidebar / combat UI. Generation service mirroring
  `deepseek_integration.py`; generate-once + aggressive cache. *Independent — can
  start any time once a Novita key is on the box.*
- **Phase 6 — Polish.** HUD overlay, sprite tilesets, procedural room generation,
  sound, animation, balance.

---

## 6. Cross-cutting concerns

- **Single-worker authority.** All positions/tilemaps live in `WorldState` in one
  process. Keep it that way; horizontal scale would need Redis + a shared sim (out
  of scope). The `broadcast_to_room` seam is still where Redis would slot in.
- **Persistence.** Phase 1 spawns entities at a zone's spawn tile and does **not**
  persist `(x,y)` (respawn at spawn on reconnect). Persisting tile position is a
  later nicety. Durable state (which room/zone, hp, inventory) still writes through.
- **Multiplayer occupancy.** MVP: movement is blocked by walls and by tiles occupied
  by any entity (clean tactical feel). Revisit if it feels cramped.
- **LLM cost.** Layer 1 is LLM-free. Layer-2 player `talk` keeps the existing
  per-account rate limit. Mob smack-talk gets its own per-mob cooldown + global
  budget + canned fallback so it can't run away on cost.
- **Deploy.** Unchanged flow (git pull + restart). New backend deps go in
  `requirements.txt`; vendor rot.js into `static/vendor/`. Watch the WS protocol
  version — client and server change together; a hard cutover is fine (closed alpha).
- **Tests.** The world-model rewrite **breaks the room-graph movement tests**
  (`test_realtime.py`, `test_world.py`, `test_exits.py`). Rewriting them is part of
  the work, not an afterthought. Keep auth/rate-limit tests green.

---

## 7. Open decisions (deferred, decide before the relevant phase)

- **Permadeath?** "Roguelike" implies it, but BGID is a *persistent multiplayer*
  world where permadeath is brutal. **Default: respawn** (as today). Revisit at
  Phase 3/4 — maybe optional hardcore characters.
- **Procedural vs authored maps.** Phase 1 uses small **authored** layouts.
  Procedural generation is Phase 6.
- **Sprites vs emoji.** Emoji/ASCII through Phase 1–4; sprite tilesets in Phase 6.
- **Map art via Novita?** Portraits first (Phase 5). Tile/scene art is a stretch,
  not committed.

---

## 8. Practical needs / dependencies

- **API keys (Bryan to provide on the box `.env`, chmod 600, never committed):**
  - `NOVITA_API_KEY` — image generation (Phase 5).
  - Any other third-party as phases require.
- **New libs:** `rot.js` (client, vendored). Backend pathfinding can be hand-rolled
  (BFS/greedy) for MVP — no new backend dep required for Phase 1.
- **Config knobs introduced:** `COMBAT_TICK_SECONDS`, mob-chatter cooldown/budget,
  move cooldown, FOV radius (see Phase 1 doc for defaults).

---

## 9. How to execute

Build **one phase per fresh session**, loading the relevant phase handoff first
(plus this master for context). Keep each phase shippable and deployed before
starting the next. Commit + push + `git pull` deploy as usual; reseed only when the
schema changes. Update this master's phase list as phases land.
