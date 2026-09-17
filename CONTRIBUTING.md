# Contributing

Contributions are welcome. Please open an issue to discuss changes that are
larger than a small fix, and keep pull requests focused on a single concern.

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Run the quality gates before submitting:

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
mypy src
```

## Important boundaries

- This project does **not** and will **not** ship carrier/Datalock unlock
  features. Pull requests for lock removal are out of scope.
- Every user-facing error is human-readable. No raw tokens, serial data, or
  HTTP bodies are ever logged.
- Formatting is enforced with `ruff format`; run it before pushing.