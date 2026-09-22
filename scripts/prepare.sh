#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for file in .env danus-setup/codex-danus.env danus-setup/danus.env; do
  if [ ! -e "$file" ]; then
    cp "$file.example" "$file"
    printf 'Created %s\n' "$file"
  else
    printf 'Kept existing %s\n' "$file"
  fi
done
printf 'Next: edit .env and set MODEL_NAME and MODEL_BASE_URL. See README.md.\n'
