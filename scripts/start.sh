#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for file in .env danus-setup/codex-danus.env danus-setup/danus.env; do
  [ -f "$file" ] || { printf 'Run bash scripts/prepare.sh and edit .env first.\n' >&2; exit 1; }
done
if grep -Eq '^MODEL_NAME[[:space:]]*=[[:space:]]*(replace-with-your-model-id)?[[:space:]]*$' .env; then
  printf 'Set the actual MODEL_NAME in .env first.\n' >&2
  exit 1
fi
docker info >/dev/null
docker compose up -d --build
ready=false
for attempt in $(seq 1 300); do
  if curl -fsS --max-time 2 http://127.0.0.1:3001/api/search/settings >/dev/null 2>&1 \
    && curl -fsS --max-time 2 http://127.0.0.1:3000/health >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
"$ready" || { printf 'Services are still starting. Check: docker compose logs --tail 80\n' >&2; exit 1; }
docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
printf 'Ready: open http://127.0.0.1:3001/\n'
