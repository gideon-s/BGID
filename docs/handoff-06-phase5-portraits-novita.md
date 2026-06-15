# Handoff 06 — Phase 5: Portraits (Novita)

**Status:** ready to build · **Depends on:** `handoff-01-graphical-overhaul-master.md`,
Phases 1–4 **plus** the post-Phase-4 character-sheet / race / windowed-UI work
(all shipped & live — see §0). **Independent track** — it touches the social/
portrait layer, not the tile sim, so it can land any time once a Novita key is on
the box. **Goal:** generate and show **character & NPC portraits** in the UI —
in the **Character window** (the player) and the **Dialogue / Status windows**
(NPCs) — via a generation service mirroring `deepseek_integration.py`, with
**generate-once + aggressive caching** so each portrait costs one API call ever.

> Read master §1, §5 (Phase 5), §8 (needs `NOVITA_API_KEY`) first, then §0 below
> for everything that changed after this doc was first drafted. This is a Layer-2
> enrichment (like DeepSeek): it must **degrade gracefully** — no key, a failed
> call, or a pending generation all fall back to the emoji glyph the game already
> uses, so nothing blocks and nothing breaks.

---

## 0. What changed since this was first drafted (READ THIS)

This handoff was written right after Phase 4. A lot shipped since — the portrait
integration points in particular are **different now**:

- **The client is a windowed UI.** There is no longer a fixed "dialogue sidebar"
  or "combat/stats strip." Instead `static/index.html` has a **floating-window
  system** (`WIN_DEFS` + `showWin`/`hideWin`/`toggleWin`, persisted to
  `localStorage`): **Dialogue**, **Battle**, **Status** (room name / You / Here /
  minimap), **Inventory**, **Character**, **Room** (description), **Map**. All are
  draggable + resizable. Dialogue/Battle/Status are "dock" windows (reparent a
  live panel); Inventory/Character/Room/Map are "content" windows (render
  generated HTML/canvas). Portraits attach to these windows, not to a sidebar.
- **Character sheet exists** (`sheet` WS cmd → `character_sheet` event;
  `renderSheet()` into `#sheetbody`). It shows name, **race**, class, gender,
  level/XP, abilities+mods, skills, and a body-slot **equipment paperdoll**. This
  is the natural home for the **player portrait** (top of the sheet).
- **Characters now have** `char_class` (`classes.py`), `race` (`races.py`),
  `gender`, `mana`/`max_mana`, `skills` (JSON, `skills.py`), plus level/exp.
  Spells live in `spells.py`; casting in `casting.py`. Use race + gender + class
  in the player prompt (§5).
- **Equipment** = `weapon`/`ring`/`amulet` + 15 body slots (`services.BODY_SLOTS`).
- **Migrations already shipped:** `migrate_phase3.py`, `migrate_phase4.py`,
  `migrate_charsheet.py`, `migrate_race_slots.py` (additive, idempotent, guard on
  `PRAGMA table_info`). `migrate_phase5.py` follows the same pattern.
- **WS events that already exist** (so you slot `portrait` alongside, not into):
  `zone_state` (room now carries `description`; `you` carries `mana/max_mana`;
  `entities` are `{id,kind,name,glyph,x,y,hp,max_hp,hostile}`; plus `items`),
  `entity_moved/spawned/died/left`, `combat`, `spell_cast`, `stats`, `inventory`,
  `spellbook`, `character_sheet`, `world_map`, `npc_thinking`, `npc_said`, `chat`.
- The live world still = Foyer / Great Hall / Cellar with the Innkeeper,
  Caretaker, and Cellar Rat. One live account/character so far.

Everything else in this doc (the generation service, the generate-once cache, the
cost controls) is unchanged — those were always UI-agnostic.

---

## 1. The slice (acceptance demo)

1. With `NOVITA_API_KEY` set on the box, open the **Character window** → your
   character's generated **portrait** sits at the top beside name/race/class. The
   first open kicks off generation; the image appears when ready and is **reused
   forever** (no re-gen on later opens, restarts, or for other players).
2. Talk to the **Innkeeper** → its portrait shows in the **Dialogue window**
   beside its lines; the **Status window**'s "Here" list shows small portrait
   thumbnails for NPCs present.
3. **No key / generation fails / still pending** → the UI shows the **emoji
   glyph** in a same-size frame, exactly as today. Fully playable without art.
4. A second player who meets the same Innkeeper gets the **cached** image
   instantly (served as a static file, no new API call).

If portraits generate once, cache durably, render in the windows, and degrade to
glyphs when absent, Phase 5 is done.

---

## 2. In scope / out

**In:** a `novita_integration.py` generation service mirroring
`deepseek_integration.py` (config from env, async client, graceful "not
configured" path); a **portrait store** (`portraits.py`) writing PNGs under
`static/portraits/` (served by the existing `/static` mount) + a `portrait_url`
DB pointer on the subject; **generate-once** keyed by a stable prompt hash + an
in-flight guard; **prompt building** from subject data (NPC name/type/description;
player **race + gender + class** + name); a WS **`portrait`** event + a
`portrait_url` field on entity/`character_sheet` payloads; client integration into
the **Character / Dialogue / Status** windows with a glyph placeholder; config
knobs; mocked tests; deploy.

**Out (later / deferred):** live image *streaming*/progress; portrait
regeneration/editing UI; per-player custom uploads; map **tile**/scene art
(master §7, "not committed"); animated portraits; moderation beyond Novita's own;
portraits for items. NPC conversation memory and other Layer-2 work stay as-is.

---

## 3. Generation service (`novita_integration.py`, new)

Mirror the shape of `deepseek_integration.py` so it reads familiarly:

- `NovitaConfig.from_settings()` ← `config.py` (`NOVITA_API_KEY`,
  `NOVITA_BASE_URL`, `NOVITA_MODEL`, image size, `NOVITA_TIMEOUT`).
- `NovitaClient` async context manager; `generate_image(prompt) -> bytes` (or a
  URL the service then downloads). **If `NOVITA_API_KEY` is empty, the service is
  "not configured"** — `is_enabled()` returns False and callers skip silently
  (exactly how DeepSeek-off degrades to canned barbs today; see `conftest.py`,
  which blanks the key so CI never calls out).
- `initialize_novita()` / `cleanup_novita()` + a global `portrait_manager`,
  started/stopped in the app lifespan next to the DeepSeek hooks (a missing key
  prints a warning and leaves the manager disabled, never raises).
- Use Novita's text-to-image HTTP API (**not** OpenAI-compatible — use `httpx`
  directly, not the `openai` SDK). Keep request/response parsing isolated in
  `NovitaClient` so the rest of the code only sees `prompt -> image bytes`.

> Novita key (Bryan): set `NOVITA_API_KEY` in `/var/www/bgid/.env` (chmod 600,
> never committed), then restart. Until then the feature is dark by default.

---

## 4. Portrait store & generate-once (`portraits.py`, new)

The cache is the heart of this phase — **one API call per portrait, ever.**

- **Key:** `prompt_hash = sha256(prompt)[:16]`. Identical prompts (same subject
  styling) map to the same file → natural dedup.
- **File:** `static/portraits/{prompt_hash}.png`, served at
  `/static/portraits/{hash}.png`. Directory created on startup, **gitignored**.
- **DB pointer:** add `portrait_url` (nullable `String`) to `Npc` and `Player`
  (additive migration, §8). Once set it's the durable record; `world.load()` /
  snapshots read it.
- **In-flight guard:** an in-memory `set` of hashes generating, so two
  simultaneous `talk`s / sheet-opens for the same subject trigger one job.
- **`ensure_portrait(subject) -> url | None`:** return `portrait_url` if set;
  else adopt an existing file for the hash and persist its url; else, if enabled
  and not in-flight, spawn an async job (`asyncio.create_task`) that generates →
  writes the file → sets `portrait_url` → broadcasts a `portrait` event. Returns
  immediately (None until ready) so it **never blocks** gameplay.

Generation is **fire-and-forget**, triggered on natural events: first `talk` to
an NPC, an entity entering a zone, **character creation**, and the **first
`sheet` request** for a player without art. Never on the combat hot path.

---

## 5. Prompt building

Deterministic templates (stable hash). Now that characters have race + gender:

- **NPC:** `f"{npc.name}, {npc.npc_type}, {npc.description} — fantasy RPG
  character portrait, painterly, bust, dark background"`.
- **Player:** `f"{name}, a {gender} {race} {char_class} adventurer — fantasy RPG
  character portrait, painterly, bust, dark background"` (skip `gender`/`race`
  tokens that are empty/`none`/`wanderer` so the hash stays clean).

Keep the style suffix in one constant. Deliberately **not** personality/mood- or
equipment-varying for MVP — that would defeat generate-once. (A future "re-roll
on level-up / gear change" is out of scope.)

---

## 6. WS protocol + entity fields

- Add `portrait_url` (nullable) to: the `you` + `entities` dicts in
  `world.zone_snapshot`, the `character_sheet` payload (`_sheet_payload` in
  `main.py`), and optionally `npc_said`/`chat` where handy.
- New broadcast **`portrait {kind, id, url}`** when a just-generated portrait
  becomes available → the client swaps the glyph placeholder for the image in any
  open window. Broadcast to the subject's room so everyone there benefits.
- **Keep the connect sequence stable** (the Phase 2–4 rule, still enforced):
  inventory/spells/sheet are fetched lazily by the client on `ws.onopen`; don't
  push portraits ahead of `zone_state`. Portraits arrive via the snapshot fields
  + later `portrait` events.

---

## 7. Client (`static/index.html`) — integrate into the windows

The UI is now windowed (§0), so attach portraits to existing windows rather than
inventing a sidebar:

- **Character window (player):** render the portrait at the top of `#sheetbody`
  (in `renderSheet`), next to name/race/class. Until art exists, show the
  player's emoji glyph in a same-size framed placeholder (no layout jump).
- **Dialogue window (NPC):** when the player `talk`s an NPC, show that NPC's
  portrait beside its lines (a small framed image at the top of the dialogue
  log / next to `npc_said`).
- **Status window "Here" list:** small portrait thumbnails next to each present
  entity in `renderPanel()` (fall back to the glyph).
- Cache `<img>`s by `portrait_url`; on a `portrait` event, fill every matching
  placeholder (`renderSheet`/`renderPanel` re-run if their window is open — use
  the existing `winOpen('fw-sheet')` / `winOpen('fw-panel')` guards).
- All art loads from `/static/portraits/...` (same-origin, browser-cacheable).
- Pure progressive enhancement: with portraits off, the UI is exactly today's.

---

## 8. Schema, files & deploy

- **Schema:** `Npc.portrait_url` + `Player.portrait_url` (nullable) →
  `migrate_phase5.py` (idempotent additive `ALTER TABLE`, guard on
  `PRAGMA table_info`) — the **5th** such migration, identical pattern to
  `migrate_race_slots.py`. Back up `game.db` first.
- **Files:** create `static/portraits/` on the box; add it to `.gitignore`
  (generated art, like `.env`/`game.db`/`.venv`). Portraits survive restarts
  (files + DB pointers); a wipe just regenerates on demand.
- **Secret:** `NOVITA_API_KEY` into `/var/www/bgid/.env` (chmod 600). Until set,
  the deploy is safe and inert.
- **Deps:** add `httpx` to `requirements.txt` if not already present; `pip
  install` on deploy since deps changed.
- Flow (matches every prior deploy): `git pull` → `pip install -r
  requirements.txt` → `migrate_phase5.py` → `systemctl restart bgid-api`. One
  worker. Accounts preserved. Verify on `https://blackgoatsociety.com`.

---

## 9. Cost & safety

- **Generate-once + hash dedup** is the cost control: N distinct subjects = N
  calls total, forever. No per-encounter or per-player regeneration.
- A **concurrency cap** (config `PORTRAIT_MAX_CONCURRENT`, a simple in-flight
  counter) so a flood of new subjects can't fan out unbounded calls at once.
- Errors never reach gameplay: a failed job logs, leaves `portrait_url` null, and
  the glyph stays. Retry is lazy (next natural trigger), not a loop.
- Don't log the key; mirror DeepSeek's "not configured" messaging.

---

## 10. Tests (`test_portraits.py`)

- Service **disabled** (no key): `is_enabled()` False; `ensure_portrait` returns
  None, spawns no job; UI path still yields glyph entities.
- Prompt hashing **stable** for identical subjects, distinct across subjects
  (and across race/gender/class for players).
- **Generate-once:** with `NovitaClient` **mocked** to return fixed bytes, first
  `ensure_portrait` writes the file + sets `portrait_url` + broadcasts `portrait`;
  a second call returns the cached url with **no** new client call (assert call
  count == 1). In-flight guard: two concurrent calls → one job.
- File adoption: a pre-existing file for a subject's hash is adopted without a
  new call.
- `zone_snapshot` + `character_sheet` carry `portrait_url` (null when absent).
- Migration idempotency (mirror the Phase 3/4/charsheet migration tests).
- **No live API calls in CI** — always mock the client; conftest already blanks
  the keys.
- Keep the full suite green (currently **140 passing**: auth / combat / spells /
  charsheet / zones / tiles / realtime / rate-limit).

---

## 11. Definition of done

- The four acceptance steps work over `wss://` with a key set; with no key the
  game is unchanged.
- Full suite green (new `test_portraits.py`, all mocked, + all prior).
- Docs: tick master §5 Phase 5; document `portrait_url` columns, the `portrait`
  event + snapshot fields, and the `static/portraits/` store in `ARCHITECTURE.md`;
  update the in-repo memory entry on ship.

---

## 12. Build order (suggested)

1. **Service + config:** `novita_integration.py`, `NOVITA_*` config, lifespan
   wiring, `is_enabled()` gating + a mocked unit test. *(dark by default)*
2. **Store + generate-once:** `portraits.py` (hash, file store, in-flight guard,
   `ensure_portrait`), `portrait_url` columns + `migrate_phase5.py`, mocked tests.
   *(cache proven without the UI)*
3. **Wire triggers + protocol:** `ensure_portrait` on first `talk` / zone entry /
   character creation / first `sheet`; `portrait` event + snapshot/sheet fields.
4. **Client:** portrait in the Character window + Dialogue window + Status "Here"
   list, glyph-placeholder fallback, `portrait`-event swap.
5. **Deploy:** key into `.env`, create `static/portraits/`, migrate, verify a
   real portrait generates once and is reused.
