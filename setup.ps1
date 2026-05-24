# Setup script for Solidocto (PowerShell)
# Creates .venv if needed, then installs all dependencies and downloads NLP models.
#
# Usage:
#   . .\setup.ps1        <- dot-source: installs AND activates venv in your current shell
#   .\setup.ps1          <- normal run: installs only (venv activation won't persist)

$venvPython = ".\.venv\Scripts\python.exe"
$venvPip    = ".\.venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
}

Write-Host "Installing Python dependencies..."
& $venvPip install -r requirements.txt

Write-Host "Downloading spaCy English model..."
& $venvPython -m spacy download en_core_web_sm

Write-Host ""
Write-Host "Activating virtual environment..."
. .\.venv\Scripts\Activate.ps1

Write-Host "Setup complete. Venv is active."

