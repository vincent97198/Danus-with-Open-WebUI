$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location $packageRoot
try {
    foreach ($relative in @('.env', 'danus-setup/codex-danus.env', 'danus-setup/danus.env')) {
        if (-not (Test-Path -LiteralPath $relative)) { throw 'Run scripts/prepare.ps1, then edit .env before starting.' }
    }
    $settings = Get-Content -LiteralPath '.env' -Raw
    if ($settings -match '(?m)^MODEL_NAME\s*=\s*(replace-with-your-model-id)?\s*$') {
        throw 'Set the actual MODEL_NAME in .env first.'
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop (Linux containers), then run this script again.' }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Check the output above.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 300; $attempt++) {
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'http://127.0.0.1:3001/api/search/settings'
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'http://127.0.0.1:3000/health'
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'Services are still starting. Check: docker compose logs --tail 80' }
    docker compose exec -T local-llm-webui /opt/danus/runtime/venv/bin/python /opt/webui/configure_research.py
    if ($LASTEXITCODE -ne 0) { throw 'Research setup failed. Check the README troubleshooting section.' }
    Start-Process 'http://127.0.0.1:3001/'
    Write-Host 'Ready: http://127.0.0.1:3001/'
} finally { Pop-Location }
