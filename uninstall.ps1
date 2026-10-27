# X52 AC8 Launcher — удаление (Windows 10/11, PowerShell 5.1+). Запускается из uninstall.bat.
param([switch]$NoMain)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$Root = $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$StatePath = Join-Path $Root 'install_state.json'
$AppName = 'X52 AC8 Launcher'
$script:Answers = @()
if ($env:X52_ANSWERS) { $script:Answers = @($env:X52_ANSWERS -split ',') }

function Write-Step([string]$t) { Write-Host ''; Write-Host "=== $t" -ForegroundColor Cyan }
function Write-Ok([string]$t) { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Note([string]$t) { Write-Host "  $t" }
function Write-Warn2([string]$t) { Write-Host "  [!] $t" -ForegroundColor Yellow }

function Ask([string]$question, [string]$default) {
    if ($script:Answers.Count -gt 0) {
        $a = $script:Answers[0]
        if ($script:Answers.Count -gt 1) { $script:Answers = @($script:Answers[1..($script:Answers.Count - 1)]) } else { $script:Answers = @() }
        Write-Host "$question [$default] -> $a"
    } else {
        $a = Read-Host "$question [Y/N, по умолчанию $default]"
    }
    if ([string]::IsNullOrWhiteSpace($a)) { $a = $default }
    return ($a.Trim().ToUpper() -in @('Y', 'YES', 'Д', 'ДА'))
}

function Get-State {
    $s = @{ python_installed_by_setup = $false; python_exe = ''; vigem_installed_by_setup = $false; opentrack_installed_by_setup = $false; shortcuts = @() }
    if (Test-Path -LiteralPath $StatePath) {
        try {
            $j = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $j.PSObject.Properties) { $s[$p.Name] = $p.Value }
        } catch { }
    }
    return $s
}

# ---- внешние действия (подменяются в тестах)
function Get-UninstallEntries([string]$pattern) {
    $paths = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
               'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
               'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
    @(Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.DisplayName -like "*$pattern*" })
}
function Invoke-Uninstaller([string]$commandLine) {
    # внешние кавычки снимает cmd /c, внутренние кавычки пути остаются целыми
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', ('"' + $commandLine + '"')) -Wait -PassThru -WindowStyle Hidden
    return $p.ExitCode
}
function Get-LauncherProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Venv, [StringComparison]::OrdinalIgnoreCase) })
}
function Stop-ProcessById([int]$id) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
function Get-ShortcutPaths {
    $desk = [Environment]::GetFolderPath('Desktop')
    $prog = [Environment]::GetFolderPath('Programs')
    return @((Join-Path $desk "$AppName.lnk"), (Join-Path $prog "$AppName.lnk"))
}
function Start-SelfDelete([string]$folder) {
    $cmd = 'ping 127.0.0.1 -n 4 >nul & cd /d "%TEMP%" & rmdir /s /q "' + $folder + '"'
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $cmd) -WindowStyle Hidden
}

function Remove-Product([string]$pattern, [string]$title, [bool]$preferQuiet) {
    $entries = Get-UninstallEntries $pattern
    if ($entries.Count -eq 0) { Write-Note "$title не найден в списке программ."; return }
    foreach ($e in $entries) {
        $cmdline = $e.UninstallString
        if ($preferQuiet -and $e.QuietUninstallString) { $cmdline = $e.QuietUninstallString }
        if (-not $cmdline) { Write-Warn2 "У «$($e.DisplayName)» нет команды удаления — удалите через «Приложения и возможности»."; continue }
        Write-Note "Удаляю $($e.DisplayName) — подтвердите UAC, если появится запрос …"
        try { $code = Invoke-Uninstaller $cmdline; Write-Ok "$($e.DisplayName): завершено (код $code)" }
        catch { Write-Warn2 "$($e.DisplayName): $($_.Exception.Message)" }
    }
}

function Invoke-Uninstall {
    Write-Host "$AppName — удаление" -ForegroundColor White
    Write-Host "Папка программы: $Root"
    $state = Get-State

    Write-Step '1/6  Закрываю лаунчер'
    $procs = Get-LauncherProcesses
    foreach ($p in $procs) { Stop-ProcessById $p.ProcessId }
    if ($procs.Count) { Write-Ok "Закрыто процессов: $($procs.Count)"; Start-Sleep -Seconds 1 } else { Write-Ok 'Лаунчер не запущен' }

    Write-Step '2/6  Ярлыки'
    foreach ($lnk in (Get-ShortcutPaths)) {
        if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; Write-Ok "Удалён: $lnk" }
    }

    Write-Step '3/6  Окружение программы (.venv)'
    if (Test-Path -LiteralPath $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force; Write-Ok 'Папка .venv удалена' }
    else { Write-Ok '.venv нет' }
    foreach ($pc in @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $pc.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Step '4/6  Настройки'
    if (Ask 'Удалить ваши настройки (оси, калибровку, кнопки)? При «N» они сохранятся для повторной установки.' 'N') {
        foreach ($f in @('x52_config.json', 'x52_config.json.broken', 'x52_config.json.tmp', 'x52_error.log',
                         'x52_global.json', 'x52_global.json.tmp')) {
            $fp = Join-Path $Root $f
            if (Test-Path -LiteralPath $fp) { Remove-Item -LiteralPath $fp -Force; Write-Ok "Удалён: $f" }
        }
        $pd = Join-Path $Root 'profiles'
        if (Test-Path -LiteralPath $pd) { Remove-Item -LiteralPath $pd -Recurse -Force; Write-Ok 'Удалена папка profiles (профили игр)' }
    } else { Write-Ok 'Настройки сохранены (x52_config.json)' }

    # строка автопрофиля в DCS: без лаунчера не нужна. Пишем без BOM — Lua 5.1 в DCS не понимает BOM.
    $sg = Join-Path $env:USERPROFILE 'Saved Games'
    foreach ($d in @(Get-ChildItem -LiteralPath $sg -Directory -Filter 'DCS*' -ErrorAction SilentlyContinue)) {
        try {
            $exp = Join-Path $d.FullName 'Scripts\Export.lua'
            if (Test-Path -LiteralPath $exp) {
                $lines = @([System.IO.File]::ReadAllLines($exp, [System.Text.Encoding]::UTF8))
                $keep = @($lines | Where-Object { $_ -notmatch 'x52launcher_export\.lua' })
                if ($keep.Count -ne $lines.Count) {
                    [System.IO.File]::WriteAllLines($exp, [string[]]$keep, (New-Object System.Text.UTF8Encoding($false)))
                    Write-Ok "DCS: убрана строка лаунчера из $($d.Name)\Scripts\Export.lua"
                }
            }
            $sf = Join-Path $d.FullName 'Scripts\x52launcher_export.lua'
            if (Test-Path -LiteralPath $sf) { Remove-Item -LiteralPath $sf -Force }
        } catch { Write-Note "DCS ($($d.Name)): $($_.Exception.Message)" }
    }

    Write-Step '5/6  Дополнительные программы'
    Write-Note 'Драйвер ViGEmBus используют и другие программы (DS4Windows, x360ce и т.п.). Удаляйте, только если они вам не нужны.'
    if (Ask 'Удалить драйвер ViGEmBus?' 'N') { Remove-Product 'ViGEm' 'Драйвер ViGEmBus' $false; Remove-Product 'Virtual Gamepad Emulation' 'Драйвер ViGEmBus (старое имя)' $false }
    if (Ask 'Удалить opentrack?' 'N') { Remove-Product 'opentrack' 'opentrack' $false }
    if ($state.python_installed_by_setup) {
        if (Ask 'Удалить Python 3.12, установленный этим установщиком?' 'N') { Remove-Product 'Python 3.12.10' 'Python 3.12.10' $true }
    } else { Write-Note 'Python ставился не этим установщиком — не трогаю.' }
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }

    Write-Step '6/6  Папка программы'
    if (Ask 'Удалить папку программы целиком (вместе с этим файлом)?' 'N') {
        Start-SelfDelete $Root
        Write-Ok 'Папка будет удалена через несколько секунд после закрытия этого окна.'
        return 10
    }
    Write-Host ''
    Write-Host 'Удаление завершено. Папку с файлами можно удалить вручную.' -ForegroundColor Green
    return 0
}

if (-not $NoMain) {
    try { $rc = Invoke-Uninstall | Select-Object -Last 1; exit [int]$rc }
    catch {
        Write-Host ''
        Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}
