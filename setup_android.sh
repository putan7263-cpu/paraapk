#!/bin/bash
set -e

WIN_PROJECT="/mnt/c/Proekt/Slava PS Game Search APK"
LINUX_PROJECT="$HOME/psprice"
VENV="$HOME/buildozer-env"

echo "=== Копируем проект в Linux-файловую систему ==="
mkdir -p "$LINUX_PROJECT"
cp "$WIN_PROJECT/main.py"         "$LINUX_PROJECT/"
cp "$WIN_PROJECT/psapi.py"        "$LINUX_PROJECT/"
cp "$WIN_PROJECT/buildozer.spec"  "$LINUX_PROJECT/"

echo "=== Создаём окружение buildozer (Python 3.14) ==="
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
# --no-deps чтобы обойти конфликт cython<3 в зависимостях buildozer
"$VENV/bin/pip" install --no-deps "git+https://github.com/kivy/buildozer.git"
"$VENV/bin/pip" install pexpect packaging
"$VENV/bin/pip" install "cython>=3.0"

echo "=== Сборка APK ==="
source "$VENV/bin/activate"
cd "$LINUX_PROJECT"
buildozer android debug

echo "=== Копируем APK обратно на Windows ==="
mkdir -p "$WIN_PROJECT/bin"
cp "$LINUX_PROJECT"/bin/*.apk "$WIN_PROJECT/bin/"
echo "=== Готово! APK в папке C:\Proekt\Slava PS Game Search APK\bin\ ==="
