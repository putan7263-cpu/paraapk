[app]

# Название и пакет
title = PS Store Поисковик
package.name = pspricechecker
package.domain = org.slava

# Исходники
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json
source.exclude_dirs = .venv, __pycache__, .git

# Версия
version = 1.0

# Зависимости (pip пакеты)
requirements = python3,kivy==2.2.1,kivymd==1.1.1,requests,certifi,charset-normalizer,idna,urllib3

# Точка входа
source.main = main.py

# Ориентация
orientation = portrait

# Полноэкранный режим (False = оставить статус-бар Android)
fullscreen = 0

# Иконка и загрузочный экран (раскомментировать когда будут файлы)
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

# Цвет загрузочного экрана (пока без картинки)
android.presplash_color = #0F1020


# ──────────────────────── Android ────────────────────────────────────────────

[buildozer]
log_level = 2
warn_on_root = 1

[app:android]

# Android API
android.minapi = 26
android.api    = 33
android.ndk    = 25b

# Архитектуры: arm64 — современные телефоны, armeabi-v7a — старые
android.archs = arm64-v8a, armeabi-v7a

# Разрешения
android.permissions = INTERNET, ACCESS_NETWORK_STATE

# gradle extras (если нужно)
# android.gradle_dependencies =

# Использовать gradle wrapper из p4a (рекомендуется)
android.accept_sdk_license = True

# Java версия (Buildozer сам определит, но лучше явно)
# android.java_version = 11
