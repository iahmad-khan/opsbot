# Contributing to OpsBot

Thank you for contributing. This document covers the development workflow, project structure, and conventions you need to know before opening a pull request.

---

## Table of Contents

- [Getting started](#getting-started)
- [Project structure](#project-structure)
- [Development workflow](#development-workflow)
- [Backend (Python)](#backend-python)
- [MCP servers (TypeScript)](#mcp-servers-typescript)
- [Frontend (Next.js)](#frontend-nextjs)
- [Tests](#tests)
- [Linting and type-checking](#linting-and-type-checking)
- [Adding a new tool](#adding-a-new-tool)
- [Adding a new MCP server](#adding-a-new-mcp-server)
- [RBAC and risk levels](#rbac-and-risk-levels)
- [Submitting a pull request](#submitting-a-pull-request)

---

## Getting started

**Prerequisites:** Docker, Python 3.12+, Node.js 20+, `uv` (`pip install uv`).

```bash
# 1. Clone
git clone <repo-url>
cd opsbot

# 2. Copy env template and fill in credentials
cp .env.example .env

# 3. Start the full local stack
docker compose -f docker/docker-compose.yml up -d

# 4. Install backend dev dependencies
cd backend
uv pip install -e ".[dev]"

# 5. Run database migrations
alembic upgrade head

# 6. Start the backend (outside Docker, for fast iteration)
uvicorn opsbot.api.main:create_app --factory --reload --port 8000
```

The API will be at `http://localhost:8000`. Swagger docs are at `http://localhost:8000/docs`.

---

## Project structure

```
opsbot/
├── backend/                    # FastAPI + Celery backend (Python 3.12)
│   ├── src/opsbot/
│   │   ├── agent/              # LLM ReAct loop, memory, router
│   │   ├── api/                # FastAPI routes (tasks, approvals, health, sre)
│   │   ├── config/             # Pydantic settings (env-driven)
│   │   ├── integrations/       # Slack Bolt handlers, GitHub client
│   │   ├── mcp/                # MCP server manager and stdio client
│   │   ├── models/             # SQLAlchemy ORM models + Pydantic schemas
│   │   ├── sre/                # SLO analyzer, RCA engine, fix generator
│   │   ├── tasks/              # Celery app and async task definitions
│   │   ├── tools/              # Tool definitions and risk registry
│   │   └── workflows/          # Approval state machine, Slack notifications
│   ├── alembic/                # Database migrations
│   └── tests/
├── mcp-servers/                # Custom TypeScript MCP servers
│   ├── argocd-mcp/
│   ├── prometheus-mcp/
│   ├── datadog-mcp/
│   ├── opensearch-mcp/
│   ├── gitlab-mcp/
│   ├── bitbucket-mcp/
│   ├── jira-mcp/
│   └── confluence-mcp/
├── frontend/                   # Next.js 14 web dashboard
├── charts/opsbot/              # Helm chart
├── docker/                     # docker-compose for local dev
└── .github/workflows/          # CI (lint + test) and CD (release)
```

---

## Development workflow

Work on feature branches off `main`.

```
main        — production-ready; protected; requires passing CI + review
develop     — integration branch (optional; use if coordinating multiple PRs)
feature/*   — your work
fix/*       — bug fixes
```

All PRs must pass CI before merging. CI runs automatically on push and PR.

---

## Backend (Python)

The backend is managed with [`uv`](https://github.com/astral-sh/uv). All dependencies are declared in `backend/pyproject.toml`.

```bash
cd backend

# Add a dependency
uv pip install --system <package>
# Then manually add it to pyproject.toml [project.dependencies]

# Run the dev server
uvicorn opsbot.api.main:create_app --factory --reload

# Run the Celery worker
celery -A opsbot.tasks.celery_app worker --loglevel=info

# Run the Celery beat scheduler (for periodic tasks)
celery -A opsbot.tasks.celery_app beat --loglevel=info
```

**Key conventions:**

- All async — use `async def` throughout; avoid blocking I/O in request handlers.
- Structured logging via `structlog`. Log with `log.info("event.name", key=value)`, not f-strings.
- Settings via `get_settings()` — never hardcode URLs, tokens, or secrets.
- DB access via SQLAlchemy async sessions — always use `await db.get(...)` / `await db.execute(...)`.
- No comments explaining *what* the code does. Add a comment only when the *why* is non-obvious.

**Database migrations:**

```bash
# After changing a model in models/db.py, generate a migration
alembic revision --autogenerate -m "describe_the_change"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```

---

## MCP servers (TypeScript)

Each custom MCP server lives under `mcp-servers/<name>-mcp/`. They are stdio-based processes compiled to `dist/index.js`.

```bash
cd mcp-servers/argocd-mcp   # or any other server

# Install dependencies
npm install

# Build
npm run build

# Type-check without emitting
npx tsc --noEmit
```

**Key conventions:**

- Use `"module": "NodeNext"` and `"moduleResolution": "NodeNext"` in `tsconfig.json`.
- Tool arguments arrive as `Record<string, unknown> | undefined`. Always cast before use:
  ```typescript
  const name = String(args?.name || "");
  const count = Number(args?.count || 10);
  ```
- Use `axios` for HTTP calls — do not import cloud-vendor SDKs unless strictly necessary.
- Every new tool must be registered with `server.setRequestHandler(CallToolRequestSchema, ...)` and listed in `ListToolsRequestSchema`.

---

## Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
npm run build
npm run lint
```

The frontend is a Next.js 14 App Router application using shadcn/ui and Tailwind CSS. It calls the backend via server components — API tokens never reach the browser.

---

## Tests

All tests live in `backend/tests/`. Tests use `pytest` with `pytest-asyncio` in auto mode.

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run a single file
pytest tests/test_approval_workflow.py -v

# Run with coverage
pytest tests/ --cov=opsbot --cov-report=term-missing
```

**Test conventions:**

- Unit tests mock all I/O — no real DB, Redis, or network calls.
- `session.add()` and `pipeline.zadd/zcard/etc.` are synchronous in SQLAlchemy/redis-py — mock them with `MagicMock`, not `AsyncMock`.
- `pipeline()` itself is synchronous; only `pipeline.execute()` is async.
- New features must include tests for the happy path and the primary failure modes.
- Do not test framework behavior (e.g. FastAPI request parsing). Test your own logic.

---

## Linting and type-checking

```bash
cd backend

# Lint (ruff)
ruff check src/ tests/

# Auto-fix safe issues
ruff check src/ tests/ --fix

# Type-check (mypy)
mypy src/opsbot/ --ignore-missing-imports
```

CI will fail if `ruff check` exits non-zero. Run it before pushing.

The active ruff rules are `E, F, I, N, UP, B, SIM` (see `pyproject.toml`). `B008` is suppressed — FastAPI `Depends()` in function signatures is idiomatic.

---

## Adding a new tool

Tools are operations the agent can call. Follow these four steps:

### 1. Implement the tool in an MCP server

If the operation talks to an external system (K8s, ArgoCD, GitHub, etc.), add it as a new `case` in the relevant MCP server's `CallToolRequestSchema` handler, and list it in `ListToolsRequestSchema`.

If it's a Python-side operation (release manager, SRE analysis, etc.), add it to the relevant file under `backend/src/opsbot/tools/`.

### 2. Register the risk level

In `backend/src/opsbot/tools/registry.py`, add an entry to `_TOOL_RISK_MAP`:

```python
"your_tool_name": RiskLevel.READ,    # auto-execute, no notification
"your_tool_name": RiskLevel.WRITE,   # execute + post Slack notification
"your_tool_name": RiskLevel.DESTRUCTIVE,  # require named approver
```

**Choose carefully.** The risk level determines whether the operation runs automatically, requires notification, or requires an approval click.

| Level | Behavior | Examples |
|---|---|---|
| `READ` | Auto-execute silently | Get logs, list pods, query metrics |
| `WRITE` | Execute + Slack notification | Restart pod, scale replicas, add repo user |
| `DESTRUCTIVE` | Block until a named approver clicks Approve | Deploy tag, rollback, terraform apply |

### 3. Add a human-readable description (DESTRUCTIVE only)

Also in `registry.py`, add an entry to `_HUMAN_DESCRIPTIONS` so the approval message is readable:

```python
"your_tool_name": "Short description of what this does with {key_arg}",
```

### 4. Write tests

Add at least a happy-path test and a permission-denied test in `backend/tests/`.

---

## Adding a new MCP server

1. Copy an existing server as a template: `cp -r mcp-servers/argocd-mcp mcp-servers/yourservice-mcp`
2. Update `package.json` — name, description.
3. Update `src/index.ts` — replace tools and HTTP calls.
4. Build and verify: `npm run build && npx tsc --noEmit`
5. Add the server config to `backend/src/opsbot/mcp/servers.py`:
   ```python
   MCPServerConfig(
       name="yourservice",
       command=s.mcp_yourservice_command,
       env={"YOURSERVICE_URL": s.yourservice_url, "YOURSERVICE_TOKEN": s.yourservice_token},
   )
   ```
6. Add the command setting to `backend/src/opsbot/config/settings.py`:
   ```python
   mcp_yourservice_command: str = "node /app/mcp-servers/yourservice-mcp/dist/index.js"
   ```
7. Register the new tool names in `backend/src/opsbot/tools/registry.py`.
8. Add the npm build step to `.github/workflows/ci.yml`.

---

## RBAC and risk levels

OpsBot enforces role-based access control on every tool call.

| Role | Allowed operations |
|---|---|
| `readonly` | READ tools only |
| `developer` | READ + WRITE |
| `sre` | READ + WRITE + can approve DESTRUCTIVE |
| `admin` | All operations + can approve DESTRUCTIVE |

Roles are stored in the `users` table and mapped to Slack user IDs. Assign roles via:

```
/opsbot rbac add @user sre
```

The approval RBAC check is enforced in `backend/src/opsbot/workflows/approval.py` (`can_approve`) and in the agent engine (`engine.py`) for WRITE operations. Both must stay consistent — if you add a new role, update both.

---

## Submitting a pull request

1. Branch from `main`: `git checkout -b feature/your-feature`
2. Make your changes, following the conventions above.
3. Run the full local check:
   ```bash
   cd backend
   ruff check src/ tests/ --fix
   pytest tests/ -v
   mypy src/opsbot/ --ignore-missing-imports
   ```
   For MCP servers: `npm run build && npx tsc --noEmit`
4. Write a clear PR description — what changed and why, not just a list of files.
5. Reference any related issue.
6. Request review from a maintainer.

CI runs automatically. PRs cannot merge with failing lint, failing tests, or unresolved review threads.

**Commit style:** `<type>: <short summary>` — e.g. `feat: add gitlab pipeline trigger tool`, `fix: rate limiter fails open on redis timeout`, `chore: update dependencies`. Keep commits focused; one logical change per commit.
