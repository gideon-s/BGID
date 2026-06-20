# Handoff 08 — Status-effect extensions: debuffs/DoT, gear effects, VFX, spell buffs

**Status:** ✅ SHIPPED 2026-06-19 — entity-keyed effects (`player:`/`npc:`) + DoT
tick (`game_loop._apply_dots`); debuffs (`debuffs.py`: Weaken/Poison/Slow) +
mob-attack fold-in + venomous mobs (Cave Spider); spell buffs/debuffs
(`spells.py` `buff`/`debuff` kinds: Bless/Slow/Venom Bolt, wired into Cleric/Mage);
effect-granting gear (`gear_effects.py`: Ring of Haste/Band of Might, synced on
equip/unequip/connect); on-token icons + flash + mob `entity_effects`; seeded
Ring of Haste + Cave Spider in the Cellar. Suite **227 green** (+ `test_debuffs.py`,
updated `test_effects.py`). No migration (effects in-memory). See `ARCHITECTURE.md`.
· **Depends on:** the timed-buff system already shipped
(`effects.py`, `potions.py` buff-kind, the combat fold-ins, `game_loop._expire_effects`,
the client `#buffs` panel — all live). **Goal:** grow the one-directional buff
system into a full status-effect layer: **debuffs + damage-over-time** on mobs (and
players), **effect-granting equipment**, **on-token VFX/icons**, and **spell-cast
buffs/debuffs**. These four are interlinked — they share one **foundational change**
(§1) — so build that first.

> Read `effects.py`, `casting.py`, and `combat.py` before starting. Keep the
> existing buff potions working; this is purely additive.

---

## 0. What exists now (the seams you build on)

- **`effects.py`** — in-memory timed effects, keyed by **`player_id` (int)**.
  Each effect = `{name, glyph, until(monotonic), atk, dmg, defn, haste}`.
  `apply_effect`, `active(pid)`, `bonuses(pid)→{attack,damage,defense}`,
  `haste_factor(pid)`, `snapshot(pid)`, `sweep()→{pid:[expired names]}`, `clear(pid)`.
  Survives reconnects; cleared on restart. **Players only — NPCs have no effects yet.**
- **Combat fold-ins** (`combat.py`): `effects.bonuses(player_id)` is added to gear in
  `resolve_player_attack` (atk/dmg), `resolve_pvp_attack` (atk/dmg + target def), and
  `resolve_mob_attack` (player def). The shared death paths `damage_npc` /
  `damage_player` already broadcast `combat` + handle death/respawn/loot/XP.
- **Move haste**: the `move` handler scales `MOVE_COOLDOWN_SECONDS * effects.haste_factor(pid)`.
- **`potions.py`** — `POTIONS[name]` with `kind` ∈ heal/mana/restore/**buff**; the `use`
  handler branches buff → `effects.apply_effect` + an `effects` WS event.
- **`game_loop`** — slow tick (`TICK_SECONDS`=15) runs `_expire_effects()`; fast combat
  tick (`COMBAT_TICK_SECONDS`) runs `_combat_tick_once()` (mob AI).
- **`casting.py`** — `resolve_cast(player, room, spell, x, y)`; spells from `spells.py`
  (`effect.kind` ∈ damage/heal; shapes self/bolt/blast). Damage routes through
  `combat.damage_npc`; self-heal mutates the caster. **No buff/debuff spell kind yet.**
- **Client** (`static/index.html`): `setBuffs()` renders `#buffs` chips in the Status
  panel from the `effects` event; tokens are drawn in `paint()` (health bar already
  drawn over hurt entities — the pattern to copy for buff icons).

---

## 1. Foundation — entity-keyed effects + a DoT tick (DO THIS FIRST)

Two of the features (debuffs on mobs, poison) need effects on **NPCs**, and poison
needs **damage over time**. Generalize `effects.py`:

- **Key by a string `"player:{id}"` / `"npc:{id}"`** (or a `(kind,id)` tuple) instead of a
  bare `player_id`. Add a thin `eid(kind, id)` helper. Keep `bonuses`/`haste_factor`
  signatures taking that key. Update the combat fold-ins + the `use`/connect/sweep
  callers to pass `eid("player", pid)`. (Mechanical rename; the buff tests pin behavior.)
- **Add a `dot` field** to each effect: `{dot: int, dot_interval: float, _next: monotonic}`
  — damage applied every `dot_interval` seconds. `apply_effect(..., dot=0, dot_interval=3)`.
- **A DoT tick**: a new `effects.due_dots()` (or fold into the fast combat tick in
  `game_loop`) that, for each active effect with `dot>0` whose `_next <= now`, yields
  `(entity_key, dot_amount)` and advances `_next`. `game_loop` applies each via
  `combat.damage_npc` / `combat.damage_player` (so death/respawn/loot/XP/broadcast all
  reuse the shared paths — a poisoned mob that dies drops loot + grants XP to the
  applier). Attribute the kill to the effect's `source` (store `source_name`/`source_id`
  on the effect so `damage_npc` reports "slain by poison from X" and XP routes right).
- `snapshot`/`sweep` unchanged in shape (now per entity key).

**Acceptance:** an effect can be applied to an NPC; `effects.bonuses("npc:3")` reflects
it; a `dot` effect drains the target on the tick and a lethal tick kills it through the
normal death path (loot + XP).

---

## 2. Debuffs — weaken & poison (on mobs *and* players)

Reuses §1. Debuffs are just effects with **negative** combat deltas and/or a `dot`.

- **Fold mob effects into the mob's attack.** Today `resolve_mob_attack` gives the mob no
  atk/dmg bonus. Add `eb = effects.bonuses(eid("npc", npc_id))` and pass
  `atk_bonus=eb["attack"], dmg_bonus=eb["damage"]` — so a **Weaken** (−2 atk/dmg) makes
  a mob miss/hit softer. (Symmetric to the player fold-ins already there.)
- **Sources of debuffs:** a thrown potion / a debuff spell (§5) / a mob's own attack
  (a "venomous" mob applies poison to the player it hits — apply in `resolve_mob_attack`
  on a hit). Author a couple in a registry (e.g. extend `potions.py` or a `debuffs`
  table): **Weaken** (−atk/−dmg, 30s), **Poison** (`dot` 2/3s, 18s).
- **Client:** debuff chips should read as harmful — render negative effects in a red
  variant of the `#buffs` chip (pass a `harm: true` flag in the snapshot; the panel +
  the on-token icons (§4) tint accordingly). A DoT hit already shows the floating
  damage number (it rides `combat`/`damage_*`).

**Acceptance:** poisoning a mob ticks visible damage until it dies (or the effect ends);
weakening a mob measurably lowers its hits; a "venomous" mob can poison the player.

---

## 3. Effect-granting equipment (e.g. a Ring of Haste)

Worn gear grants a **non-expiring** effect while equipped.

- **Registry**: `gear_effects.py` (or reuse the item name) mapping an item name →
  effect params, e.g. `{"Ring of Haste": {"glyph":"⚡","haste":0.5}}`,
  `{"Band of Might": {"atk":1,"dmg":1}}`. (Authoring lives next to `shops.py`/`classes.py`.)
- **Equip/unequip hooks** (`ItemService.equip`/`unequip`, or the `equip`/`unequip` WS
  handlers in `main.py`): on **equip**, `effects.apply_effect(eid("player",pid), name,
  glyph, duration=GEAR_PERSIST, ...)` with a sentinel "infinite" duration and a
  `source:"gear"` marker; on **unequip**, remove that named effect (add
  `effects.remove(key, name)`). Re-sync on connect (after the worn gear is known) and
  whenever inventory changes — simplest is to **rebuild gear effects from the worn set**
  in one helper `sync_gear_effects(pid, worn_items)` called from equip/unequip/connect.
- **Display**: gear effects show in `#buffs`/on-token icons **without a countdown** (the
  snapshot should mark `gear:true` → the client hides "Ns" and maybe shows a ◆).

**Design note:** keep gear effects in the same `_active` store (so `bonuses`/`haste_factor`
already pick them up) but flag them `gear` + non-expiring; `sweep()` must skip gear
effects. Alternatively compute gear contributions separately and merge in
`bonuses`/`haste_factor` — pick whichever keeps `sweep` cleanest (the flag approach is
fewer call-site changes).

**Acceptance:** equipping a Ring of Haste makes you move faster and shows a ⚡ chip;
unequipping removes it; it persists across a reconnect (re-synced from worn gear).

---

## 4. On-token VFX + icons

Surface effects on the **map**, not just the panel.

- **Icons over the token** (`paint()` in `static/index.html`): for the player (and any
  entity whose effects you know — see below), draw the active effect glyphs in a small
  row just above the token (mirror `drawHealthBar`'s placement; keep ≤3 then "+N").
  Tint debuffs red, gear effects with a ◆. Source: `S.buffs` for the player.
- **Apply/expire VFX**: on an `effects` add, a brief glow on the token (reuse
  `flashEntity(animId(id), color)` — gold for buffs, sickly green for poison/debuffs) +
  optionally a rising "💪 Strength!" floater (reuse `floatText`). On expire, a fade.
- **Other entities' effects (optional):** to show a poisoned *mob*'s icon, include a
  compact `effects:[{glyph,harm}]` summary in the **`zone_state` entity** payload + the
  `entity_spawned`/a small `entity_effects` broadcast when a mob's effects change
  (`world.zone_snapshot` reads `effects.snapshot(eid("npc",id))`). Scope this last —
  the player's own icons are the high-value bit.

**Acceptance:** your active buffs/debuffs show as icons over your token with the right
tint and a flash on apply; (stretch) a poisoned mob shows a green icon.

---

## 5. Spell-cast buffs & debuffs

Let spells apply effects, not just damage/heal.

- **`spells.py`**: add `effect.kind` ∈ **`buff`** (self/ally) and **`debuff`** (on the
  target) carrying the effect params (`atk/dmg/defn/haste/dot/dot_interval/duration`).
  Author e.g. **Bless** (self, shape `self`, +atk/+def 30s), **Slow** (shape `bolt`,
  target debuff haste×2 i.e. slower, 15s), **Venom Bolt** (shape `bolt`, damage + a
  poison `dot`).
- **`casting.resolve_cast`**: after resolving `targets`, branch on `eff_kind`:
  - `buff` → `effects.apply_effect(eid("player", player_id or ally), …)` (self shape =
    the caster; could extend to target-ally later).
  - `debuff` → for each target entity (npc), `effects.apply_effect(eid("npc", tid), …)`
    with `source=caster`. Combine with damage when a spell does both (Venom Bolt).
  - Emit the existing `spell_cast` VFX; push an `effects` event to the caster (self
    buffs) and rely on §4 for target-debuff icons.
- Mana/cooldown gating, LOS, range — all already enforced by `resolve_cast`; buff/debuff
  spells slot into the same flow.

**Acceptance:** casting Bless self-buffs (chip + combat bonus); a debuff bolt applies
weaken/poison to the struck mob (its icon + ticking damage).

---

## 6. Tests (extend `test_effects.py` + new `test_debuffs.py`)

- `effects` keyed by entity; `bonuses`/`haste_factor`/`snapshot` per `npc:`/`player:`.
- DoT: a `dot` effect drains an NPC on `due_dots`; a lethal tick kills via `damage_npc`
  (assert loot/XP path fired) attributed to the source.
- Weaken folds into `resolve_mob_attack` (monkeypatch `_attack_roll`, assert the mob's
  `atk_bonus` is negative).
- Gear effect: equip a Ring of Haste → `haste_factor` < 1; unequip → back to 1; re-sync
  on a fresh connect.
- Spell buff/debuff: `resolve_cast` of a `buff` spell adds a self effect; a `debuff`
  bolt adds an effect to the target npc.
- Keep the full suite green (currently **219**). No migration expected (effects are
  in-memory; gear-effect & spell metadata are code/registry). If you add seeded items
  (a Ring of Haste, debuff potions), use `_get_or_create` (idempotent) + `seed.py` on deploy.

## 7. Definition of done

- The four features work over `wss://`; existing buff potions unaffected.
- Full suite green (+ new tests, all deterministic — no live timing flakes: drive
  `due_dots`/`sweep` directly and monkeypatch rolls).
- `ARCHITECTURE.md` updated (the effects layer now covers NPCs, DoT, gear, spells);
  in-repo memory entry refreshed on ship.

## 8. Build order (suggested)

1. **§1 foundation** — entity-keyed effects + DoT tick (+ retarget the existing buff
   call-sites; tests stay green). *Nothing visible yet, but everything else needs it.*
2. **§2 debuffs** — mob-attack fold-in + Weaken/Poison + the DoT-death path. First
   visible payoff: poison a mob to death.
3. **§5 spell buff/debuff** — the most fun delivery vector for §1–2.
4. **§3 gear effects** — equip/unequip sync.
5. **§4 on-token VFX/icons** — polish pass once the data is flowing (player icons first,
   mob icons as a stretch).
