# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LoreKeeper is an AI-powered D&D campaign lore assistant. It fetches data from Obsidian Portal (OAuth1), stores it in Qdrant (vector DB), and exposes a streaming chat API backed by a pydantic-ai Agent with MCP toolsets.

## Development Commands

### Backend (Python 3.13, managed with uv)
```bash
cd backend
uv sync                               # Install dependencies from pyproject.toml
uv run python agent.py                # Interactive CLI chat
uv run python obsidian_portal/fetcher.py   # Fetch & ingest data from Obsidian Portal
uv run python qdrant_mcp_extended.py  # Start Qdrant MCP server (port 8000)
uv run python -m obsidian_portal.mcp_server  # Start Obsidian MCP server (port 8080)
uv run uvicorn api:app --host 0.0.0.0 --port 8001  # Start API server
```

### Frontend (React + TypeScript + Vite)
```bash
cd frontend
npm install
npm run dev    # Dev server at http://localhost:5173
npm run build  # Production build
```

### Docker (full stack)
```bash
docker-compose build
docker-compose up -d
```

### JetBrains Run Configurations (`.run/`)
Pre-configured run configurations for JetBrains IDEs (PyCharm/IntelliJ):

| Name | Type | What it runs |
|---|---|---|
| `agent` | Python | `backend/agent.py` — interactive CLI chat |
| `fetcher` | Python | `backend/obsidian_portal/fetcher.py` — ingest data |
| `qdrant_mcp_server` | Python | `backend/qdrant_mcp_extended.py` — Qdrant MCP (port 8000) |
| `obsidian_mcp_server` | Python | `backend/obsidian_portal/mcp_server.py` — Obsidian MCP (port 8080) |
| `api` | FastAPI | `backend/api.py` with `--reload --port 8001` |
| `dev` | npm | `frontend/` — `npm run dev` |
| `Compose Deployment` | Docker | `docker-compose.yml` |
| `Compose Deployment --build` | Docker | `docker-compose.yml --build` |

All Python configs load `backend/.env` for credentials (no secrets are embedded in the XML).

### Linting & Type Checking
```bash
cd backend
uv run ruff check --fix .
uv run ruff format .
uv run ty check
```
Pre-commit hooks run ruff + ty automatically on commit.

## Architecture

### Services
| Service | Port | Description |
|---|---|---|
| `qdrant-mcp` | 8000 | Extended Qdrant MCP server (`qdrant_mcp_extended.py`) |
| `obsidian-mcp` | 8080 | Obsidian Portal MCP server (`obsidian_portal/mcp_server.py`) |
| `api` | 8001 | FastAPI streaming chat server (`api.py`) |
| `frontend` | 5173 | React chat UI (Nginx in production) |
| `cron` | — | Supercronic container; hits `/api/fetch` at 3 AM daily |

### Data Flow
1. **Ingestion**: `obsidian_portal/fetcher.py` fetches wiki pages + characters via OAuth1, chunks them (`ingest.py`), embeds with `BAAI/bge-base-en-v1.5`, stores in Qdrant collection `lorekeeper_knowledge`
2. **Query**: Chat request → `api.py` → `agent.py` (pydantic-ai Agent) → MCP tools on qdrant-mcp/obsidian-mcp → LLM → SSE stream back to frontend

### Key Files
- **`backend/agent.py`** — pydantic-ai Agent; connects to both MCP toolsets, strips tool messages from history, has output validator with retry budget
- **`backend/api.py`** — FastAPI; `/api/chat` (SSE), `/api/fetch` (rate-limited 1/hr), `/api/fetch-status`, `/api/last-fetched`
- **`backend/qdrant_mcp_extended.py`** — Adds `qdrant-expand-context`, `qdrant-get-document-chunks`, `qdrant-get-chunk` on top of base mcp-server-qdrant
- **`backend/obsidian_portal/quest_parser.py`** — Parses/renders Obsidian Portal's accordion HTML for quests; must round-trip cleanly
- **`backend/config.py`** — All env var loading; single source of truth for credentials and model selection

### MCP Tool Notes
- `qdrant-find` results: metadata field is `"id"` (not `"document_id"`); `document_id` is the *parameter* to `qdrant-expand-context` and `qdrant-get-document-chunks`
- Wiki pages have `"title"` in metadata; characters have `"name"`

### Model Configuration
Default model is OpenAI (`gpt-5-mini-2025-08-07`). Groq (Llama 4 Scout 17B, token-sensitive) and OpenRouter are alternatives. Local Ollama is also supported. Model is selected via env vars in `config.py`.

### Logging
Root logger is set to WARNING; app logger to DEBUG. Noisy loggers that must be silenced: `httpcore`, `httpx`, `groq`, `mcp`, `asyncio`.

## Code Style
- Line length: 120 chars
- Ruff rules enforced: E, F, UP, PL, B, SIM, I, ANN, COM, C4, Q, N, RUF, C90
- Python 3.13+, type annotations required on all functions
