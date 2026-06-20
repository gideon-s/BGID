"""Author-time map generator (handoff-11 Slice D)."""
import pytest

import mapgen
import tiles


KINDS = ["cave", "rooms"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", [1, 7, 42, 1234])
def test_generated_grid_is_well_formed(kind, seed):
    grid = mapgen.generate(kind, 40, 24, seed=seed)
    assert len(grid) == 24                                  # height
    assert all(len(row) == 40 for row in grid)             # rectangular
    assert all(tiles.known(g) for row in grid for g in row)  # registry glyphs only
    assert mapgen.validate(grid)                            # rect + floor + connected


@pytest.mark.parametrize("kind", KINDS)
def test_fully_connected(kind):
    grid = mapgen.generate(kind, 50, 30, seed=99)
    # validate() already asserts single-component floor; double-check there IS floor.
    assert any("." in row for row in grid)
    assert mapgen.validate(grid)


@pytest.mark.parametrize("kind", KINDS)
def test_deterministic_for_a_seed(kind):
    a = mapgen.generate(kind, 32, 20, seed=2024)
    b = mapgen.generate(kind, 32, 20, seed=2024)
    assert a == b                                          # same seed → identical
    c = mapgen.generate(kind, 32, 20, seed=2025)
    assert isinstance(c, list)                             # a different seed still works


def test_border_is_walled():
    grid = mapgen.generate("rooms", 30, 18, seed=5)
    assert set(grid[0]) == {"#"} and set(grid[-1]) == {"#"}
    assert all(row[0] == "#" and row[-1] == "#" for row in grid)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        mapgen.generate("spaghetti", 20, 20, seed=1)


def test_validate_rejects_ragged_and_unknown_glyphs():
    assert mapgen.validate(["###", "#.#", "###"]) is True
    assert mapgen.validate(["###", "#.##", "###"]) is False     # ragged rows
    assert mapgen.validate(["#Z#", "#.#", "###"]) is False      # unknown glyph
    assert mapgen.validate(["###", "###", "###"]) is False      # no floor
    # two disconnected floor cells → invalid
    assert mapgen.validate(["#####", "#.#.#", "#####"]) is False
