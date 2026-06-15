# Handoff 04 — Phase 3: Inventory & Equipment

**Status:** shipped · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phase 1 + Phase 2 (shipped). **Goal:** give characters an inventory and worn
equipment — pick items up off the floor, carry them (no encumbrance), equip them
into slots, and have that gear actually change combat numbers.

> Read master §3–4 and the Phase 1/2 handoffs first. Items already exist as a DB
> concept (`Item`, room/player ownership, the Rusty Key as an exit key). Phase 3
> makes them *spatial* (a tile on the floor), *wearable* (equip slots), and
> *mechanical* (stat bonuses into the D20 combat resolver).

---

## 1. The slice (acceptance demo)

1. Spawn in the Foyer. An **Iron Sword (⚔️)** and **Leather Armor (🛡️)** lie on
   the floor as map glyphs. Walk onto the sword's tile → a "grab" affordance
   appears; press **G** (or `get sword`) → it leaves the floor and enters your
   inventory; everyone in the zone sees it vanish.
2. Press **I** → an **inventory overlay** lists what you carry. **Equip** the
   sword and armor (weapon / armor slots). Equipped gear shows under "You".
3. Fight the **Cellar Rat** with gear on: your hits land harder and you take less
   — the sword's `damage_bonus`/`attack_bonus` and the armor's `defense_bonus`
   feed the rolls. Unequip/`drop` puts an item back on your tile.
4. The **Rusty Key** is on the Foyer floor; the **Cellar stairs are locked again**
   (Phase 2 left them open only because there was no pickup yet). Grab the key →
   descend → a **ring** waits in the Cellar as the reward.

If pickup/drop, equip/unequip across slots, and the combat stat effect all work
over `wss://`, Phase 3 is done.

---

## 2. In scope / out

**In:** item tile positions (ground items render on the map); pickup (bump/stand
+ **G**, or `get`) and drop onto tiles; equip slots (weapon, armor, ring ×2,
amulet) with per-slot limits; item combat stats (`attack_bonus`, `defense_bonus`,
`damage_bonus`) feeding the D20 resolver; inventory overlay + equipped summary;
quickslot **G**/**I** keys; seeded gear; re-locking the Cellar; column migration;
tests.

**Out (later):** consumables/potions & `use` effects (the `is_usable`/`use` verb
stays a stub — heals/charges are P4-adjacent); weight/encumbrance (locked out by
D7); item rarity/affixes/generation; trading/economy; NPC equipment (mobs use
bare ability scores for now); persisting dropped-item *layouts* beyond the DB
row (they persist because they're DB rows, but no per-session cleanup).

---

## 3. Data model (`models.py` + `schemas.py`)

`Item` already had `name/description/item_type/value/room_id/player_id/
is_movable/is_usable/is_equippable`. Phase 3 **adds columns** (all nullable or
defaulted, so the migration is additive — see §9):

| column | type | meaning |
|--------|------|---------|
| `glyph` | `String(8)` default `📦` | map glyph when on the ground |
| `tile_x`, `tile_y` | `Integer` null | ground position within `room_id`'s grid |
| `equip_slot` | `String(20)` null | `weapon`\|`armor`\|`ring`\|`amulet` — the slot it occupies |
| `equipped` | `Boolean` default false | currently worn by its owning player |
| `attack_bonus` | `Integer` default 0 | + to-hit when equipped (weapon/ring/amulet) |
| `defense_bonus` | `Integer` default 0 | + AC when equipped (armor/ring/amulet) |
| `damage_bonus` | `Integer` default 0 | + damage when equipped (weapon/ring) |

`equip_slot is not None` ⇒ the item is equippable (`is_equippable` kept in sync).
Slot limits live in one place (`services.SLOT_LIMITS`): weapon 1, armor 1,
amulet 1, ring 2.

Item location is a 3-state, mutually exclusive: **on the ground** (`room_id`
set, `tile_x/y` set, `player_id` null), **carried** (`player_id` set, room/tile
null, `equipped` false), or **equipped** (`player_id` set, `equipped` true).

---

## 4. WorldState ground-item layer (`world.py`)

Items don't occupy tiles for movement (you walk *over* them to grab them), so
they're tracked separately from `_occupant`:

- `RoomNode.item_pos: {item_id: (x,y)}` and `RoomNode.item_meta: {item_id:
  {name, glyph}}`, populated in `load()` from ground items (those with a
  `room_id` and no owner). Missing/blocked `tile_x/y` falls back to a free floor
  tile.
- Helpers: `ground_items(room_id)`, `item_at(room_id,x,y)` (topmost id on a
  tile), `add_ground_item(...)`, `remove_ground_item(item_id)`.
- `zone_snapshot` gains an **`items: [{id,name,glyph,x,y}]`** array (separate
  from `entities`, so the client renders them on the map but doesn't list them
  in "who's here").

The DB row is the durable truth; `item_pos` is the live mirror, updated on
pickup/drop alongside the DB write (pickup/drop are not on the combat hot path,
so a DB round-trip is fine).

---

## 5. Inventory / equipment services (`services.py`)

`ItemService` gains:

- `inventory_of(db, player_id) -> [Item]` — everything the player carries.
- `pickup(db, player_id, item_id) -> Item` — ground→carried (validates the item
  is on the player's room and movable).
- `drop(db, player_id, item_id) -> Item` — carried/equipped→ground (clears
  `equipped`).
- `equip(db, player_id, item_id)` — sets `equipped`, enforcing `SLOT_LIMITS`
  (auto-unequips the oldest item in the slot when full, so equip never errors on
  a full slot — it swaps).
- `unequip(db, player_id, item_id)`.
- `equipment_bonuses(db, player_id) -> {attack, defense, damage}` — sums equipped
  items; **the single seam combat reads.**

World-side tile placement (add/remove `item_pos`) is done in `main.py` around
these calls, mirroring how `move`/transitions split DB (services/world) vs tile
(world) vs broadcast (main).

---

## 6. Combat integration (`combat.py`)

`_attack_roll(attacker, defender, atk_bonus=0, dmg_bonus=0, def_bonus=0)`:

- `to_hit = d20 + STR_mod + atk_bonus` vs `AC = 10 + DEX_mod + def_bonus`
- `damage = max(1, 1d6 + STR_mod + dmg_bonus)`

`resolve_player_attack` passes the *player's* `attack`/`damage` bonuses (NPCs
have no gear, so defender `def_bonus=0`). `resolve_mob_attack` passes the
*player-as-defender's* `defense` bonus (`atk/dmg_bonus=0` for the bare mob).
Bonuses are read via `equipment_bonuses` inside the existing DB session each
function already opens. NPC gear is out of scope (mobs stay bare).

---

## 7. WS protocol delta (`main.py` + client)

New **client→server** commands:

- `inventory` → server replies `inventory`.
- `pickup {item_id?}` — `item_id` optional; default = the item on the player's
  current tile. Ground→inventory; broadcast `item_taken`; reply `inventory`.
- `drop {item_id}` — inventory→ground at the player's tile; broadcast
  `item_dropped`; reply `inventory`.
- `equip {item_id}` / `unequip {item_id}` — reply `inventory` (gear is
  server-side; no room broadcast needed).

New **server→client** events:

- `inventory {items:[{id,name,glyph,type,equip_slot,equipped,attack_bonus,
  defense_bonus,damage_bonus}]}` — personal.
- `item_dropped {id,name,glyph,x,y}` — to the room (an item appears on a tile).
- `item_taken {id, by}` — to the room (an item leaves the floor).

`zone_state` now also carries `items` (§4). `move {dx,dy}` is unchanged.

---

## 8. Client (`static/index.html`)

- Render `S.groundItems` as glyphs on the map (in FOV), beneath living entities.
- **G** / `get [name]` picks up the item on your tile (a transient "you see X —
  press G" line on step-on). **I** / `inv` toggles an **inventory overlay**
  (modeled on the map overlay): Equipped section + Carried section, each row
  `glyph name (slot)` with `Equip`/`Unequip` and `Drop` buttons.
- Equipped gear summarized under "You" in the panel.
- `equip`/`unequip`/`drop`/`get` text verbs in the command box; update `help`
  and the footer hint.

---

## 9. Migration & deploy

**Schema changes** (new `items` columns) but **no reseed of accounts.** SQLite
takes additive `ALTER TABLE items ADD COLUMN ...` with defaults without
rewriting rows, so the deploy is:

1. `git pull` the code.
2. Run the additive column migration on the box's `game.db` (idempotent guard:
   check `PRAGMA table_info(items)` before adding). A `migrate_phase3.py` script
   is provided; it's safe to run repeatedly.
3. `python seed.py` (idempotent) — adds the new ground items + re-locks the
   Cellar exit **in place** (the down exit's `is_locked`/`key_item_id` are
   updated even though the row exists, mirroring the Phase-1.5/2 in-place tile
   update pattern).
4. `systemctl restart bgid-api` (one worker) → `world.load()` picks up the new
   items/positions.

Accounts, characters, and `game.db` are preserved.

---

## 10. Tests (`test_inventory.py`)

- `equipment_bonuses` sums equipped items; ignores carried-but-unequipped.
- `equip` slot limits: a 2nd weapon swaps out the first; two rings both fit; a
  3rd ring swaps the oldest.
- Pickup over the socket: standing on a ground item + `pickup` → `item_taken` to
  the room, `inventory` to the picker, item gone from `zone_state.items`.
- Drop → `item_dropped` at the player's tile; reappears in `zone_state.items`.
- Combat: an equipped weapon raises damage / armor raises AC (assert via a
  forced roll or bonus plumb-through).
- Locked Cellar with the key now on the floor: grab key → descend (Phase-2
  lock/key path still green).
- Keep auth / combat / rate-limit / Phase-1/2 tile + zone tests green.

---

## 11. Definition of done

- The four acceptance steps work over `wss://`.
- Full suite green (new inventory tests + all prior).
- Docs: tick master §5 Phase 3; note the new `items` columns, `inventory`/
  `item_dropped`/`item_taken` events, and `zone_state.items` in `ARCHITECTURE.md`.

---

## 12. Build order (suggested)

1. **Model + migration:** Item columns, schema, `migrate_phase3.py`. *(data)*
2. **Services:** inventory/equip/bonuses + slot limits + tests. *(rules)*
3. **World + combat:** ground-item layer, `zone_state.items`, combat bonus seam.
4. **WS + client:** commands/events, map rendering, overlay, keys.
5. **Seed + deploy:** gear, re-lock the Cellar, in-place migration on the box.
