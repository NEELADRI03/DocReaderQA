# DocQA

Upload PDFs and ask questions about them. Answers cite the pages they come from. The LLM and embeddings run locally through Ollama.

```
docqa-backend/    FastAPI API and ARQ worker (Python 3.12), one shared image
docqa-frontend/   React + TypeScript + Vite
docs/             Architecture, backlog and story guides
scripts/          Host-side helpers (Ollama setup)
docker-compose.yml
.env.example      Every environment variable, documented
```

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running (on Windows, with the WSL 2 backend)
- Git
- [Ollama](https://ollama.com/) on the host machine (not in Docker). See [Ollama](#ollama) below.

You only need Python 3.12 and Node 22+ if you want to run the backend or frontend outside Docker.

## Getting started

1. Create your local `.env` from the template:

   ```powershell
   cp .env.example .env
   ```

   The defaults work for local development. `.env` is git-ignored, so never commit it.

2. Build and start the whole stack:

   ```powershell
   docker compose up --build
   ```

   The first build takes a few minutes. Add `-d` to run it in the background.

3. Check that all five services are up, and that `postgres` and `redis` show as `healthy`:

   ```powershell
   docker compose ps
   ```

## Ollama

The LLM and embedding models run in Ollama on the host. Ollama is installed on Windows, not in Docker. The containers reach it at `OLLAMA_BASE_URL` (`http://host.docker.internal:11434`).

Pull the models named in `.env` and check that they work:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-ollama.ps1
```

Re-run it after you change `LLM_MODEL` or `EMBEDDING_MODEL`.

### RAM needs

| Model | Role | Download | RAM while loaded |
|---|---|---|---|
| `qwen3:8b` (default) | Answers | ~5.2 GB | ~6–8 GB |
| `qwen3:4b` | Lighter alternative | ~2.5 GB | ~3–4 GB |
| `gpt-oss:20b` | Stronger alternative | ~14 GB | ~14–16 GB |
| `nomic-embed-text` | Embeddings (768-d) | ~0.3 GB | < 1 GB |

- **16 GB RAM**: works with `qwen3:8b`. Close other heavy apps while it runs.
- **32 GB RAM**, or a GPU with 16 GB+ VRAM: needed for `gpt-oss:20b`.
- Ollama shares RAM with Docker Desktop (the stack uses about 1–2 GB).
- Without a supported GPU (NVIDIA, or recent AMD), models run on the CPU. That works, but expect a few tokens per second.
- If you change `EMBEDDING_MODEL`, set `EMBEDDING_DIM` to match. Documents embedded with the old model must be re-embedded.

## Services

| Service | URL / port | What it is |
|---|---|---|
| `frontend` | http://localhost:5173 | Vite dev server with hot reload |
| `api` | http://localhost:8000/api/v1/health | FastAPI. It reloads automatically when you edit code. |
| | http://localhost:8000/docs | Interactive API docs |
| `worker` | (no port) | ARQ background worker. See its output with `docker compose logs -f worker`. |
| `postgres` | `localhost:5432` | PostgreSQL 16 with pgvector (user, password and database: `docqa`) |
| `redis` | `localhost:6379` | Redis 7, used as the job queue |

The backend `app/` folder and the whole frontend folder are mounted into the containers, so code changes take effect without a rebuild. After you change `requirements.txt` or `package.json`, rebuild with `docker compose up --build`.

## Stopping and resetting

```powershell
docker compose down      # stop and remove containers; database data is kept
docker compose down -v   # also delete the volumes, which WIPES THE DATABASE
```

Uploaded files are stored in `./storage` on the host, and `down -v` does not touch them. Delete that folder by hand for a full reset.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `port is already allocated` | Another process is using 5432, 6379, 8000 or 5173. Stop it, or change the left-hand port in `docker-compose.yml`. |
| Frontend doesn't hot-reload | `server.watch.usePolling` must stay `true` in `docqa-frontend/vite.config.ts`. |
| Frontend fails with missing packages after a dependency change | Run `docker compose up --build --renew-anon-volumes frontend`. |
| `api`/`worker` wait forever | Run `docker compose logs postgres redis` and check that the healthchecks pass. |
| `api`/`worker` can't reach Ollama | Check `Invoke-RestMethod http://localhost:11434/api/version` on the host first; see the S0.1.2 guide in `docs/`. |
