// Adaptive camera math (handoff-11 Slice C) — PURE functions, no DOM, so they're
// unit-testable (loaded as globals in the browser; require()'d in node tests).
//
// A floor that fits the viewport at a readable tile size renders STATIC (the whole
// grid, fit-to-panel, as before). A floor too big switches to a player-centered
// FOLLOW camera at a fixed readable cell, showing a clamped viewport window.

// Decide render mode + cell size + viewport (in tiles) for a grid in a panel.
// opts: {pad, minCell, readable, minReadable}.
function cameraView(gridW, gridH, panelW, panelH, opts) {
  opts = opts || {};
  const pad = opts.pad != null ? opts.pad : 24;
  const minCell = opts.minCell || 14;
  const readable = opts.readable || 26;
  const minReadable = opts.minReadable || 18;
  // The cell size if the WHOLE grid were fit into the panel.
  const fitCell = Math.floor(Math.min((panelW - pad) / gridW, (panelH - pad) / gridH));
  if (fitCell >= minReadable) {
    // Fits at a readable size → static (whole grid; no camera).
    return { mode: 'static', cell: Math.max(minCell, fitCell), viewCols: gridW, viewRows: gridH };
  }
  // Too big → follow: fixed readable cell, viewport = tiles that fit (≤ grid).
  const cell = readable;
  const viewCols = Math.max(1, Math.min(gridW, Math.floor((panelW - pad) / cell)));
  const viewRows = Math.max(1, Math.min(gridH, Math.floor((panelH - pad) / cell)));
  return { mode: 'follow', cell, viewCols, viewRows };
}

// Top-left tile of a player-centered viewport, clamped to the grid bounds.
function cameraOffset(viewCols, viewRows, gridW, gridH, px, py) {
  const cx = Math.round(px - viewCols / 2);
  const cy = Math.round(py - viewRows / 2);
  return {
    camX: Math.max(0, Math.min(cx, gridW - viewCols)),
    camY: Math.max(0, Math.min(cy, gridH - viewRows)),
  };
}

// Inverse: which tile a canvas-pixel (relative to the canvas top-left) maps to,
// through the current camera offset. (In static mode camX=camY=0.)
function tileFromPixel(pxX, pxY, cell, camX, camY) {
  return { x: Math.floor(pxX / cell) + camX, y: Math.floor(pxY / cell) + camY };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { cameraView, cameraOffset, tileFromPixel };
}
