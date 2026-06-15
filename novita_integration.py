#!/usr/bin/env python3
"""
Novita Integration for character & NPC portraits (Phase 5).

Generates a portrait image from a text prompt via Novita's text-to-image HTTP
API. Mirrors the shape of ``deepseek_integration.py`` (config from env, async
client, graceful "not configured" path) so it reads familiarly, but Novita is
NOT OpenAI-compatible — we talk to it with ``httpx`` directly.

Public surface (used by ``portraits.py`` and the app lifespan):
    - initialize_novita() / cleanup_novita()
    - global ``portrait_manager``
    - PortraitManager.is_enabled() / generate_image(prompt) -> bytes

This is a Layer-2 enrichment: if ``NOVITA_API_KEY`` is empty the manager is
"not configured" (``is_enabled()`` is False) and every caller skips silently,
falling back to the emoji glyph the game already uses. A failed call never
reaches gameplay — it logs and leaves the glyph in place.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx

import config


@dataclass
class NovitaConfig:
    """Shared Novita settings. The model + image size are NOT here — they are
    per-purpose (portrait vs token) and passed to generate_image() by the caller
    from portraits.STYLES."""
    api_key: str = ""
    base_url: str = "https://api.novita.ai"
    steps: int = 28
    guidance_scale: float = 7.0
    sampler: str = "DPM++ 2M Karras"
    timeout: int = 120
    poll_interval: float = 2.0

    @classmethod
    def from_settings(cls) -> "NovitaConfig":
        """Build a config from the project's config.py / environment."""
        return cls(
            api_key=config.NOVITA_API_KEY,
            base_url=config.NOVITA_BASE_URL,
            steps=config.NOVITA_STEPS,
            guidance_scale=config.NOVITA_GUIDANCE_SCALE,
            sampler=config.NOVITA_SAMPLER,
            timeout=config.NOVITA_TIMEOUT,
            poll_interval=config.NOVITA_POLL_INTERVAL,
        )


class NovitaClient:
    """Client for Novita's async text-to-image API.

    Flow (kept isolated here so the rest of the code only sees
    ``prompt -> image bytes``):
      1. POST ``/v3/async/txt2img`` → ``{"task_id": ...}``
      2. poll GET ``/v3/async/task-result?task_id=...`` until the task status is
         ``TASK_STATUS_SUCCEED`` (or ``TASK_STATUS_FAILED`` / timeout)
      3. download the returned ``image_url`` → raw PNG bytes
    """

    def __init__(self, cfg: Optional[NovitaConfig] = None):
        self.config = cfg or NovitaConfig.from_settings()
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NovitaClient":
        if not self.config.api_key:
            raise RuntimeError(
                "NOVITA_API_KEY is not set. Add it to your environment or .env file."
            )
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            timeout=httpx.Timeout(self.config.timeout),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def generate_image(self, prompt: str, model: str,
                             width: int, height: int) -> bytes:
        """Generate one image for ``prompt`` with the given model + size and
        return its raw PNG bytes.

        Raises on any failure (no key, API error, timeout, empty result); the
        caller is responsible for catching and degrading to the glyph.
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        task_id = await self._submit(prompt, model, width, height)
        image_url = await self._await_result(task_id)
        return await self._download(image_url)

    async def _submit(self, prompt: str, model: str, width: int, height: int) -> str:
        """Submit the txt2img task; return its task_id."""
        body = {
            "extra": {"response_image_type": "png"},
            "request": {
                "model_name": model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "image_num": 1,
                "steps": self.config.steps,
                "guidance_scale": self.config.guidance_scale,
                "sampler_name": self.config.sampler,
            },
        }
        resp = await self.client.post("/v3/async/txt2img", json=body)
        resp.raise_for_status()
        task_id = (resp.json() or {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Novita txt2img returned no task_id: {resp.text[:200]}")
        return task_id

    async def _await_result(self, task_id: str) -> str:
        """Poll task-result until SUCCEED; return the first image_url."""
        deadline = self.config.timeout
        waited = 0.0
        while waited < deadline:
            resp = await self.client.get(
                "/v3/async/task-result", params={"task_id": task_id})
            resp.raise_for_status()
            data = resp.json() or {}
            status = (data.get("task") or {}).get("status")
            if status == "TASK_STATUS_SUCCEED":
                images = data.get("images") or []
                if not images or not images[0].get("image_url"):
                    raise RuntimeError("Novita task succeeded but returned no image")
                return images[0]["image_url"]
            if status == "TASK_STATUS_FAILED":
                reason = (data.get("task") or {}).get("reason", "unknown")
                raise RuntimeError(f"Novita task failed: {reason}")
            await asyncio.sleep(self.config.poll_interval)
            waited += self.config.poll_interval
        raise TimeoutError(f"Novita task {task_id} did not finish in {deadline}s")

    async def _download(self, image_url: str) -> bytes:
        """Download the generated image's bytes from its signed URL.

        Uses a SEPARATE client with NO auth header: the result is an AWS S3
        pre-signed URL, and sending our ``Authorization: Bearer`` header to S3
        makes it reject the request (400 — it conflicts with the query-string
        signature). So never reuse self.client (which carries the Novita key).
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout)) as dl:
            resp = await dl.get(image_url)
            resp.raise_for_status()
            return resp.content


class PortraitManager:
    """Manages portrait generation through Novita.

    Holds the lifecycle (a single reusable httpx client) and bounds concurrent
    API calls with a semaphore. ``is_enabled()`` keys off the API key, so the
    feature is dark by default until a key is configured.
    """

    def __init__(self, cfg: Optional[NovitaConfig] = None):
        self.config = cfg or NovitaConfig.from_settings()
        self.client: Optional[NovitaClient] = None
        self._sem = asyncio.Semaphore(max(1, config.PORTRAIT_MAX_CONCURRENT))

    def is_enabled(self) -> bool:
        """Whether portrait generation is configured (a key is present)."""
        return bool(self.config.api_key)

    async def initialize(self):
        """Open the Novita client if a key is configured; otherwise stay dark.

        Never raises on a missing key — a disabled manager is a valid state.
        """
        if not self.is_enabled():
            print("ℹ️  Novita portraits disabled (no NOVITA_API_KEY) — using glyphs.")
            return
        client = NovitaClient(self.config)
        await client.__aenter__()
        self.client = client
        print("✅ Novita portrait generation enabled.")

    async def cleanup(self):
        if self.client:
            await self.client.__aexit__(None, None, None)
            self.client = None

    async def generate_image(self, prompt: str, model: str,
                             width: int, height: int) -> bytes:
        """Generate image bytes for ``prompt`` with the given model + size,
        bounded by the concurrency cap."""
        if not self.is_enabled():
            raise RuntimeError("Novita is not configured.")
        async with self._sem:
            # Reuse the persistent client if initialized; else make a one-shot.
            if self.client:
                return await self.client.generate_image(prompt, model, width, height)
            async with NovitaClient(self.config) as client:
                return await client.generate_image(prompt, model, width, height)


# Global instance — created eagerly so ``is_enabled()`` works before the app
# lifespan calls initialize() (e.g. in tests that import portraits directly).
portrait_manager: PortraitManager = PortraitManager()


async def initialize_novita(cfg: Optional[NovitaConfig] = None) -> PortraitManager:
    """Initialize the global portrait manager (called in the app lifespan)."""
    global portrait_manager
    if cfg is not None:
        portrait_manager = PortraitManager(cfg)
    await portrait_manager.initialize()
    return portrait_manager


async def cleanup_novita():
    """Clean up the global portrait manager."""
    global portrait_manager
    if portrait_manager:
        await portrait_manager.cleanup()
