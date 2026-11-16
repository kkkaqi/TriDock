@echo off
where python.exe >nul 2>nul
if errorlevel 1 (
    echo Python 3.10 or later is required.
    pause
    exit /b 1
)
if not exist "%~dp0node_modules\electron\dist\electron.exe" (
    pushd "%~dp0"
    if not exist "node_modules\.bin\install-electron.cmd" call npm.cmd ci --no-audit --no-fund
    if errorlevel 1 (
        echo Install Node.js 22.12 or later and try again.
        popd
        pause
        exit /b 1
    )
    call "node_modules\.bin\install-electron.cmd"
    if not exist "node_modules\electron\dist\electron.exe" (
        echo Electron could not be installed.
        popd
        pause
        exit /b 1
    )
    popd
)
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
