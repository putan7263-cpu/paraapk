# -*- coding: utf-8 -*-
"""JS↔Python мост для pywebview.

Все методы вызываются из JS как `pywebview.api.<method>(...)`.
"""

import threading
import webbrowser
from collections import OrderedDict

from api import (
    DEFAULT_BRACKETS,
    PSStoreAPI,
    REGION_BRACKETS,
    REGIONS,
    calc_rub,
    item_has_discount,
)

# Размер LRU-кеша подгруженных деталей и сколько верхних результатов префетчить.
_DETAILS_CACHE_MAX = 80
_PREFETCH_TOP_N = 5


SECRET_CODE = "9094549528"


class Bridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._region = REGIONS[0][0]
        self._api = PSStoreAPI(self._region)
        self._brackets = self._load_brackets()
        self.window = None  # выставляется из app.py после create_window

        # Кеш деталей: {(region, product_id) -> enriched dict}
        self._details_cache: OrderedDict = OrderedDict()
        self._cache_lock = threading.Lock()
        # Per-key Lock — чтобы конкурентные запросы на ту же игру
        # (например, префетч + клик) не плодили дублирующие HTTP
        self._key_locks: dict = {}
        self._key_locks_lock = threading.Lock()

    # ── загрузка/сохранение коэффициентов ────────────────────────────────

    def _load_brackets(self) -> dict:
        """Зашитые в код коэффициенты (REGION_BRACKETS). Внешний settings.json не читается."""
        out: dict[str, list] = {}
        for code, *_ in REGIONS:
            rows = REGION_BRACKETS.get(code) or DEFAULT_BRACKETS
            out[code] = [list(b) for b in rows]
        return out

    # ── публичные методы для JS ──────────────────────────────────────────

    def get_regions(self) -> list[dict]:
        return [
            {"code": code, "label": label, "currency": cur, "symbol": sym}
            for code, label, cur, sym in REGIONS
        ]

    def set_region(self, code: str) -> bool:
        for c, *_ in REGIONS:
            if c == code:
                with self._lock:
                    self._region = code
                    self._api = PSStoreAPI(code)
                # Кеш цен зависит от региона — сбрасываем
                with self._cache_lock:
                    self._details_cache.clear()
                return True
        return False

    def is_secret_code(self, text: str) -> bool:
        return (text or "").strip() == SECRET_CODE

    def search(self, query: str) -> list[dict]:
        """Поиск + расчёт цены в рублях для каждого результата."""
        try:
            results = self._api.search(query, limit=12)
        except Exception:
            results = []
        brackets = self._brackets[self._region]
        out = []
        for it in results:
            out.append(self._enrich(it, brackets))
        return out

    def fetch_details(self, product_id: str) -> dict:
        """Полные детали продукта + расчёт цен в рублях.
        Использует LRU-кеш, чтобы повторные клики были мгновенными,
        и per-key lock — чтобы дедуплицировать HTTP с параллельным префетчем."""
        if not product_id:
            return {}
        return self._fetch_one(self._region, self._api, product_id)

    def prefetch_details(self, ids) -> bool:
        """Фоновая предзагрузка деталей: пока пользователь смотрит в список,
        мы уже тянем HTTP — клик после этого будет мгновенный."""
        if not ids:
            return False
        region = self._region
        api = self._api  # снимок: если регион сменится, потоки не уйдут не туда
        def worker(pid: str):
            self._fetch_one(region, api, pid)
        for pid in list(ids)[:_PREFETCH_TOP_N]:
            if not pid:
                continue
            if self._cache_get(region, pid) is not None:
                continue
            threading.Thread(target=worker, args=(pid,), daemon=True).start()
        return True

    # ── внутреннее: кеш и одиночный fetch с дедупом ──────────────────────

    def _cache_get(self, region: str, pid: str):
        with self._cache_lock:
            v = self._details_cache.get((region, pid))
            if v is not None:
                self._details_cache.move_to_end((region, pid))
            return v

    def _cache_put(self, region: str, pid: str, value: dict) -> None:
        with self._cache_lock:
            self._details_cache[(region, pid)] = value
            self._details_cache.move_to_end((region, pid))
            while len(self._details_cache) > _DETAILS_CACHE_MAX:
                self._details_cache.popitem(last=False)

    def _key_lock(self, key) -> threading.Lock:
        with self._key_locks_lock:
            lk = self._key_locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._key_locks[key] = lk
            return lk

    def _fetch_one(self, region: str, api: PSStoreAPI, pid: str) -> dict:
        cached = self._cache_get(region, pid)
        if cached is not None:
            return cached
        key = (region, pid)
        with self._key_lock(key):
            # двойная проверка под локом — на случай если соседний поток уже сходил
            cached = self._cache_get(region, pid)
            if cached is not None:
                return cached
            try:
                details = api.fetch_product_details(pid) or {}
            except Exception:
                details = {}
            enriched = self._enrich(details, self._brackets[region], with_id=pid)
            self._cache_put(region, pid, enriched)
            return enriched

    def calc_manual(self, price_str: str) -> dict:
        """Расчёт оптовой цены по ручной локальной цене."""
        brackets = self._brackets[self._region]
        val = calc_rub(price_str, brackets)
        return {"rub": val}

    def get_brackets(self) -> dict:
        return {code: [list(r) for r in rows] for code, rows in self._brackets.items()}

    def save_brackets(self, data: dict) -> bool:
        """Коэффициенты зашиты в код — сохранение отключено."""
        return False

    def open_url(self, url: str) -> None:
        if url:
            webbrowser.open(url)

    def resize_window(self, height: int) -> bool:
        """Подгонка высоты окна под содержимое (вызывается из JS ResizeObserver)."""
        if not self.window:
            return False
        try:
            h = max(420, min(int(height) + 40, 1400))
            w = getattr(self.window, 'width', 504) or 504
            self.window.resize(w, h)
            return True
        except Exception:
            return False

    # ── вспомогательное ──────────────────────────────────────────────────

    def _enrich(self, item: dict, brackets: list, with_id: str = "") -> dict:
        """Добавляет к item рассчитанные цены в рублях + флаг discount."""
        out = dict(item)
        if with_id and not out.get("id"):
            out["id"] = with_id
        out["price_rub"]              = calc_rub(item.get("price", ""), brackets)
        out["original_price_rub"]     = calc_rub(item.get("original_price", ""), brackets)
        out["ps_plus_price_rub"]      = calc_rub(item.get("ps_plus_price", ""), brackets)
        out["sub_discount_price_rub"] = calc_rub(item.get("sub_discount_price", ""), brackets)
        out["has_discount"]           = item_has_discount(item)
        return out
