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
requirements = python3,kivy==2.2.1,openssl,pyjnius

# Точка входа
source.main = main.py

# Ориентация
orientation = portrait

# Полноэкранный режим (False = оставить статус-бар Android)
fullscreen = 0

# Цвет загрузочного экрана (пока без картинки)
android.presplash_color = #0F1020

# ──────────── Android-настройки (читаются buildozer из секции [app]) ─────────

# Android API
android.minapi = 26
android.api    = 33
android.ndk    = 25b

# Архитектуры: arm64 — современные телефоны, armeabi-v7a — старые
android.archs = arm64-v8a, armeabi-v7a

# Разрешения — ДОЛЖНЫ быть в [app], иначе buildozer их игнорирует
android.permissions = android.permission.INTERNET, android.permission.ACCESS_NETWORK_STATE

# Принять лицензии Android SDK автоматом
android.accept_sdk_license = True


[buildozer]
log_level = 2
warn_on_root = 1
