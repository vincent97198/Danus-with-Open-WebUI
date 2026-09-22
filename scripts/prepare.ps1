$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$templates = @('.env', 'danus-setup/codex-danus.env', 'danus-setup/danus.env')
foreach ($relative in $templates) {
    $target = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath ($target + '.example') -Destination $target
        Write-Host "Created $relative"
    } else {
        Write-Host "Kept existing $relative"
    }
}
Write-Host 'Next: edit .env and set MODEL_NAME and MODEL_BASE_URL. See README.md.'
