# X52 AC8 Launcher — установка (Windows 10/11, PowerShell 5.1+)
# Запускается из install.bat. Права администратора НЕ нужны: установщики драйвера
# и opentrack сами попросят подтверждение (UAC).
param([switch]$NoMain)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Root = $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw = Join-Path $Venv 'Scripts\pythonw.exe'
$AppScript = Join-Path $Root 'x52_ac8_launcher.py'
$IconPath = Join-Path $Root 'x52_launcher.ico'
$StatePath = Join-Path $Root 'install_state.json'
$AppName = 'X52 AC8 Launcher'
$PyVersion = '3.12.10'
$PyUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
$Packages = @('pygame==2.6.1', 'vgamepad==0.1.0')
$VigemFallback = 'https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe'
$OtFallback = 'https://github.com/opentrack/opentrack/releases/download/opentrack-2026.1.0/opentrack-2026.1.0-win32-setup.exe'
$script:Answers = @()
if ($env:X52_ANSWERS) { $script:Answers = @($env:X52_ANSWERS -split ',') }

# ---------------------------------------------------------------- вывод
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

# ---------------------------------------------------------------- состояние установки
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
function Save-State($s) {
    ($s | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

# ---------------------------------------------------------------- внешние действия (подменяются в тестах)
function Invoke-Download([string]$url, [string]$dest) {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dest -TimeoutSec 900 -Headers @{ 'User-Agent' = 'X52-AC8-Launcher' }
    if (-not (Test-Path -LiteralPath $dest) -or (Get-Item -LiteralPath $dest).Length -lt 1024) { throw "файл не загружен: $url" }
    return $dest
}
function Start-Installer([string]$file, [string[]]$argList) {
    if ($argList -and $argList.Count -gt 0) { $p = Start-Process -FilePath $file -ArgumentList $argList -Wait -PassThru }
    else { $p = Start-Process -FilePath $file -Wait -PassThru }
    return $p.ExitCode
}
function Invoke-Py([string]$exe, [string[]]$pyArgs) {
    # В Windows PowerShell 5.1 вывод stderr внешней программы при Stop превращается в исключение,
    # поэтому временно переключаемся на Continue и собираем всё как текст.
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return @{ code = -1; out = "не найдено: $exe" } }
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        $out = (& $exe @pyArgs 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
    return @{ code = $code; out = $out }
}
function Get-Signature([string]$file) {
    $sig = Get-AuthenticodeSignature -LiteralPath $file
    $subj = ''
    if ($sig.SignerCertificate) { $subj = $sig.SignerCertificate.Subject }
    return @{ status = [string]$sig.Status; subject = $subj }
}
function Get-UninstallEntries([string]$pattern) {
    $paths = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
               'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
               'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
    @(Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.DisplayName -like "*$pattern*" })
}
function Get-FinalUrl([string]$url) {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -MaximumRedirection 5 -TimeoutSec 30 -Headers @{ 'User-Agent' = 'X52-AC8-Launcher' }
    if ($r.BaseResponse.ResponseUri) { return $r.BaseResponse.ResponseUri.AbsoluteUri }
    return $r.BaseResponse.RequestMessage.RequestUri.AbsoluteUri
}
function Get-Text([string]$url) {
    return (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 30 -Headers @{ 'User-Agent' = 'X52-AC8-Launcher' }).Content
}
function Get-Json([string]$url) {
    return Invoke-RestMethod -UseBasicParsing -Uri $url -TimeoutSec 30 -Headers @{ 'User-Agent' = 'X52-AC8-Launcher' }
}

function Get-LatestAsset([string]$repo, [string]$pattern, [string]$fallback) {
    try {
        $r = Get-Json "https://api.github.com/repos/$repo/releases/latest"
        foreach ($a in $r.assets) { if ($a.name -match $pattern) { return $a.browser_download_url } }
    } catch { }
    try {
        $final = Get-FinalUrl "https://github.com/$repo/releases/latest"
        $tag = ($final.TrimEnd('/') -split '/')[-1]
        $html = Get-Text "https://github.com/$repo/releases/expanded_assets/$tag"
        foreach ($m in [regex]::Matches($html, 'href="(/[^"]+/releases/download/[^"]+)"')) {
            $href = $m.Groups[1].Value
            if ((($href -split '/')[-1]) -match $pattern) { return "https://github.com$href" }
        }
    } catch { }
    return $fallback
}

# ---------------------------------------------------------------- Python
function Test-PythonCandidate([string]$exe, [string[]]$prefix) {
    $code = "import sys,struct,tkinter;print('PYOK %d %d %d %s' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8, sys.executable))"
    try { $r = Invoke-Py $exe ($prefix + @('-c', $code)) } catch { return $null }
    if ($r.code -ne 0) { return $null }
    $m = [regex]::Match($r.out, 'PYOK (\d+) (\d+) (\d+) (.+)')
    if (-not $m.Success) { return $null }
    $maj = [int]$m.Groups[1].Value; $min = [int]$m.Groups[2].Value; $bits = [int]$m.Groups[3].Value
    if ($maj -ne 3 -or $min -lt 9 -or $min -gt 13 -or $bits -ne 64) { return $null }
    $path = $m.Groups[4].Value.Trim()
    if ($path -like '*\WindowsApps\*') { return $null }   # заглушка Microsoft Store
    return $path
}

function Find-Python {
    $cands = New-Object System.Collections.ArrayList
    foreach ($v in @('3.13', '3.12', '3.11', '3.10', '3.9')) { [void]$cands.Add(@('py', @("-$v"))) }
    [void]$cands.Add(@('python', @()))
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrEmpty($base)) { continue }   # на 32-битной Windows нет Program Files (x86)
        if ($base -eq $env:LOCALAPPDATA) { $base = Join-Path $base 'Programs\Python' }
        foreach ($v in @('313', '312', '311', '310', '39')) {
            $p = Join-Path $base "Python$v\python.exe"
            if (Test-Path -LiteralPath $p) { [void]$cands.Add(@($p, @())) }
        }
    }
    foreach ($c in $cands) {
        $found = Test-PythonCandidate $c[0] $c[1]
        if ($found) { return $found }
    }
    return $null
}

function Install-Python {
    $dest = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
    Write-Note "Загружаю Python $PyVersion с python.org …"
    Invoke-Download $PyUrl $dest | Out-Null
    $sig = Get-Signature $dest
    if ($sig.status -ne 'Valid' -or $sig.subject -notmatch 'Python Software Foundation') {
        throw "подпись установщика Python не прошла проверку ($($sig.status)). Установка остановлена."
    }
    Write-Note 'Устанавливаю Python только для текущего пользователя (без прав администратора) …'
    $code = Start-Installer $dest @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0',
        'Include_test=0', 'Include_doc=0', 'Include_tcltk=1', 'Include_pip=1', 'Shortcuts=0', 'AssociateFiles=0')
    if ($code -ne 0) { throw "установщик Python завершился с кодом $code" }
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "Python не найден после установки: $exe" }
    return $exe
}

# ---------------------------------------------------------------- ViGEmBus
# Имя в «Приложениях и возможностях»: «ViGEm Bus Driver» или «Nefarius Virtual Gamepad Emulation Bus Driver»
function Test-ViGEmInstalled { return (((Get-UninstallEntries 'ViGEm').Count + (Get-UninstallEntries 'Virtual Gamepad Emulation').Count) -gt 0) }

function Install-ViGEm {
    $url = Get-LatestAsset 'nefarius/ViGEmBus' '^ViGEmBus_.*\.exe$' $VigemFallback
    $dest = Join-Path $env:TEMP (($url -split '/')[-1])
    Write-Note "Загружаю драйвер: $url"
    Invoke-Download $url $dest | Out-Null
    $sig = Get-Signature $dest
    if ($sig.status -ne 'Valid' -or $sig.subject -notmatch 'Nefarius') {
        Write-Warn2 "Подпись установщика драйвера: $($sig.status) $($sig.subject)"
        if (-not (Ask 'Подпись не подтверждена. Всё равно запустить установщик драйвера?' 'N')) { throw 'установка драйвера отменена' }
    }
    Write-Note 'Запускаю установщик ViGEmBus — подтвердите UAC и пройдите шаги (Next/Install/Finish).'
    $code = Start-Installer $dest @()
    Write-Note "Установщик драйвера закрыт (код $code)."
}

# ---------------------------------------------------------------- окружение и библиотеки
function New-Venv([string]$py) {
    if ((Test-Path -LiteralPath $VenvPy)) {
        $chk = Invoke-Py $VenvPy @('-c', 'import sys; print(sys.version)')
        if ($chk.code -eq 0) { Write-Ok 'Окружение .venv уже есть'; return }
        Write-Warn2 'Окружение .venv повреждено — пересоздаю'
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
    $r = Invoke-Py $py @('-m', 'venv', $Venv)
    if ($r.code -ne 0 -or -not (Test-Path -LiteralPath $VenvPy)) { throw "не удалось создать окружение: $($r.out)" }
    Write-Ok 'Создано окружение .venv'
}

function Install-Libs {
    Invoke-Py $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip') | Out-Null
    $r = Invoke-Py $VenvPy (@('-m', 'pip', 'install', '--disable-pip-version-check') + $Packages)
    if ($r.code -ne 0) { throw "pip не смог установить библиотеки:`n$($r.out)" }
    $chk = Invoke-Py $VenvPy @('-c', "import pygame, vgamepad, tkinter; print('LIBSOK')")
    if ($chk.code -ne 0 -or $chk.out -notmatch 'LIBSOK') { throw "библиотеки не импортируются:`n$($chk.out)" }
    Write-Ok ('Библиотеки установлены: ' + ($Packages -join ', '))
}

function Test-Driver {
    $r = Invoke-Py $VenvPy @('-c', "import vgamepad,time; p=vgamepad.VX360Gamepad(); p.reset(); p.update(); time.sleep(0.2); print('PADOK')")
    return ($r.code -eq 0 -and $r.out -match 'PADOK')
}

# ---------------------------------------------------------------- ярлыки и прочее
function Get-ShortcutPaths {
    $desk = [Environment]::GetFolderPath('Desktop')
    $prog = [Environment]::GetFolderPath('Programs')
    return @((Join-Path $desk "$AppName.lnk"), (Join-Path $prog "$AppName.lnk"))
}
function New-Shortcuts {
    $made = @()
    foreach ($lnk in (Get-ShortcutPaths)) {
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
        $s.TargetPath = $VenvPyw
        $s.Arguments = '"' + $AppScript + '"'
        $s.WorkingDirectory = $Root
        if (Test-Path -LiteralPath $IconPath) { $s.IconLocation = $IconPath }
        $s.Description = 'Saitek X52 -> Xbox 360 для ACE COMBAT 8'
        $s.Save()
        $made += $lnk
    }
    return $made
}
function Unblock-All { Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "$Venv*" } | Unblock-File -ErrorAction SilentlyContinue }

function Install-OpenTrack {
    $url = Get-LatestAsset 'opentrack/opentrack' 'win32-setup\.exe$' $OtFallback
    $dest = Join-Path $env:TEMP (($url -split '/')[-1])
    Write-Note "Загружаю opentrack: $url"
    Invoke-Download $url $dest | Out-Null
    Write-Note 'Запускаю установщик opentrack — подтвердите UAC и пройдите шаги.'
    $code = Start-Installer $dest @()
    Write-Note "Установщик opentrack закрыт (код $code)."
}

# ---------------------------------------------------------------- главный сценарий
function Invoke-Setup {
    Write-Host "$AppName — установка" -ForegroundColor White
    Write-Host "Папка программы: $Root"
    if ($Root -match '[^\x00-\x7F]') { Write-Warn2 'В пути к папке есть русские буквы. Обычно это работает, но надёжнее держать программу в папке вроде C:\Games\X52_AC8.' }
    $state = Get-State
    Unblock-All

    Write-Step '1/6  Python'
    $py = Find-Python
    if ($py) { Write-Ok "Найден подходящий Python: $py" }
    else {
        Write-Note 'Подходящий Python (3.9–3.13, 64-бит, с tkinter) не найден.'
        $py = Install-Python
        $state.python_installed_by_setup = $true
        Write-Ok "Python $PyVersion установлен: $py"
    }
    $state.python_exe = $py
    Save-State $state

    Write-Step '2/6  Драйвер ViGEmBus (виртуальный геймпад)'
    if (Test-ViGEmInstalled) { Write-Ok 'Драйвер ViGEmBus уже установлен' }
    else {
        try {
            Install-ViGEm
            if (Test-ViGEmInstalled) { $state.vigem_installed_by_setup = $true; Write-Ok 'Драйвер ViGEmBus установлен' }
            else { Write-Warn2 'Драйвер не появился в списке программ — при установке библиотек может открыться встроенный установщик драйвера, согласитесь на него.' }
        } catch {
            Write-Warn2 "Не удалось установить драйвер с GitHub: $($_.Exception.Message)"
            Write-Warn2 'При установке библиотек откроется встроенный установщик драйвера из пакета vgamepad — согласитесь на него.'
        }
    }
    Save-State $state

    Write-Step '3/6  Окружение программы (.venv)'
    New-Venv $py

    Write-Step '4/6  Библиотеки (pygame, vgamepad)'
    Install-Libs

    Write-Step '5/6  Проверка виртуального геймпада'
    if (Test-Driver) { Write-Ok 'Виртуальный Xbox 360 геймпад создаётся — драйвер работает' }
    else { Write-Warn2 'Виртуальный геймпад пока не создаётся. Перезагрузите ПК; если не поможет — лаунчер, вкладка «Установка» → «Установить / обновить» ViGEmBus.' }

    Write-Step '6/6  Ярлыки и дополнительно'
    try { $state.shortcuts = @(New-Shortcuts); Write-Ok 'Ярлыки созданы: рабочий стол и меню «Пуск»' }
    catch { Write-Warn2 "Ярлыки не созданы: $($_.Exception.Message). Запускайте через start.bat." }
    $hadOt = ((Get-UninstallEntries 'opentrack').Count -gt 0)
    if ($hadOt) { Write-Ok 'opentrack уже установлен' }
    elseif (Ask 'Установить opentrack (нужен только для обзора поворотом головы через веб-камеру/трекер)?' 'N') {
        try {
            Install-OpenTrack
            if ((Get-UninstallEntries 'opentrack').Count -gt 0) { $state.opentrack_installed_by_setup = $true; Write-Ok 'opentrack установлен' }
        } catch { Write-Warn2 "opentrack не установлен: $($_.Exception.Message). Можно позже на вкладке «Установка»." }
    }
    Save-State $state

    Write-Host ''
    Write-Host 'Установка завершена.' -ForegroundColor Green
    Write-Host "Запуск: ярлык «$AppName» на рабочем столе или start.bat в папке программы."
    Write-Host 'Во время игры должны работать: лаунчер (мост включён), Steam/игра и opentrack (если обзор головой).'
    if (Ask 'Запустить лаунчер сейчас?' 'Y') { Start-Process -FilePath $VenvPyw -ArgumentList ('"' + $AppScript + '"') -WorkingDirectory $Root }
}

if (-not $NoMain) {
    try { Invoke-Setup; exit 0 }
    catch {
        Write-Host ''
        Write-Host "ОШИБКА УСТАНОВКИ: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'Исправьте причину и запустите install.bat ещё раз (повторный запуск безопасен).'
        exit 1
    }
}
