@echo off
setlocal EnableExtensions EnableDelayedExpansion

title AXON // Neural Boot Sequence
cd /d "%~dp0"

set "ROOT_DIR=%cd%"
set "APP_DIR=%ROOT_DIR%\axon"
set "VENV_ACTIVATE=%ROOT_DIR%\.venv\Scripts\activate.bat"
set "APP_ENTRY=%APP_DIR%\app.py"
set "APP_URL=http://127.0.0.1:5000"
set "LM_API_URL=http://127.0.0.1:1234/v1/models"
set "LM_STUDIO_PATH="
set "LAN_URL="
set "CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "TUNNEL_URL="
set "TUNNEL_LOG=%ROOT_DIR%\cloudflared.log"

call :banner

call :step 6 "Waking dormant circuits"
call :step 14 "Routing power to local inference core"
call :step 24 "Initializing model telemetry"
call :step 35 "Calibrating memory lattice"

if not exist "%VENV_ACTIVATE%" call :fatal "Virtual environment not found: %VENV_ACTIVATE%"
if not exist "%APP_ENTRY%" call :fatal "Axon app entry not found: %APP_ENTRY%"

call :find_lm_studio
call :step 46 "Scanning LM Studio uplink"
call :check_lm_api

if /I not "%LM_API_ONLINE%"=="1" (
    call :step 56 "LM signal offline, checking process state"
    call :is_lm_running
    if /I "%LM_PROCESS_RUNNING%"=="1" (
        call :step 63 "LM Studio process detected, waiting for API"
        call :wait_for_lm 8
    ) else (
        if defined LM_STUDIO_PATH (
            call :step 63 "Launching LM Studio"
            start "LM Studio" "%LM_STUDIO_PATH%"
            call :wait_for_lm 18
        ) else (
            echo.
            echo [WARN] LM Studio is offline and no install path was auto-detected.
            echo        Start LM Studio manually if you want chat to work.
        )
    )
)

call :check_lm_api
if /I "%LM_API_ONLINE%"=="1" (
    echo.
    echo [OK]   LM Studio API locked.
) else (
    echo.
    echo [WARN] LM Studio API still not responding at 127.0.0.1:1234.
    echo        Axon will launch, but responses will fail until LM Studio is ready.
)

call :step 78 "Spinning up Axon command shell"
start "Axon Server" cmd /k "cd /d "%APP_DIR%" && call "%VENV_ACTIVATE%" && python app.py"

call :step 90 "Acquiring local access route"
call :detect_lan_url

call :step 92 "Establishing Cloudflare tunnel"
call :start_tunnel

call :step 97 "Opening command viewport"
timeout /t 3 >nul
start "" "%APP_URL%"

call :step 100 "Axon online"
echo.
echo ============================================================
echo   LOCAL :  %APP_URL%
if defined LAN_URL if not "%LAN_URL%"=="" (
    echo   LAN   :  %LAN_URL%
) else (
    echo   LAN   :  Use your PC LAN IP, e.g. http://192.168.x.x:5000
)
if defined TUNNEL_URL (
    echo   PUBLIC:  %TUNNEL_URL%
) else (
    echo   PUBLIC:  [tunnel failed — check cloudflared.log]
)
echo ============================================================
echo.
echo Keep the "Axon Server" window open while you use Axon.
echo Close this launcher window whenever you want.
echo When you close this window, the Cloudflare tunnel will stop.
echo.
pause
exit /b 0

:step
set "PCT=%~1"
set "MSG=%~2"
call :progress !PCT! "%MSG%"
timeout /t 1 >nul
exit /b 0

:progress
set /a FILLED=%~1 / 5
set "BAR="
for /l %%I in (1,1,20) do (
    if %%I LEQ !FILLED! (
        set "BAR=!BAR!#"
    ) else (
        set "BAR=!BAR!."
    )
)
powershell -NoProfile -Command "Write-Host ('`r[' + '%BAR%' + '] ' + '%~2' + '  ' + '%~1%%') -NoNewline"
if "%~1"=="100" echo.
exit /b 0

:check_lm_api
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing '%LM_API_URL%' -Headers @{ Authorization = 'Bearer lm-studio' } -TimeoutSec 2; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    set "LM_API_ONLINE=0"
) else (
    set "LM_API_ONLINE=1"
)
exit /b 0

:wait_for_lm
set "LM_API_ONLINE=0"
for /l %%S in (1,1,%~1) do (
    powershell -NoProfile -Command "Write-Host ('`r[################....] Waiting for LM Studio API  ' + %%S + '/%~1') -NoNewline"
    timeout /t 1 >nul
    call :check_lm_api
    if /I "!LM_API_ONLINE!"=="1" (
        echo.
        exit /b 0
    )
)
echo.
exit /b 0

:is_lm_running
powershell -NoProfile -Command "if (Get-Process | Where-Object { $_.ProcessName -match 'LM.*Studio|lmstudio' }) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    set "LM_PROCESS_RUNNING=0"
) else (
    set "LM_PROCESS_RUNNING=1"
)
exit /b 0

:find_lm_studio
set "LM_STUDIO_PATH="
for %%P in (
    "%ProgramFiles%\LM Studio\LM Studio.exe"
    "%LocalAppData%\Programs\LM Studio\LM Studio.exe"
    "%LocalAppData%\LM Studio\LM Studio.exe"
    "%LocalAppData%\Programs\LM-Studio\LM Studio.exe"
    "%ProgramFiles%\LM-Studio\LM Studio.exe"
) do (
    if exist "%%~P" (
        set "LM_STUDIO_PATH=%%~P"
        goto :find_lm_done
    )
)
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$roots = @($env:LOCALAPPDATA, $env:ProgramFiles) ^| Where-Object { $_ -and (Test-Path $_) }; $hit = Get-ChildItem -Path $roots -Filter 'LM Studio.exe' -File -Recurse -ErrorAction SilentlyContinue ^| Select-Object -First 1 -ExpandProperty FullName; if ($hit) { Write-Output $hit }"`) do (
    set "LM_STUDIO_PATH=%%P"
    goto :find_lm_done
)
:find_lm_done
exit /b 0

:detect_lan_url
set "LAN_URL="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$cfg = Get-NetIPConfiguration ^| Where-Object { $_.IPv4DefaultGateway -ne $null } ^| Select-Object -First 1; if ($cfg) { $ip = ($cfg.IPv4Address ^| Where-Object { $_.IPAddress -notlike '169.254*' } ^| Select-Object -First 1 -ExpandProperty IPAddress); if ($ip) { Write-Output ('http://' + $ip + ':5000') } }"`) do set "LAN_URL=%%I"
exit /b 0

:start_tunnel
set "TUNNEL_URL="
if not exist "%CLOUDFLARED%" (
    echo [WARN] cloudflared not found at %CLOUDFLARED%
    exit /b 0
)
:: Kill any leftover cloudflared
taskkill /f /im cloudflared.exe >nul 2>&1
:: Start tunnel, log output to file
start "Cloudflare Tunnel" /min cmd /c ""%CLOUDFLARED%" tunnel --url http://127.0.0.1:5000 > "%TUNNEL_LOG%" 2>&1"
:: Wait for the URL to appear in the log (up to 20 seconds)
for /l %%W in (1,1,20) do (
    timeout /t 1 >nul
    powershell -NoProfile -Command "Write-Host ('`r[################....] Waiting for tunnel URL  ' + %%W + '/20') -NoNewline"
    for /f "usebackq tokens=*" %%U in (`powershell -NoProfile -Command "$c = Get-Content '%TUNNEL_LOG%' -ErrorAction SilentlyContinue; $m = $c | Select-String -Pattern 'https://[a-z0-9\-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { [regex]::Match($m.Line, 'https://[a-z0-9\-]+\.trycloudflare\.com').Value }"`) do (
        set "TUNNEL_URL=%%U"
    )
    if defined TUNNEL_URL (
        echo.
        exit /b 0
    )
)
echo.
exit /b 0

:fatal
echo.
echo [FATAL] %~1
echo.
pause
exit /b 1

:banner
cls
echo.
echo      ___   __   __   ______   _   _
echo     / _ \  \ \ / /  / __  \ ^| \ ^| ^|
echo    / /_\ \  \ V /   `' / /' ^|  \^| ^|
echo    ^|  _  ^|  /   \     / /   ^| . ` ^|
echo    ^| ^| ^| ^| / /^\ \  ./ /___ ^| ^|\  ^|
echo    \_^| ^|_/ \/   \/  \_____/ \_^| \_^
echo.
echo            AXON // LOCAL INTELLIGENCE BOOTSTRAP
echo            ------------------------------------
echo.
exit /b 0