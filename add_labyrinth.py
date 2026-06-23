#!/usr/bin/env python3
"""
One-off content build: a 49-room procedurally-generated LABYRINTH (handoff-11
maps model), entered from the Great Hall.

- A new level "The Labyrinth" (all rooms z=0).
- 49 rooms (uniform 11x9) with mapgen interiors (a cave/rooms mix) + a carved
  center hub so every door connects to the spawn and to every other door.
- Labyrinthine topology: a randomized spanning tree over a 7x7 lattice (so every
  room is reachable) + a few extra "braid" links for loops. Adjacent lattice
  cells are linked by matching N/S/E/W door exits (discrete rooms, not one
  contiguous map).
- Entrance: the Great Hall's EAST wall (its south already leads to the Foyer) ↔
  labyrinth start room, both ways.

Idempotent: if a level named "The Labyrinth" already exists, it does nothing.
Deterministic (fixed seed). Run as the DB owner, then restart the service:

    python add_labyrinth.py
"""
import random

import database
import models
import mapgen

LEVEL_NAME = "The Labyrinth"
GRID = 7                      # 7x7 = 49 cells
RW, RH = 11, 9               # uniform room size
SEED = 20260623
BRAID_EXTRA = 14            # extra loop links beyond the spanning tree
ENTRANCE_PREF = ["east", "west", "north", "south"]   # Great Hall wall to use

_REV = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _carve(grid, side):
    """Punch a border door on `side` + a straight corridor to the room center
    (guaranteeing the door connects to the spawn hub). `grid` is list[list[str]]."""
    h, w = len(grid), len(grid[0])
    cx, cy = w // 2, h // 2
    if side in ("north", "south"):
        y = 0 if side == "north" else h - 1
        grid[y][cx] = "+"
        step = 1 if side == "north" else -1
        yy = y + step
        while yy != cy:
            grid[yy][cx] = "."
            yy += step
    else:
        x = w - 1 if side == "east" else 0
        grid[cy][x] = "+"
        step = -1 if side == "east" else 1
        xx = x + step
        while xx != cx:
            grid[cy][xx] = "."
            xx += step


def _gen_room(idx):
    """A mapgen interior with a guaranteed floor center (the hub/spawn)."""
    kind = "cave" if idx % 2 == 0 else "rooms"
    rows = mapgen.generate(kind, RW, RH, seed=SEED + idx)
    grid = [list(r) for r in rows]
    grid[RH // 2][RW // 2] = "."        # spawn hub
    return grid


def _maze_edges(rng):
    """Randomized-DFS spanning tree over the GRIDxGRID lattice + braid loops.
    Returns a set of frozenset({cellA, cellB}) edges (cell = (r, c))."""
    cells = [(r, c) for r in range(GRID) for c in range(GRID)]
    seen = {cells[0]}
    stack = [cells[0]]
    edges = set()
    while stack:
        r, c = stack[-1]
        nbrs = [(r + dr, c + dc) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= r + dr < GRID and 0 <= c + dc < GRID and (r + dr, c + dc) not in seen]
        if not nbrs:
            stack.pop()
            continue
        nxt = rng.choice(nbrs)
        edges.add(frozenset(((r, c), nxt)))
        seen.add(nxt)
        stack.append(nxt)
    # Braid: add extra adjacent links for labyrinthine loops.
    all_adj = [frozenset(((r, c), (r + dr, c + dc)))
               for r in range(GRID) for c in range(GRID)
               for dr, dc in ((1, 0), (0, 1))
               if 0 <= r + dr < GRID and 0 <= c + dc < GRID]
    rng.shuffle(all_adj)
    extra = BRAID_EXTRA
    for e in all_adj:
        if extra <= 0:
            break
        if e not in edges:
            edges.add(e)
            extra -= 1
    return edges


def _dir_between(a, b):
    """Cardinal from cell a to adjacent cell b (rows增 = south, cols增 = east)."""
    (ra, ca), (rb, cb) = a, b
    if rb == ra + 1:
        return "south"
    if rb == ra - 1:
        return "north"
    if cb == ca + 1:
        return "east"
    return "west"


def build():
    db = database.SessionLocal()
    try:
        if db.query(models.Level).filter_by(name=LEVEL_NAME).first():
            print(f"'{LEVEL_NAME}' already exists — nothing to do.")
            return
        hall = db.query(models.Room).filter_by(name="Great Hall").first()
        if hall is None:
            print("Great Hall not found — aborting.")
            return

        rng = random.Random(SEED)
        level = models.Level(name=LEVEL_NAME, description="A sprawling procedural maze.")
        db.add(level); db.commit()

        # 1) create the 49 rooms with generated interiors (tiles patched later for doors)
        cells = [(r, c) for r in range(GRID) for c in range(GRID)]
        grids = {cell: _gen_room(i) for i, cell in enumerate(cells)}
        rooms = {}
        for i, cell in enumerate(cells):
            room = models.Room(name=f"Labyrinth {i + 1}", description="Twisting stone passages.",
                               width=RW, height=RH, spawn_x=RW // 2, spawn_y=RH // 2,
                               room_type="dungeon", is_safe=False, level_id=level.id, z=0,
                               tiles="")     # tiles set after doors are carved
            db.add(room); rooms[cell] = room
        db.commit()

        # 2) topology → carve doors + create bidirectional exits
        edges = _maze_edges(rng)
        exits = []
        for e in edges:
            a, b = tuple(e)
            da = _dir_between(a, b)
            db_ = _REV[da]
            _carve(grids[a], da)
            _carve(grids[b], db_)
            exits.append((rooms[a].id, rooms[b].id, da))
            exits.append((rooms[b].id, rooms[a].id, db_))

        # 3) entrance from the Great Hall (first free wall; south is the Foyer)
        used = {x.direction for x in db.query(models.RoomExit).filter_by(from_room_id=hall.id)}
        wall = next(d for d in ENTRANCE_PREF if d not in used)
        start = (0, 0)
        hgrid = [list(r) for r in (hall.tiles or "").split("\n")]
        _carve(hgrid, wall)
        hall.tiles = "\n".join("".join(r) for r in hgrid)
        _carve(grids[start], _REV[wall])
        exits.append((hall.id, rooms[start].id, wall))
        exits.append((rooms[start].id, hall.id, _REV[wall]))

        # 4) persist tiles + exits
        for cell, room in rooms.items():
            room.tiles = "\n".join("".join(r) for r in grids[cell])
        for frm, to, direction in exits:
            db.add(models.RoomExit(from_room_id=frm, to_room_id=to, direction=direction))
        db.commit()

        # 5) reachability self-check (BFS over exits from the Great Hall)
        adj = {}
        for x in db.query(models.RoomExit).all():
            adj.setdefault(x.from_room_id, []).append(x.to_room_id)
        seen, stack = set(), [hall.id]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack += adj.get(n, [])
        lab_ids = {r.id for r in rooms.values()}
        unreached = lab_ids - seen
        print(f"Built {len(rooms)} labyrinth rooms via the Great Hall's {wall} wall; "
              f"{len(exits)} exit rows. Reachable from Great Hall: "
              f"{len(lab_ids & seen)}/{len(lab_ids)}.")
        if unreached:
            raise SystemExit(f"REACHABILITY FAILURE: {len(unreached)} rooms unreachable: {sorted(unreached)[:10]}")
        print("All labyrinth rooms reachable. ✅")
    finally:
        db.close()


if __name__ == "__main__":
    build()
