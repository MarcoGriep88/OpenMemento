$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Die virtuelle Umgebung .venv fehlt. Bitte zuerst die Einrichtung aus README.md ausführen."
}
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements-build.txt") -r (Join-Path $PSScriptRoot "requirements-runtime.lock")
if ($LASTEXITCODE -ne 0) { throw "Buildabhängigkeiten konnten nicht installiert werden." }
& $python (Join-Path $PSScriptRoot "scripts\build_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Build oder Prüfung fehlgeschlagen." }
