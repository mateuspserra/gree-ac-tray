# Gera o aplicativo Windows a partir do código-fonte.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonApp = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonApp)) {
    throw 'Crie o ambiente virtual primeiro: python -m venv .venv'
}
& $pythonApp -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências.' }
& $pythonApp -m PyInstaller --noconfirm --noconsole --name ArCondicionado ac_tray.py
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o executável.' }
# Evita carregar uma biblioteca ICU incompatível com o Qt nesta versão.
$icuWindows = Join-Path $env:WINDIR 'System32\icuuc.dll'
$icuDestino = Join-Path $PSScriptRoot 'dist\ArCondicionado\_internal\icuuc.dll'
if ((Test-Path -LiteralPath $icuWindows) -and (Test-Path -LiteralPath $icuDestino)) {
    Copy-Item -LiteralPath $icuWindows -Destination $icuDestino -Force
}
Write-Host 'Aplicativo gerado em dist\ArCondicionado\ArCondicionado.exe'
Write-Host 'Mantenha toda a pasta ArCondicionado ao distribuir o aplicativo.'
