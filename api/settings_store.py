# -*- coding: utf-8 -*-
"""Загрузка/сохранение settings.json (таблицы коэффициентов по регионам)."""

import json
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller: settings.json лежит рядом с .exe
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETTINGS_FILE = os.path.join(_BASE_DIR, "settings.json")


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(regions_data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"regions": regions_data}, f, ensure_ascii=False, indent=2)
