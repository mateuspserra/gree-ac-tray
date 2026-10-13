# Cria ou remove o atalho de inicialização do usuário atual.
param(
    [string]$Nome = 'Quarto',
    [switch]$Remover
)
$ErrorActionPreference = 'Stop'
$pastaInicializar = [Environment]::GetFolderPath('Startup')
$caminhoAtalho = Join-Path $pastaInicializar 'ArCondicionado.lnk'
if ($Remover) {
    if (Test-Path -LiteralPath $caminhoAtalho) {
        Remove-Item -LiteralPath $caminhoAtalho
    }
    Write-Host 'Inicialização automática removida.'
    return
}
$executavel = Join-Path $PSScriptRoot 'dist\ArCondicionado\ArCondicionado.exe'
if (-not (Test-Path -LiteralPath $executavel)) {
    throw 'Gere o executável antes, usando gerar_executavel.ps1.'
}
if ($Nome.Contains('"')) { throw 'O nome não pode conter aspas duplas.' }
$shellWindows = New-Object -ComObject WScript.Shell
$atalho = $shellWindows.CreateShortcut($caminhoAtalho)
$atalho.TargetPath = $executavel
$atalho.Arguments = '--name "' + $Nome + '"'
$atalho.WorkingDirectory = Split-Path -Parent $executavel
$atalho.Description = 'Controle do ar-condicionado pela bandeja do Windows'
$atalho.Save()
Write-Host 'Atalho criado. O aplicativo iniciará com o Windows.'
