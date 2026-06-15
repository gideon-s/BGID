#!/usr/bin/env python3
"""
Portrait store & generate-once cache (Phase 5).

The cache is the heart of this phase: **one API call per portrait, ever.**

- A portrait is keyed by ``sha256(prompt)[:16]`` — identical prompts (same
  subject styling) map to the same PNG file, giving natural dedup.
- Files live under ``static/portraits/{hash}.png`` (served by the existing
  ``/static`` mount, gitignored) and a ``portrait_url`` pointer is persisted on
  the subject row (Npc / Player) so it survives restarts.
- ``ensure_portrait`` is fire-and-forget: it returns the url if known, adopts an
  existing file if present, else (when enabled and not already in flight)
  spawns an async job that generates → writes the file → sets ``portrait_url``
  → broadcasts a ``portrait`` event. It NEVER blocks gameplay and NEVER raises.

Triggered on natural events (first ``talk`` to an NPC, a player entering a zone,
the first ``sheet`` request), never on the combat hot path.
"""

import asyncio
import hashlib
import os
from typing import Optional

import config
import models
import novita_integration
from database import SessionLocal

PORTRAIT_DIR = os.path.join(os.path.dirname(__file__), "static", "portraits")

# Per-purpose generation styles: which model, image size, and prompt suffix to
# use. The suffix steers the look and is part of the hashed prompt, so bumping a
# suffix (or swapping a model) re-keys that purpose's images (a deliberate,
# manual "re-roll all"). Add new purposes here — e.g. items, scenery.
#   - portrait: painterly fantasy character bust (player + NPC windows).
#   - token:    top-down overhead map token (future overhead-view feature).
STYLES = {
    "portrait": {
        "model": config.NOVITA_PORTRAIT_MODEL,
        "width": config.NOVITA_PORTRAIT_WIDTH,
        "height": config.NOVITA_PORTRAIT_HEIGHT,
        "suffix": "fantasy RPG character portrait, painterly, bust, dark background",
    },
    "token": {
        "model": config.NOVITA_TOKEN_MODEL,
        "width": config.NOVITA_TOKEN_WIDTH,
        "height": config.NOVITA_TOKEN_HEIGHT,
        "suffix": ("top-down overhead view, centered RPG battle-map character token, "
                   "circular vignette, clean dark background, game asset"),
    },
}

# Back-compat alias: the portrait suffix (the original single style).
STYLE_SUFFIX = STYLES["portrait"]["suffix"]
# Item tokens want an object icon, not a character token.
TOKEN_ITEM_SUFFIX = ("top-down game item icon token, single centered object, "
                     "clean dark background, game asset")

# Which DB column each purpose persists its url to.
_URL_COLUMN = {"portrait": "portrait_url", "token": "token_url"}

# Hashes currently being generated — guards against two simultaneous triggers
# for the same subject spawning two jobs.
_inflight: set[str] = set()


def ensure_portrait_dir() -> None:
    """Create the portraits directory (called on startup; safe to repeat)."""
    os.makedirs(PORTRAIT_DIR, exist_ok=True)


def _hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _url_for(prompt_hash: str) -> str:
    return f"/static/portraits/{prompt_hash}.png"


def _path_for(prompt_hash: str) -> str:
    return os.path.join(PORTRAIT_DIR, f"{prompt_hash}.png")


def _clean(token: Optional[str]) -> str:
    """Drop empty/placeholder tokens so they don't pollute the prompt/hash."""
    t = (token or "").strip()
    if t.lower() in ("", "none", "wanderer"):
        return ""
    return t


def build_npc_prompt(name: str, npc_type: str, description: str) -> str:
    """Deterministic NPC prompt (stable hash)."""
    desc = (description or "").strip()
    core = f"{name}, {npc_type}"
    if desc:
        core += f", {desc}"
    return f"{core} — {STYLE_SUFFIX}"


def build_player_prompt(name: str, gender: str, race: str, char_class: str,
                        appearance: str = "") -> str:
    """Deterministic player prompt from race + gender + class + appearance.

    Empty/`none`/`wanderer` tokens are skipped so the hash stays clean. The
    free-form `appearance` (looks/bio) is appended when present, so editing it
    re-keys the hash and regenerates the portrait.
    """
    descriptors = " ".join(t for t in (_clean(gender), _clean(race), _clean(char_class)) if t)
    who = f"{name}, a {descriptors} adventurer" if descriptors else f"{name}, an adventurer"
    look = (appearance or "").strip()
    if look:
        who = f"{who}, {look}"
    return f"{who} — {STYLE_SUFFIX}"


def prompt_for_subject(kind: str, subject) -> str:
    """Build the deterministic PORTRAIT prompt for an Npc or Player ORM object."""
    if kind == "npc":
        return build_npc_prompt(subject.name, subject.npc_type, subject.description)
    return build_player_prompt(
        subject.name, subject.gender, subject.race, subject.char_class,
        subject.appearance)


def _subject_core(kind: str, subject) -> str:
    """The subject-describing part of a prompt (no style suffix), per kind."""
    if kind == "npc":
        desc = (subject.description or "").strip()
        return f"{subject.name}, {subject.npc_type}" + (f", {desc}" if desc else "")
    if kind == "item":
        return f"{subject.name}, a {subject.item_type or 'object'}"
    # player
    descriptors = " ".join(t for t in (_clean(subject.gender), _clean(subject.race),
                                       _clean(subject.char_class)) if t)
    who = f"{subject.name}, a {descriptors} adventurer" if descriptors \
        else f"{subject.name}, an adventurer"
    look = (subject.appearance or "").strip()
    return f"{who}, {look}" if look else who


def prompt_for(purpose: str, kind: str, subject) -> str:
    """Deterministic prompt for a (purpose, kind) — the hashed cache key."""
    if purpose == "portrait":
        return prompt_for_subject(kind, subject)
    suffix = TOKEN_ITEM_SUFFIX if kind == "item" else STYLES["token"]["suffix"]
    return f"{_subject_core(kind, subject)} — {suffix}"


def ensure_image(purpose: str, kind: str, subject_id: int,
                 broadcast_room: Optional[int] = None) -> Optional[str]:
    """Ensure a generated image (``purpose`` = portrait | token) exists for a
    subject; return its url if already known.

    - Returns the stored url column if set.
    - Else adopts an existing on-disk file for the prompt hash (persists +
      returns its url) — covers a wiped DB with surviving files, and dedup
      across distinct subjects that share a prompt.
    - Else, if generation is enabled and not already in flight, spawns a
      fire-and-forget job and returns ``None`` (the glyph shows until ready).

    Safe to call from any async handler; never blocks on the network, never
    raises. ``broadcast_room`` (if given) is the room the availability event is
    broadcast to once the image is ready.
    """
    column = _URL_COLUMN[purpose]
    db = SessionLocal()
    try:
        subject = _load(db, kind, subject_id)
        if subject is None:
            return None
        if getattr(subject, column):
            return getattr(subject, column)
        prompt = prompt_for(purpose, kind, subject)
        prompt_hash = _hash(prompt)
        # Adopt an existing file for this hash (no new API call).
        if os.path.exists(_path_for(prompt_hash)):
            url = _url_for(prompt_hash)
            setattr(subject, column, url)
            db.commit()
            return url
    finally:
        db.close()

    if not novita_integration.portrait_manager.is_enabled():
        return None
    if prompt_hash in _inflight:
        return None
    _inflight.add(prompt_hash)
    try:
        asyncio.create_task(
            _generate_job(purpose, kind, subject_id, prompt, prompt_hash, broadcast_room))
    except RuntimeError:
        # No running event loop (e.g. a sync REST path) — drop the guard so a
        # later trigger from an async context can retry.
        _inflight.discard(prompt_hash)
    return None


def ensure_portrait(kind: str, subject_id: int, broadcast_room: Optional[int] = None
                    ) -> Optional[str]:
    """Ensure a character portrait (Npc/Player). See ensure_image."""
    return ensure_image("portrait", kind, subject_id, broadcast_room)


def ensure_token(kind: str, subject_id: int, broadcast_room: Optional[int] = None
                 ) -> Optional[str]:
    """Ensure an overhead map token (Npc/Player/Item). See ensure_image."""
    return ensure_image("token", kind, subject_id, broadcast_room)


async def _generate_job(purpose: str, kind: str, subject_id: int, prompt: str,
                        prompt_hash: str, broadcast_room: Optional[int]) -> None:
    """Generate the image, persist the file + pointer, broadcast availability.

    Errors are swallowed (logged): a failed job leaves the url column null and
    the glyph stays. Retry is lazy — the next natural trigger tries again.
    """
    column = _URL_COLUMN[purpose]
    try:
        style = STYLES[purpose]
        image_bytes = await novita_integration.portrait_manager.generate_image(
            prompt, style["model"], style["width"], style["height"])
        ensure_portrait_dir()
        with open(_path_for(prompt_hash), "wb") as fh:
            fh.write(image_bytes)
        url = _url_for(prompt_hash)
        db = SessionLocal()
        try:
            subject = _load(db, kind, subject_id)
            if subject is not None:
                setattr(subject, column, url)
                db.commit()
        finally:
            db.close()
        await _broadcast(purpose, kind, subject_id, url, broadcast_room)
    except Exception as exc:  # never let a generation job crash the loop
        print(f"⚠️  {purpose} generation failed for {kind} {subject_id}: {exc}")
    finally:
        _inflight.discard(prompt_hash)


async def _broadcast(purpose: str, kind: str, subject_id: int, url: str,
                     room_id: Optional[int]) -> None:
    """Broadcast a ``portrait``/``token`` event so the client swaps the glyph."""
    if room_id is None:
        return
    # Imported lazily to avoid an import cycle at module load.
    from websocket_manager import manager
    await manager.broadcast_to_room(
        room_id, {"event": purpose, "kind": kind, "id": subject_id, "url": url})


def _load(db, kind: str, subject_id: int):
    """Load the Npc/Player/Item row for a subject (or None)."""
    model = {"npc": models.Npc, "player": models.Player, "item": models.Item}[kind]
    return db.query(model).filter(model.id == subject_id).first()
