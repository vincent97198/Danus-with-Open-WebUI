# Danus Local Research Workspace

A local web workspace combining Open WebUI chat, Danus math projects, paper search, and per-project search controls. The default entry point is **http://127.0.0.1:3001/**.

See [the full Traditional Chinese README](README.md) for features, troubleshooting, data management and publishing instructions.

## Requirements

- Docker Desktop with Linux containers, or Docker Engine with Compose v2.
- An **already running local model** with `/health`, `/v1/models`, and OpenAI-compatible `/v1/chat/completions`, including streaming and tool calls.
- A model context window consistent with the included 65,536-token bridge configuration.
- Internet access for first-time dependency installation and enabled searches.

The package does not include model weights, a GPU model Dockerfile, user projects, chat history, runtime caches or private credentials. It does not start your model container.

## Quick start

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare.ps1
notepad .env
# Set MODEL_NAME to the exact ID from your model's /v1/models endpoint.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Linux / macOS:

```bash
bash scripts/prepare.sh
# Edit .env with your model address and ID.
bash scripts/start.sh
```

Example `.env`:

```dotenv
MODEL_BASE_URL=http://host.docker.internal:8080
MODEL_NAME=your-actual-model-id
COMPOSE_PROJECT_NAME=danus-webui
```

The base URL must be reachable **from the containers**; do not append `/v1` or a trailing slash. On Linux, ensure the model listens on an interface accessible from Docker, or connect both services through a shared Docker network.

The internal `local-model` alias is intentionally independent of your external model ID. The current model adapter assumes a local endpoint without API authentication.

Manual startup, after preparing the three local `.env` files:

```bash
docker compose up -d --build
# Wait for http://127.0.0.1:3001/api/search/settings and :3000/health.
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
```

The copied integration Dockerfile is unchanged. No Dockerfile editing is normally needed. Ports 3000, 3001 and 7860 must be free.

## Use

- **Chat**: choose the local research assistant; attach PDFs for questions.
- **Projects**: create a problem, start/stop it, inspect progress, results, sources and the fact graph.
- **Search settings**: independently configure chat and Danus defaults; projects may inherit or override them.
- **Sources**: SearXNG web engines, Wikipedia, DuckDuckGo Instant Answers, arXiv, Crossref, IACR ePrint and Matlas. No paid search key is required; upstream availability and rate limits still apply.
- **IACR**: searches official OAI-PMH metadata and abstracts in a local index. It does not scrape ePrint search pages or download its PDFs automatically.

Search preferences gate integrated tools, not arbitrary container networking. In-flight requests may finish. Danus verification is model-based, not a formal proof guarantee.

## Restart and data

Start Docker and your model, then run `docker compose up -d`. To continue a stopped Danus project, use its Continue button. `docker compose down` preserves the named volumes: `danus-runtime` and `open-webui-data`, prefixed by your Compose project name.

## Publish the source

The modified Danus snapshot is included; there is no submodule to fetch. Preserve all licenses and [third-party notices](THIRD_PARTY_NOTICES.md). Real `.env` files and runtime data are ignored by Git. The optional Git bundle can be restored with `git clone /path/to/danus-webui-v0.1.0.bundle danus-webui`.

This is a local, single-user deployment with loopback ports and Open WebUI authentication disabled. Public hosting requires a separate authentication, authorization and TLS design. Uploading the source repository alone does not deploy the application.

License: [Apache-2.0](LICENSE), with third-party components under their respective licenses.
