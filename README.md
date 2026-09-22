# Danus Local Research Workspace

A local web workspace combining **Open WebUI chat, Danus mathematical reasoning, PDF conversations, and web and paper search**.

Connect an existing local model and open **[http://127.0.0.1:3001/](http://127.0.0.1:3001/)**.

The interface, default research assistant, and documentation use English. Project names and user content can use any language.

[Quick start](README.en.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Changelog](CHANGELOG.md)

## Features

- Chat with your local model and upload PDFs for questions.
- Create mathematical research projects and view intermediate progress.
- Read full-width results, proofs, literature references, and fact dependencies.
- Stop, rename, duplicate, and export projects.
- Move projects to Trash, restore them, or permanently delete them. Permanent deletion in Trash takes effect immediately without another confirmation.
- Configure online search separately for chat and Danus, with per-project overrides.
- Search arXiv, Crossref, IACR ePrint, and Matlas.
- Read arXiv HTML or extracted PDF text.
- Use the included TeX Live environment with Danus authoring workflows.

This source package includes the portal, supporting backend, and integration settings. Model weights, user projects, chat history, document caches, and private credentials are excluded.

## 1. Requirements and Model Startup

You need:

1. Docker Desktop with Linux containers on Windows/macOS, or Docker Engine with Compose v2 on Linux.
2. An existing local model service reachable from Docker containers.
3. Internet access for initial dependency downloads and enabled searches.
4. Available host ports **3000**, **3001**, and **7860**.
5. PowerShell on Windows, or Bash and curl on Linux/macOS.

The integration expects a llama.cpp/KVMem-style model service providing:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Model service health |
| `GET /v1/models` | Available model IDs |
| `POST /v1/chat/completions` | Chat, streaming, and tool calls |

Danus needs reliable tool calling and a long context window. The included bridge uses **65,536 tokens**; configure the model server accordingly. Speed, memory requirements, and reasoning quality depend on your model and hardware.

Start your model using Docker Desktop or its normal startup method. For an existing container:

```bash
docker start YOUR_MODEL_CONTAINER
```

Replace `YOUR_MODEL_CONTAINER` with your container name. Model installation and startup are managed separately from this package.

The current adapter assumes a local model endpoint without API authentication. It does not automatically forward a private model API key.

## 2. Prepare Local Configuration

Open a terminal in the repository root.

### Windows PowerShell

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare.ps1
notepad .env
```

### Linux / macOS

```bash
bash scripts/prepare.sh
# Open .env in your preferred text editor.
```

The script copies missing templates and preserves existing settings. It creates:

```text
.env
danus-setup/codex-danus.env
danus-setup/danus.env
```

Edit `.env`:

```dotenv
MODEL_BASE_URL=http://host.docker.internal:8080
MODEL_NAME=your-actual-model-id
COMPOSE_PROJECT_NAME=danus-webui
```

- **MODEL_BASE_URL:** Must be reachable from the containers. Omit `/v1` and any trailing slash.
- **MODEL_NAME:** The exact `id` returned by `/v1/models`, not a local file path.
- **COMPOSE_PROJECT_NAME:** Use a distinct name for each installation.

On Docker Desktop, `host.docker.internal` generally reaches a service published on the host. On Linux, ensure the model listens on an interface accessible from Docker. Services sharing a Docker network can also use a resolvable container or service name.

To find a model ID on host port 8080:

```powershell
(Invoke-RestMethod http://127.0.0.1:8080/v1/models).data.id
```

Or:

```bash
curl http://127.0.0.1:8080/v1/models
```

The name `local-model` in the Danus bridge is an internal alias. Keep it as supplied; `MODEL_NAME` selects the actual model.

## 3. Start the Workspace

### Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

After configuring `.env`, you can also double-click `webui/start.bat`.

### Linux / macOS

```bash
bash scripts/start.sh
```

The script builds and starts the services, waits for readiness, and configures **Local Research Assistant** in Open WebUI. It then opens or prints the workspace URL.

The integration Dockerfile is preserved from the original setup. Normal installation does not require editing it.

Initial startup downloads Node.js, Python dependencies, and the container's Codex CLI. The supplied API bridge connects to your local model without a ChatGPT login. Runtime dependencies are kept in a Docker volume.

### Manual startup

After preparing the three local configuration files:

```bash
docker compose up -d --build
docker compose ps
```

Wait for [the workspace API](http://127.0.0.1:3001/api/search/settings) and [Open WebUI health](http://127.0.0.1:3000/health), then run:

```bash
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
```

### Open the interface

| Interface | Address |
|---|---|
| Unified workspace | [http://127.0.0.1:3001/](http://127.0.0.1:3001/) |
| Standalone Open WebUI | [http://127.0.0.1:3000/](http://127.0.0.1:3000/) |
| Search settings | [http://127.0.0.1:3001/#settings](http://127.0.0.1:3001/#settings) |
| Backend and legacy controls | [http://127.0.0.1:7860/](http://127.0.0.1:7860/) |

The default ports must be free. A different Compose project name does not prevent port conflicts with another installation.

### Update an existing installation to English

Run the startup script again after updating the source. It rebuilds the application and refreshes the package-managed research assistant's name, instructions, description, and suggested prompts.

The assistant now responds in English by default and can use another language when requested. Existing chats, project titles, and research content retain their original text.

Open WebUI defaults to English for new sessions. If a browser or account already has a saved language preference, select **English (US)** in Open WebUI's language settings and refresh the page.

## 4. Daily Use

### Chat and PDFs

Open **Chat**, select **Local Research Assistant**, and send a message. Use the attachment button to upload a PDF.

The search toggle above the chat controls whether the integrated tools may retrieve external information.

PDF extraction can lose formulas, symbols, or layout. Check important expressions against the original document.

### Danus projects

1. Click **＋** and enter a project name and mathematical problem.
2. Choose whether to use Danus search defaults, enable search, or use existing information.
3. Select **Create and start**.
4. Open **Progress** for worker activity, **Results** for saved statements and proofs, **Literature** for retrieved sources, and **Fact graph** for dependencies.
5. Use **Stop now** to end the current worker while keeping saved data.
6. Use **Continue reasoning** to resume a stopped project.

Danus verification is performed by a model. Important conclusions still require mathematical review; acceptance by Danus is not a formal proof guarantee.

The portal offers a common workflow with one worker. See the [Danus operating guide](danus-setup/Danus/docs/operating-guide.md) for main-agent coordination, multiple workers, and paper authoring.

### Search sources and controls

| Category | Included sources |
|---|---|
| General web search through SearXNG | Bing, Brave, Google, DuckDuckGo |
| Direct information APIs | Wikipedia, DuckDuckGo Instant Answers |
| Papers and mathematical literature | arXiv, Crossref, IACR ePrint, Matlas |

The included integrations require no paid search API keys. Providers may impose rate limits, return CAPTCHAs, or become unavailable. DuckDuckGo Instant Answers primarily supplies summaries and definitions.

Use **Test selected sources** to check current availability. Defaults include Bing, Wikipedia, and the paper sources.

Chat and Danus have separate preferences. Projects can inherit or override the Danus defaults; verification subprocesses inherit project preferences too.

Disabling search blocks new calls to the integrated search, paper-reading, and theorem-search tools. Requests already in progress may finish. These preferences control the tools; worker containers retain network access, and agent instructions require respecting the settings.

Model inference runs through your configured model service. Enabled searches send queries to the selected external providers.

### IACR ePrint and paper reading

ePrint search uses a local index of official OAI-PMH metadata, covering titles, authors, abstracts, and categories. Initial use may require index preparation. Refreshes occur on demand, at most once per day.

These results are metadata and abstracts. The integration does not automatically download ePrint PDFs subject to the site's automated-access restrictions. Obtain a PDF from its source and upload it to chat when needed.

arXiv reading prefers HTML that preserves LaTeX, with extracted PDF text as a fallback.

### LaTeX and reports

The image includes TeX Live. Danus main-agent tools provide the paper-writing workflows.

A separately installed Tectonic runtime is not bundled. Danus human-summary PDF generation also requires Chromium, which this package does not install automatically.

## 5. Restart, Stop, and Preserve Data

After rebooting:

1. Start Docker Desktop or Docker Engine.
2. Start your local model.
3. From the repository directory, run:

```bash
docker compose up -d
```

4. Open the workspace.
5. Resume any projects you want to continue.

Services may restart automatically according to their Docker restart policies.

To stop this workspace while preserving its volumes:

```bash
docker compose down
```

| Volume | Contents |
|---|---|
| `danus-runtime` | Projects, results, trash, search preferences, literature cache, and runtime dependencies |
| `open-webui-data` | Chats, attachments, and Open WebUI settings |

Actual volume names use the `COMPOSE_PROJECT_NAME` prefix. Back up both volumes to preserve your data. They are separate from Git and are not included when sharing source code.

Deleting a volume deletes the data stored in it.

## 6. Troubleshooting

### Model disconnected

Check the model service, `MODEL_BASE_URL`, and `MODEL_NAME`. Inside a container, `127.0.0.1` refers to that container, not your host.

### Missing configuration during Docker COPY

Run `scripts/prepare.ps1` or `scripts/prepare.sh` before building. The real configuration files are excluded from Git and must be created from the templates.

### Chat works but research tools are missing

Enable search, refresh, create a new chat, and select **Local Research Assistant**. You can rerun:

```bash
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
```

### The first ePrint search has no results

The metadata index may still be initializing. Try again later, or prepare it explicitly:

```bash
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python -m danus.integrations.iacr
```

### Other startup issues

```bash
docker compose ps
docker compose logs --tail 80
```

### Changing ports

Update the Compose port mappings, chat URLs in `webui/portal.js` and `webui/portal.html`, and readiness/opening URLs in `scripts/start.*` together.

## 7. Publish the Source

The modified Danus source snapshot is included; no submodule initialization is required.

Preserve [LICENSE](LICENSE), [NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and all bundled license files.

### From a ZIP

In the extracted repository directory:

```bash
git init -b main
git add .
git commit -m "Initial release"
git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git
git push -u origin main
```

Replace the URL with your own empty repository. If Git is already initialized, use its existing branch and configure the remote as appropriate.

### From a Git bundle

```bash
git clone /path/to/danus-webui-v0.1.0.bundle danus-webui
cd danus-webui
git remote set-url origin https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git
git push -u origin main
```

The ignore rules exclude local environment files, models, runtime data, and common credential files. Review `git status` before publishing.

### Public hosting

The default ports bind to `127.0.0.1`, and Open WebUI authentication is disabled for local use. Publishing source code does not deploy the running application.

Public hosting requires authentication, authorization, TLS, and an appropriate reverse proxy. Do not expose the default authentication-free configuration directly to the internet. The application requires its Docker backend and a reachable model.

## Development and Validation

```bash
docker compose exec -T -e PYTHONPATH=/opt/webui local-llm-webui /opt/danus/runtime/venv/bin/python -m unittest discover -s /opt/webui/tests -v
```

Tests cover project stopping and trash behavior, paper extraction, ePrint indexing, search controls, source filtering, and project preferences in verification.

The initial source release passed 31 unit tests plus Compose and script syntax checks. See [VALIDATION.md](VALIDATION.md) for the validation scope and limitations.

## Repository Layout

```text
webui/                    Portal, backend, search tools, tests, and static assets
danus-setup/Danus/         Modified Danus source snapshot and upstream license
danus-setup/Dockerfile     Preserved integration Dockerfile
danus-setup/start.sh       Container startup script
danus-setup/*.env.example  Local configuration templates
danus-setup/proxy-config/  Internal API bridge settings
scripts/                  Preparation and startup helpers
docker-compose.yml        Workspace service definitions
.env.example              Model address and ID template
LICENSE                   Apache License 2.0
NOTICE                    Attribution and distribution notices
THIRD_PARTY_NOTICES.md     Third-party source and license information
UPSTREAM_CHANGES.md        Changes to the Danus snapshot
VALIDATION.md             Release validation scope
```

## License and Attribution

The integration source is distributed under [Apache License 2.0](LICENSE). Third-party components retain their own licenses:

- Danus: Apache License 2.0.
- KaTeX JavaScript/CSS and marked: MIT.
- KaTeX fonts: SIL Open Font License 1.1, including reserved font names.
- highlight.js: BSD 3-Clause.
- Separately downloaded images and dependencies: their respective terms, including Open WebUI's license and branding requirements.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

Upstream: [frenzymath/Danus — Orchestrating Mathematical Reasoning Agents with Fact-Graph Memory](https://github.com/frenzymath/Danus).

Baseline commit: `6d92e8d415933ca2ef52fd1a4da73fdfcd418f1c`.

This is an independent integration, not an official release or endorsement by Danus, Open WebUI, or other upstream projects.
