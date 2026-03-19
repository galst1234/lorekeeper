# Contributing to LoreKeeper

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js (for frontend)
- Docker (to run Qdrant and for full-stack deployments)

## Running locally

**1. Start Qdrant**

Qdrant must be running before the fetcher or any backend services can start (the Docker Compose stack does not include a Qdrant container):
```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

**2. Configure credentials**

Copy the example env file and fill in your values — never commit secrets:
```bash
cp backend/.env.example backend/.env
```

**3. Install dependencies**

```bash
cd backend && uv sync
cd frontend && npm install
```

Install pre-commit hooks (run once after cloning):
```bash
cd backend && uv run pre-commit install
```

**4. Populate Qdrant**

Run the `fetcher` JetBrains run configuration, or manually:
```bash
cd backend
uv run python obsidian_portal/fetcher.py
```
This fetches all wiki pages and characters from Obsidian Portal, chunks and embeds them, and stores them in Qdrant. On first run it will prompt you through the Obsidian Portal OAuth1 flow and store the resulting access tokens automatically. Subsequent runs are incremental.

**5. Start services**

The easiest way is via the JetBrains run configurations in `.run/`. Start in this order:

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
