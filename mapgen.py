#!/usr/bin/env python3
"""
Author-time map generator (handoff-11 Slice D).

**Author-time only** — imported by the designer / a CLI, NEVER by the live sim:
the persistent shared world is hand-authored, so generation is a one-way bake to
static `tiles.py` glyphs. `generate(kind, w, h, params, seed)` returns a list of
glyph rows (geometry only — `#` wall / `.` floor); spawn, stairs, entrances,
items, and NPCs are placed by hand afterward. Output is **deterministic** for a
fixed seed and passes the same `validate()` a hand-painted layout would.

Modes (all off one pipeline): hand-paint = skip generate; fully procedural =
generate→save; generate-then-edit = generate then hand-edit the glyphs.
"""
import random
from typing import List, Optional, Set, Tuple

import tiles

WALL, FLOOR = "#", "."


def generate(kind: str, w: int, h: int,
             params: Optional[dict] = None, seed: Optional[int] = None) -> List[str]:
    """Generate a whole floor of the given kind. Returns glyph rows.

    kinds: ``"cave"`` (cellular automata) · ``"rooms"`` (BSP rooms + corridors).
    Deterministic given ``seed``. Always border-walled and fully connected."""
    params = params or {}
    rng = random.Random(seed)
    if kind == "cave":
        grid = _cave(w, h, params, rng)
    elif kind == "rooms":
        grid = _rooms(w, h, params, rng)
    else:
        raise ValueError(f"unknown mapgen kind: {kind!r}")
    return _ensure_floor(_keep_largest(grid))


# ---------- cave: cellular automata ----------
def _cave(w: int, h: int, params: dict, rng: random.Random) -> List[str]:
    w, h = max(5, w), max(5, h)
    fill = params.get("fill", 0.45)
    steps = params.get("steps", 4)
    g = [[WALL] * w for _ in range(h)]
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            g[y][x] = WALL if rng.random() < fill else FLOOR
    for _ in range(steps):
        ng = [row[:] for row in g]
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                walls = sum(1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                            if (dx or dy) and g[y + dy][x + dx] == WALL)
                ng[y][x] = WALL if walls >= 5 else FLOOR   # classic 4-5 rule
        g = ng
    return ["".join(r) for r in g]


# ---------- rooms: BSP partitions + L-corridors ----------
def _bsp_leaves(x: int, y: int, w: int, h: int, min_leaf: int,
                rng: random.Random, depth: int = 0) -> List[Tuple[int, int, int, int]]:
    can_h = h >= min_leaf * 2
    can_v = w >= min_leaf * 2
    if depth >= 6 or (not can_h and not can_v):
        return [(x, y, w, h)]
    horizontal = rng.random() < 0.5 if (can_h and can_v) else can_h
    if horizontal:
        cut = rng.randint(min_leaf, h - min_leaf)
        return (_bsp_leaves(x, y, w, cut, min_leaf, rng, depth + 1)
                + _bsp_leaves(x, y + cut, w, h - cut, min_leaf, rng, depth + 1))
    cut = rng.randint(min_leaf, w - min_leaf)
    return (_bsp_leaves(x, y, cut, h, min_leaf, rng, depth + 1)
            + _bsp_leaves(x + cut, y, w - cut, h, min_leaf, rng, depth + 1))


def _carve_corridor(g, a, b, w, h) -> None:
    (x0, y0), (x1, y1) = a, b
    for x in range(min(x0, x1), max(x0, x1) + 1):
        if 0 < y0 < h - 1 and 0 < x < w - 1:
            g[y0][x] = FLOOR
    for y in range(min(y0, y1), max(y0, y1) + 1):
        if 0 < y < h - 1 and 0 < x1 < w - 1:
            g[y][x1] = FLOOR


def _rooms(w: int, h: int, params: dict, rng: random.Random) -> List[str]:
    w, h = max(7, w), max(7, h)
    min_leaf = params.get("min_leaf", 6)
    g = [[WALL] * w for _ in range(h)]
    leaves = _bsp_leaves(1, 1, w - 2, h - 2, min_leaf, rng)
    centers = []
    for (lx, ly, lw, lh) in leaves:
        rw = min(lw, rng.randint(3, max(3, lw)))
        rh = min(lh, rng.randint(3, max(3, lh)))
        rx = lx + rng.randint(0, max(0, lw - rw))
        ry = ly + rng.randint(0, max(0, lh - rh))
        for yy in range(ry, ry + rh):
            for xx in range(rx, rx + rw):
                if 0 < yy < h - 1 and 0 < xx < w - 1:
                    g[yy][xx] = FLOOR
        centers.append((rx + rw // 2, ry + rh // 2))
    for i in range(1, len(centers)):     # chain rooms → fully connected
        _carve_corridor(g, centers[i - 1], centers[i], w, h)
    return ["".join(r) for r in g]


# ---------- connectivity + validation ----------
def _largest_component(grid: List[str]) -> Set[Tuple[int, int]]:
    h, w = len(grid), len(grid[0])
    seen = [[False] * w for _ in range(h)]
    best: Set[Tuple[int, int]] = set()
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or grid[sy][sx] != FLOOR:
                continue
            comp: Set[Tuple[int, int]] = set()
            stack = [(sx, sy)]
            while stack:
                x, y = stack.pop()
                if not (0 <= x < w and 0 <= y < h) or seen[y][x] or grid[y][x] != FLOOR:
                    continue
                seen[y][x] = True
                comp.add((x, y))
                stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
            if len(comp) > len(best):
                best = comp
    return best


def _keep_largest(grid: List[str]) -> List[str]:
    """Keep only the largest connected floor region; wall off the rest, so the
    baked floor is always fully connected."""
    comp = _largest_component(grid)
    return ["".join(FLOOR if (x, y) in comp else WALL for x in range(len(row)))
            for y, row in enumerate(grid)]


def _ensure_floor(grid: List[str]) -> List[str]:
    """A degenerate generation (no floor) gets a single carved center tile so the
    result is still a valid (trivially connected) floor."""
    if any(FLOOR in row for row in grid):
        return grid
    h, w = len(grid), len(grid[0])
    g = [list(r) for r in grid]
    g[h // 2][w // 2] = FLOOR
    return ["".join(r) for r in g]


def validate(grid: List[str]) -> bool:
    """A baked floor is valid if it's rectangular, uses only registry glyphs, has
    floor, and that floor is fully (orthogonally) connected. Reused by the
    designer (handoff-10 §2) alongside its spawn/exit checks."""
    if not grid:
        return False
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        return False
    if any(not tiles.known(g) for row in grid for g in row):
        return False
    floors = [(x, y) for y, row in enumerate(grid)
              for x, g in enumerate(row) if tiles.walkable(g)]
    if not floors:
        return False
    seen, stack = set(), [floors[0]]
    fset = set(floors)
    while stack:
        cell = stack.pop()
        if cell in seen or cell not in fset:
            continue
        seen.add(cell)
        x, y = cell
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return len(seen) == len(floors)
