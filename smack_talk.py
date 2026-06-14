#!/usr/bin/env python3
"""
The Layer-1 → Layer-2 "smack-talk" bridge.

Combat/aggro events in the deterministic tile layer (Layer 1) fan out to short
in-character barbs in the narrative layer (Layer 2), shown in the sidebar as
``npc_said``. This is the one place the otherwise-LLM-free combat loop touches
the LLM — and it MUST stay cheap and bounded:

- **Per-mob cooldown** (``MOB_CHATTER_COOLDOWN_SECONDS``) so one mob can't spam.
- **Global per-room budget** (``rate_limit.check_mob_chatter``) so a brawl can't
  run away on DeepSeek cost — distinct from the player-initiated `talk` budget.
- **Canned-barb fallback** so the game is fully playable and free when DeepSeek
  is unconfigured, throttled, or over budget. The LLM is a garnish, never a
  dependency.

See docs/handoff-02-phase1-tiled-combat-slice.md §7.
"""
import random
import time

import config
import rate_limit
import deepseek_integration
from websocket_manager import manager

# Canned barbs by event. Kept punchy; the LLM (when on) replaces these with
# context-aware lines, but these are always the floor.
_BARBS = {
    "aggro": [
        "Fresh meat wanders in!",
        "You picked the wrong cellar, stranger.",
        "I've been waiting for someone to gut.",
    ],
    "landed_hit": [
        "Hold still, meat!",
        "Feel that?",
        "Bleed for me.",
    ],
    "took_hit": [
        "Is that all you've got?",
        "Tickles.",
        "You'll pay for that.",
    ],
    "wounded": [
        "Lucky swing!",
        "I'm not done with you yet!",
        "Grrr — you'll regret that.",
    ],
    "player_wounded": [
        "You're looking pale, friend.",
        "Almost over now.",
        "Stay down and it'll hurt less.",
    ],
}
_DEFAULT_BARBS = ["...", "Grrr."]

# Per-mob cooldown clock (monotonic seconds). In-memory; single worker.
_last_chatter: dict[int, float] = {}


def _cooldown_ok(npc_id: int) -> bool:
    now = time.monotonic()
    last = _last_chatter.get(npc_id)
    if last is not None and (now - last) < config.MOB_CHATTER_COOLDOWN_SECONDS:
        return False
    return True


def _system_prompt(name: str, event: str) -> str:
    return (
        f"You are {name}, a hostile monster in a dark-fantasy dungeon, mid-fight. "
        f"The current beat is: {event}. Snarl ONE short line of trash talk "
        f"(max 12 words), in character, no quotes, no narration."
    )


async def _generate_line(npc_id: int, name: str, event: str) -> str:
    """An LLM barb when DeepSeek is live; otherwise a canned one."""
    barbs = _BARBS.get(event, _DEFAULT_BARBS)
    canned = random.choice(barbs)
    mgr = deepseek_integration.npc_manager
    if mgr is None or getattr(mgr, "client", None) is None:
        return canned
    try:
        line = await mgr.client.generate_response(
            f"({event})", system_prompt=_system_prompt(name, event))
        line = (line or "").strip().strip('"')
        return line or canned
    except Exception as e:  # never let chatter break combat
        print(f"smack-talk LLM failed for npc {npc_id}: {e}")
        return canned


async def maybe_smack(npc_id: int, room_id: int, name: str, event: str,
                      glyph: str | None = None) -> None:
    """Maybe emit a smack-talk line for a combat event. No-op when the per-mob
    cooldown or the global room budget says so. Always degrades to a canned barb
    (never blocks combat, never requires the network)."""
    if not _cooldown_ok(npc_id):
        return
    allowed, _ = rate_limit.check_mob_chatter(room_id)
    if not allowed:
        return
    _last_chatter[npc_id] = time.monotonic()
    line = await _generate_line(npc_id, name, event)
    payload = {"event": "npc_said", "npc_id": npc_id, "name": name, "text": line}
    if glyph:
        payload["glyph"] = glyph
    await manager.broadcast_to_room(room_id, payload)


def reset() -> None:
    """Clear per-mob cooldowns (test harness between tests)."""
    _last_chatter.clear()
