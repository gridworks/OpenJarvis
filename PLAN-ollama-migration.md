# OpenJarvis: MLX → Ollama Migration Plan

**Author:** GridWorks  
**Date:** 2026-04-09  
**Status:** Approved — pending execution  
**Goal:** Switch inference backend from MLX to Ollama for out-of-the-box compatibility with upstream repo. MLX migration can be revisited once core functionality is validated.

---

## Overview

The good news: Ollama is already fully implemented (`engine/ollama.py`), the code default is already `"ollama"` in `config.py`, and `scripts/quickstart.sh` is the Ollama-native startup path. This is mostly config changes, a few patch reversions, and model downloads — not new code.

---

## Phase 1 — Prerequisite: Ollama Installation & Models

**1.1 Confirm Ollama is installed and running**

```bash
ollama --version
curl http://localhost:11434/api/tags
```

If not installed:
```bash
brew install ollama
```

**1.2 Pull equivalent models**

Current MLX model is `Qwen3.5-27B` (4-bit). On M5 Max (64GB) the following run comfortably:

```bash
# Primary model — close equivalent to Qwen3.5-27B-4bit
ollama pull qwen2.5:32b

# Lightweight model for agents/tools (deep-research, channels)
ollama pull qwen2.5:14b

# Fast/cheap model for evals and testing
ollama pull qwen2.5:7b
```

> If `qwen3.5:27b` becomes available on Ollama, prefer it. Check with `ollama list`.

**1.3 Validate Ollama serves the model**

```bash
ollama serve &   # if not already running as a service
curl http://localhost:11434/api/tags | python3 -m json.tool
```

Expected: JSON with `models` list containing `qwen2.5:32b`.

**Gate:** Do not proceed until `curl localhost:11434/api/tags` returns HTTP 200.

---

## Phase 2 — Config Changes

**2.1 Update `~/.openjarvis/config.toml`**

Current:
```toml
[engine]
default = "mlx"

[intelligence]
preferred_engine = "mlx"
default_model = "mlx-community/Qwen3.5-27B-4bit-DWQ"
```

Replace with:
```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen2.5:32b"
```

Drop `preferred_engine` entirely — it is deprecated and was MLX-only.

**2.2 Verify engine config section**

Ensure there is no `[engine.mlx]` section overriding the host. The `[engine.ollama]` section defaults to `http://localhost:11434` and does not need to be set explicitly unless the port was changed.

**Gate:** Run `uv run jarvis config show` and confirm `engine.default = ollama`, `intelligence.default_model = qwen2.5:32b`.

---

## Phase 3 — Patch Cleanup (gridworks/main)

The 6 commits ahead of upstream fall into two categories: **keep** and **revert/simplify**.

### Keep (general fixes, not MLX-specific)

| Commit | What it does | Action |
|--------|-------------|--------|
| `8f8c5ab` | Executor import path fix | Keep |
| `af4e397` | Deep-research model resolution (channel path) | Keep |
| `c0be740` | Energy/M5 TDP fix | Keep |
| `47d5d7b` | Apple Music implicit launch fix | Keep |

### Revert / Simplify

| Commit | What it does | Action |
|--------|-------------|--------|
| `e17c9cf` | Gates vllm to non-Darwin; mlx-lm/vllm conflict | Revert `pyproject.toml` vllm gate + `[tool.uv] conflicts` block |
| `3c85dba` | `_LOCAL_HF_ORGS` allowlist in cloud_router | Revert — no more `mlx-community/` model names to protect |
| `2b5d74b` | MLX 404 fix: wires `_configured_model` into engine | **Partially keep.** Keep `_discovery.py` and `_openai_compat.py` changes (harmless, helps other OpenAI-compat engines). Revert only the `mlx-lm>=0.31` version bump in `pyproject.toml`. |

**3.1 Revert mlx-lm version bump in pyproject.toml**

```toml
# Change back to upstream:
inference-mlx = ["mlx-lm>=0.19; sys_platform == 'darwin'"]

# Remove the vllm Darwin gate — revert to:
inference-vllm = ["vllm>=0.16.0"]

# Remove the [tool.uv] conflicts block entirely
```

**3.2 Revert `_LOCAL_HF_ORGS` in cloud_router**

Remove the `_LOCAL_HF_ORGS` block from `src/openjarvis/server/cloud_router.py`. Upstream does not have it.

**3.3 Hardcoded model references in CLI commands**

These files hardcode Ollama model names that won't match the configured model — update them to read from config:

- `src/openjarvis/cli/channels_cmd.py` — `"qwen3.5:4b"` → `config.intelligence.default_model`
- `src/openjarvis/cli/deep_research_setup_cmd.py` — same

**Gate:** `uv run ruff check src/ tests/` clean. `uv sync --extra server` resolves without conflicts.

---

## Phase 4 — Uninstall MLX Extra

```bash
# Remove the mlx extra from environment
uv sync --extra server

# Confirm mlx_lm is gone
uv run python -c "import mlx_lm" 2>&1   # should fail with ImportError
```

Running with `--extra server` only — no inference extras needed since Ollama is a system service.

**Gate:** `uv run python -c "import mlx_lm"` fails with ImportError. `uv run jarvis --help` succeeds.

---

## Phase 5 — Startup Script

**Decision: replace `start-jarvis.sh` with a simpler `start.sh`**

`scripts/quickstart.sh` is designed for first-time setup. `start-jarvis.sh` is MLX-specific (version checks, auto-restart loop, 5-min health timeout). Neither is right for daily Ollama use.

Create `start.sh` in the repo root:

```bash
#!/usr/bin/env bash
set -e

# Ensure Ollama is running
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "Starting Ollama..."
  ollama serve &
  sleep 3
fi

# Kill any stale backend/frontend
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

# Backend
uv run jarvis serve &
BACKEND_PID=$!

# Frontend
cd frontend && npm run dev &
FRONTEND_PID=$!

echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Ollama:   http://localhost:11434"
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
```

Retire `start-jarvis.sh` — keep in git history but do not maintain going forward.

---

## Phase 6 — Test Plan

### Block A: Engine Health

```bash
# A1 — Ollama responds
curl http://localhost:11434/api/tags

# A2 — Engine discovery finds Ollama
uv run python -c "
from openjarvis.core.config import load_config
from openjarvis.engine import get_engine
cfg = load_config()
name, eng = get_engine(cfg, None)
print(f'Engine: {name}')
print(f'Healthy: {eng.health()}')
print(f'Models: {eng.list_models()}')
"

# A3 — Expected: engine=ollama, healthy=True, models=['qwen2.5:32b', ...]
```

**Gate:** All three pass before moving on.

---

### Block B: Basic Inference

```bash
# B1 — CLI ask
uv run jarvis ask "What is 2 + 2?"

# B2 — Streaming works
uv run jarvis ask "Count to five, one word per line."

# B3 — Tool call round-trip
uv run jarvis ask "What time is it?" --tools time
```

**Gate:** B1 and B2 return coherent text. B3 invokes a tool call (visible in output).

---

### Block C: Knowledge Store

```bash
# C1 — Existing data intact
uv run jarvis knowledge sources

# C2 — Search still works
uv run jarvis knowledge search "Linux"

# C3 — HN re-sync (uses updated content format with title in body)
uv run python -c "
from openjarvis.connectors.hackernews import HackerNewsConnector
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
store = KnowledgeStore()
pipeline = IngestionPipeline(store)
for doc in HackerNewsConnector().sync():
    pipeline.ingest(doc)
print('done')
"
uv run jarvis knowledge list --source hackernews
```

**Gate:** C1 shows obsidian (745) and hackernews (5). C2 returns results. C3 shows titles in the content column.

---

### Block D: Knowledge Chat

```bash
# D1 — Interactive knowledge chat against Obsidian notes
uv run jarvis knowledge chat
# Ask: "What programming languages do I know?"
# Expected: answer drawn from Obsidian notes, agent calls knowledge_search tool
```

**Gate:** Agent calls `knowledge_search` (visible in output), returns answer citing Obsidian source — not a hallucinated LLM answer.

---

### Block E: Server / Web App API

```bash
# E1 — Backend starts clean
uv run jarvis serve &
sleep 3
curl http://localhost:8000/health

# E2 — Chat endpoint works
curl -s -X POST http://localhost:8000/v1/agents/default/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, what engine are you using?"}' | python3 -m json.tool

# E3 — Connectors endpoint
curl http://localhost:8000/v1/connectors | python3 -m json.tool

# E4 — HN sync via API
curl -X POST http://localhost:8000/v1/connectors/hackernews/sync
sleep 5
curl http://localhost:8000/v1/connectors/hackernews/sync
```

**Gate:** E1 returns `{"status": "ok"}`. E2 returns a response (no 404, no engine error). E3 lists connectors. E4 sync state transitions to complete.

---

### Block F: Full Stack UI

```bash
./start.sh
```

In browser at `http://localhost:5173`:
1. Send a chat message → response comes back (no "model not found" error)
2. Data Sources → Hacker News → Sync → chunk count = 5
3. Agents → Personal Deep Research → Launch → ask "Search hackernews and tell me what stories are stored" → agent uses `knowledge_search` tool and returns actual titles

**Gate:** All three UI flows complete without error.

---

### Block G: Regression Tests

```bash
# G1 — Unit tests (no live engine, no cloud)
uv run pytest tests/ -m "not live and not cloud" -v

# G2 — Connector tests
uv run pytest tests/connectors/ -v

# G3 — Ruff clean
uv run ruff check src/ tests/
```

**Gate:** G1 and G2 pass. G3 zero errors.

---

## Execution Checklist

| # | Phase | Action | Gate |
|---|-------|--------|------|
| 1 | Phase 1 | Ollama installed + models pulled | `curl localhost:11434/api/tags` = 200 |
| 2 | Phase 2 | `~/.openjarvis/config.toml` updated | `jarvis config show` confirms ollama |
| 3 | Phase 3 | MLX patches reverted in pyproject.toml + cloud_router; hardcoded models fixed | `uv sync` clean, ruff clean |
| 4 | Phase 4 | MLX extra removed | `import mlx_lm` fails |
| 5 | Phase 5 | `start.sh` created, `start-jarvis.sh` retired | New script starts stack |
| 6 | Block A | Engine health | engine=ollama, healthy=True |
| 7 | Block B | Basic inference | Text responses return correctly |
| 8 | Block C | Knowledge store | Existing data intact + HN re-sync |
| 9 | Block D | Knowledge chat | Agent uses tools, cites sources |
| 10 | Block E | Server API | All endpoints return correct data |
| 11 | Block F | Full stack UI | Chat + sync + deep research work |
| 12 | Block G | Regression tests | All pass, ruff clean |

---

## Notes

- Ollama has no Python package dependency — it is a system-level service. No `inference-ollama` extra is needed or exists.
- The `_configured_model` / `_openai_compat.py` changes from commit `2b5d74b` are kept because they benefit all OpenAI-compatible engines (vLLM, LlamaCpp, etc.), not just MLX.
- MLX support remains in the codebase as an option. This migration only changes the **default** and removes our local overrides. MLX can be re-enabled per-user by setting `engine.default = "mlx"` in config.
- The `recommend_engine()` function in `config.py` still recommends `mlx` for Apple Silicon — this is upstream behaviour and is left unchanged.
