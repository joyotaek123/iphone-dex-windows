@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "GH_BIN=gh"
where gh >nul 2>&1
if errorlevel 1 (
    if exist "C:\Program Files\GitHub CLI\gh.exe" (
        set "GH_BIN=C:\Program Files\GitHub CLI\gh.exe"
    ) else (
        echo [ERROR] GitHub CLI ^(gh.exe^) tidak ditemukan!
        pause
        exit /b 1
    )
)

echo === iPhone DeX for Windows: Download .ipa dari GitHub Actions ===
echo.

"%GH_BIN%" auth status >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Anda belum login GitHub. Jalankan tools\push_to_github.bat terlebih dahulu.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "& '%GH_BIN%' run list --workflow build-ios-ipa.yml --limit 1 --json databaseId --jq '.[0].databaseId'"`) do set "RUN_ID=%%i"

if not defined RUN_ID (
    echo [ERROR] Belum ada riwayat build workflow build-ios-ipa.yml di GitHub.
    echo Pastikan Anda sudah menjalankan tools\push_to_github.bat.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "& '%GH_BIN%' run view %RUN_ID% --json status --jq '.status'"`) do set "RUN_STATUS=%%i"

echo [*] Workflow Run ID: %RUN_ID% ^(Status: %RUN_STATUS%^)
if /I not "%RUN_STATUS%"=="completed" (
    echo [*] Build macOS masih berjalan. Menunggu hingga selesai...
    "%GH_BIN%" run watch %RUN_ID% --exit-status
    if errorlevel 1 (
        echo [ERROR] Build di GitHub Actions gagal! Buka log dengan: "%GH_BIN%" run view %RUN_ID% --log-failed
        pause
        exit /b 1
    )
)

if not exist "dist" mkdir "dist"
if exist "dist\iPhoneDeXHost-unsigned.ipa" del /q "dist\iPhoneDeXHost-unsigned.ipa"

echo [*] Mengunduh artifact iPhoneDeXHost-unsigned-ipa ke folder dist\ ...
"%GH_BIN%" run download %RUN_ID% --name iPhoneDeXHost-unsigned-ipa --dir dist
if errorlevel 1 (
    echo [ERROR] Gagal mengunduh .ipa. Cek status run di GitHub Actions.
    pause
    exit /b 1
)

echo.
echo [SUKSES] File .ipa siap di: %CD%\dist\iPhoneDeXHost-unsigned.ipa
start "" "%CD%\dist"
pause
