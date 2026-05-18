# -*- coding: utf-8 -*-
"""
PlayStation Store — Поисковик цен с автодополнением.
"""

import json
import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from types import SimpleNamespace
from urllib.parse import quote

import requests

# ───────────────────────────────── константы ──────────────────────────────────

REGIONS = [
    ("en-tr", "🇹🇷  Турция",  "TRY", "₺"),
    ("ru-ua", "🇺🇦  Украина", "UAH", "₴"),
]

PS_STORE_BASE = "https://store.playstation.com"

_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(_SCRIPT_DIR, "settings.json")

BG            = "#0F1020"
SURFACE       = "#181A35"
SURFACE_2     = "#1F2147"
BORDER        = "#2A2D5C"
ACCENT        = "#1E88FF"
ACCENT_HOV    = "#3FA0FF"
TEXT          = "#FFFFFF"
TEXT_DIM      = "#9AA0C7"
TEXT_MUTED    = "#6E73A0"
SUCCESS       = "#22C55E"
DANGER        = "#EF4444"
PS_PLUS_COLOR = "#B8A9FF"

PRICE_FONT_SIZE = 22

# Таблица коэффициентов по умолчанию (min, max, коэффициент, добавка ₽)
DEFAULT_BRACKETS = [
    (1,    20,    7.0, 0),
    (21,   50,    4.3, 0),
    (51,   100,   3.9, 0),
    (101,  125,   3.6, 0),
    (126,  150,   3.6, 0),
    (151,  200,   3.6, 0),
    (201,  250,   3.3, 0),
    (251,  300,   3.3, 0),
    (301,  350,   3.1, 0),
    (351,  400,   3.1, 0),
    (401,  450,   3.1, 0),
    (451,  500,   2.7, 0),
    (501,  600,   2.6, 0),
    (601,  700,   2.6, 0),
    (701,  800,   2.6, 0),
    (801,  900,   2.5, 0),
    (901,  1000,  2.5, 0),
    (1001, 1100,  2.5, 0),
    (1101, 1200,  2.5, 0),
    (1201, 1300,  2.5, 0),
    (1301, 1400,  2.4, 0),
    (1401, 1500,  2.4, 0),
    (1501, 1700,  2.4, 0),
    (1701, 1900,  2.4, 0),
    (1901, 2100,  2.4, 0),
    (2101, 2300,  2.4, 0),
    (2301, 2500,  2.4, 0),
    (2501, 2700,  2.4, 0),
    (2701, 3000,  2.4, 0),
    (3001, 4000,  2.4, 0),
    (4000, 10000, 2.4, 0),
]


# ───────────────────────────────── утилиты ────────────────────────────────────

def get_price_params(price: float, brackets: list) -> tuple[float, float]:
    """Возвращает (коэффициент, добавка_₽) для заданной цены."""
    for row in brackets:
        mn, mx, c = float(row[0]), float(row[1]), float(row[2])
        add = float(row[3]) if len(row) > 3 else 0.0
        if mn <= price <= mx:
            return c, add
    last = brackets[-1] if brackets else [0, 0, 2.4, 0]
    return float(last[2]), float(last[3]) if len(last) > 3 else 0.0


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(regions_data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"regions": regions_data}, f, ensure_ascii=False, indent=2)


def clean_price(s) -> float:
    if s is None:
        return 0.0
    s = str(s)
    cleaned = re.sub(r'[^\d,.\s]', '', s).strip()
    if not cleaned:
        return 0.0
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        parts = cleaned.split(',')
        if len(parts[-1]) <= 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    cleaned = cleaned.replace(' ', '')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_json_scripts(html: str) -> list[dict]:
    results = []
    for raw in re.findall(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            results.append(json.loads(raw))
        except Exception:
            pass
    return results


# ───────────────────── PS Store: поиск + детали продукта ──────────────────────

class PSStoreAPI:
    def __init__(self, region: str):
        self.region = region
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,*/*",
        })

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not query or len(query) < 2:
            return []
        return self._html_search(query, limit)

    def _html_search(self, query: str, limit: int) -> list[dict]:
        try:
            url = f"{PS_STORE_BASE}/{self.region}/search/{quote(query)}"
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            html = r.text
        except Exception:
            return []

        results  = []
        seen_ids = set()

        for data in _parse_json_scripts(html):
            cache = data.get('cache', {})
            if not cache:
                continue
            for k, node in cache.items():
                if not isinstance(node, dict):
                    continue
                if node.get('__typename') not in ('Product', 'Concept'):
                    continue
                pid = node.get('id')
                name = node.get('name') or node.get('invariantName')
                if not pid or not name or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                price_info = self._extract_prices_from_cache(cache, node)
                results.append({
                    "name": name, "id": pid,
                    "price":                price_info.get("price", ""),
                    "original_price":       price_info.get("original_price", ""),
                    "discount_pct":         price_info.get("discount_pct", ""),
                    "ps_plus_price":        price_info.get("ps_plus_price", ""),
                    "ps_plus_discount_pct": price_info.get("ps_plus_discount_pct", ""),
                    "image_url":            self._extract_image_url(cache, node),
                    "url": f"{PS_STORE_BASE}/{self.region}/product/{pid}",
                })
            if results:
                break

        if not results:
            m = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                html, re.DOTALL,
            )
            if m:
                try:
                    blob = json.loads(m.group(1))
                    self._walk_next_data(blob, seen_ids, results)
                except Exception:
                    pass

        return results[:limit]

    @staticmethod
    def _extract_image_url(cache: dict, node: dict) -> str:
        """Извлекает URL обложки из медиа-массива узла Apollo-кеша."""
        PREFERRED = {'MASTER', 'PORTRAIT_BG', 'BACKGROUND', 'THUMB', 'THUMBNAIL'}
        media_list = node.get('media', [])
        fallback   = ''
        for item in media_list:
            if not isinstance(item, dict):
                continue
            # прямая запись
            if 'url' in item:
                role = item.get('role', '')
                url  = item['url']
                if not fallback:
                    fallback = url
                if role in PREFERRED:
                    return url
            # ссылка через __ref
            elif '__ref' in item:
                m = cache.get(item['__ref'], {})
                if isinstance(m, dict) and m.get('url'):
                    role = m.get('role', '')
                    url  = m['url']
                    if not fallback:
                        fallback = url
                    if role in PREFERRED:
                        return url
        return fallback

    @staticmethod
    def _extract_prices_from_cache(cache: dict, prod_node: dict) -> dict:
        webctas = prod_node.get('webctas', [])
        regular = None
        ps_plus = None

        for ref_obj in webctas:
            if not isinstance(ref_obj, dict):
                continue
            ref_key = ref_obj.get('__ref', '')
            cta = cache.get(ref_key, {})
            if not isinstance(cta, dict):
                continue
            price = cta.get('price')
            if not isinstance(price, dict):
                continue
            service = price.get('serviceBranding', [])
            if isinstance(service, list):
                if 'PS_PLUS' in service:
                    ps_plus = price
                elif 'NONE' in service or not service:
                    if regular is None:
                        regular = price

        result: dict = {}

        if regular:
            base = regular.get('basePrice') or ''
            disc = regular.get('discountedPrice') or ''
            text = regular.get('discountText') or ''
            if disc and base and disc != base:
                result['price']          = disc
                result['original_price'] = base
                result['discount_pct']   = text
            else:
                result['price']          = base or disc
                result['original_price'] = ''
                result['discount_pct']   = ''
        elif ps_plus:
            result['price']          = ps_plus.get('basePrice') or ''
            result['original_price'] = ''
            result['discount_pct']   = ''

        if ps_plus:
            ps_disc = ps_plus.get('discountedPrice') or ''
            ps_base = ps_plus.get('basePrice') or ''
            if ps_disc and ps_base and ps_disc != ps_base:
                result['ps_plus_price']        = ps_disc
                result['ps_plus_discount_pct'] = ps_plus.get('discountText') or ''
            elif ps_disc and not ps_base:
                result['ps_plus_price']        = ps_disc
                result['ps_plus_discount_pct'] = ps_plus.get('discountText') or ''

        return result

    @staticmethod
    def _extract_platforms_from_html(html: str) -> list[str]:
        found = set()
        for m in re.finditer(r'"platforms"\s*:\s*(\[[^\]]{1,300}\])', html):
            try:
                for item in json.loads(m.group(1)):
                    if isinstance(item, str):
                        up = item.upper()
                        if 'PS5' in up:
                            found.add('PS5')
                        elif 'PS4' in up:
                            found.add('PS4')
            except Exception:
                pass
            if found:
                break
        return sorted(found)

    @staticmethod
    def _extract_language_support_from_html(html: str) -> tuple[bool, bool]:
        has_voice = has_text = False
        for m in re.finditer(r'"spokenLanguages"\s*:\s*(\[[^\]]{1,2000}\])', html):
            try:
                if 'ru' in json.loads(m.group(1)):
                    has_voice = True
                    break
            except Exception:
                pass
        for m in re.finditer(r'"screenLanguages"\s*:\s*(\[[^\]]{1,2000}\])', html):
            try:
                if 'ru' in json.loads(m.group(1)):
                    has_text = True
                    break
            except Exception:
                pass
        return has_voice, has_text

    def _walk_next_data(self, blob, seen_ids, results):
        region = self.region

        def extract_cta_price(node):
            price = orig = disc = ''
            p = node.get('price')
            if isinstance(p, dict):
                price = p.get('discountedPrice') or p.get('basePrice') or ''
                orig  = p.get('basePrice') or ''
                disc  = p.get('discountText') or ''
                if price == orig:
                    orig = ''
            for cta in (node.get('webctas') or []):
                if not isinstance(cta, dict):
                    continue
                cp = cta.get('price')
                if isinstance(cp, dict) and not price:
                    price = cp.get('discountedPrice') or cp.get('basePrice') or ''
                    orig  = cp.get('basePrice') or ''
                    disc  = cp.get('discountText') or ''
                    if price == orig:
                        orig = ''
            return price, orig, disc

        def walk(node):
            if isinstance(node, dict):
                if (node.get('__typename') in ('Product', 'Concept')
                        and node.get('id') and node.get('name')
                        and node['id'] not in seen_ids):
                    seen_ids.add(node['id'])
                    price, orig, disc = extract_cta_price(node)
                    results.append({
                        "name": node['name'], "id": node['id'],
                        "price": price, "original_price": orig,
                        "discount_pct": disc,
                        "ps_plus_price": '', "ps_plus_discount_pct": '',
                        "url": f"{PS_STORE_BASE}/{region}/product/{node['id']}",
                    })
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(blob)

    def fetch_product_details(self, product_id: str) -> dict:
        if not product_id:
            return {}
        try:
            url = f"{PS_STORE_BASE}/{self.region}/product/{product_id}"
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
        except Exception:
            return {}

        html = r.text
        has_trial = bool(re.search(r'"TRIAL"|"trial_play"|"TRY_FREE"|"FREE_TRIAL"', html))

        for data in _parse_json_scripts(html):
            if product_id not in json.dumps(data):
                continue
            cache = data.get('cache', {})
            if not cache:
                continue

            # Собираем все узлы Product/Concept с нужным product_id
            candidate_nodes = [
                v for k, v in cache.items()
                if isinstance(v, dict)
                and v.get('__typename') in ('Product', 'Concept')
                and product_id in k
            ]
            if not candidate_nodes:
                continue

            # Ищем первый узел у которого есть реальная цена (пропускаем trial / бесплатные)
            for prod_node in candidate_nodes:
                price_info = self._extract_prices_from_cache(cache, prod_node)
                has_price    = bool(price_info.get('price'))
                ps_plus_val  = clean_price(price_info.get('ps_plus_price', ''))
                has_ps_price = ps_plus_val > 0
                if not has_price and not has_ps_price:
                    continue
                name = (prod_node.get('name') or prod_node.get('invariantName') or '')
                platforms = PSStoreAPI._extract_platforms_from_html(html)
                has_ru_voice, has_ru_text = PSStoreAPI._extract_language_support_from_html(html)
                return {
                    "name":                 name,
                    "price":                price_info.get('price', ''),
                    "original_price":       price_info.get('original_price', ''),
                    "discount_pct":         price_info.get('discount_pct', ''),
                    "ps_plus_price":        price_info.get('ps_plus_price', ''),
                    "ps_plus_discount_pct": price_info.get('ps_plus_discount_pct', ''),
                    "image_url":            self._extract_image_url(cache, prod_node),
                    "has_trial":            has_trial,
                    "platforms":            platforms,
                    "has_ru_voice":         has_ru_voice,
                    "has_ru_text":          has_ru_text,
                }

        # Запасной вариант: __NEXT_DATA__ (Next.js SSR — используется на некоторых страницах)
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if m:
            try:
                blob = json.loads(m.group(1))
                next_results: list[dict] = []
                seen: set = set()
                self._walk_next_data(blob, seen, next_results)
                for item in next_results:
                    if item.get("id") == product_id and (item.get("price") or item.get("ps_plus_price")):
                        nd_plats = PSStoreAPI._extract_platforms_from_html(html)
                        nd_voice, nd_text = PSStoreAPI._extract_language_support_from_html(html)
                        return {
                            "name":                 item.get("name", ""),
                            "price":                item.get("price", ""),
                            "original_price":       item.get("original_price", ""),
                            "discount_pct":         item.get("discount_pct", ""),
                            "ps_plus_price":        item.get("ps_plus_price", ""),
                            "ps_plus_discount_pct": item.get("ps_plus_discount_pct", ""),
                            "image_url":            "",
                            "has_trial":            has_trial,
                            "platforms":            nd_plats,
                            "has_ru_voice":         nd_voice,
                            "has_ru_text":          nd_text,
                        }
            except Exception:
                pass

        if has_trial:
            return {"has_trial": True}
        return {}


def _item_has_discount(item: dict) -> bool:
    """Возвращает True только при реальной скидке (не просто 'включено в подписку')."""
    disc_pct  = item.get("discount_pct") or ""
    orig      = item.get("original_price") or ""
    ps_price  = item.get("ps_plus_price") or ""
    reg_price = item.get("price") or ""
    # disc_pct считается скидкой только если содержит '%'
    real_disc = "%" in disc_pct and disc_pct not in ("0%", "-0%")
    # PS+ цена считается скидкой только если она > 0 И меньше обычной цены
    # (ноль = включено в подписку бесплатно; равная цена = просто PS+ цена без скидки)
    ps_val  = clean_price(ps_price) if ps_price else 0.0
    reg_val = clean_price(reg_price) if reg_price else 0.0
    real_ps = ps_val > 0 and (reg_val <= 0 or ps_val < reg_val)
    return bool(real_disc or orig or real_ps)


# ─────────────────────────────────── GUI ──────────────────────────────────────

class HoverButton(tk.Button):
    def __init__(self, master, hover_bg=None, normal_bg=None, **kw):
        super().__init__(master, **kw)
        self._normal = normal_bg or kw.get("bg", BG)
        self._hover  = hover_bg  or self._normal
        self.bind("<Enter>", lambda e: self._on_enter())
        self.bind("<Leave>", lambda e: self._on_leave())

    def _on_enter(self):
        if str(self["state"]) != "disabled":
            self.configure(bg=self._hover)

    def _on_leave(self):
        if str(self["state"]) != "disabled":
            self.configure(bg=self._normal)


class PSPriceCheckerApp:
    _SECRET_CODE = "9094549528"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PlayStation Store · Поисковик цен от Slava")
        self.root.geometry("650x820+200+30")
        self.root.minsize(610, 740)
        self.root.configure(bg=BG)

        cfg         = load_settings()
        regions_cfg = cfg.get("regions", {})

        # Загружаем таблицы коэффициентов для каждого региона
        self.region_brackets: dict[str, list] = {}
        for code, *_ in REGIONS:
            r = regions_cfg.get(code, {})
            raw = r.get("brackets")
            if raw and isinstance(raw, list) and len(raw) > 0:
                rows = []
                for b in raw:
                    row = list(b)
                    if len(row) == 3:          # старый формат без добавки
                        row.append(0)
                    rows.append(row)
                self.region_brackets[code] = rows
            else:
                self.region_brackets[code] = [list(b) for b in DEFAULT_BRACKETS]

        self.region_var      = tk.StringVar(value="en-tr")
        self.search_var      = tk.StringVar()
        self.free_price_var  = tk.StringVar()
        self.selected_game   = None
        self.api             = PSStoreAPI(self.region_var.get())
        self._params_dialog  = None
        self._muting_vars    = False   # защита от рекурсии при очистке полей

        self.search_suggestions  = []
        self.search_lock         = threading.Lock()
        self._search_after_id    = None
        self._prefetch_gen       = 0   # счётчик для отмены устаревших prefetch-задач

        self._init_styles()
        self._build_ui()

        self.free_price_var.trace_add("write", self._on_free_price_changed)

    # ── стили ─────────────────────────────────────────────────────────────

    def _init_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("PS.TCombobox",
                        fieldbackground=SURFACE_2, background=SURFACE_2,
                        foreground=TEXT, arrowcolor=TEXT, borderwidth=0,
                        relief="flat", padding=8)
        style.map("PS.TCombobox",
                  fieldbackground=[("readonly", SURFACE_2)],
                  selectbackground=[("readonly", SURFACE_2)],
                  selectforeground=[("readonly", TEXT)])

    # ── вспомогательные ───────────────────────────────────────────────────

    def _current_sym(self) -> str:
        code = self.region_var.get()
        for c, _, _, sym in REGIONS:
            if c == code:
                return sym
        return ""

    @staticmethod
    def _build_item_text(item: dict) -> str:
        name = item.get('name', '')
        if _item_has_discount(item):
            return name + '   Скидка!'
        return name

    # ── построение UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG, height=56)
        header.pack(fill="x", padx=20, pady=(14, 4))
        header.pack_propagate(False)
        tk.Label(header, text="PlayStation Store by Slava",
                 bg=BG, fg=TEXT, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(header, text="Поиск игр и расчёт цены в рублях",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI", 10)).pack(anchor="w")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=20)

        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True, padx=20, pady=10)

        # ── Регион ────────────────────────────────────────────────────────
        region_panel = self._make_card(content, "Регион магазина", "🌍")
        region_combo = ttk.Combobox(
            region_panel, state="readonly", style="PS.TCombobox",
            values=[f"{label}   ({code})" for code, label, *_ in REGIONS],
            font=("Segoe UI", 11),
        )
        region_combo.set(f"{REGIONS[0][1]}   ({REGIONS[0][0]})")
        region_combo.pack(fill="x")

        def on_region(_):
            sel = region_combo.get()
            for code, _label, *_ in REGIONS:
                if f"({code})" in sel:
                    self.region_var.set(code)
                    self.api = PSStoreAPI(code)
                    self._clear_results()
                    if hasattr(self, "free_price_sym_label"):
                        self.free_price_sym_label.configure(
                            text=f"Цена в {self._current_sym()}:")
                    break
        region_combo.bind("<<ComboboxSelected>>", on_region)

        # ── Поиск ─────────────────────────────────────────────────────────
        search_panel = self._make_card(content, "Название игры", "🎮")
        tk.Label(search_panel, text="Введите название (от 2 символов):",
                 bg=SURFACE, fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        self.search_entry = tk.Entry(
            search_panel, textvariable=self.search_var,
            bg=SURFACE_2, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=("Segoe UI", 12), highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
        )
        self.search_entry.pack(fill="x", ipady=8)
        self.search_entry.bind("<KeyRelease>", self._on_search_keyrelease)
        self.search_entry.bind("<Return>",     self._on_search_enter)
        # Явная поддержка вставки из буфера обмена (Ctrl+V / Shift+Ins)
        self.search_entry.bind("<Control-v>",   self._paste_to_search)
        self.search_entry.bind("<Control-V>",   self._paste_to_search)
        self.search_entry.bind("<Shift-Insert>", self._paste_to_search)

        s_wrap  = tk.Frame(search_panel, bg=BORDER)
        s_wrap.pack(fill="both", expand=True, pady=(6, 0))
        s_inner = tk.Frame(s_wrap, bg=SURFACE_2)
        s_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.suggestions_listbox = tk.Listbox(
            s_inner, bg=SURFACE_2, fg=TEXT, relief="flat",
            font=("Segoe UI", 10), height=5, selectbackground=ACCENT,
            selectforeground=TEXT, borderwidth=0, highlightthickness=0,
            activestyle="none",
        )
        self.suggestions_listbox.pack(side="left", fill="both", expand=True,
                                      padx=8, pady=6)
        self.suggestions_listbox.bind("<<ListboxSelect>>", self._on_suggestion_select)
        self.suggestions_listbox.bind("<Key>", self._on_key_press)
        sb = tk.Scrollbar(s_inner, command=self.suggestions_listbox.yview, bg=SURFACE)
        sb.pack(side="right", fill="y")
        self.suggestions_listbox.configure(yscrollcommand=sb.set)

        # ── Ручная цена ───────────────────────────────────────────────────
        self._build_free_price_card(content)

        # ── Результат ─────────────────────────────────────────────────────
        self._build_result_card(content)

    def _build_free_price_card(self, parent):
        body = self._make_card(parent, "Ручная цена", "✏")

        self.free_price_sym_label = tk.Label(
            body, text=f"Цена в {self._current_sym()} (вместо выбора игры):",
            bg=SURFACE, fg=TEXT_MUTED, font=("Segoe UI", 9),
        )
        self.free_price_sym_label.pack(anchor="w", pady=(0, 4))

        self.free_price_entry = tk.Entry(
            body, textvariable=self.free_price_var,
            bg=SURFACE_2, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=("Segoe UI", 12), highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
        )
        self.free_price_entry.pack(fill="x", ipady=8)

    def _build_result_card(self, parent):
        body = self._make_card(parent, "Оптовая цена", "💰")

        # Строка: название игры слева, теги платформы/языка справа
        name_row = tk.Frame(body, bg=SURFACE)
        name_row.pack(fill="x", pady=(0, 6))

        self.game_lang_label = tk.Label(
            name_row, text="", bg=SURFACE, fg=SUCCESS,
            font=("Segoe UI Semibold", 9),
        )
        self.game_lang_label.pack(side="right", padx=(4, 0))
        self.game_platform_label = tk.Label(
            name_row, text="", bg=SURFACE, fg=ACCENT,
            font=("Segoe UI Semibold", 9),
        )
        self.game_platform_label.pack(side="right", padx=(8, 0))

        self.result_name_label = tk.Label(
            name_row, text="—", bg=SURFACE, fg=TEXT,
            font=("Segoe UI Semibold", 12), anchor="w",
            justify="left", wraplength=380,
        )
        self.result_name_label.pack(side="left", fill="x", expand=True)

        self.trial_label = tk.Label(
            body, text="🎮  ДОСТУПНА ПРОБНАЯ ВЕРСИЯ",
            bg=SURFACE, fg="#f0a500",
            font=("Segoe UI Semibold", 9),
        )
        # изначально скрыт
        self.trial_label.pack_forget()

        # Один блок ОПТОВАЯ ЦЕНА — по центру
        self.price_wrap = tk.Frame(body, bg=SURFACE)
        self.price_wrap.pack(fill="x", pady=(4, 0))

        self.wholesale = self._build_price_box(self.price_wrap, "ОПТОВАЯ ЦЕНА", SUCCESS)

    def _build_price_box(self, parent, title: str, main_color: str) -> SimpleNamespace:
        box = tk.Frame(parent, bg=SURFACE_2, highlightthickness=1,
                       highlightbackground=BORDER)
        box.pack(fill="x", expand=True)

        tk.Label(box, text=title, bg=SURFACE_2, fg=TEXT_MUTED,
                 font=("Segoe UI Semibold", 8)).pack(anchor="center", padx=12, pady=(10, 4))

        row1 = tk.Frame(box, bg=SURFACE_2)
        row1.pack(anchor="center", padx=12)

        prefix_lbl = tk.Label(row1, text="", bg=SURFACE_2, fg=TEXT_MUTED,
                               font=("Segoe UI", 9))
        prefix_lbl.pack(side="left")

        price_lbl = tk.Label(row1, text="—", bg=SURFACE_2, fg=main_color,
                              font=("Segoe UI Bold", PRICE_FONT_SIZE), anchor="center")
        price_lbl.pack(side="left", padx=(2, 0))

        badge_lbl = tk.Label(row1, text="", bg=SURFACE_2, fg=DANGER,
                              font=("Segoe UI Semibold", 9))
        badge_lbl.pack(side="left", padx=(8, 0), pady=(4, 0))

        old_lbl = tk.Label(box, text="", bg=SURFACE_2, fg=TEXT_MUTED,
                           font=("Segoe UI", 10, "overstrike"))
        old_lbl.pack(anchor="center", padx=12)

        row3 = tk.Frame(box, bg=SURFACE_2)
        row3.pack(anchor="center", padx=12, pady=(2, 0))

        ps_prefix_lbl = tk.Label(row3, text="", bg=SURFACE_2, fg=TEXT_DIM,
                                  font=("Segoe UI Semibold", 9))
        ps_prefix_lbl.pack(side="left")

        ps_price_lbl = tk.Label(row3, text="", bg=SURFACE_2, fg=PS_PLUS_COLOR,
                                 font=("Segoe UI Bold", PRICE_FONT_SIZE))
        ps_price_lbl.pack(side="left", padx=(4, 0))

        ps_badge_lbl = tk.Label(row3, text="", bg=SURFACE_2, fg=PS_PLUS_COLOR,
                                 font=("Segoe UI Semibold", 9))
        ps_badge_lbl.pack(side="left", padx=(6, 0), pady=(4, 0))

        tk.Frame(box, bg=SURFACE_2, height=8).pack()

        return SimpleNamespace(
            price=price_lbl, prefix=prefix_lbl, badge=badge_lbl,
            old=old_lbl,
            ps_prefix=ps_prefix_lbl, ps_price=ps_price_lbl, ps_badge=ps_badge_lbl,
        )

    def _make_card(self, parent, title: str, icon: str = "", *, return_head: bool = False):
        outer = tk.Frame(parent, bg=BORDER)
        outer.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(outer, bg=SURFACE)
        inner.pack(fill="x", padx=1, pady=1)
        head = tk.Frame(inner, bg=SURFACE)
        head.pack(fill="x", padx=16, pady=(10, 6))
        if icon:
            tk.Label(head, text=icon, bg=SURFACE, fg=ACCENT,
                     font=("Segoe UI", 13)).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, bg=SURFACE, fg=TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        body = tk.Frame(inner, bg=SURFACE)
        body.pack(fill="x", padx=16, pady=(0, 12))
        if return_head:
            return head, body
        return body

    # ── ручная цена ───────────────────────────────────────────────────────

    def _on_free_price_changed(self, *args):
        if self._muting_vars:
            return
        val = self.free_price_var.get().strip()
        if val:
            # Снимаем выбор игры, не очищая поле поиска (он может остаться как подсказка)
            self.selected_game = None
            self._muting_vars = True
            self.search_var.set("")
            self._muting_vars = False
            self._clear_suggestions()
            self.result_name_label.configure(text="Ручная цена")
            self._update_game_info({})
            self._recalc_prices()
        else:
            self._reset_wholesale_display()

    # ── вставка из буфера обмена ──────────────────────────────────────────

    def _paste_to_search(self, event=None):
        try:
            text = self.root.clipboard_get()
            if not text:
                return "break"
            # Удаляем выделение если есть
            try:
                s = self.search_entry.index(tk.SEL_FIRST)
                e = self.search_entry.index(tk.SEL_LAST)
                self.search_entry.delete(s, e)
            except tk.TclError:
                pass
            self.search_entry.insert(tk.INSERT, text.strip())
        except tk.TclError:
            pass
        return "break"

    # ── скрытый код доступа к параметрам ─────────────────────────────────

    def _on_search_enter(self, event):
        if self.search_var.get().strip() == self._SECRET_CODE:
            self.search_var.set("")
            self._clear_suggestions()
            self._open_params_dialog()

    def _open_params_dialog(self):
        if self._params_dialog and self._params_dialog.winfo_exists():
            self._params_dialog.lift()
            self._params_dialog.focus_force()
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Параметры расчёта")
        dlg.configure(bg=BG)
        dlg.resizable(True, False)
        dlg.transient(self.root)
        self._params_dialog = dlg

        tk.Label(dlg, text="⚙  Коэффициенты расчёта цены",
                 bg=BG, fg=TEXT, font=("Segoe UI Semibold", 13)
                 ).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(dlg, text="Итоговая цена = цена × коэффициент + добавка ₽",
                 bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9)
                 ).pack(anchor="w", padx=20, pady=(0, 6))
        tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(0, 10))

        # Выбор региона
        region_bar = tk.Frame(dlg, bg=BG)
        region_bar.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(region_bar, text="Регион:", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))

        region_names = [f"{label}  ({code})" for code, label, *_ in REGIONS]
        dlg_region_var = tk.StringVar(value=region_names[0])
        region_cb = ttk.Combobox(region_bar, state="readonly", style="PS.TCombobox",
                                  textvariable=dlg_region_var,
                                  values=region_names, font=("Segoe UI", 10), width=28)
        region_cb.pack(side="left")

        # Временные StringVar для коэффициентов и добавок
        coeff_vars: dict[str, list[tk.StringVar]] = {}
        add_vars:   dict[str, list[tk.StringVar]] = {}
        for code, *_ in REGIONS:
            coeff_vars[code] = [
                tk.StringVar(value=str(row[2]))
                for row in self.region_brackets[code]
            ]
            add_vars[code] = [
                tk.StringVar(value=str(int(row[3]) if float(row[3]) == int(float(row[3])) else row[3]))
                for row in self.region_brackets[code]
            ]

        # Область таблицы
        table_outer = tk.Frame(dlg, bg=BG)
        table_outer.pack(fill="both", expand=True, padx=20)

        # Заголовок таблицы
        hdr = tk.Frame(table_outer, bg=SURFACE_2)
        hdr.pack(fill="x")
        for col_text, col_w in [("Мин", 7), ("Макс", 7), ("Коэффициент", 10), ("Добавка ₽", 9)]:
            tk.Label(hdr, text=col_text, bg=SURFACE_2, fg=TEXT_DIM,
                     font=("Segoe UI Semibold", 9), width=col_w,
                     anchor="center").pack(side="left", padx=4, pady=4)

        # Скролл-область для строк
        scroll_frame = tk.Frame(table_outer, bg=BG)
        scroll_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0, height=360)
        scrollbar = tk.Scrollbar(scroll_frame, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        rows_container = tk.Frame(canvas, bg=BG)
        canvas_window  = canvas.create_window((0, 0), window=rows_container, anchor="nw")

        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())
        rows_container.bind("<Configure>", on_configure)
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_window, width=e.width))

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Отрисовка строк для текущего региона
        row_widgets: list[tk.Frame] = []

        def draw_table(code: str):
            for w in row_widgets:
                w.destroy()
            row_widgets.clear()
            brackets = self.region_brackets[code]
            cvars    = coeff_vars[code]
            avars    = add_vars[code]
            for i, bkt in enumerate(brackets):
                bg_row = SURFACE if i % 2 == 0 else SURFACE_2
                row_f  = tk.Frame(rows_container, bg=bg_row)
                row_f.pack(fill="x")
                row_widgets.append(row_f)

                tk.Label(row_f, text=str(int(bkt[0])), bg=bg_row, fg=TEXT_DIM,
                         font=("Segoe UI", 10), width=7, anchor="center"
                         ).pack(side="left", padx=4, pady=2)
                tk.Label(row_f, text=str(int(bkt[1])), bg=bg_row, fg=TEXT_DIM,
                         font=("Segoe UI", 10), width=7, anchor="center"
                         ).pack(side="left", padx=4)
                ent_c = tk.Entry(row_f, textvariable=cvars[i], width=10,
                                 bg="#2A2D4A", fg=TEXT, insertbackground=TEXT,
                                 relief="flat", font=("Segoe UI Semibold", 10),
                                 highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=ACCENT, justify="center")
                ent_c.pack(side="left", padx=4, pady=2, ipady=2)
                ent_a = tk.Entry(row_f, textvariable=avars[i], width=9,
                                 bg="#1A2A1A", fg=SUCCESS, insertbackground=TEXT,
                                 relief="flat", font=("Segoe UI Semibold", 10),
                                 highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=SUCCESS, justify="center")
                ent_a.pack(side="left", padx=4, pady=2, ipady=2)

        draw_table(REGIONS[0][0])

        def on_region_change(_=None):
            sel = dlg_region_var.get()
            for code, label, *_ in REGIONS:
                if f"({code})" in sel:
                    draw_table(code)
                    break
        region_cb.bind("<<ComboboxSelected>>", on_region_change)

        tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(anchor="e", padx=20, pady=12)

        def on_save():
            for code, *_ in REGIONS:
                brackets = self.region_brackets[code]
                for i, (cv, av) in enumerate(zip(coeff_vars[code], add_vars[code])):
                    try:
                        brackets[i][2] = float(cv.get().replace(',', '.'))
                    except ValueError:
                        pass
                    try:
                        brackets[i][3] = float(av.get().replace(',', '.'))
                    except ValueError:
                        pass
            data = {}
            for code, *_ in REGIONS:
                data[code] = {"brackets": self.region_brackets[code]}
            save_settings(data)
            self._recalc_prices()
            dlg.destroy()

        HoverButton(
            btn_row, text="Сохранить", command=on_save,
            bg=ACCENT, hover_bg=ACCENT_HOV, normal_bg=ACCENT, fg=TEXT,
            font=("Segoe UI Semibold", 10), relief="flat", borderwidth=0,
            padx=16, pady=8, cursor="hand2",
            activebackground=ACCENT_HOV, activeforeground=TEXT,
        ).pack(side="left", padx=(0, 8))

        HoverButton(
            btn_row, text="Закрыть", command=dlg.destroy,
            bg=SURFACE_2, hover_bg=BORDER, normal_bg=SURFACE_2, fg=TEXT_DIM,
            font=("Segoe UI", 10), relief="flat", borderwidth=0,
            padx=16, pady=8, cursor="hand2",
            activebackground=BORDER, activeforeground=TEXT,
        ).pack(side="left")

        self.root.update_idletasks()
        rx = self.root.winfo_x() + self.root.winfo_width()  // 2
        ry = self.root.winfo_y() + self.root.winfo_height() // 2
        dlg.update_idletasks()
        dlg.geometry(
            f"+{rx - dlg.winfo_width() // 2}+{ry - dlg.winfo_height() // 2}"
        )

    # ── автодополнение ────────────────────────────────────────────────────

    def _on_search_keyrelease(self, event):
        if self._muting_vars:
            return
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab",
                             "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return
        query = self.search_var.get().strip()
        if len(query) < 2:
            self._clear_suggestions()
            return
        if self._search_after_id:
            self.root.after_cancel(self._search_after_id)
        self._search_after_id = self.root.after(
            400, lambda: threading.Thread(
                target=self._fetch_suggestions, args=(query,), daemon=True
            ).start()
        )

    def _fetch_suggestions(self, query: str):
        try:
            results = self.api.search(query, limit=12)
        except Exception:
            results = []
        if self.search_var.get().strip() != query:
            return
        with self.search_lock:
            self.search_suggestions = results
        self.root.after(0, self._update_suggestions_ui)

    def _update_suggestions_ui(self):
        self.suggestions_listbox.delete(0, tk.END)
        with self.search_lock:
            items_snapshot = list(self.search_suggestions)
        for i, item in enumerate(items_snapshot):
            self.suggestions_listbox.insert(tk.END, self._build_item_text(item))
            if _item_has_discount(item):
                self.suggestions_listbox.itemconfigure(i, foreground=SUCCESS)
        # Запускаем фоновую предзагрузку скидок для всех игр в списке
        self._prefetch_gen += 1
        gen = self._prefetch_gen
        threading.Thread(
            target=self._prefetch_discounts,
            args=(items_snapshot, gen),
            daemon=True,
        ).start()

    def _on_suggestion_select(self, event):
        sel = self.suggestions_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        with self.search_lock:
            if idx >= len(self.search_suggestions):
                return
            game = dict(self.search_suggestions[idx])
        self.selected_game = game
        # Очищаем поле ручной цены
        self._muting_vars = True
        self.free_price_var.set("")
        self._muting_vars = False
        self.suggestions_listbox.focus_set()
        threading.Thread(target=self._refresh_selected_details, daemon=True).start()
        self._show_price()

    def _refresh_selected_details(self):
        if not self.selected_game:
            return
        details = self.api.fetch_product_details(self.selected_game["id"])
        if not details:
            return
        for field in ("price", "original_price", "discount_pct",
                      "ps_plus_price", "ps_plus_discount_pct", "name"):
            val = details.get(field)
            # Не затираем существующие данные пустыми строками из details
            if val is not None and (val != "" or not self.selected_game.get(field)):
                self.selected_game[field] = val
        if details.get("has_trial"):
            self.selected_game["has_trial"] = True
        for field in ("platforms", "has_ru_voice", "has_ru_text"):
            if details.get(field) is not None:
                self.selected_game[field] = details[field]
        self.root.after(0, self._show_price)
        self.root.after(0, self._refresh_listbox_discount)

    def _prefetch_discounts(self, items: list, gen: int):
        for i, item in enumerate(items):
            if gen != self._prefetch_gen:
                return
            details = self.api.fetch_product_details(item.get("id", ""))
            if not details:
                continue
            changed = False
            with self.search_lock:
                if i < len(self.search_suggestions):
                    si = self.search_suggestions[i]
                    for f in ("discount_pct", "original_price", "ps_plus_price",
                              "ps_plus_discount_pct", "platforms", "has_ru_voice", "has_ru_text"):
                        new_val = details.get(f)
                        if new_val is not None and new_val != si.get(f):
                            si[f] = new_val
                            changed = True
            if changed:
                idx = i
                self.root.after(0, lambda ix=idx: self._refresh_listbox_item(ix))

    def _refresh_listbox_item(self, idx: int):
        try:
            with self.search_lock:
                if idx >= len(self.search_suggestions):
                    return
                item = self.search_suggestions[idx]
            new_text = self._build_item_text(item)
            if self.suggestions_listbox.get(idx) != new_text:
                sel = self.suggestions_listbox.curselection()
                self.suggestions_listbox.delete(idx)
                self.suggestions_listbox.insert(idx, new_text)
                if _item_has_discount(item):
                    self.suggestions_listbox.itemconfigure(idx, foreground=SUCCESS)
                if sel and sel[0] == idx:
                    self.suggestions_listbox.selection_set(idx)
        except tk.TclError:
            pass

    def _refresh_listbox_discount(self):
        if not self.selected_game:
            return
        game_id = self.selected_game.get("id")
        idx = None
        with self.search_lock:
            for i, item in enumerate(self.search_suggestions):
                if item.get("id") != game_id:
                    continue
                for field in ("price", "original_price", "discount_pct",
                              "ps_plus_price", "ps_plus_discount_pct",
                              "platforms", "has_ru_voice", "has_ru_text"):
                    if self.selected_game.get(field) is not None:
                        item[field] = self.selected_game[field]
                idx = i
                break
        if idx is not None:
            self._refresh_listbox_item(idx)

    def _clear_suggestions(self):
        self.suggestions_listbox.delete(0, tk.END)
        with self.search_lock:
            self.search_suggestions = []

    def _reset_wholesale_display(self):
        ns = self.wholesale
        ns.prefix.configure(text="")
        ns.price.configure(text="—")
        ns.badge.configure(text="")
        ns.old.configure(text="")
        ns.ps_prefix.configure(text="")
        ns.ps_price.configure(text="")
        ns.ps_badge.configure(text="")

    def _clear_results(self):
        self.selected_game = None
        self.result_name_label.configure(text="—")
        self._update_game_info({})
        self.trial_label.pack_forget()
        self._reset_wholesale_display()
        self._clear_suggestions()

    # ── отображение цены ──────────────────────────────────────────────────

    def _update_game_info(self, game: dict):
        platforms = game.get('platforms') or []
        ps4 = any('PS4' in p.upper() for p in platforms)
        ps5 = any('PS5' in p.upper() for p in platforms)
        if ps4 and ps5:
            plat_text = '[PS4 и PS5]'
        elif ps5:
            plat_text = '[PS5]'
        elif ps4:
            plat_text = '[PS4]'
        else:
            plat_text = ''
        has_voice = game.get('has_ru_voice', False)
        has_text  = game.get('has_ru_text', False)
        if has_voice and has_text:
            lang_text = '[Звук+Текст]'
        elif has_text:
            lang_text = '[Текст]'
        elif has_voice:
            lang_text = '[Звук]'
        else:
            lang_text = ''
        self.game_platform_label.configure(text=plat_text)
        self.game_lang_label.configure(text=lang_text)

    def _show_price(self):
        if not self.selected_game:
            return
        self.result_name_label.configure(text=self.selected_game["name"])
        self._update_game_info(self.selected_game)
        if self.selected_game.get("has_trial"):
            self.trial_label.pack(fill="x", pady=(0, 4), before=self.price_wrap)
        else:
            self.trial_label.pack_forget()
        self._recalc_prices()

    def _recalc_prices(self):
        free_price = self.free_price_var.get().strip()

        if free_price:
            price_str   = free_price
            orig_str    = ""
            disc_pct    = ""
            ps_str      = ""
            ps_disc_pct = ""
        elif self.selected_game:
            g           = self.selected_game
            price_str   = g.get("price") or ""
            orig_str    = g.get("original_price") or ""
            disc_pct    = g.get("discount_pct") or ""
            ps_str      = g.get("ps_plus_price") or ""
            ps_disc_pct = g.get("ps_plus_discount_pct") or ""
        else:
            return

        brackets = self.region_brackets[self.region_var.get()]

        def to_rub(price_s: str):
            val = clean_price(price_s)
            if val == 0:
                return None
            coeff, add = get_price_params(val, brackets)
            return round(round(val * coeff + add) / 10) * 10

        def fmt(amt):
            return f"{amt} ₽" if amt is not None else ""

        has_regular_discount = bool(orig_str and disc_pct)
        has_ps_plus          = bool(ps_str)

        reg  = to_rub(price_str)
        orig = to_rub(orig_str)
        ps   = to_rub(ps_str)

        ns = self.wholesale

        if reg is not None:
            ns.price.configure(text=fmt(reg))
            if has_regular_discount:
                ns.prefix.configure(text="")
                ns.badge.configure(text=f"СКИДКА {disc_pct}")
                ns.old.configure(text=fmt(orig))
            elif has_ps_plus:
                ns.prefix.configure(text="Обычная ")
                ns.badge.configure(text="")
                ns.old.configure(text="")
            else:
                ns.prefix.configure(text="")
                ns.badge.configure(text="")
                ns.old.configure(text="")
        else:
            ns.prefix.configure(text="")
            ns.price.configure(text="—")
            ns.badge.configure(text="")
            ns.old.configure(text="")

        if has_ps_plus and ps is not None:
            ns.ps_prefix.configure(text="PS+  ")
            ns.ps_price.configure(text=fmt(ps))
            ns.ps_badge.configure(
                text=f"СКИДКА {ps_disc_pct}" if ps_disc_pct else "")
        else:
            ns.ps_prefix.configure(text="")
            ns.ps_price.configure(text="")
            ns.ps_badge.configure(text="")

    def _on_key_press(self, event):
        if event.char == "=":
            self._open_in_browser()
            return "break"

    def _open_in_browser(self):
        if not self.selected_game or not self.selected_game.get("url"):
            return
        webbrowser.open(self.selected_game["url"])


# ─────────────────────────────────── main ─────────────────────────────────────

def main():
    root = tk.Tk()
    PSPriceCheckerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
