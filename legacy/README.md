# Legacy Utilities

This folder contains the original single-DEX scripts, CLI helpers, and strategy experiments that preceded the new modular architecture in `app/` and `dexes/`.

They remain available for reference and ad-hoc usage, but they are no longer loaded by the FastAPI application. Prefer the endpoints exposed by `app/server.py` for production workloads.

Run any script with the module path, for example:

```bash
uv run python -m legacy.small_capital_strategy --help
```
