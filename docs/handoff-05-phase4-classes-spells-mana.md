# Handoff 05 — Phase 4: Classes, Spells & Mana

**Status:** ready to build · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phases 1–3 (shipped). **Goal:** give characters a **class**, a **mana** pool, and
a **data-driven spell list** they cast from quickslots — including the first
**ranged and AoE** effects on the tile grid (line-of-sight bolts, target-tile
blasts), reusing the Phase-1 combat plumbing.

> Read master §1–4 and the Phase 1–3 handoffs first. This phase builds directly
> on: the tile grid + FOV (`world.py`), the D20 melee resolver (`combat.py`), the
> equipment-bonus seam (`ItemService.equipment_bonuses`, Phase 3), the regen tick
> (`game_loop._tick_once`), and the per-player cooldown pattern (`_last_move`).

---

## 1. The slice (acceptance demo)

1. **Create a character and pick a class** (Warrior / Mage / Cleric / Rogue) at the gate.
   The class sets starting abilities, a **mana** pool, a default glyph, and a
   **spell list**.
2. A **mana bar** sits under the HP bar; **quickslots** (number keys **1–9** +
   on-screen buttons) show the character's spells with cost + cooldown state.
3. As a **Mage**, press the Firebolt quickslot, **click a tile with the Cellar
   Rat in line of sight** → a bolt streaks across the grid, damages it, spends
   mana, and goes on cooldown. Out of mana / on cooldown / no line of sight /
   out of range → a soft `error`, no spend.
4. As a **Cleric**, cast **Heal** on yourself (self-target, no LOS needed) → HP
   rises, mana drops. As a **Mage**, cast **Frost Blast** on a target tile → all
   entities within its radius take damage (AoE).
5. **Mana regenerates** out of combat on the regen tick. A **Warrior**'s
   Power Strike (cheap, melee-range, mana-fuelled bonus damage) works too.

If class selection, mana spend/regen, cooldowns, and ranged + AoE casting all
work over `wss://`, Phase 4 is done.

---

## 2. In scope / out

**In:** a small set of **data-driven classes** (`classes.py`) and **spells**
(`spells.py`); `Player.char_class` + `mana`/`max_mana` columns (additive
migration); class pick at character creation; mana pool + per-spell mana cost +
per-(player,spell) cooldown; server-side **line-of-sight** (`world.line_of_sight`)
and **radius** (`world.tiles_in_radius`) helpers; a `cast` WS command resolving
self / single-target-bolt / target-tile-blast; damage reuses the kill/respawn
paths, heal adjusts HP; `spell_cast` VFX event; mana regen on the regen tick;
quickslot UI + mana bar + click-to-target; tests; migration + deploy.

**Out (later / deferred):** durable buffs/debuffs with timers (status-effect
*system* — keep effects instantaneous for MVP; a single optional one-shot like
"heal" is fine, "haste for 10s" is Phase 6); summons/pets; spell leveling/scaling
trees; cones/walls (only single-target bolt + circular blast + self for now);
friendly-fire toggles (blast hits everyone in radius — simplest tactical rule,
revisit); NPC spellcasting (mobs stay melee); a 5th+ class beyond the four MVP
(Warrior / Mage / Cleric / Rogue); respec. **Permadeath stays deferred — respawn
as today** (master §7).

---

## 3. Data model (`models.py` + migration)

Add to `Player` (all defaulted → additive `ALTER TABLE`, see §9):

| column | type | meaning |
|--------|------|---------|
| `char_class` | `String(20)` default `'wanderer'` | class id (key into `classes.py`) |
| `mana` | `Integer` default 0 | current mana |
| `max_mana` | `Integer` default 0 | mana pool cap |

`wanderer` is the migration default for **existing characters** (a no-frills
melee fallback so old rows keep working); new characters pick a real class. A
class's `max_mana`/abilities/glyph are applied at creation; `mana` starts full.
`Player.level` already exists — spell access can gate on it later, not now.

`CharacterOut` / `CharacterCreate` (`auth_schemas.py`) gain `char_class`;
`CharacterService.create(db, user, name, char_class)` validates it against
`classes.py` and stamps the class's starting stats. Plumb `char_class` through
`auth_api.create_character`.

---

## 4. Classes (`classes.py`, new — data-driven)

A plain registry, mirroring how the world stays authored/reviewable:

```python
CLASSES = {
  "warrior": {"name":"Warrior","glyph":"🛡️","max_mana":10,"mana_regen":1,
              "abilities":{"str":15,"con":14,"dex":11},"spells":["power_strike"]},
  "mage":    {"name":"Mage","glyph":"🧙","max_mana":30,"mana_regen":3,
              "abilities":{"intel":15,"dex":12,"con":10},"spells":["firebolt","frost_blast"]},
  "cleric":  {"name":"Cleric","glyph":"⛪","max_mana":24,"mana_regen":2,
              "abilities":{"wis":15,"con":12,"str":11},"spells":["heal","smite"]},
  "rogue":   {"name":"Rogue","glyph":"🗡️","max_mana":16,"mana_regen":2,
              "abilities":{"dex":15,"str":12,"con":11},"spells":["backstab","throw_dagger"]},
  # 'wanderer' = the ability-neutral fallback for pre-Phase-4 characters: melee only.
  "wanderer":{"name":"Wanderer","glyph":"🧝","max_mana":0,"mana_regen":0,
              "abilities":{},"spells":[]},
}
```

A helper `class_spells(player)` returns the resolved spell defs for a player's
class. `mana_regen` is per regen tick (§7).

---

## 5. Spells (`spells.py`, new — data-driven)

A registry keyed by spell id. Each spell:

```python
SPELLS = {
  "firebolt":   {"name":"Firebolt","glyph":"🔥","cost":3,"cooldown":1.0,
                 "range":6,"shape":"bolt","effect":{"kind":"damage","dice":(2,6),"mod":"intel"}},
  "frost_blast":{"name":"Frost Blast","glyph":"❄️","cost":7,"cooldown":5.0,
                 "range":6,"radius":1,"shape":"blast","effect":{"kind":"damage","dice":(2,4),"mod":"intel"}},
  "heal":       {"name":"Heal","glyph":"✨","cost":5,"cooldown":3.0,
                 "range":0,"shape":"self","effect":{"kind":"heal","dice":(2,6),"mod":"wis"}},
  "smite":      {"name":"Smite","glyph":"⚡","cost":4,"cooldown":1.5,
                 "range":5,"shape":"bolt","effect":{"kind":"damage","dice":(1,8),"mod":"wis"}},
  "power_strike":{"name":"Power Strike","glyph":"💥","cost":4,"cooldown":2.0,
                 "range":1,"shape":"bolt","effect":{"kind":"damage","dice":(1,6),"mod":"str","bonus":4}},
  # Rogue: a melee burst (range 1, hits the adjacent tile) + a thrown ranged poke.
  "backstab":   {"name":"Backstab","glyph":"🗡️","cost":4,"cooldown":2.0,
                 "range":1,"shape":"bolt","effect":{"kind":"damage","dice":(2,6),"mod":"dex","bonus":2}},
  "throw_dagger":{"name":"Throw Dagger","glyph":"🔪","cost":2,"cooldown":1.0,
                 "range":5,"shape":"bolt","effect":{"kind":"damage","dice":(1,6),"mod":"dex"}},
}
```

> **Mod note:** spell effects scale on the caster's *class* ability (Rogue spells
> on `dex`, Mage on `intel`, Cleric on `wis`, Warrior on `str`) — `effect.mod`
> already encodes this, so a Rogue with high DEX hits as hard with Backstab as a
> Mage does with Firebolt. No melee to-hit roll (spells auto-hit; §5).

- `shape`: **`self`** (target = caster), **`bolt`** (single entity on the target
  tile, requires range + LOS), **`blast`** (all entities within `radius` of the
  target tile, requires range + LOS to the center tile).
- `effect.kind`: **`damage`** or **`heal`**; `dice=(n,d)` rolls `n`d`d`; `mod` is
  the caster ability modifier added (e.g. `intel`); optional flat `bonus`.
- Keep the math its own tiny resolver in `spells.py` (`roll_effect(caster, spell)`)
  — combat.py's `_attack_roll` is melee-to-hit; spells **auto-hit** for MVP
  (range/LOS *is* the counterplay), so no separate attack roll. Revisit saves/
  resist later.

---

## 6. Casting resolver (`combat.py` or new `casting.py`)

`resolve_cast(player_id, room_id, spell_id, tx, ty)`:

1. Validate the player **knows** the spell (in their class list), is **alive**.
2. **Mana**: `player.mana >= cost` else soft error. **Cooldown**: per
   `(player_id, spell_id)` monotonic table (mirror `_last_move`) — `_ready(...)`
   else soft error with `retry_after`.
3. **Targeting**: `self` → target = caster's tile. `bolt`/`blast` → require
   `chebyshev(caster, (tx,ty)) <= range` **and** `world.line_of_sight(room_id,
   caster, (tx,ty))`.
4. **Resolve effect** on the target set (`bolt`: the one entity on the tile;
   `blast`: entities in `world.tiles_in_radius(room_id, (tx,ty), radius)`; `self`:
   the caster). For `damage`, reuse the **existing HP-write + `kill_npc` /
   player-death+`_respawn` paths** (refactor `resolve_player_attack`'s tail so
   damage application is shared, not duplicated). For `heal`, clamp to max and
   write through.
5. **Spend** mana, **set cooldown**, `db.commit()`.
6. Broadcast a **`spell_cast`** VFX event (caster, spell glyph, from-tile,
   target tile, radius) + the usual `combat` / `entity_died` / `player_defeated`
   / `respawn` events per affected entity, plus a personal **`stats`** update so
   the caster's mana bar refreshes.

`world.line_of_sight(room_id, a, b)`: Bresenham over tiles; blocked by
**non-transparent** tiles — reuse the client's sight rule (`WALL`, `PILLAR`
block; `WATER`/floor/doors don't). Add a `SIGHT_BLOCKING = {WALL, PILLAR}` set in
`world.py` next to `BLOCKING`. `world.tiles_in_radius(room_id, center, r)`:
in-bounds tiles within Chebyshev `r` (optionally LOS-gated from center).

---

## 7. Mana regen (`game_loop.py`)

Extend `_tick_once` (the 15s regen tick): for each **online** player not in
recent combat, regenerate `CLASSES[char_class]["mana_regen"]` mana up to
`max_mana`, and push a `stats` event when it changes. Keep it DB-light (batch the
commit). A faster, separate mana tick is an option but the 15s regen tick is the
natural home and matches the NPC-HP-regen precedent. Out-of-combat gating can be
coarse for MVP (regenerate always, or skip players who took/dealt damage in the
last few seconds — reuse a `_last_combat_at` stamp if easy).

New config knobs (with defaults, in `config.py`): none strictly required (regen
lives in class data); add `MANA_REGEN_TICK_SECONDS` only if you split the tick.

---

## 8. WS protocol delta + client (`main.py` + `static/index.html`)

**Client→server:** `cast {spell_id, x, y}` (`x,y` omitted/ignored for `self`).

**Server→client:**
- `spell_cast {caster_id, spell, glyph, fx, x0,y0, x,y, radius}` — broadcast for
  the animation (a streaking line for bolt, an expanding ring for blast, a glow
  for self/heal). Drawn as a short transient overlay on the canvas.
- `stats {player_id, hp, max_hp, mana, max_mana}` — personal mana/HP refresh
  (the existing `combat` event already carries target HP; `stats` covers mana and
  out-of-combat regen).
- Reuse `combat` / `entity_died` / `player_defeated` / `respawn`.

`zone_state.you` and the connect `inventory`-style lazy fetch pattern extend
naturally: include `mana`/`max_mana` in `you`, and send the class's spell list
once (a lazy `spells` command or fold it into the first `stats`). **Don't push
new frames on connect before the existing `zone_state`** — keep the connect
sequence stable (the Phase 2/3 rule).

**Client:**
- **Mana bar** under the HP bar (same widget style).
- **Quickslot bar** in the actions strip under the map: one button per known
  spell, showing glyph + cost, greyed while on cooldown / unaffordable. Number
  keys **1–9** map to slots.
- **Targeting:** pressing a `self` spell casts immediately; a `bolt`/`blast`
  spell enters **target mode** — the next map click sends `cast` with that tile
  (Esc cancels; optionally highlight range + a target reticle). Auto-target the
  nearest visible enemy as a convenience if no click within a moment is overkill
  — click-to-target is the MVP.
- **VFX:** render `spell_cast` as a brief canvas overlay (line / ring / flash),
  then `draw()`.

---

## 9. Migration & deploy

**Schema change** (new `players` columns) — same additive, accounts-preserved
pattern as Phase 3:

1. `git pull`.
2. `python migrate_phase4.py` — idempotent `ALTER TABLE players ADD COLUMN`
   (`char_class` default `'wanderer'`, `mana`/`max_mana` default 0), guarded by
   `PRAGMA table_info(players)`. **Back up `game.db` first.**
3. `python seed.py` — no new world rows strictly needed, but a good place to (a)
   give the seeded **Caretaker/Innkeeper** nothing new, and (b) if desired, drop
   a starter spell-scroll item (optional, P6). Existing characters stay
   `wanderer` until the player makes a new one (or add a one-time "reclass at the
   altar" later).
4. `systemctl restart bgid-api` (one worker).

Existing live characters become **`wanderer`** (melee, 0 mana) — playable,
unchanged feel. New characters get the full kit. Note this in the deploy.

---

## 10. Tests (`test_spells.py`)

- `classes.py` / `spells.py` registry sanity (every class spell exists; costs ≥ 0).
- `CharacterService.create` stamps class abilities/mana/glyph; rejects an unknown
  class; defaults to `wanderer`.
- `world.line_of_sight`: clear across floor; blocked by a wall/pillar between.
- `world.tiles_in_radius`: correct set, in-bounds, radius-bounded.
- `resolve_cast`: bolt damages the entity on the target tile (LOS+range ok);
  rejects out-of-range / no-LOS / insufficient mana / on-cooldown with no spend;
  spends mana + sets cooldown on success.
- `blast` hits every entity in radius (seed two mobs adjacent and assert both
  take damage).
- `heal` raises HP, clamped to max, costs mana.
- Mana regen on `_tick_once` restores up to `max_mana`, not beyond.
- Damage path reuse: a spell killing a mob fires `entity_died` + schedules
  respawn (same as melee); a spell that drops a player triggers `_respawn`.
- Keep auth / combat / rate-limit / Phase 1–3 tests green (watch the shared
  `test_bgid.db` — one pytest at a time).

---

## 11. Definition of done

- The five acceptance steps work over `wss://`.
- Full suite green (new `test_spells.py` + all prior).
- Docs: tick master §5 Phase 4; document `char_class`/`mana` columns, the
  `cast` command, and `spell_cast`/`stats` events + LOS/radius helpers in
  `ARCHITECTURE.md`; update the in-repo memory entry on ship.

---

## 12. Build order (suggested)

1. **Data + model:** `classes.py`, `spells.py`, Player columns, `migrate_phase4.py`,
   class plumb-through in character creation + schemas + tests. *(no behavior yet)*
2. **World helpers:** `line_of_sight`, `tiles_in_radius`, `SIGHT_BLOCKING` + tests.
3. **Casting core:** `resolve_cast` (refactor the shared damage-application tail
   out of `resolve_player_attack`), mana spend + cooldown + the `cast` WS command,
   `spell_cast`/`stats` events + tests. *(castable from a raw WS message)*
4. **Mana regen:** extend the regen tick + tests.
5. **Client:** mana bar, quickslot bar, number keys, click-to-target, VFX, class
   picker at the gate.
6. **Seed + deploy:** migration on the box, existing chars → `wanderer`, verify
   a freshly-created Mage can Firebolt the Rat.
