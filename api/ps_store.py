# -*- coding: utf-8 -*-
"""Клиент PlayStation Store: поиск и детали продукта.

Логика парсинга идентична оригинальной Tkinter-версии (ps_price_checker.py).
"""

import json
import re
from urllib.parse import quote

import requests

from .constants import PS_STORE_BASE
from .pricing import clean_price


SUB_LABEL_PRIORITY = [
    ('EA_PLAY',       'EA Play'),
    ('EA_ACCESS',     'EA Play'),
    ('UBISOFT_PLUS',  'Ubisoft+'),
    ('GAME_CATALOG',  'PS+ Catalog'),
    ('PREMIUM',       'PS+ Premium'),
    ('DELUXE',        'PS+ Deluxe'),
    ('EXTRA',         'PS+ Extra'),
]


def _is_real_price(s) -> bool:
    """Истина, если строка содержит цифры — т.е. это реальная цена,
    а не маркер вроде 'Included' / 'Free'."""
    return isinstance(s, str) and bool(re.search(r'\d', s))


def _label_subscription(brandings) -> str:
    for code, label in SUB_LABEL_PRIORITY:
        if code in brandings:
            return label
    return ''


_SCRIPT_RE = re.compile(
    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def _iter_json_scripts(html: str, must_contain=None):
    """Лениво парсит application/json блоки. Если задан must_contain — пропускает
    блоки, не содержащие подстроку (фильтр до дорогого json.loads)."""
    for m in _SCRIPT_RE.finditer(html):
        raw = m.group(1)
        if must_contain and must_contain not in raw:
            continue
        try:
            yield json.loads(raw)
        except Exception:
            continue


def _parse_json_scripts(html: str) -> list[dict]:
    return list(_iter_json_scripts(html))


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

    # ── публичный API ────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not query or len(query) < 2:
            return []
        return self._html_search(query, limit)

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
        unavailable = 'msgid_not_available_purchase' in html
        platforms = self._extract_platforms_from_html(html)
        has_ru_voice, has_ru_text = self._extract_language_support_from_html(html)

        # Базовая инфа доступна всегда — даже если цена не нашлась
        result = {
            "has_trial":    has_trial,
            "unavailable":  unavailable,
            "platforms":    platforms,
            "has_ru_voice": has_ru_voice,
            "has_ru_text":  has_ru_text,
        }

        chosen_node = None
        chosen_price: dict = {}
        chosen_cache: dict = {}

        # PS Store разбрасывает Apollo-кеш по нескольким <script type=application/json>.
        # Идём по всем подходящим, пока не найдём узел с реальной ценой.
        # Фильтр по сырой строке product_id — чтобы не парсить нерелевантные блоки.
        for data in _iter_json_scripts(html, must_contain=product_id):
            cache = data.get('cache', {})
            if not cache:
                continue
            candidate_nodes = [
                v for k, v in cache.items()
                if isinstance(v, dict)
                and v.get('__typename') in ('Product', 'Concept')
                and product_id in k
            ]
            if not candidate_nodes:
                continue

            # 1) Предпочитаем узел с реальной ценой
            priced_here = False
            for prod_node in candidate_nodes:
                pi = self._extract_prices_from_cache(cache, prod_node)
                if pi.get('price') or clean_price(pi.get('ps_plus_price', '')) > 0:
                    chosen_node, chosen_price, chosen_cache = prod_node, pi, cache
                    priced_here = True
                    break
            if priced_here:
                break

            # 2) webctas пустой → пробуем сканировать ВЕСЬ кеш этого блока
            #    (EA Play / Ubisoft+ — цены лежат на отдельных GameCTA)
            whole = self._extract_prices_from_whole_cache(cache)
            if whole.get('price') or whole.get('ps_plus_price'):
                chosen_node = candidate_nodes[0]
                chosen_price = whole
                chosen_cache = cache
                break

            # 3) Запоминаем первый найденный узел на случай, если цены нет вообще
            if chosen_node is None:
                chosen_node = candidate_nodes[0]
                chosen_price = self._extract_prices_from_cache(cache, candidate_nodes[0])
                chosen_cache = cache
            # обогащаем имя/подписку из whole, если в основном пусто
            for k, v in whole.items():
                if v and not chosen_price.get(k):
                    chosen_price[k] = v

        if chosen_node is not None:
            name = chosen_node.get('name') or chosen_node.get('invariantName') or ''
            if name:
                result["name"] = name
            img = self._extract_image_url(chosen_cache, chosen_node)
            if img:
                result["image_url"] = img
            for k in ("price", "original_price", "discount_pct",
                      "ps_plus_price", "ps_plus_discount_pct",
                      "sub_discount_price", "sub_discount_pct", "sub_discount_label",
                      "subscription"):
                v = chosen_price.get(k)
                if v:
                    result[k] = v

        # __NEXT_DATA__ — догружаем то, что не нашлось в Apollo-кеше
        # (часто там сидит цена для подписочных игр вроде F1 24)
        if not result.get('price') and not result.get('ps_plus_price'):
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
                        if item.get("id") != product_id:
                            continue
                        if not (item.get("price") or item.get("ps_plus_price") or item.get("subscription")):
                            continue
                        if not result.get("name") and item.get("name"):
                            result["name"] = item["name"]
                        for k in ("price", "original_price", "discount_pct",
                                  "ps_plus_price", "ps_plus_discount_pct",
                                  "sub_discount_price", "sub_discount_pct", "sub_discount_label",
                                  "subscription"):
                            v = item.get(k)
                            if v and not result.get(k):
                                result[k] = v
                        break
                except Exception:
                    pass

        return result

    # ── внутренние ───────────────────────────────────────────────────────

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
        PREFERRED = {'MASTER', 'PORTRAIT_BG', 'BACKGROUND', 'THUMB', 'THUMBNAIL'}
        media_list = node.get('media', [])
        fallback   = ''
        for item in media_list:
            if not isinstance(item, dict):
                continue
            if 'url' in item:
                role = item.get('role', '')
                url  = item['url']
                if not fallback:
                    fallback = url
                if role in PREFERRED:
                    return url
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
        webctas = prod_node.get('webctas') or []
        regular = None
        ps_plus = None
        sub_fallback = None         # CTA c полной включённостью (disc="Included" или ==base)
        sub_discount_cta = None     # CTA с реальной скидкой через подписку (две разные числовые цены)
        sub_inc_brandings: set[str] = set()   # бренды для full-inclusion
        sub_disc_brandings: set[str] = set()  # бренды для скидки

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
            if not isinstance(service, list):
                service = []

            if 'PS_PLUS' in service:
                ps_plus = price
                continue
            if 'NONE' in service or not service:
                if regular is None:
                    regular = price
                continue

            # Подписочный CTA — различаем «включено» и «скидка»
            base = price.get('basePrice') or ''
            disc = price.get('discountedPrice') or ''
            if _is_real_price(disc) and _is_real_price(base) and disc != base:
                # реальная скидка через подписку (10%/15%/…)
                if sub_discount_cta is None:
                    sub_discount_cta = price
                    sub_disc_brandings.update(service)
            else:
                # «Included» или нет цены — игра в подписке
                if sub_fallback is None and (base or disc):
                    sub_fallback = price
                sub_inc_brandings.update(service)

        # Если обычного CTA нет, но игра полностью в подписке — используем sub_fallback как regular
        used_sub_as_regular = False
        if regular is None and sub_fallback is not None:
            regular = sub_fallback
            used_sub_as_regular = True

        result: dict = {}

        if regular:
            base = regular.get('basePrice') or ''
            disc = regular.get('discountedPrice') or ''
            text = regular.get('discountText') or ''
            base_real = _is_real_price(base)
            disc_real = _is_real_price(disc)
            if disc_real and base_real and disc != base:
                result['price']          = disc
                result['original_price'] = base
                result['discount_pct']   = text
            elif base_real:
                result['price']          = base
            elif disc_real:
                result['price']          = disc
        elif ps_plus:
            ps_base = ps_plus.get('basePrice') or ''
            if _is_real_price(ps_base):
                result['price'] = ps_base

        if ps_plus:
            ps_disc = ps_plus.get('discountedPrice') or ''
            ps_base = ps_plus.get('basePrice') or ''
            ps_disc_real = _is_real_price(ps_disc)
            ps_base_real = _is_real_price(ps_base)
            if ps_disc_real and ps_base_real and ps_disc != ps_base:
                result['ps_plus_price']        = ps_disc
                result['ps_plus_discount_pct'] = ps_plus.get('discountText') or ''
            elif ps_base_real:
                result['ps_plus_price']        = ps_base
            elif ps_disc_real:
                result['ps_plus_price']        = ps_disc
                result['ps_plus_discount_pct'] = ps_plus.get('discountText') or ''

        # Скидка через подписку (НЕ полное включение) — показываем как вторую цену
        if sub_discount_cta is not None:
            sd_disc = sub_discount_cta.get('discountedPrice') or ''
            sd_base = sub_discount_cta.get('basePrice') or ''
            sd_text = sub_discount_cta.get('discountText') or ''
            if _is_real_price(sd_disc):
                result['sub_discount_price'] = sd_disc
                result['sub_discount_pct']   = sd_text
                result['sub_discount_label'] = (
                    _label_subscription(sub_disc_brandings) or 'EA Play'
                )
                # Если обычной (NONE) цены не нашлось, но есть скидочная через подписку —
                # подставляем basePrice из неё как обычную, чтобы можно было сравнить.
                if not result.get('price') and _is_real_price(sd_base):
                    result['price'] = sd_base

        # Тег подписки — только если игра действительно включена (полная включённость)
        if sub_fallback is not None or used_sub_as_regular:
            sub_label = _label_subscription(sub_inc_brandings)
            if sub_label:
                result['subscription'] = sub_label

        return result

    @staticmethod
    def _extract_prices_from_whole_cache(cache: dict) -> dict:
        """Сканирует ВСЕ CTA-объекты в кеше — на случай когда у Product
        webctas пустой, а цены живут на отдельных CTAMeta (EA Play и т.п.)."""
        synthetic = {
            'webctas': [
                {'__ref': k}
                for k, v in cache.items()
                if isinstance(v, dict) and isinstance(v.get('price'), dict)
            ]
        }
        if not synthetic['webctas']:
            return {}
        return PSStoreAPI._extract_prices_from_cache(cache, synthetic)

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

        def cta_to_info(cp):
            """Из dict price извлекает (price, orig, disc_text, subscription_label)."""
            base = cp.get('basePrice') or ''
            disc = cp.get('discountedPrice') or ''
            text = cp.get('discountText') or ''
            br   = cp.get('serviceBranding') or []
            if not isinstance(br, list):
                br = []
            sub_label = _label_subscription(br) if 'PS_PLUS' not in br else ''
            base_real = _is_real_price(base)
            disc_real = _is_real_price(disc)
            if disc_real and base_real and disc != base:
                return disc, base, text, sub_label
            if base_real:
                return base, '', '', sub_label
            if disc_real:
                return disc, '', text, sub_label
            return '', '', '', sub_label

        def extract(node):
            price = orig = disc = sub = ''
            p = node.get('price')
            if isinstance(p, dict):
                price, orig, disc, sub = cta_to_info(p)
            for cta in (node.get('webctas') or []):
                if not isinstance(cta, dict):
                    continue
                cp = cta.get('price')
                if not isinstance(cp, dict):
                    continue
                pp, oo, dd, ss = cta_to_info(cp)
                if not price and pp:
                    price, orig, disc = pp, oo, dd
                if not sub and ss:
                    sub = ss
            return price, orig, disc, sub

        def walk(node):
            if isinstance(node, dict):
                if (node.get('__typename') in ('Product', 'Concept')
                        and node.get('id') and node.get('name')
                        and node['id'] not in seen_ids):
                    seen_ids.add(node['id'])
                    price, orig, disc, sub = extract(node)
                    entry = {
                        "name": node['name'], "id": node['id'],
                        "price": price, "original_price": orig,
                        "discount_pct": disc,
                        "ps_plus_price": '', "ps_plus_discount_pct": '',
                        "image_url": '',
                        "url": f"{PS_STORE_BASE}/{region}/product/{node['id']}",
                    }
                    if sub:
                        entry["subscription"] = sub
                    results.append(entry)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(blob)
