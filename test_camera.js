// Unit tests for the pure adaptive-camera math (handoff-11 Slice C).
// Run: node test_camera.js   (not part of pytest — it's client JS).
const assert = require('assert');
const { cameraView, cameraOffset, tileFromPixel } = require('./static/camera.js');

// A small grid that fits the panel → static (whole grid, no camera).
let v = cameraView(8, 6, 800, 600);
assert.strictEqual(v.mode, 'static');
assert.strictEqual(v.viewCols, 8);
assert.strictEqual(v.viewRows, 6);

// A large grid → follow: a fixed readable cell + a viewport smaller than the grid.
v = cameraView(80, 60, 800, 600);
assert.strictEqual(v.mode, 'follow');
assert.strictEqual(v.cell, 26);
assert.ok(v.viewCols < 80 && v.viewRows < 60);

// Offset centers the player and clamps to grid bounds.
let o = cameraOffset(20, 15, 80, 60, 40, 30);
assert.strictEqual(o.camX, 30);   // round(40 - 10)
assert.strictEqual(o.camY, 23);   // round(30 - 7.5)

o = cameraOffset(20, 15, 80, 60, 2, 1);       // near origin → clamp to 0,0
assert.deepStrictEqual(o, { camX: 0, camY: 0 });

o = cameraOffset(20, 15, 80, 60, 79, 59);     // far corner → clamp to max
assert.deepStrictEqual(o, { camX: 60, camY: 45 });

// Inverse maps a canvas pixel back to the right tile (static: cam 0,0).
assert.deepStrictEqual(tileFromPixel(50, 30, 26, 0, 0), { x: 1, y: 1 });
// …and through a camera offset.
assert.deepStrictEqual(tileFromPixel(50, 30, 26, 30, 23), { x: 31, y: 24 });

console.log('camera math OK');
