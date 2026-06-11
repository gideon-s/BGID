# DeepSeek Setup

NPCs in this game use the **DeepSeek API** (OpenAI-compatible) for intelligent,
in-character responses. If no API key is configured, NPCs automatically fall
back to the built-in rule-based responses — the game still runs.

## 1. Get an API key

Sign up at <https://platform.deepseek.com/> and create an API key.

## 2. Configure your environment

Copy the example env file and add your key:

```bash
cp .env.example .env
# edit .env and set DEEPSEEK_API_KEY=sk-...
```

The app loads `.env` automatically (via `python-dotenv` in `config.py`).
Alternatively, export it directly:

```bash
export DEEPSEEK_API_KEY=sk-...
```

## 3. Install dependencies

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 4. Run

```bash
python run.py
```

On startup you should see `✅ Connected to DeepSeek successfully!`. If the key
is missing or invalid you'll see a warning and NPCs will use rule-based
responses.

## Configuration

All settings are read from the environment (see `config.py` / `.env.example`):

| Variable | Default | Notes |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | _(required for LLM)_ | Your DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | `deepseek-chat` (V3) or `deepseek-reasoner` (R1) |
| `DEEPSEEK_TEMPERATURE` | `0.7` | Sampling temperature |
| `DEEPSEEK_MAX_TOKENS` | `500` | Max tokens per response |
| `DEEPSEEK_TIMEOUT` | `30` | Request timeout (seconds) |

## How it works

- `deepseek_integration.py` — `DeepSeekClient` / `DeepSeekNPCManager` wrap the
  `openai` async SDK pointed at DeepSeek's base URL.
- `llm_npcs.py` — `BaseLLMNPC.generate_response()` uses the global
  `npc_manager`, falling back to rule-based logic on any error.
- `main.py` — initializes the manager on startup; the `POST /chat/npc`
  endpoint builds an NPC from the DB record and returns an LLM response.
