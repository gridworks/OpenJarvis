# OpenJarvis — Local Setup Notes (M5 Max)

MacBook Pro, Apple M5 Max, 64GB unified memory, macOS 15.

---

## 1. Install

```bash
git clone https://github.com/gridworks-tech-inc/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev --extra inference-mlx --extra inference-cloud --extra energy-apple
```

---

## 2. Configure

The user config at `~/.openjarvis/config.toml` takes precedence over the repo config.
`jarvis init` writes it automatically — ensure it contains:

```toml
[engine]
default = "mlx"

[engine.mlx]
# host = "http://localhost:8080"  # default, no need to set

[intelligence]
default_model = "mlx-community/Qwen3.5-27B-4bit-DWQ"
```

> **Note:** Use the full HuggingFace repo ID (`mlx-community/...`), not the catalog alias
> (`qwen3.5:27b`). The MLX server rejects the catalog format with a 404.

---

## 3. Download model

```bash
uv run jarvis init
```

Detects M5 Max hardware and recommends `mlx-community/Qwen3.5-27B-4bit-DWQ`.
Download takes ~10 min on first run. Model cached at `~/.cache/huggingface/hub/`.

---

## 4. Start all services

Use `start-jarvis.sh` (gitignored, lives at repo root):

```bash
./start-jarvis.sh
```

Starts in one terminal window:
- MLX inference server → `http://localhost:8080`
- OpenJarvis backend → `http://localhost:8000`
- Vite frontend → `http://localhost:5173`

Ctrl+C cleanly stops all three.

**First prompt is slow** (~10–30s): MLX JIT-compiles Metal GPU kernels on first use.
Subsequent prompts are fast.

---

## 5. Energy monitoring on AC power (powermetrics)

Battery drain monitoring works automatically on battery. On AC power, use `powermetrics`.

Add a passwordless sudoers entry so powermetrics can run without a password prompt:

```
sudo visudo -f /etc/sudoers.d/powermetrics
```

Add this line (replace `yourusername` with your macOS username):

```
yourusername ALL=(ALL) NOPASSWD: /usr/bin/powermetrics
```

Once set, `AppleEnergyMonitor` auto-detects and uses `powermetrics` on AC,
reporting real CPU/GPU/ANE power instead of zeros.

---

## 6. Web UI routing fix (one-time)

If the web UI sends chat directly to port 8080 (MLX) instead of port 8000 (backend),
a stale localStorage setting is the cause. Fix in browser console:

```js
localStorage.clear()
```

Hard-refresh (`Cmd+Shift+R`). Telemetry rows in the dashboard will now populate correctly.

---

## 7. Known local patches (not yet PR'd)

**`src/openjarvis/server/cloud_router.py`**

The `is_cloud_model()` function treats any model ID containing `/` as an OpenRouter
cloud model. This wrongly classifies local HuggingFace repo IDs like
`mlx-community/Qwen3.5-27B-4bit-DWQ`, causing requests to be routed to the cloud
instead of the local MLX engine. Fix (line ~67):

```python
# Before:
if "/" in model:
    return "openrouter"

# After:
_LOCAL_HF_ORGS = ("mlx-community/", "bartowski/", "unsloth/", "lmstudio-community/")
if "/" in model and not any(model.startswith(p) for p in _LOCAL_HF_ORGS):
    return "openrouter"
```

**`src/openjarvis/telemetry/energy_apple.py`**

- M5 / M5 Pro / M5 Max / M5 Ultra added to `_CHIP_TDP`
- M5 Amperage fallback: M5+ uses signed `Amperage` key in `AppleSmartBattery`
  instead of `CurrentDischargeRate` — without this, battery drain always reads 0
- `powermetrics` poller: background thread reading CPU/GPU/ANE watts,
  used automatically when `sudo -n powermetrics` is available (AC power)

Tests: 25 passing (`tests/telemetry/test_energy_apple.py`).

---

## 8. Dependency note

`start-jarvis.sh` calls `.venv/bin/python` directly (not `uv run`) to avoid `uv sync`
downgrading `huggingface_hub`. Root cause: `vllm` optional extra pins `transformers<5`,
which forces `huggingface_hub` to an old 0.x version that breaks `mlx_lm` imports.
