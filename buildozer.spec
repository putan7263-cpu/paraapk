[app]

# (str) Title of your application
title = PS Store by Slava

# (str) Package name
package.name = psstorebyslava

# (str) Package domain (needs to be a reverse-DNS)
package.domain = ua.slava.psstore

# (str) Source code where the main.py live
source.dir = .

# Какие файлы включать (расширения)
source.include_exts = py,png,jpg,jpeg,kv,atlas,html,css,js,svg,json,ico,ttf,otf

# Включить всю папку web/ (статика для WebView)
source.include_patterns = web/*,web/**/*,api/*,ui/*

# Исключить виртуалки и сборочный мусор
source.exclude_dirs = .venv,.venv39,build,dist,bin,__pycache__,.github

# (str) Application versioning
version = 1.0.0

# (list) Application requirements — python-for-android сам подтянет зависимости
requirements = python3,kivy==2.3.0,requests,certifi,charset-normalizer,idna,urllib3

# (str) Supported orientation: portrait | landscape | sensor | all
orientation = portrait

# (bool) Fullscreen
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET

# (list) Android архитектуры для сборки
android.archs = arm64-v8a,armeabi-v7a

# (int) Минимальный API уровень (Android 5.0 = API 21)
android.minapi = 21

# (int) Целевой API
android.api = 34

# (str) NDK версия
android.ndk = 25b

# (bool) Резервное копирование
android.allow_backup = False

# (str) Иконка приложения (1024x1024 PNG рекомендуется)
icon.filename = %(source.dir)s/web/img/icon.png

# (str) Сплеш-экран (можно ту же иконку)
presplash.filename = %(source.dir)s/web/img/icon.png

# Цвет фона сплеш-экрана
android.presplash_color = #06070F

# Не запрашивать установку как launcher
android.entrypoint = org.kivy.android.PythonActivity


[buildozer]

# Log level (0 = error, 1 = info, 2 = debug)
log_level = 2

# Display warning if buildozer is run as root
warn_on_root = 1
