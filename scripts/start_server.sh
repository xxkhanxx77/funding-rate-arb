#!/bin/bash
# Multi-DEX Funding Bot Server Startup Script
# Boots the FastAPI application in app/server.py

echo "🚀 Starting AsterDex Funding Bot Server..."
echo "================================================"

# Check if required files exist
if [[ ! -f "app/server.py" ]]; then
    echo "❌ Error: app/server.py not found!"
    echo "Make sure you're in the project directory"
    exit 1
fi

# Load .env if present (preferred configuration)
if [[ -f ".env" ]]; then
    echo "📄 Loading environment from .env"
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    echo "ℹ️  .env not found; falling back to shell environment"
fi

# Optional config file remains supported for compatibility
if [[ -f "samples/bot_config.json" ]]; then
    echo "📁 samples/bot_config.json detected (legacy support)"
fi

# Ensure required credentials exist (use placeholders only if unset)
export ASTERDEX_API_KEY="${ASTERDEX_API_KEY}"
export ASTERDEX_API_SECRET="${ASTERDEX_API_SECRET}"

echo "✅ Environment variables ready"
echo ""

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 8000 is already in use. Stopping existing server..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    sleep 2
fi

echo "🎯 Starting server on http://0.0.0.0:8000"
echo "📊 API Documentation: http://0.0.0.0:8000/docs"
echo "📈 Live Status: http://0.0.0.0:8000/monitor/asterdex/simple"
echo ""
echo "Press Ctrl+C to stop the server"
echo "================================================"

# Start the server with uv (restrict reload watchers to new code paths)
uv run uvicorn app.server:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --reload-dir app \
  --reload-dir dexes \
  --reload-dir scripts \
  --reload-dir samples \
  --reload-include "*.py" \
  --reload-include "*.json" \
  --reload-exclude "legacy" \
  --reload-exclude "docs"
