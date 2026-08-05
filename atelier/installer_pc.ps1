# Installe le poste "atelier" sur le PC Windows (idempotent) :
#   - venv Python avec torch CUDA + demucs
#   - tache planifiee qui lance le watcher a l'ouverture de session
# Relancer ce script met a jour l'installation.
#
#   powershell -ExecutionPolicy Bypass -File atelier\installer_pc.ps1
#
# Prerequis : Python 3.10+, ffmpeg dans le PATH, acces au partage \\pi\data
# (identifiants enregistres via : cmdkey /add:<ip-du-pi> /user:<user> /pass).

param(
    [string]$DossierAtelier = "$env:USERPROFILE\karaoke-atelier",
    [string]$PartageAtelier = "\\192.168.1.157\data\karaoke\atelier",
    [string]$PartageBibliotheque = "\\192.168.1.157\data\karaoke\bibliotheque"
)

$ErrorActionPreference = "Stop"
$venv = Join-Path $DossierAtelier "venv"
$script = Join-Path $PSScriptRoot "atelier_pc.py"

if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Write-Host "== Creation du venv =="
    python -m venv $venv
}

Write-Host "== Installation de demucs (long au premier passage) =="
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$venv\Scripts\pip.exe" install --quiet torch torchaudio --index-url https://download.pytorch.org/whl/cu124
& "$venv\Scripts\pip.exe" install --quiet demucs numpy soundfile
# hf_xet (telechargeur Hugging Face en Rust) plante avec "Fatal Error: HW
# capability" sur ce PC ; sans lui, huggingface_hub retombe sur du HTTP simple.
& "$venv\Scripts\pip.exe" uninstall --quiet -y hf_xet 2>$null

Write-Host "== Tache planifiee (demarrage a l'ouverture de session) =="
$commande = "`"$venv\Scripts\pythonw.exe`" `"$script`" --atelier `"$PartageAtelier`" --bibliotheque `"$PartageBibliotheque`""
schtasks /Create /F /SC ONLOGON /TN "KaraokeAtelier" /TR $commande /RL LIMITED | Out-Null
schtasks /Run /TN "KaraokeAtelier" | Out-Null

Write-Host "Atelier installe. Journal : $DossierAtelier\atelier.log"
