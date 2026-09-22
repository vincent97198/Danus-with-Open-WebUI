#!/usr/bin/env bash
set -euo pipefail

cd /opt/danus
bash scripts/bootstrap.sh
if ! runtime/venv/bin/python -c 'import httpx, bs4, pypdf, fontTools' >/dev/null 2>&1; then
  runtime/venv/bin/pip install --no-cache-dir -r /opt/webui/requirements.txt
fi
bash scripts/setup-codex.sh api
{
  printf 'model_context_window = 65536\nmodel_auto_compact_token_limit = 50000\nweb_search = "disabled"\n'
  cat runtime/codex-home/config.toml
} > runtime/codex-home/config.toml.tmp
mv runtime/codex-home/config.toml.tmp runtime/codex-home/config.toml
bash scripts/services.sh up verify
. scripts/env.sh
exec "$DANUS_PY" -m uvicorn server:app --app-dir /opt/webui --host 0.0.0.0 --port 7860
