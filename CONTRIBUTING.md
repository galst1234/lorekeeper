# Contributing to LoreKeeper

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js (for frontend)
- Docker (for full-stack runs)

## Setup

**Backend**
```bash
cd backend
uv sync
```

**Frontend**
```bash
cd frontend
npm install
```

**Pre-commit hooks** (run once from `backend/`)
```bash
cd backend
uv run pre-commit install
```

## Running locally

The easiest way to run the stack is via the JetBrains run configurations in `.run/`. Start services in this order:

1. `qdrant_mcp_server` — Qdrant MCP (port 8000)
2. `obsidian_mcp_server` — Obsidian Portal MCP (port 8080)
3. `api` — FastAPI server (port 8001)
4. `dev` — Vite frontend (port 5173)

Alternatively, run each service manually:

```bash
cd backend
uv run python qdrant_mcp_extended.py                        # Qdrant MCP (port 8000)
uv run python -m obsidian_portal.mcp_server                 # Obsidian MCP (port 8080)
uv run uvicorn api:app --host 0.0.0.0 --port 8001 --reload  # API (port 8001)
```

```bash
cd frontend
npm run dev  # Frontend (port 5173)
```

Credentials go in `backend/.env` (gitignored). Copy `backend/.env.example` as a starting point and fill in your values. Never commit secrets.

## Code quality

Pre-commit hooks run automatically on `git commit` and enforce:
- `ruff check --fix` — linting
- `ruff format` — formatting
- `ty check` — type checking

To run manually:
```bash
cd backend
uv run ruff check --fix . && uv run ruff format . && uv run ty check
```

Or equivalently, run all hooks at once:
```bash
cd backend
uv run pre-commit run --all-files
```

CI (GitHub Actions) runs the same checks on all PRs that touch `backend/`.

There is no automated test suite — linting and type checking are the current quality gates.

## Making changes

- **Backend**: changes must pass ruff and ty before merging.
- **Frontend**: no CI currently; run `npm run build` to verify the build is clean before opening a PR.
