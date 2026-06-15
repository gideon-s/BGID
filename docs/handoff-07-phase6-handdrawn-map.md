# Handoff 07 — Phase 6 (slice 1): Hand-drawn cartographic map

**Status:** in progress · **Depends on:** Phases 1–5 (all shipped & live).
**Goal:** re-skin the tile world from the current dark-vellum emoji-tile look to a
**hand-drawn ink-on-graph-paper dungeon-map** aesthetic (see `map.jpg` in the repo
root — cross-hatched walls, graph-paper grid, arc doorways, compass rose, numbered
chambers). **Client-only** — gameplay, the server, the WS protocol, and the world
model are all UNCHANGED. This is art direction, not mechanics.

> Phase 6 ("Polish") is a basket of independent slices (this one, plus sound,
> animation/juice, balance, sprite tilesets). This handoff covers the **map
> reskin** only. Decision (Bryan, 2026-06-15): reskin the **per-zone play view +
> the overview map** to the hand-drawn style; keep one-room-at-a-time play with
> fog-of-war exactly as today. Render **procedurally** with **rough.js** (vendored
> like rot.js) — NOT AI-generated images, because the surface must support live FOV
> and moving entities.

---

## 1. The slice (acceptance)

1. The play view (`#map` canvas) renders the current zone as a hand-drawn map:
   warm graph-paper background, **cross-hatched ink walls**, crisp ink room
   outline, **arc doorways**, ink pillars / rippled water / rubble, and a small
   **compass rose**. Fog-of-war is preserved: tiles in FOV are full ink; remembered
   (out-of-FOV) tiles are faded ink; unseen tiles are blank paper.
2. Entities + items still render as their emoji/glyph **tokens** on top, legible on
   the light paper (a faint token disc behind each). The target reticle + spell FX
   are recolored to read on paper.
3. The **M-key overview** map (`#mapcv`) is redrawn as a `map.jpg`-style floor plan:
   graph paper, chambers with hatched walls, doors (locked = different), room
   names/numbers, "you are here", a compass rose, and a cartouche title.
4. No shimmer: casting a spell (which redraws on FX start/stop without moving) does
   **not** re-randomize the hand-drawn lines. Moving re-renders the map layer (FOV
   changes anyway).
5. Server suite stays green (no server changes); the client JS passes `node --check`.

---

## 2. Approach

- **Vendor** `static/vendor/rough.min.js` (UMD, global `rough`); load it after
  rot.js. `rough.canvas(el)` → a RoughCanvas; use `rc.rectangle/line/circle/path`
  with `{roughness, bowing, stroke, strokeWidth, fill, fillStyle:'cross-hatch',
  hachureGap, seed}`. Pass a **stable per-tile seed** so geometry is deterministic.
- **Offscreen map layer.** `draw()` is event-driven (move / spawn / die / FX
  start+stop), not a rAF loop. Render the static map (paper, grid, walls, floor,
  doors, features, compass) to an **offscreen canvas** in `renderMapLayer()`,
  re-rendered only when the key `roomId:you.x,you.y` changes (i.e. zone or FOV
  change). `draw()` blits the layer, then draws items / entities / reticle / FX on
  top each call — so FX frames reuse the cached ink and never shimmer.
- **Palette** flips to cartographic: warm paper `#f4efe2`, faint blue grid, brown-
  black ink `#2b2620` (visible) / faded `#9b9482` (remembered). The map becomes a
  light "sheet" inset in the otherwise-dark Black-Goat UI (paper-on-a-dark-desk).
- **Walls** are the hatched tiles (a wall tile is "revealed" when any adjacent
  open/door tile is seen): cross-hatch fill + a crisp ink outline traced along the
  floor↔wall boundary (reusing the existing edge logic, drawn as rough lines).
- **Touch points** (all in `static/index.html`): the renderer constants + `draw()`,
  a new `renderMapLayer()`, `drawReticle`/`drawFx` recolor, `drawMinimap` +
  `drawOverview` reskin, and CSS for the light map panel.

## 3. Out of scope (later Phase 6 slices)

Sound, movement tweening / combat juice, sprite tilesets, procedural generation,
balance. The hand-drawn look here is the foundation those can build on.
