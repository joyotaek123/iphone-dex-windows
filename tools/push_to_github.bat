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
        echo Install dulu dengan: winget install --id GitHub.cli -e
        pause
        exit /b 1
    )
)

echo === iPhone DeX for Windows: GitHub Setup ^& Push ===
echo.

"%GH_BIN%" auth status >nul 2>&1
if errorlevel 1 (
    echo [*] Anda belum login GitHub. Browser akan dibuka untuk login resmi GitHub...
    "%GH_BIN%" auth login --web --git-protocol https
    if errorlevel 1 (
        echo [ERROR] Login GitHub gagal atau dibatalkan.
        pause
        exit /b 1
    )
)

"%GH_BIN%" auth setup-git

if not exist ".git" (
    git init -b main
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "& '%GH_BIN%' api user --jq '.login'"`) do set "GH_USER=%%i"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "& '%GH_BIN%' api user --jq '.id'"`) do set "GH_ID=%%i"

set "GIT_NAME="
for /f "delims=" %%i in ('git config user.name 2^>nul') do set "GIT_NAME=%%i"
if not defined GIT_NAME if defined GH_USER (
    git config user.name "%GH_USER%"
)

set "GIT_EMAIL="
for /f "delims=" %%i in ('git config user.email 2^>nul') do set "GIT_EMAIL=%%i"
if not defined GIT_EMAIL if defined GH_USER if defined GH_ID (
    git config user.email "%GH_ID%+%GH_USER%@users.noreply.github.com"
)

echo [*] Akun GitHub aktif: %GH_USER%
echo [*] Menyiapkan commit...
git add .
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "feat: Phase 1 PoC (IDEX v1 protocol, iOS Host, Windows Client, CI)"
) else (
    echo [*] Tidak ada perubahan baru untuk di-commit.
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [*] Membuat repo publik 'iphone-dex-windows' di GitHub dan mengunggah kode...
    "%GH_BIN%" repo create iphone-dex-windows --public --source=. --remote=origin --push
    if errorlevel 1 (
        echo [!] Repo mungkin sudah ada. Mencoba push ke https://github.com/%GH_USER%/iphone-dex-windows.git ...
        git remote add origin "https://github.com/%GH_USER%/iphone-dex-windows.git" 2>nul
        git push -u origin main
        if errorlevel 1 (
            echo [ERROR] Push gagal. Cek pesan error di atas.
            pause
            exit /b 1
        )
    )
) else (
    echo [*] Mengunggah perubahan ke origin/main...
    git push -u origin main
    if errorlevel 1 (
        echo [ERROR] Push gagal. Cek pesan error di atas.
        pause
        exit /b 1
    )
)

echo.
echo [SUKSES] Kode sudah di-push ke GitHub!
echo [*] Membuka tab Actions di browser untuk melihat progress compile .ipa di macOS...
"%GH_BIN%" browse --actions
echo.
echo Setelah build di GitHub Actions selesai ^(centang hijau^), jalankan:
echo   tools\download_ipa.bat
echo untuk mengunduh file iPhoneDeXHost-unsigned.ipa ke folder dist\.
pause
