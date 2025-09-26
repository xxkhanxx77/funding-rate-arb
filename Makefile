.PHONY: help install dev-install run-server run-bot test lint format clean

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	uv sync --no-dev

dev-install: ## Install development dependencies
	uv sync

run-server: ## Run the FastAPI server
	uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload

run-bot: ## Run the bot directly (CLI mode)
	uv run python legacy/funding_bot.py --help

test: ## Run tests
	uv run pytest -v

lint: ## Run linting
	uv run ruff check .
	uv run mypy .

format: ## Format code
	uv run black .
	uv run ruff --fix .

clean: ## Clean cache and temporary files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
