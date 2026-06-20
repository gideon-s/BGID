#!/usr/bin/env python3
"""
In-memory authoritative world state for the MUD.

WorldState is the live source of truth for who/what is where. The database is
for persistence and recovery, not live reads:

- Structural data (rooms, resident NPCs, ground items) is loaded at startup.
- Player presence (who is online and in which room) is tracked in memory.
- Durable mutations (a player moving rooms) are written through to the DB.

See ARCHITECTURE.md (step 1).
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, List, Any, Tuple

from database import SessionLocal
import services
import models
import directions
import shops
import effects
import tiles
from config import MOB_RESPAWN_SECONDS

# A generous cap so load() pulls the whole table (service defaults are paged).
_LOAD_LIMIT = 100_000

# Tile semantics now live in the data-driven `tiles.py` registry (handoff-11
# Slice A): a glyph resolves to {name, walkable, transparent, transition}. The
# three predicates below (walkable / sight / transition) read the registry, so a
# new tile type is data, not code. A few glyph constants are kept as readable
# names for the door/stairs transition geometry.
WALL, FLOOR, DOOR = "#", ".", "+"
PILLAR, WATER, RUBBLE = "o", "~", ":"
STAIRS_DOWN, STAIRS_UP = ">", "<"
# Derived from the registry (known glyphs only) — these sets are convenience
# views; the predicates use the registry directly so UNKNOWN glyphs fail safe
# (wall/opaque), which a bare set-membership test could not guarantee.
BLOCKING = {g for g, d in tiles.TILES.items() if not d["walkable"]}
SIGHT_BLOCKING = {g for g, d in tiles.TILES.items() if not d["transparent"]}
TRANSITION_TILES = {g for g, d in tiles.TILES.items() if d["transition"]}
# Fallback box dimensions for rooms with no authored layout (legacy room-graph
# rooms a player might still end up in — Phase 2 tiles the whole world).
_DEFAULT_W, _DEFAULT_H = 11, 9


def _default_grid(w: int, h: int) -> List[str]:
    """A simple walled box: '#' border, '.' floor interior."""
    rows = []
    for y in range(h):
        if y == 0 or y == h - 1:
            rows.append(WALL * w)
        else:
            rows.append(WALL + FLOOR * (w - 2) + WALL)
    return rows


@dataclass
class StepResult:
    """Outcome of attempting a single tile step (the single source of truth for
    both player and mob movement). ``kind`` is one of MOVED / BLOCKED / ATTACK.
    On MOVED, (x, y) is the new tile. On ATTACK, target_kind/target_id name the
    entity occupying the destination (a valid melee target)."""
    kind: str                       # "MOVED" | "BLOCKED" | "ATTACK"
    x: int = 0
    y: int = 0
    target_kind: Optional[str] = None  # "player" | "npc"
    target_id: Optional[int] = None


@dataclass
class RoomNode:
    """Live state for a single room (now an overhead tiled zone)."""
    id: int
    name: str
    description: str
    npc_ids: Set[int] = field(default_factory=set)    # resident NPCs
    item_ids: Set[int] = field(default_factory=set)   # items on the ground
    players: Set[int] = field(default_factory=set)     # online players present
    # direction -> {to_room_id, description, is_locked, key_item_id}
    exits: Dict[str, dict] = field(default_factory=dict)
    # ----- tile layer (Phase 1) -----
    width: int = _DEFAULT_W
    height: int = _DEFAULT_H
    tiles: List[str] = field(default_factory=list)      # row-major glyph rows
    spawn: Tuple[int, int] = (1, 1)
    npc_pos: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    player_pos: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    # Ground items: their tile + static render metadata (name/glyph). Items do
    # NOT participate in occupancy (you walk over them to pick them up), so they
    # live apart from npc_pos/player_pos (Phase 3).
    item_pos: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    item_meta: Dict[int, dict] = field(default_factory=dict)
    # Static per-NPC metadata cached at load (glyph/hostile/aggro/combat/name),
    # so the combat tick can reason about mobs without touching the DB. Live HP
    # is read from the DB only when an attack actually resolves.
    npc_meta: Dict[int, dict] = field(default_factory=dict)
    # ----- room type (Phase 7 / handoff-09 §5) -----
    room_type: str = "dungeon"
    is_safe: bool = False           # sanctuary: blocks PvP + mob aggro
    # ----- levels & z-floors (handoff-11 Slice B) -----
    level_id: Optional[int] = None  # the level this room is a floor of
    z: int = 0                      # signed floor index within the level
    # ----- tile features (handoff-09 §6): id -> {id,x,y,kind,glyph,config} -----
    # Traps/hazards/signs/spawners/kegs attached to tiles. Room.tiles stays
    # geometric; features are an overlay layer the client draws on top.
    features: Dict[int, dict] = field(default_factory=dict)


class WorldState:
    """The authoritative, in-memory game world."""

    def __init__(self):
        self.rooms: Dict[int, RoomNode] = {}
        self.levels: Dict[int, str] = {}            # level_id -> name (handoff-11 B)
        self.player_locations: Dict[int, int] = {}  # online player_id -> room_id
        # Slain hostile mobs awaiting respawn: npc_id -> {room_id, due (monotonic)}.
        self.pending_respawns: Dict[int, dict] = {}
        # Temporarily-open locked doors: (from_room_id, direction) -> expiry
        # (monotonic). While present+future, the exit's key check is bypassed for
        # everyone; on expiry the door re-locks and its key respawns.
        self.door_unlocks: Dict[Tuple[int, str], float] = {}
        # Home tile of each exit key: item_id -> (room_id, x, y). Recorded at load
        # from the key's floor position; used to respawn it after a re-lock.
        self.key_home: Dict[int, Tuple[int, int, int]] = {}
        self.loaded: bool = False

    # ---------- loading ----------
    def load(self) -> None:
        """(Re)load structural world data from the DB. Players start offline."""
        db = SessionLocal()
        try:
            rooms: Dict[int, RoomNode] = {}
            for room in services.RoomService.get_rooms(db, limit=_LOAD_LIMIT):
                node = RoomNode(
                    id=room.id, name=room.name, description=room.description or "",
                    room_type=getattr(room, "room_type", None) or "dungeon",
                    is_safe=bool(getattr(room, "is_safe", False)),
                    level_id=getattr(room, "level_id", None),
                    z=int(getattr(room, "z", 0) or 0),
                )
                self._load_tiles(node, room)
                rooms[room.id] = node
            self.levels = {lvl.id: lvl.name for lvl in db.query(models.Level).all()}
            for feat in db.query(models.RoomFeature).all():
                node = rooms.get(feat.room_id)
                if node is not None:
                    node.features[feat.id] = self._feature_record(feat)
            for npc in services.NpcService.get_npcs(db, limit=_LOAD_LIMIT):
                node = rooms.get(npc.room_id)
                if node is None:
                    continue
                if npc.health <= 0:        # revive anything slain in a prior run
                    npc.health = npc.max_health
                    db.commit()
                node.npc_ids.add(npc.id)
                self._place_npc(node, npc)
            for item in services.ItemService.get_items(db, limit=_LOAD_LIMIT):
                if item.room_id and item.room_id in rooms:
                    self._place_item(rooms[item.room_id], item)
            for ex in db.query(models.RoomExit).all():
                node = rooms.get(ex.from_room_id)
                if node:
                    node.exits[ex.direction] = {
                        "to_room_id": ex.to_room_id,
                        "description": ex.description or "",
                        "is_locked": ex.is_locked,
                        "key_item_id": ex.key_item_id,
                    }
            self.rooms = rooms
            self.player_locations = {}
            self.pending_respawns = {}
            self.door_unlocks = {}            # restarts revert any open door to locked
            self._arm_doors(db)               # record key homes; recover a lost key
            self.loaded = True
        finally:
            db.close()

    def _arm_doors(self, db) -> None:
        """For every locked exit, remember its key's floor home and make sure the
        key actually exists on a floor when the door is locked (recovers a key
        that was mid-'crumble' if the server restarted during an open window)."""
        for node in self.rooms.values():
            for direction, ex in node.exits.items():
                kid = ex.get("key_item_id")
                if not (ex.get("is_locked") and kid):
                    continue
                item = db.query(models.Item).filter_by(id=kid).first()
                if item is None:
                    continue
                if item.room_id and item.tile_x is not None and item.room_id in self.rooms:
                    self.key_home[kid] = (item.room_id, item.tile_x, item.tile_y)
                else:
                    # Not on a floor at load — held by a since-disconnected player
                    # (holding state is stale across restarts) or mid-'crumble'.
                    # Reform it on its home floor so a shared key can't be hoarded
                    # offline; it's always available when no one is carrying it.
                    home = self.key_home.get(kid)
                    if home is None:
                        sx, sy = node.spawn
                        home = (node.id, sx, sy)
                    rid, hx, hy = home
                    item.room_id, item.tile_x, item.tile_y, item.player_id = rid, hx, hy, None
                    item.equipped = False
                    db.commit()
                    self.key_home[kid] = (rid, hx, hy)
                    if rid in self.rooms:
                        self._place_item(self.rooms[rid], item)

    @staticmethod
    def _load_tiles(node: "RoomNode", room) -> None:
        """Populate a node's tile grid from a Room row (or a default box)."""
        layout = (room.tiles or "").strip("\n")
        if layout:
            rows = layout.split("\n")
            node.tiles = rows
            node.height = room.height or len(rows)
            node.width = room.width or max((len(r) for r in rows), default=_DEFAULT_W)
            # Validate glyphs against the registry — unknown glyphs still load
            # (they fail safe as walls) but we warn so an author catches a typo.
            unknown = {g for row in rows for g in row if not tiles.known(g)}
            if unknown:
                print(f"world: room {room.id} '{room.name}' has unknown tile "
                      f"glyphs {sorted(unknown)} — rendering them as walls")
        else:
            node.width = room.width or _DEFAULT_W
            node.height = room.height or _DEFAULT_H
            node.tiles = _default_grid(node.width, node.height)
        sx = room.spawn_x if room.spawn_x is not None else 1
        sy = room.spawn_y if room.spawn_y is not None else 1
        node.spawn = (sx, sy)

    def _place_npc(self, node: "RoomNode", npc) -> None:
        """Cache an NPC's static metadata and resolve its anchor tile."""
        x = npc.home_x
        y = npc.home_y
        if x is None or y is None or not self._is_walkable_grid(node, x, y):
            x, y = self._first_free_tile(node)
        node.npc_pos[npc.id] = (x, y)
        node.npc_meta[npc.id] = {
            "name": npc.name,
            "glyph": npc.glyph or "👤",
            "hostile": bool(npc.is_hostile),
            "aggro_radius": npc.aggro_radius if npc.aggro_radius is not None else 6,
            "combat_enabled": bool(npc.combat_enabled),
            "wanders": bool(getattr(npc, "wanders", False)),
            "home": (x, y),   # anchor tile, used to respawn the mob
        }

    def _place_item(self, node: "RoomNode", item) -> None:
        """Cache a ground item's tile + render metadata. Uses its stored
        tile_x/tile_y if walkable, else the first free floor tile (items don't
        block, so 'free' here just means walkable ground)."""
        x, y = item.tile_x, item.tile_y
        if x is None or y is None or not self._is_walkable_grid(node, x, y):
            x, y = self._first_free_tile(node)
        node.item_ids.add(item.id)
        node.item_pos[item.id] = (x, y)
        node.item_meta[item.id] = {"name": item.name, "glyph": item.glyph or "📦",
                                   "item_type": item.item_type or "generic",
                                   "movable": bool(item.is_movable)}

    @staticmethod
    def _is_walkable_grid(node: "RoomNode", x: int, y: int) -> bool:
        if not (0 <= y < node.height and 0 <= x < len(node.tiles[y])):
            return False
        return tiles.walkable(node.tiles[y][x])   # registry-driven (unknown → wall)

    def _is_spawnable(self, node: "RoomNode", x: int, y: int) -> bool:
        """Open, unoccupied ground a player/mob may be placed on — explicitly
        NOT a transition tile (a door/stairs), so nobody spawns in a doorway and
        blocks it (or auto-transitions)."""
        return (self._is_walkable_grid(node, x, y)
                and node.tiles[y][x] not in TRANSITION_TILES
                and self._occupant(node, x, y) is None)

    def _first_free_tile(self, node: "RoomNode") -> Tuple[int, int]:
        """Spawn tile if free, else the first free non-transition floor tile."""
        if self._is_spawnable(node, *node.spawn):
            return node.spawn
        for y in range(node.height):
            for x in range(len(node.tiles[y])):
                if self._is_spawnable(node, x, y):
                    return (x, y)
        return node.spawn

    def _free_tile_near(self, node: "RoomNode", near: Tuple[int, int],
                        radius: int) -> Optional[Tuple[int, int]]:
        """Nearest spawnable tile within ``radius`` of ``near`` (spiral out), or
        None if the area is full — used by spawners (handoff-09 §3)."""
        cx, cy = near
        for r in range(0, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:    # only this ring
                        continue
                    x, y = cx + dx, cy + dy
                    if self._is_spawnable(node, x, y):
                        return (x, y)
        return None

    def spawn_npc_from_template(self, room_id: int, template: dict,
                                near: Tuple[int, int], radius: int) -> Optional[Dict[str, Any]]:
        """Create a fresh NPC row from a spawner template and register it live.
        Marks the mob ``spawned`` so it won't auto-respawn (the spawner manages
        population). Returns ``{id, entity}`` for an ``entity_spawned`` broadcast,
        or None if there's no free tile."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        tile = self._free_tile_near(node, near, radius)
        if tile is None:
            return None
        hp = int(template.get("max_health", template.get("health", 8)))
        db = SessionLocal()
        try:
            npc = models.Npc(
                name=template.get("name", "Creature"),
                description=template.get("description", ""),
                npc_type=template.get("npc_type", "combat_mob"), room_id=room_id,
                combat_enabled=bool(template.get("combat_enabled", True)),
                is_hostile=bool(template.get("is_hostile", True)),
                aggro_radius=int(template.get("aggro_radius", 6)),
                wanders=bool(template.get("wanders", False)),
                glyph=template.get("glyph", "👾"),
                home_x=tile[0], home_y=tile[1], health=hp, max_health=hp,
                str=int(template.get("str", 10)), dex=int(template.get("dex", 10)),
                con=int(template.get("con", 10)), intel=int(template.get("intel", 10)),
                wis=int(template.get("wis", 10)), cha=int(template.get("cha", 10)),
            )
            db.add(npc); db.commit()
            nid, name, glyph = npc.id, npc.name, npc.glyph
            hostile, aggro, combat_on = npc.is_hostile, npc.aggro_radius, npc.combat_enabled
            wanders = npc.wanders
        finally:
            db.close()
        node.npc_ids.add(nid)
        node.npc_pos[nid] = tile
        node.npc_meta[nid] = {
            "name": name, "glyph": glyph or "👾", "hostile": bool(hostile),
            "aggro_radius": aggro, "combat_enabled": bool(combat_on),
            "wanders": bool(wanders), "home": tile, "spawned": True,
        }
        return {"id": nid, "entity": {
            "id": nid, "kind": "npc", "name": name, "glyph": glyph or "👾",
            "x": tile[0], "y": tile[1], "hostile": bool(hostile),
            "hp": hp, "max_hp": hp, "vendor": False, "effects": [],
            "portrait_url": None, "token_url": None}}

    def delete_npc(self, npc_id: int) -> None:
        """Permanently remove a (dead, spawner-managed) NPC's DB row."""
        db = SessionLocal()
        try:
            row = db.get(models.Npc, npc_id)
            if row is not None:
                db.delete(row); db.commit()
        finally:
            db.close()

    # ---------- tile helpers ----------
    def is_walkable(self, room_id: int, x: int, y: int) -> bool:
        """In-bounds and not a wall (doors and floor are walkable)."""
        node = self.rooms.get(room_id)
        return node is not None and self._is_walkable_grid(node, x, y)

    @staticmethod
    def _occupant(node: "RoomNode", x: int, y: int) -> Optional[Tuple[str, int]]:
        for pid, pos in node.player_pos.items():
            if pos == (x, y):
                return ("player", pid)
        for nid, pos in node.npc_pos.items():
            if pos == (x, y):
                return ("npc", nid)
        return None

    def occupant_at(self, room_id: int, x: int, y: int) -> Optional[Tuple[str, int]]:
        """(kind, id) of the entity on a tile, or None."""
        node = self.rooms.get(room_id)
        return self._occupant(node, x, y) if node else None

    # ---------- ground items (Phase 3) ----------
    def ground_items(self, room_id: int) -> List[Dict[str, Any]]:
        """Serializable ground items in a room: [{id,name,glyph,token_url,x,y}]."""
        node = self.rooms.get(room_id)
        if node is None:
            return []
        ids = list(node.item_pos.keys())
        tokens: Dict[int, Any] = {}
        if ids:   # fetch token urls fresh (set lazily after generation)
            db = SessionLocal()
            try:
                for iid, turl in db.query(models.Item.id, models.Item.token_url).filter(
                        models.Item.id.in_(ids)):
                    tokens[iid] = turl
            finally:
                db.close()
        out = []
        for iid, (x, y) in node.item_pos.items():
            meta = node.item_meta.get(iid, {})
            out.append({"id": iid, "name": meta.get("name", "item"),
                        "glyph": meta.get("glyph", "📦"), "token_url": tokens.get(iid),
                        "item_type": meta.get("item_type", "generic"), "x": x, "y": y})
        return out

    def item_at(self, room_id: int, x: int, y: int) -> Optional[int]:
        """The (topmost) ground item id on a tile, or None."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        for iid, pos in node.item_pos.items():
            if pos == (x, y):
                return iid
        return None

    def add_ground_item(self, room_id: int, item_id: int, x: int, y: int,
                        name: str, glyph: str, item_type: str = "generic") -> None:
        """Place an item onto a tile in the live world (a drop)."""
        node = self.rooms.get(room_id)
        if node is None:
            return
        node.item_ids.add(item_id)
        node.item_pos[item_id] = (x, y)
        node.item_meta[item_id] = {"name": name, "glyph": glyph or "📦",
                                   "item_type": item_type or "generic", "movable": True}

    def grabbable_at(self, room_id: int, x: int, y: int) -> Optional[int]:
        """A MOVABLE ground item id on a tile — skips immovable objects (a chest,
        furniture) so an item resting on/under one stays retrievable."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        for iid, pos in node.item_pos.items():
            if pos == (x, y) and node.item_meta.get(iid, {}).get("movable", True):
                return iid
        return None

    def chest_near(self, room_id: int, x: int, y: int) -> Optional[int]:
        """Id of a 'chest' ground item on or adjacent to (x, y), or None."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        for iid, (ix, iy) in node.item_pos.items():
            if max(abs(ix - x), abs(iy - y)) <= 1 \
                    and node.item_meta.get(iid, {}).get("item_type") == "chest":
                return iid
        return None

    def remove_ground_item(self, item_id: int) -> None:
        """Drop an item from whatever room's ground holds it (a pickup)."""
        for node in self.rooms.values():
            node.item_ids.discard(item_id)
            node.item_pos.pop(item_id, None)
            node.item_meta.pop(item_id, None)

    # ---------- tile features (handoff-09 §6) ----------
    @staticmethod
    def _feature_record(feat) -> dict:
        """Parse a RoomFeature row into the live dict held in RoomNode.features."""
        import json
        try:
            cfg = json.loads(feat.config or "{}")
        except (ValueError, TypeError):
            cfg = {}
        return {"id": feat.id, "x": feat.x, "y": feat.y, "kind": feat.kind,
                "glyph": feat.glyph or "", "config": cfg}

    def feature_at(self, room_id: int, x: int, y: int, kind: str = None) -> Optional[dict]:
        """The feature on tile (x, y) (optionally filtered by kind), or None."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        for f in node.features.values():
            if f["x"] == x and f["y"] == y and (kind is None or f["kind"] == kind):
                return f
        return None

    def feature_near(self, room_id: int, x: int, y: int, kind: str = None) -> Optional[dict]:
        """A feature on or adjacent to (x, y) (Chebyshev ≤ 1), or None — the
        interaction reach for signs/kegs (mirrors ``chest_near``)."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        for f in node.features.values():
            if max(abs(f["x"] - x), abs(f["y"] - y)) <= 1 \
                    and (kind is None or f["kind"] == kind):
                return f
        return None

    def add_feature(self, room_id: int, feat) -> Optional[dict]:
        """Register a freshly-created RoomFeature row into the live world."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        rec = self._feature_record(feat)
        node.features[feat.id] = rec
        return rec

    def remove_feature(self, room_id: int, feature_id: int) -> None:
        """Drop a feature from the live world (e.g. a consumed powder keg)."""
        node = self.rooms.get(room_id)
        if node is not None:
            node.features.pop(feature_id, None)

    def features_payload(self, room_id: int) -> List[Dict[str, Any]]:
        """Serializable features for the client overlay: signs hide their text
        (read on demand); everything else exposes glyph + harmless config hints."""
        node = self.rooms.get(room_id)
        if node is None:
            return []
        out = []
        for f in node.features.values():
            out.append({"id": f["id"], "x": f["x"], "y": f["y"],
                        "kind": f["kind"], "glyph": f["glyph"]})
        return out

    def position_of(self, kind: str, room_id: int, entity_id: int) -> Optional[Tuple[int, int]]:
        node = self.rooms.get(room_id)
        if node is None:
            return None
        return (node.player_pos if kind == "player" else node.npc_pos).get(entity_id)

    def place_player(self, player_id: int, room_id: int,
                     at: Optional[Tuple[int, int]] = None) -> Optional[Tuple[int, int]]:
        """Set a player onto a tile: `at` if given and free (zone-transition
        arrival), otherwise the zone's spawn/nearest-free tile (fresh connect).

        Complements ``enter_world`` (room membership + DB); this is the tile
        layer. Live (x,y) is not persisted — re-placed on connect/transition."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        # A player occupies exactly one zone's tile grid — clear any prior tile
        # position (e.g. the doorway in the zone they just left) so stale ghosts
        # can't be targeted by the old zone's mobs after a transition.
        for n in self.rooms.values():
            n.player_pos.pop(player_id, None)
        if at is not None and self._is_walkable_grid(node, *at) and self._occupant(node, *at) is None:
            pos = at
        else:
            pos = self._first_free_tile(node)
        node.player_pos[player_id] = pos
        return pos

    def remove_player_pos(self, player_id: int) -> None:
        """Drop a player's tile position from whatever room holds it."""
        for node in self.rooms.values():
            node.player_pos.pop(player_id, None)

    def try_step(self, kind: str, entity_id: int, room_id: int, dx: int, dy: int) -> StepResult:
        """Attempt one tile step. The single resolver for players and mobs:

        - off-grid / wall            -> BLOCKED
        - tile holds a valid target  -> ATTACK (bump-to-attack)
        - tile holds a non-target    -> BLOCKED
        - free walkable tile         -> MOVED (position updated)
        """
        node = self.rooms.get(room_id)
        if node is None:
            return StepResult("BLOCKED")
        store = node.player_pos if kind == "player" else node.npc_pos
        pos = store.get(entity_id)
        if pos is None:
            return StepResult("BLOCKED")
        nx, ny = pos[0] + dx, pos[1] + dy
        if not self._is_walkable_grid(node, nx, ny):
            return StepResult("BLOCKED")
        occ = self._occupant(node, nx, ny)
        if occ is not None:
            occ_kind, occ_id = occ
            if kind == "player" and occ_kind == "npc":
                # Bump a combatant -> attack; can't walk through anyone.
                if node.npc_meta.get(occ_id, {}).get("combat_enabled"):
                    return StepResult("ATTACK", target_kind="npc", target_id=occ_id)
                return StepResult("BLOCKED")
            if kind == "npc" and occ_kind == "player":
                return StepResult("ATTACK", target_kind="player", target_id=occ_id)
            # PvP is intentional only: bumping a player does NOT attack (you just
            # can't walk through them). Use the strike action / `attack` command.
            return StepResult("BLOCKED")  # player↔player, npc↔npc
        store[entity_id] = (nx, ny)
        return StepResult("MOVED", x=nx, y=ny)

    def step_candidates(self, frm: Tuple[int, int], to: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Ordered orthogonal step deltas that head from `frm` toward `to`
        (greedy: longer axis first). The caller applies each via ``try_step``
        until one MOVES or ATTACKS. No new dependency — rooms are tiny."""
        fx, fy = frm
        tx, ty = to
        sdx = (tx > fx) - (tx < fx)
        sdy = (ty > fy) - (ty < fy)
        cands: List[Tuple[int, int]] = []
        if abs(tx - fx) >= abs(ty - fy):
            if sdx:
                cands.append((sdx, 0))
            if sdy:
                cands.append((0, sdy))
        else:
            if sdy:
                cands.append((0, sdy))
            if sdx:
                cands.append((sdx, 0))
        return cands

    @staticmethod
    def chebyshev(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    def wander_candidates(self, room_id: int, npc_id: int, leash: int) -> List[Tuple[int, int]]:
        """Step deltas to an adjacent walkable, unoccupied, non-transition tile
        within ``leash`` of the mob's home — for idle wandering (handoff-09 §4).
        Empty if boxed in. The caller picks one (randomly) and applies try_step."""
        node = self.rooms.get(room_id)
        if node is None:
            return []
        pos = node.npc_pos.get(npc_id)
        if pos is None:
            return []
        home = node.npc_meta.get(npc_id, {}).get("home", pos)
        out: List[Tuple[int, int]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = pos[0] + dx, pos[1] + dy
                if not self._is_walkable_grid(node, nx, ny):
                    continue
                if node.tiles[ny][nx] in TRANSITION_TILES:   # don't wander through doors
                    continue
                if self._occupant(node, nx, ny) is not None:
                    continue
                if max(abs(nx - home[0]), abs(ny - home[1])) > leash:
                    continue
                out.append((dx, dy))
        return out

    # ---------- line of sight & area (Phase 4) ----------
    def _is_transparent(self, node: "RoomNode", x: int, y: int) -> bool:
        """A tile sight can pass *through* (in-bounds, not a wall/pillar)."""
        if not (0 <= y < node.height and 0 <= x < len(node.tiles[y])):
            return False
        return tiles.transparent(node.tiles[y][x])   # registry-driven (unknown → opaque)

    def line_of_sight(self, room_id: int, a: Tuple[int, int], b: Tuple[int, int]) -> bool:
        """True if nothing sight-blocking lies strictly between tiles a and b
        (Bresenham). Endpoints themselves are not tested — you can target a
        creature standing in a doorway or against a wall."""
        node = self.rooms.get(room_id)
        if node is None:
            return False
        x0, y0 = a
        x1, y1 = b
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        cx, cy = x0, y0
        while (cx, cy) != (x1, y1):
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                cx += sx
            if e2 < dx:
                err += dx
                cy += sy
            if (cx, cy) == (x1, y1):
                break
            if not self._is_transparent(node, cx, cy):
                return False
        return True

    def tiles_in_radius(self, room_id: int, center: Tuple[int, int], radius: int
                        ) -> List[Tuple[int, int]]:
        """In-bounds, non-wall tiles within Chebyshev `radius` of center (the
        center included). Used to gather AoE targets for blast spells."""
        node = self.rooms.get(room_id)
        if node is None:
            return []
        cx, cy = center
        out = []
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if self._is_walkable_grid(node, x, y):
                    out.append((x, y))
        return out

    def nearest_player_within(self, room_id: int, frm: Tuple[int, int], radius: int
                              ) -> Optional[Tuple[int, Tuple[int, int]]]:
        """The closest online player (id, pos) within `radius` (Chebyshev), or None."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        best = None
        best_d = radius + 1
        for pid, pos in node.player_pos.items():
            d = self.chebyshev(frm, pos)
            if d <= radius and d < best_d:
                best, best_d = (pid, pos), d
        return best

    def hostile_mobs(self, room_id: int) -> List[int]:
        """Living hostile NPC ids present in a room (positions tracked)."""
        node = self.rooms.get(room_id)
        if node is None:
            return []
        return [nid for nid in node.npc_pos
                if node.npc_meta.get(nid, {}).get("hostile")]

    def kill_npc(self, room_id: int, npc_id: int) -> None:
        """Remove a defeated NPC from the room's tile + membership state. If it
        was a hostile mob, schedule it to respawn (see ``due_respawns``)."""
        node = self.rooms.get(room_id)
        if node is None:
            return
        meta = node.npc_meta.get(npc_id, {})
        node.npc_ids.discard(npc_id)
        node.npc_pos.pop(npc_id, None)
        # Spawner-managed mobs don't auto-respawn — their spawner repopulates
        # (and reaps the dead row); only hand-placed hostiles respawn at home.
        if meta.get("hostile") and not meta.get("spawned"):
            self.pending_respawns[npc_id] = {
                "room_id": room_id, "due": time.monotonic() + MOB_RESPAWN_SECONDS}

    def due_respawns(self) -> List[int]:
        """Mob ids whose respawn timer has elapsed (call ``respawn_npc`` on each)."""
        now = time.monotonic()
        return [nid for nid, info in self.pending_respawns.items() if now >= info["due"]]

    def respawn_npc(self, npc_id: int) -> Optional[Dict[str, Any]]:
        """Bring a slain mob back at its home tile with full health. Returns
        ``{room_id, entity}`` for an ``entity_spawned`` broadcast, or None."""
        info = self.pending_respawns.pop(npc_id, None)
        if info is None:
            return None
        room_id = info["room_id"]
        node = self.rooms.get(room_id)
        if node is None:
            return None
        db = SessionLocal()
        try:
            npc = services.NpcService.get_npc(db, npc_id)
            if npc is None:
                return None
            npc.health = npc.max_health
            db.commit()
            name, glyph, hp = npc.name, npc.glyph or "👤", npc.max_health
            portrait_url = npc.portrait_url
            token_url = npc.token_url
            vendor = shops.is_vendor(npc.npc_type)
        finally:
            db.close()
        meta = node.npc_meta.get(npc_id, {})
        home = meta.get("home")
        if home and self._is_walkable_grid(node, *home) and self._occupant(node, *home) is None:
            x, y = home
        else:
            x, y = self._first_free_tile(node)
        node.npc_ids.add(npc_id)
        node.npc_pos[npc_id] = (x, y)
        return {"room_id": room_id, "entity": {
            "id": npc_id, "kind": "npc", "name": name, "glyph": glyph,
            "x": x, "y": y, "hostile": meta.get("hostile", False),
            "hp": hp, "max_hp": hp, "vendor": vendor,
            "portrait_url": portrait_url, "token_url": token_url}}

    # ---------- zone transitions (Phase 2) ----------
    def transition_for_tile(self, room_id: int, x: int, y: int) -> Optional[Dict[str, Any]]:
        """If (x, y) is a transition tile with a matching exit, return that exit
        dict augmented with its 'direction'; else None. A border door maps to its
        wall's cardinal; stairs map to up/down. Exits come from the room-graph."""
        node = self.rooms.get(room_id)
        if node is None or not self._is_walkable_grid(node, x, y):
            return None
        kind = tiles.transition(node.tiles[y][x])   # None | "door" | "up" | "down"
        direction = None
        if kind in ("up", "down"):
            direction = kind
        elif kind == "door":
            if y == 0:
                direction = "north"
            elif y == node.height - 1:
                direction = "south"
            elif x == 0:
                direction = "west"
            elif x == node.width - 1:
                direction = "east"
        if direction is None:
            return None
        ex = node.exits.get(direction)
        return {"direction": direction, **ex} if ex else None

    def exit_key_ids(self) -> Set[int]:
        """All item ids that are keys for some locked exit (shared door keys)."""
        return {ex["key_item_id"] for node in self.rooms.values()
                for ex in node.exits.values() if ex.get("key_item_id")}

    # ---------- temporary door unlocks (shared, timed) ----------
    def door_is_open(self, from_room: int, direction: str) -> bool:
        """True while a locked door is in its shared open window."""
        exp = self.door_unlocks.get((from_room, direction))
        return exp is not None and time.monotonic() < exp

    def open_door(self, from_room: int, direction: str, seconds: float) -> None:
        """Open a locked door for everyone for `seconds` (resets the window)."""
        self.door_unlocks[(from_room, direction)] = time.monotonic() + seconds

    def relock_door(self, from_room: int, direction: str) -> None:
        self.door_unlocks.pop((from_room, direction), None)

    def due_door_relocks(self) -> List[Tuple[int, str]]:
        """Open windows that have expired (ready to re-lock + respawn the key)."""
        now = time.monotonic()
        return [k for k, exp in self.door_unlocks.items() if now >= exp]

    def _find_transition_tile(self, node: "RoomNode", direction: str) -> Optional[Tuple[int, int]]:
        """Locate the tile in a room that triggers `direction` (a stair glyph, or
        a door on the matching border)."""
        if direction == "up":
            glyph = STAIRS_UP
        elif direction == "down":
            glyph = STAIRS_DOWN
        elif direction in ("north", "south", "east", "west"):
            glyph = DOOR
        else:
            return None
        for y in range(node.height):
            row = node.tiles[y]
            for x in range(len(row)):
                if row[x] != glyph:
                    continue
                if glyph == DOOR:
                    on_border = ((direction == "north" and y == 0) or
                                 (direction == "south" and y == node.height - 1) or
                                 (direction == "west" and x == 0) or
                                 (direction == "east" and x == len(row) - 1))
                    if not on_border:
                        continue
                return (x, y)
        return None

    def arrival_tile(self, room_id: int, from_direction: str) -> Tuple[int, int]:
        """Where a player lands after entering `room_id` by travelling
        `from_direction`: one tile inward from the destination's return exit (so
        they don't immediately re-trigger it), else that tile, else the spawn."""
        node = self.rooms.get(room_id)
        if node is None:
            return (0, 0)
        rev = directions.reverse(from_direction)  # e.g. arrived going 'north' -> return is 'south'
        target = self._find_transition_tile(node, rev)
        if target is None:
            return node.spawn
        tx, ty = target
        # Step one tile clear of the return exit (stairs have no wall side, so
        # just step south off them if possible).
        inward = {"north": (0, 1), "south": (0, -1), "west": (1, 0), "east": (-1, 0),
                  "up": (0, 1), "down": (0, 1)}.get(rev, (0, 0))
        ix, iy = tx + inward[0], ty + inward[1]
        if self._is_walkable_grid(node, ix, iy) and self._occupant(node, ix, iy) is None:
            return (ix, iy)
        if self._occupant(node, tx, ty) is None:
            return (tx, ty)
        return self._first_free_tile(node)

    def world_map(self) -> Dict[str, Any]:
        """The overview graph: rooms (with their level + z), levels, and exits.
        The client builds two tiers — a level graph (entrances = cross-level
        exits) and, per level, a floor stack by z (handoff-11 Slice B)."""
        rooms = [{"id": n.id, "name": n.name, "level_id": n.level_id,
                  "level_name": self.levels.get(n.level_id), "z": n.z}
                 for n in self.rooms.values()]
        levels = [{"id": lid, "name": name} for lid, name in self.levels.items()]
        exits = []
        for n in self.rooms.values():
            for direction, ex in n.exits.items():
                to_id = ex["to_room_id"]
                to_node = self.rooms.get(to_id)
                # An entrance crosses into another level; a stair stays intra-level.
                entrance = bool(to_node and to_node.level_id != n.level_id)
                exits.append({"from": n.id, "to": to_id, "dir": direction,
                              "locked": bool(ex["is_locked"]), "entrance": entrance})
        return {"rooms": rooms, "levels": levels, "exits": exits}

    def zone_snapshot(self, room_id: int, viewer_id: int) -> Optional[Dict[str, Any]]:
        """Serializable tiled-zone view for a `zone_state` event, from one
        viewer's perspective ('you' = the viewer; 'entities' = everyone else)."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        db = SessionLocal()
        try:
            you = None
            vpos = node.player_pos.get(viewer_id)
            entities: List[dict] = []
            for pid, pos in node.player_pos.items():
                player = services.PlayerService.get_player(db, pid)
                if not player:
                    continue
                rec = {"id": pid, "kind": "player", "name": player.name,
                       "glyph": player.glyph or "🧙", "x": pos[0], "y": pos[1],
                       "hp": player.health, "max_hp": player.max_health,
                       "effects": effects.snapshot(effects.eid("player", pid)),
                       "portrait_url": player.portrait_url, "token_url": player.token_url}
                if pid == viewer_id:
                    rec["mana"] = player.mana
                    rec["max_mana"] = player.max_mana
                    rec["coins"] = player.coins or 0
                    you = rec
                else:
                    entities.append(rec)
            for nid, pos in node.npc_pos.items():
                meta = node.npc_meta.get(nid, {})
                npc = services.NpcService.get_npc(db, nid)
                if not npc:
                    continue
                entities.append({
                    "id": nid, "kind": "npc", "name": npc.name,
                    "glyph": meta.get("glyph", npc.glyph or "👤"),
                    "x": pos[0], "y": pos[1], "hostile": meta.get("hostile", False),
                    "hp": npc.health, "max_hp": npc.max_health,
                    "effects": effects.snapshot(effects.eid("npc", nid)),
                    "vendor": shops.is_vendor(npc.npc_type),
                    "portrait_url": npc.portrait_url, "token_url": npc.token_url,
                })
        finally:
            db.close()
        if you is None:
            sx, sy = node.spawn
            you = {"id": viewer_id, "x": sx, "y": sy, "glyph": "🧙"}
        return {
            "room": {"id": node.id, "name": node.name, "description": node.description,
                     "room_type": node.room_type, "is_safe": node.is_safe,
                     "level_id": node.level_id, "level_name": self.levels.get(node.level_id),
                     "z": node.z},
            "tiles": {"w": node.width, "h": node.height, "grid": node.tiles,
                      # Registry defs for the glyphs present, so the client derives
                      # its render/sight rules from data (handoff-11 Slice A).
                      "tiledefs": tiles.tiledefs_for("".join(node.tiles))},
            "you": you,
            "entities": entities,
            "items": self.ground_items(room_id),
            "features": self.features_payload(room_id),
        }

    def reload(self) -> None:
        """Resync structural data from the DB while preserving online presence.

        Use after admin/REST edits to rooms/NPCs/items.
        """
        online = dict(self.player_locations)
        self.load()
        for player_id, room_id in online.items():
            if room_id in self.rooms:
                self.rooms[room_id].players.add(player_id)
                self.player_locations[player_id] = room_id

    # ---------- presence ----------
    def enter_world(self, player_id: int) -> Optional[int]:
        """Bring an online player into their persisted room. Returns the room id."""
        db = SessionLocal()
        try:
            player = services.PlayerService.get_player(db, player_id)
            room_id = player.room_id if player else None
        finally:
            db.close()
        if room_id is None or room_id not in self.rooms:
            return None
        self.rooms[room_id].players.add(player_id)
        self.player_locations[player_id] = room_id
        return room_id

    def leave_world(self, player_id: int) -> Optional[int]:
        """Mark a player offline. Returns the room they left, if any."""
        room_id = self.player_locations.pop(player_id, None)
        if room_id is not None and room_id in self.rooms:
            self.rooms[room_id].players.discard(player_id)
            self.rooms[room_id].player_pos.pop(player_id, None)
        return room_id

    def room_of(self, player_id: int) -> Optional[int]:
        """Current room of an online player, or None if offline."""
        return self.player_locations.get(player_id)

    def is_sanctuary(self, room_id: int) -> bool:
        """True if the room is a sanctuary (PvP refused + mob aggro suppressed)."""
        node = self.rooms.get(room_id)
        return bool(node and node.is_safe)

    def room_type(self, room_id: int) -> str:
        node = self.rooms.get(room_id)
        return node.room_type if node else "dungeon"

    def living_hostiles(self, room_id: int) -> int:
        """Count of hostile mobs currently present (for the tavern `rest` gate)."""
        node = self.rooms.get(room_id)
        if node is None:
            return 0
        return sum(1 for nid in node.npc_ids
                   if node.npc_meta.get(nid, {}).get("hostile"))

    def room_of_npc(self, npc_id: int) -> Optional[int]:
        """Room currently holding an NPC, or None — mirrors ``room_of`` for mobs.
        Used to route DoT damage and effect broadcasts to the right zone."""
        for rid, node in self.rooms.items():
            if npc_id in node.npc_ids:
                return rid
        return None

    def move_player(self, player_id: int, to_room_id: int) -> bool:
        """Move an online player to another room, writing the change through to
        the DB. Returns False if the target room doesn't exist."""
        if to_room_id not in self.rooms:
            return False
        from_room = self.player_locations.get(player_id)
        if from_room == to_room_id:
            return True
        if from_room is not None and from_room in self.rooms:
            self.rooms[from_room].players.discard(player_id)
        self.rooms[to_room_id].players.add(player_id)
        self.player_locations[player_id] = to_room_id

        db = SessionLocal()
        try:
            player = services.PlayerService.get_player(db, player_id)
            if player:
                player.room_id = to_room_id
                db.commit()
        finally:
            db.close()
        return True

    # ---------- queries ----------
    def room_snapshot(self, room_id: int) -> Optional[Dict[str, Any]]:
        """A serializable view of a room: metadata + present players, NPCs, items.

        Suitable as the payload for a ``room_state`` event.
        """
        node = self.rooms.get(room_id)
        if node is None:
            return None
        db = SessionLocal()
        try:
            npcs = []
            for npc_id in node.npc_ids:
                npc = services.NpcService.get_npc(db, npc_id)
                if npc:
                    npcs.append({"id": npc.id, "name": npc.name, "npc_type": npc.npc_type})
            items = []
            for item_id in node.item_ids:
                item = services.ItemService.get_item(db, item_id)
                if item:
                    items.append({"id": item.id, "name": item.name})
            players = []
            for player_id in node.players:
                player = services.PlayerService.get_player(db, player_id)
                if player:
                    players.append({"id": player.id, "name": player.name})
        finally:
            db.close()
        exits = [
            {
                "direction": direction,
                "to_room_id": ex["to_room_id"],
                "to_room": self.rooms[ex["to_room_id"]].name if ex["to_room_id"] in self.rooms else None,
                "description": ex["description"],
                "is_locked": ex["is_locked"],
            }
            for direction, ex in sorted(node.exits.items())
        ]
        return {
            "room": {"id": node.id, "name": node.name, "description": node.description},
            "players": players,
            "npcs": npcs,
            "items": items,
            "exits": exits,
        }

    def exit_in_direction(self, room_id: int, direction: str) -> Optional[dict]:
        """Return the exit dict for a direction from a room, or None.

        Accepts shorthands ('n' -> 'north')."""
        node = self.rooms.get(room_id)
        if node is None:
            return None
        return node.exits.get(directions.normalize(direction))

    def occupants(self, room_id: int) -> List[int]:
        """Online player ids currently in a room."""
        node = self.rooms.get(room_id)
        return list(node.players) if node else []

    def online_players(self) -> List[int]:
        """All online player ids."""
        return list(self.player_locations.keys())


# Global instance
world = WorldState()
