#!/bin/bash
set -e

WIN_PROJECT="/mnt/c/Proekt/Slava PS Game Search APK"
LINUX_PROJECT="$HOME/psprice"

echo "=== Копируем проект в Linux-файловую систему ==="
mkdir -p "$LINUX_PROJECT"
cp "$WIN_PROJECT/main.py"         "$LINUX_PROJECT/"
cp "$WIN_PROJECT/psapi.py"        "$LINUX_PROJECT/"
cp "$WIN_PROJECT/buildozer.spec"  "$LINUX_PROJECT/"

echo "=== Активируем окружение buildozer ==="
source ~/buildozer-env/bin/activate

echo "=== Сборка APK ==="
cd "$LINUX_PROJECT"
buildozer android debug

echo ""
echo "=== Копируем APK обратно на Windows ==="
mkdir -p "$WIN_PROJECT/bin"
cp "$LINUX_PROJECT"/bin/*.apk "$WIN_PROJECT/bin/"

echo "=== Готово! APK в папке C:\Proekt\Slava PS Game Search APK\bin\ ==="
