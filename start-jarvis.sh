#!/bin/zsh

# OpenJarvis Startup Script
# Starts llama-server, the Jarvis backend, and the frontend

MODEL="${HOME}/models/Qwen_Qwen3-4B-Q4_K_M.gguf"
JARVIS_DIR="${HOME}/OpenJarvis"
LLAMA_PORT=8080
BACKEND_PORT=8000
FRONTEND_PORT=5173
THREADS=8
CONTEXT=4096

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "${GREEN}Starting OpenJarvis...${NC}"

# --- 1. Start llama-server ---
echo "${YELLOW}[1/3] Starting llama-server...${NC}"
llama-server -m "$MODEL" -c $CONTEXT -t $THREADS > /tmp/llama-server.log 2>&1 &
LLAMA_PID=$!

# Wait for llama-server to be ready
echo "  Waiting for model to load (this may take a moment)..."
for i in {1..60}; do
  if curl -s "http://127.0.0.1:${LLAMA_PORT}/health" | grep -q "ok"; then
    echo "  ${GREEN}✓ llama-server ready (pid $LLAMA_PID)${NC}"
    break
  fi
  if ! kill -0 $LLAMA_PID 2>/dev/null; then
    echo "  ${RED}✗ llama-server crashed. Check /tmp/llama-server.log${NC}"
    exit 1
  fi
  sleep 2
done

# --- 2. Start Jarvis backend ---
echo "${YELLOW}[2/3] Starting Jarvis backend...${NC}"
cd "$JARVIS_DIR"
uv run jarvis serve --port $BACKEND_PORT > /tmp/jarvis-backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..30}; do
  if curl -s "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
    echo "  ${GREEN}✓ Jarvis backend ready (pid $BACKEND_PID)${NC}"
    break
  fi
  if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "  ${RED}✗ Jarvis backend crashed. Check /tmp/jarvis-backend.log${NC}"
    kill $LLAMA_PID 2>/dev/null
    exit 1
  fi
  sleep 1
done

# --- 3. Start frontend ---
echo "${YELLOW}[3/3] Starting frontend...${NC}"
cd "$JARVIS_DIR/frontend"
npm run dev > /tmp/jarvis-frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 3

echo ""
echo "${GREEN}✓ OpenJarvis is running!${NC}"
echo "  Browser UI: http://localhost:${FRONTEND_PORT}"
echo "  Backend:    http://localhost:${BACKEND_PORT}"
echo "  llama-server: http://localhost:${LLAMA_PORT}"
echo ""
echo "  Logs: /tmp/llama-server.log | /tmp/jarvis-backend.log | /tmp/jarvis-frontend.log"
echo ""
echo "Press Ctrl+C to stop everything."

# Open browser
open "http://localhost:${FRONTEND_PORT}"

# Trap Ctrl+C and kill all processes
cleanup() {
  echo ""
  echo "${YELLOW}Shutting down OpenJarvis...${NC}"
  kill $FRONTEND_PID 2>/dev/null
  kill $BACKEND_PID 2>/dev/null
  kill $LLAMA_PID 2>/dev/null
  echo "${GREEN}Done.${NC}"
  exit 0
}
trap cleanup INT TERM

# Keep script alive
wait
