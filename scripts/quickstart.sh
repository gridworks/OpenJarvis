#!/usr/bin/env bash
set -eo pipefail

# ── OpenJarvis Quickstart ─────────────────────────────────────────────
# One-command setup: installs deps, starts Ollama + model, launches
# the backend API server and frontend, then opens the browser.
#
# Usage:
#   git clone https://github.com/open-jarvis/OpenJarvis.git
#   cd OpenJarvis
#   ./scripts/quickstart.sh
# ──────────────────────────────────────────────────────────────────────

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

info()  { echo -e "${BLUE}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

CLEANUP_PIDS=""
cleanup() {
  echo ""
  info "Shutting down..."
  for pid in $CLEANUP_PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  ok "Done."
}
trap cleanup EXIT INT TERM

# ── Navigate to repo root ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo -e "${BOLD}"
echo "  ┌──────────────────────────────────┐"
echo "  │       OpenJarvis Quickstart      │"
echo "  └──────────────────────────────────┘"
echo -e "${NC}"

# ── 1. Check uv ─────────────────────────────────────────────────────
info "Checking uv..."
if command -v uv &>/dev/null; then
  ok "uv $(uv --version 2>/dev/null | head -1)"
else
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  ok "uv installed"
fi

# ── 2. Check Node.js ────────────────────────────────────────────────
info "Checking Node.js..."
if command -v node &>/dev/null; then
  NODE_VERSION=$(node --version)
  NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
  if [ "$NODE_MAJOR" -ge 18 ]; then
    ok "Node.js $NODE_VERSION"
  else
    fail "Node.js 18+ required (found $NODE_VERSION). Install from https://nodejs.org"
  fi
else
  fail "Node.js not found. Install from https://nodejs.org"
fi

# ── 3. Check Ollama ──────────────────────────────────────────────────
info "Checking Ollama..."
if command -v ollama &>/dev/null; then
  ok "Ollama found"
else
  warn "Ollama not found — download from https://ollama.com and re-run."
  exit 1
fi

# ── 4. Start Ollama if not running ───────────────────────────────────
info "Checking if Ollama is running..."
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
  ok "Ollama is running"
else
  info "Starting Ollama..."
  ollama serve &>/dev/null &
  CLEANUP_PIDS="$CLEANUP_PIDS $!"
  sleep 3
  if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama started"
  else
    fail "Could not start Ollama. Start the Ollama app and re-run."
  fi
fi

# ── 5. Ensure a model is available ──────────────────────────────────
info "Checking models..."
EXISTING_MODEL=$(ollama list 2>/dev/null | awk 'NR>1 {print $1; exit}')
if [ -n "$EXISTING_MODEL" ]; then
  ok "Using existing model: $EXISTING_MODEL"
  MODEL="$EXISTING_MODEL"
else
  MODEL="${OPENJARVIS_MODEL:-qwen3.5:9b}"
  info "No models found — pulling '$MODEL'..."
  ollama pull "$MODEL"
  ok "Model '$MODEL' ready"
fi

# ── 6. Install Python dependencies ──────────────────────────────────
info "Installing Python dependencies..."
uv sync --extra server --quiet 2>/dev/null || uv sync --extra server
ok "Python dependencies installed"

# ── 7. Build Rust extension ──────────────────────────────────────────
info "Building Rust extension..."
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml --quiet 2>/dev/null \
  || uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
ok "Rust extension built"

# ── 8. Install frontend dependencies ────────────────────────────────
info "Installing frontend dependencies..."
(cd frontend && npm install --silent 2>/dev/null || npm install)
ok "Frontend dependencies installed"

# ── 9. Kill stale ports ──────────────────────────────────────────────
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

# ── 10. Start backend ────────────────────────────────────────────────
info "Starting backend API server on port 8000..."
uv run jarvis serve --port 8000 &>/dev/null &
CLEANUP_PIDS="$CLEANUP_PIDS $!"
sleep 3

if curl -sf http://localhost:8000/health &>/dev/null; then
  ok "Backend running at http://localhost:8000"
  # Write PID file so `jarvis status` can detect the server
  mkdir -p "$HOME/.openjarvis"
  echo "${CLEANUP_PIDS##* }" > "$HOME/.openjarvis/server.pid"
else
  warn "Backend may still be starting..."
fi

# ── 11. Start frontend ───────────────────────────────────────────────
info "Starting frontend dev server on port 5173..."
(cd frontend && npm run dev) &>/dev/null &
CLEANUP_PIDS="$CLEANUP_PIDS $!"
sleep 3
ok "Frontend running at http://localhost:5173"

# ── 12. Open browser ─────────────────────────────────────────────────
URL="http://localhost:5173"
info "Opening $URL ..."
case "$(uname -s)" in
  Darwin) open "$URL" ;;
  Linux)  xdg-open "$URL" 2>/dev/null || true ;;
  *)      true ;;
esac

echo ""
echo -e "${GREEN}${BOLD}  OpenJarvis is running!${NC}"
echo ""
echo "  Chat UI:  http://localhost:5173"
echo "  API:      http://localhost:8000"
echo "  Model:    $MODEL"
echo ""
echo "  Press Ctrl+C to stop all services."
echo ""

wait
