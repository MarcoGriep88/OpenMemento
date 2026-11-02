$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Die Python-Umgebung fehlt. Bitte die Einrichtung aus README.md ausführen."
}
$mementoPreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $PSScriptRoot "src"
    & $python -m memento.app @args
}
finally {
    $env:PYTHONPATH = $mementoPreviousPythonPath
}
