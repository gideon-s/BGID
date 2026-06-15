# Handoff 06 — Phase 5: Portraits (Novita)

**Status:** ready to build · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phases 1–4 (shipped). **Independent track** — it touches the social/portrait layer,
not the tile sim, so it can land any time once a Novita key is on the box.
**Goal:** generate and show **character & NPC portraits** in the UI — a portrait
panel in the dialogue sidebar / combat view — via a generation service that
mirrors `deepseek_integration.py`, with **generate-once + aggressive caching** so
each portrait costs one API call ever.

> Read master §1, §5 (Phase 5), §8 (needs `NOVITA_API_KEY`) first. This is a
> Layer-2 enrichment (like DeepSeek): it must **degrade gracefully** — no key, a
> failed call, or a pending generation all fall back to the emoji glyph the game
> already uses, so nothing blocks and nothing breaks.

---

## 1. The slice (acceptance demo)

1. With `NOVITA_API_KEY` set on the box, talk to the **Innkeeper** → the
   dialogue sidebar shows a generated **portrait** beside its lines. The first
   `talk`/encounter kicks off generation; the image appears when ready and is
   **reused forever after** (no re-generation on later visits, restarts, or other
   players).
2. Engaging the **Cellar Rat** in combat shows its portrait in the combat/stats
   strip; your own character has a portrait too (generated from class + name).
3. **No key / generation fails / still pending** → the UI just shows the emoji
   glyph as today. The game is fully playable without portraits.
4. A second player who meets the same Innkeeper gets the **cached** image
   instantly (served as a static file, no new API call).

If portraits generate once, cache durably, render in the UI, and degrade to
glyphs when absent, Phase 5 is done.

---

## 2. In scope / out

**In:** a `novita_integration.py` generation service mirroring
`deepseek_integration.py` (config from env, async client, graceful "not
configured" path); a **portrait store** (generated image saved to disk under
`static/portraits/`, served by the existing `/static` mount; a DB pointer on the
subject); **generate-once** keyed by a stable prompt hash + an in-flight guard so
concurrent requests don't double-generate; **prompt building** from subject data
(NPC name/description/type; player name/class); a WS **`portrait`** event + a
field on entities so the client can show it; client **portrait panel** in the
sidebar + a small portrait in the combat/stats strip; config knobs; tests
(mocked — no live API calls in CI); deploy.

**Out (later / deferred):** live image *streaming*/progress bars; portrait
regeneration/editing UI; per-player custom art uploads; map **tile**/scene art
(master §7 — "not committed"); animated portraits; moderation pipeline beyond
Novita's own; portraits for items. NPC conversation memory and other Layer-2
work stay as-is.

---

## 3. Generation service (`novita_integration.py`, new)

Mirror the shape of `deepseek_integration.py` so it reads familiarly:

- `NovitaConfig.from_settings()` ← `config.py` (`NOVITA_API_KEY`,
  `NOVITA_BASE_URL`, `NOVITA_MODEL`, image size, `NOVITA_TIMEOUT`).
- `NovitaClient` async context manager; `generate_image(prompt) -> bytes` (or a
  URL the service then downloads). **If `NOVITA_API_KEY` is empty, the service is
  "not configured"** — `is_enabled()` returns False and callers skip silently
  (exactly how DeepSeek-off degrades to canned barbs today).
- `initialize_novita()` / `cleanup_novita()` + a global `portrait_manager`,
  started/stopped in the app lifespan next to the DeepSeek hooks (a missing key
  prints a warning and leaves the manager disabled, never raises).
- Use Novita's text-to-image HTTP API (it is **not** OpenAI-compatible — use
  `httpx`/`aiohttp` directly, not the `openai` SDK). Keep the request/response
  parsing isolated in `NovitaClient` so the rest of the code only sees
  `prompt -> image bytes`.

> Novita key (Bryan): set `NOVITA_API_KEY` in `/var/www/bgid/.env` (chmod 600,
> never committed), then restart. Until then the feature is dark by default.

---

## 4. Portrait store & generate-once (`portraits.py`, new)

The cache is the heart of this phase — **one API call per portrait, ever.**

- **Key:** a stable `prompt_hash = sha256(prompt)[:16]`. Identical prompts (same
  NPC, same class+name styling) map to the same file → natural dedup.
- **File:** `static/portraits/{prompt_hash}.png`, served by the existing
  `/static` mount at `/static/portraits/{hash}.png`. The directory is created on
  startup and **gitignored** (generated art is not source).
- **DB pointer:** add `portrait_url` (nullable `String`) to `Npc` and `Player`
  (additive migration, §8). Once set, it's the durable record; `world.load()` /
  snapshots read it. A null pointer + enabled service = "generate on first need."
- **In-flight guard:** an in-memory `set` of hashes currently generating, so two
  simultaneous `talk`s to the same NPC trigger one job; the loser awaits/*skips*.
- **`ensure_portrait(subject) -> url | None`:** if the subject already has a
  `portrait_url`, return it; else if the file for its prompt hash exists, adopt +
  persist it; else if the service is enabled and not already in-flight, spawn an
  async job (`asyncio.create_task`) that generates → writes the file → sets
  `portrait_url` → broadcasts a `portrait` event. Returns immediately (None when
  not yet available) so it **never blocks** gameplay.

Generation is **fire-and-forget**, triggered on natural events (first `talk` to
an NPC; an entity entering a zone; character creation) — never on the combat hot
path.

---

## 5. Prompt building

Small, deterministic prompt templates (so the hash is stable):

- **NPC:** `f"{npc.name}, {npc.npc_type}, {npc.description} — fantasy RPG
  character portrait, painterly, bust, dark background"`.
- **Player:** `f"{name}, a {char_class} adventurer — fantasy RPG character
  portrait, painterly, bust, dark background"`.

Keep the style suffix in one constant so all portraits look consistent and the
hash only changes when the subject does. (Deliberately not personality/mood-
varying for MVP — that would defeat generate-once.)

---

## 6. WS protocol + entity fields

- Include `portrait_url` (nullable) on the entity dicts in `zone_snapshot`
  (`you` + `entities`) and on `npc_said`/`chat` payloads where useful, so the
  client can attach art it already has.
- New broadcast **`portrait {kind, id, url}`** when a just-generated portrait
  becomes available → the client swaps the glyph placeholder for the image in
  any open panel. (Broadcast to the subject's room; everyone there benefits from
  the cache.)
- Connect sequence stays stable (the Phase 2–4 rule): don't push portraits ahead
  of `zone_state`; they arrive via `zone_state` fields + later `portrait` events.

---

## 7. Client (`static/index.html`)

- **Sidebar portrait panel:** above/inline with the Dialogue log, show the
  portrait of the NPC currently being talked to (and optionally the player).
  Until an image exists, show the **emoji glyph** in a framed placeholder of the
  same size — so layout doesn't jump when the image arrives.
- **Combat strip:** a small portrait of the current foe next to the combat log /
  target HP.
- Cache image elements by `portrait_url`; on a `portrait` event, fill any
  matching placeholders. All art loads from `/static/portraits/...` (same-origin,
  cacheable by the browser too).
- Pure progressive enhancement: with portraits off, the UI is exactly today's.

---

## 8. Schema, files & deploy

- **Schema:** add `Npc.portrait_url` + `Player.portrait_url` (nullable) →
  `migrate_phase5.py` (idempotent additive `ALTER TABLE`, guard on
  `PRAGMA table_info`), same pattern as Phases 3–4. Back up `game.db` first.
- **Files:** create `static/portraits/` on the box; add `static/portraits/` to
  `.gitignore` (generated art, like `.env`/`game.db`/`.venv`). Portraits survive
  restarts (they're files + DB pointers); a wipe just regenerates on demand.
- **Secret:** `NOVITA_API_KEY` into `/var/www/bgid/.env` (chmod 600). Until set,
  the deploy is safe and inert — no portraits, no errors.
- **Deps:** if not already present, add the HTTP client (`httpx`) to
  `requirements.txt`; `pip install` on deploy since deps changed.
- Flow: `git pull` → `pip install -r requirements.txt` → `migrate_phase5.py` →
  restart. One worker. Accounts preserved.

---

## 9. Cost & safety

- **Generate-once + hash dedup** is the cost control: N distinct subjects = N
  calls total, forever. No per-encounter or per-player regeneration.
- A small **global generation budget / concurrency cap** (config
  `PORTRAIT_MAX_CONCURRENT`, a simple in-flight counter) so a flood of new NPCs
  can't fan out unbounded API calls at once.
- Errors never surface to gameplay: a failed job logs, leaves `portrait_url`
  null, and the glyph stays. Retry is lazy (next natural trigger), not a loop.
- Don't log the key; mirror DeepSeek's "not configured" messaging.

---

## 10. Tests (`test_portraits.py`)

- Service **disabled** (no key): `is_enabled()` False; `ensure_portrait` returns
  None and spawns no job; UI path still yields glyph entities.
- Prompt hashing is **stable** for identical subjects, distinct for different
  ones.
- **Generate-once:** with the Novita client **mocked** to return fixed bytes,
  first `ensure_portrait` writes the file + sets `portrait_url` + broadcasts
  `portrait`; a second call returns the cached url and makes **no** new client
  call (assert call count == 1). In-flight guard: two concurrent calls → one job.
- File adoption: a pre-existing file for a subject's hash is adopted without a
  new call.
- `zone_snapshot` carries `portrait_url` (null when absent).
- Migration idempotency (mirror the Phase 3/4 migration tests).
- **No live API calls in CI** — the client is always mocked; the DeepSeek tests'
  key-blanking pattern (conftest) applies to Novita too.
- Keep auth / combat / spells / Phase 1–4 tests green.

---

## 11. Definition of done

- The four acceptance steps work over `wss://` with a key set; with no key the
  game is unchanged.
- Full suite green (new `test_portraits.py`, all mocked, + all prior).
- Docs: tick master §5 Phase 5; document `portrait_url` columns, the `portrait`
  event + `zone_state` field, and the `static/portraits/` store in
  `ARCHITECTURE.md`; update the in-repo memory entry on ship.

---

## 12. Build order (suggested)

1. **Service + config:** `novita_integration.py`, `NOVITA_*` config, lifespan
   wiring, `is_enabled()` gating + a mocked unit test. *(dark by default)*
2. **Store + generate-once:** `portraits.py` (hash, file store, in-flight guard,
   `ensure_portrait`), `portrait_url` columns + `migrate_phase5.py`, tests with a
   mocked client. *(cache proven without the UI)*
3. **Wire triggers + protocol:** call `ensure_portrait` on first `talk` / zone
   entry / character creation; `portrait` event + snapshot fields.
4. **Client:** sidebar portrait panel + combat-strip portrait + glyph-placeholder
   fallback + `portrait`-event swap.
5. **Deploy:** key into `.env`, create `static/portraits/`, migrate, verify a
   real portrait generates once and is reused.
