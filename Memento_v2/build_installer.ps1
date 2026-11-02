param([switch]$UseExisting)
$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Die virtuelle Umgebung .venv fehlt. Bitte zuerst README.md befolgen."
}
if (-not $UseExisting) {
    & $python -m pip install -r (Join-Path $PSScriptRoot "requirements-build.txt") -r (Join-Path $PSScriptRoot "requirements-runtime.lock")
    if ($LASTEXITCODE -ne 0) { throw "Buildabhängigkeiten konnten nicht installiert werden." }
}
$arguments = @((Join-Path $PSScriptRoot "scripts\build_installer.py"))
if ($UseExisting) { $arguments += "--use-existing" }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Installer-Build oder Installationsprüfung fehlgeschlagen." }
