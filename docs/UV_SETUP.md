# UV Python Environment Setup

This project uses [UV](https://docs.astral.sh/uv/) for fast Python package management and environment handling.

## Quick Start

1. **Install UV** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # or with homebrew: brew install uv
   ```

2. **Create `.env` and sync dependencies**:
  ```bash
  cat <<'ENV' > .env
ASTERDEX_API_KEY=your_api_key
ASTERDEX_API_SECRET=your_api_secret
FUNDING_DEX=asterdex
FUNDING_CAPITAL=100
FUNDING_BATCH_QUOTE=10
FUNDING_MODE=buy_spot_short_futures
FUNDING_MONITOR_INTERVAL=60
FUNDING_LOG_LEVEL=INFO
ENV

  uv sync  # Creates .venv and installs dependencies
  ```

3. **Run the server**:
   ```bash
   make run-server
   # or directly: uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
   ```

## Available Commands

Use the Makefile for common tasks:

```bash
make help              # Show all available commands
make install           # Install production dependencies only
make dev-install       # Install with development dependencies
make run-server        # Start FastAPI server with hot reload
make run-bot           # Show bot CLI help
make test              # Run tests
make lint              # Check code quality
make format            # Format code with black and ruff
make clean             # Clean cache files
```

## Manual Commands

**Install dependencies**:
```bash
uv sync                # Install all dependencies
uv sync --no-dev       # Production dependencies only
```

**Run commands in the environment**:
```bash
uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload  # Run server
uv run python legacy/funding_bot.py --help  # Bot CLI
uv run pytest                        # Run tests
```

**Add new dependencies**:
```bash
uv add fastapi                        # Add to main dependencies
uv add --dev pytest                  # Add to dev dependencies
```

## Environment

- Python version: 3.11 (specified in `.python-version`)
- Virtual environment: `.venv/` (auto-created)
- Dependencies: Defined in `pyproject.toml`

## API Usage

Once the server is running:

- **Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health
- **Examples**: http://localhost:8000/docs/examples

Example API call:
```bash
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{
    "capital": "1000",
    "spot_symbol": "ASTERUSDT",
    "batch_quote": "100",
    "mode": "buy_spot_short_futures"
  }'
```
