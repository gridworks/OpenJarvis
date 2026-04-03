#!/usr/bin/env zsh
# start-jarvis.sh — Start OpenJarvis stack (MLX server + backend + frontend)
# Ctrl+C cleanly stops all three services.

SCRIPT_DIR="${0:A:h}"
MODEL="mlx-community/Qwen3.5-27B-4bit-DWQ"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

MLX_PID=""
SERVE_PID=""
FRONTEND_PID=""

# ── Cleanup ────────────────────────────────────────────────────────────────────
cleanup() {
    stty sane 2>/dev/null
    echo "\nStopping OpenJarvis..."
    [[ -n "$FRONTEND_PID" ]] && kill -TERM -"$FRONTEND_PID" 2>/dev/null
    [[ -n "$SERVE_PID"    ]] && kill -TERM  "$SERVE_PID"    2>/dev/null
    [[ -n "$MLX_PID"      ]] && kill -TERM  "$MLX_PID"      2>/dev/null
    sleep 2
    [[ -n "$FRONTEND_PID" ]] && kill -KILL -"$FRONTEND_PID" 2>/dev/null
    [[ -n "$SERVE_PID"    ]] && kill -KILL  "$SERVE_PID"    2>/dev/null
    [[ -n "$MLX_PID"      ]] && kill -KILL  "$MLX_PID"      2>/dev/null
    echo "Done."
    exit 0
}

trap cleanup INT TERM

# ── Preflight checks ───────────────────────────────────────────────────────────
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python venv not found at $PYTHON"
    echo "       Run: uv sync --extra inference-mlx"
    exit 1
fi

if ! "$PYTHON" -c "import mlx_lm" 2>/dev/null; then
    echo "ERROR: mlx_lm not installed in venv."
    echo "       Run: uv pip install mlx-lm"
    exit 1
fi

if [[ ! -d "$SCRIPT_DIR/frontend" ]]; then
    echo "ERROR: frontend directory not found at $SCRIPT_DIR/frontend"
    exit 1
fi

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js via: brew install node"
    exit 1
fi

# ── Port cleanup ───────────────────────────────────────────────────────────────
for port in 8080 8000 5173; do
    lsof -ti ":$port" | xargs kill -9 2>/dev/null
done

cd "$SCRIPT_DIR" || exit 1

# ── MLX server ─────────────────────────────────────────────────────────────────
echo "Starting MLX model server ($MODEL)..."
"$PYTHON" -m mlx_lm server --model "$MODEL" --port 8080 < /dev/null &
MLX_PID=$!

echo "Waiting for MLX server to be ready (model may need to load)..."
MLX_WAIT=0
MLX_TIMEOUT=300  # 5 minutes max — model is large
until curl -sf http://localhost:8080/v1/models > /dev/null 2>&1; do
    if ! kill -0 "$MLX_PID" 2>/dev/null; then
        echo "ERROR: MLX server exited unexpectedly. Aborting."
        cleanup
    fi
    (( MLX_WAIT++ ))
    if (( MLX_WAIT == 15 )); then
        echo "  (still loading — model files are being read from cache...)"
    fi
    if (( MLX_WAIT >= MLX_TIMEOUT / 2 )); then
        echo "ERROR: MLX server did not become ready after ${MLX_TIMEOUT}s. Aborting."
        cleanup
    fi
    sleep 2
done
echo "MLX server ready."

# ── Backend ────────────────────────────────────────────────────────────────────
echo "Starting OpenJarvis backend..."
"$PYTHON" -m openjarvis.cli serve < /dev/null &
SERVE_PID=$!

echo "Waiting for backend to be ready..."
SERVE_WAIT=0
SERVE_TIMEOUT=30
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    if ! kill -0 "$SERVE_PID" 2>/dev/null; then
        echo "ERROR: Backend exited unexpectedly. Aborting."
        cleanup
    fi
    (( SERVE_WAIT++ ))
    if (( SERVE_WAIT >= SERVE_TIMEOUT )); then
        echo "ERROR: Backend did not become ready after ${SERVE_TIMEOUT}s. Aborting."
        cleanup
    fi
    sleep 1
done
echo "Backend ready."

# ── Frontend ───────────────────────────────────────────────────────────────────
echo "Starting frontend..."
# Use setsid via python to put npm in its own session with no controlling
# terminal — prevents Vite from opening /dev/tty and disabling ISIG,
# which would cause Ctrl+C to echo "^C" instead of sending SIGINT.
cd "$SCRIPT_DIR/frontend" || { echo "ERROR: cannot cd to frontend/"; cleanup; }
"$PYTHON" -c "import os; os.setsid(); os.execlp('npm', 'npm', 'run', 'dev')" < /dev/null &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo "\nOpenJarvis running:"
echo "  MLX server: http://localhost:8080"
echo "  Backend:    http://localhost:8000"
echo "  Web UI:     http://localhost:5173"
echo "\nPress Ctrl+C to stop all services.\n"

# Monitor all three services — if any exits unexpectedly, shut everything down.
# (zsh has no `wait -p`, so we poll. SIGINT from Ctrl+C interrupts sleep and fires the trap.)
while true; do
    sleep 5
    if [[ -n "$MLX_PID"      ]] && ! kill -0 "$MLX_PID"      2>/dev/null; then
        echo "MLX server stopped unexpectedly."; cleanup; fi
    if [[ -n "$SERVE_PID"    ]] && ! kill -0 "$SERVE_PID"    2>/dev/null; then
        echo "Backend stopped unexpectedly.";    cleanup; fi
    if [[ -n "$FRONTEND_PID" ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "Frontend stopped unexpectedly.";   cleanup; fi
done
