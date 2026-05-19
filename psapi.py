# -*- coding: utf-8 -*-
"""
Бизнес-логика PlayStation Store: поиск, парсинг цен, настройки.
Без зависимостей от GUI — используется и десктопом, и мобильным Kivy-приложением.
"""

import json
import re
import socket
import ssl
import struct
import urllib.error
import urllib.request
from random import randint
from urllib.parse import quote


# ── DNS fallback ─────────────────────────────────────────────────────────────
# Python на Android (p4a) часто не видит DNS-сервера системы (нет /etc/resolv.conf),
# и getaddrinfo падает с "No address associated with hostname". Подменяем резолвер
# на ручной UDP-запрос к публичным DNS, если стандартный не сработал.

_DNS_SERVERS = ("8.8.8.8", "1.1.1.1", "9.9.9.9")
_DNS_CACHE: dict = {}


def _dns_query_a(hostname: str, server: str, timeout: float = 4.0) -> str:
    tid = randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    qname = b""
    for part in hostname.split("."):
        if not part:
            continue
        b = part.encode("ascii")
        qname += bytes([len(b)]) + b
    qname += b"\x00"
    query = header + qname + struct.pack(">HH", 1, 1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query, (server, 53))
        data, _ = sock.recvfrom(1024)
    finally:
        sock.close()

    if len(data) < 12:
        raise OSError("DNS response too short")
    n_answers = struct.unpack(">H", data[6:8])[0]
    if n_answers == 0:
        raise OSError("DNS no answers")

    pos = 12
    while pos < len(data) and data[pos] != 0:
        if data[pos] & 0xC0:
            pos += 2
            break
        pos += data[pos] + 1
    else:
        pos += 1
    pos += 4

    for _ in range(n_answers):
        if pos >= len(data):
            break
        if data[pos] & 0xC0:
            pos += 2
        else:
            while pos < len(data) and data[pos] != 0:
                pos += data[pos] + 1
            pos += 1
        if pos + 10 > len(data):
            break
        atype, _aclass, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        if atype == 1 and rdlen == 4 and pos + 4 <= len(data):
            return "{}.{}.{}.{}".format(*data[pos:pos + 4])
        pos += rdlen
    raise OSError("No A record")


def _resolve(hostname: str) -> str:
    if hostname in _DNS_CACHE:
        return _DNS_CACHE[hostname]
    last_err = None
    for srv in _DNS_SERVERS:
        try:
            ip = _dns_query_a(hostname, srv)
            _DNS_CACHE[hostname] = ip
            return ip
        except Exception as e:
            last_err = e
    raise (last_err or OSError("DNS resolve failed"))


_orig_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, *args, **kwargs):
    try:
        return _orig_getaddrinfo(host, port, *args, **kwargs)
    except socket.gaierror:
        if not isinstance(host, str):
            raise
        ip = _resolve(host)
        try:
            port_int = int(port) if port is not None else 0
        except (TypeError, ValueError):
            port_int = 0
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port_int))]

socket.getaddrinfo = _patched_getaddrinfo


# ── мини-обёртка над urllib (вместо requests; работает на Android без certifi) ─

class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text
    def raise_for_status(self):
        if self.status_code >= 400:
            raise urllib.error.HTTPError("", self.status_code, "HTTP error", {}, None)


def _try_import_jnius():
    try:
        from jnius import autoclass
        return autoclass
    except Exception:
        return None

_AUTOCLASS = _try_import_jnius()


class _Session:
    def __init__(self):
        self.headers = {}
        self._ctx_strict = ssl.create_default_context()
        self._ctx_loose = ssl.create_default_context()
        try:
            self._ctx_loose.check_hostname = False
            self._ctx_loose.verify_mode = ssl.CERT_NONE
        except Exception:
            pass

    def get(self, url, timeout=15, verify=True):
        # На Android идём через Java HttpURLConnection — у него и DNS, и TLS, и сокеты работают.
        if _AUTOCLASS is not None:
            try:
                return self._get_java(url, timeout)
            except Exception:
                pass
        return self._get_urllib(url, timeout, verify)

    def _get_urllib(self, url, timeout, verify):
        ctx = self._ctx_strict if verify else self._ctx_loose
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                status = getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            try:
                raw = e.read() or b""
            except Exception:
                raw = b""
            status = e.code
        text = raw.decode("utf-8", errors="replace") if raw else ""
        return _Resp(status, text)

    def _get_java(self, url, timeout):
        URL = _AUTOCLASS("java.net.URL")
        Scanner = _AUTOCLASS("java.util.Scanner")
        u = URL(url)
        conn = u.openConnection()
        for k, v in self.headers.items():
            try:
                conn.setRequestProperty(k, v)
            except Exception:
                pass
        ms = int(timeout * 1000)
        conn.setConnectTimeout(ms)
        conn.setReadTimeout(ms)
        conn.setInstanceFollowRedirects(True)
        conn.connect()
        status = conn.getResponseCode()
        try:
            stream = conn.getInputStream() if 200 <= status < 400 else conn.getErrorStream()
        except Exception:
            stream = conn.getErrorStream()
        text = ""
        if stream is not None:
            sc = Scanner(stream)
            try:
                sc.useDelimiter("\\A")
                if sc.hasNext():
                    text = sc.next()
            finally:
                sc.close()
        try:
            conn.disconnect()
        except Exception:
            pass
        return _Resp(status, text)

# ──────────────────────────────────────────── константы ──────────────────────

REGIONS = [
    ("en-tr", "Турция",  "TRY", "₺"),
    ("ru-ua", "Украина", "UAH", "₴"),
]

PS_STORE_BASE = "https://store.playstation.com"

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

# ──────────────────────────────────────────── утилиты ────────────────────────

def get_price_params(price: float, brackets: list) -> tuple:
    for row in brackets:
        mn, mx, c = float(row[0]), float(row[1]), float(row[2])
        add = float(row[3]) if len(row) > 3 else 0.0
        if mn <= price <= mx:
            return c, add
    last = brackets[-1] if brackets else [0, 0, 2.4, 0]
    return float(last[2]), float(last[3]) if len(last) > 3 else 0.0


def load_settings(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(path: str, regions_data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
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


def _parse_json_scripts(html: str) -> list:
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


def _item_has_discount(item: dict) -> bool:
    disc_pct  = item.get("discount_pct") or ""
    orig      = item.get("original_price") or ""
    ps_price  = item.get("ps_plus_price") or ""
    reg_price = item.get("price") or ""
    real_disc = "%" in disc_pct and disc_pct not in ("0%", "-0%")
    ps_val    = clean_price(ps_price) if ps_price else 0.0
    reg_val   = clean_price(reg_price) if reg_price else 0.0
    real_ps   = ps_val > 0 and (reg_val <= 0 or ps_val < reg_val)
    return bool(real_disc or orig or real_ps)


# ──────────────────────────────── PS Store API ────────────────────────────────

class PSStoreAPI:
    def __init__(self, region: str):
        self.region = region
        self.session = _Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        })

    def search(self, query: str, limit: int = 10) -> list:
        if not query or len(query) < 2:
            return []
        return self._html_search(query, limit)

    def _html_search(self, query: str, limit: int) -> list:
        self.last_debug = ""
        try:
            url = f"{PS_STORE_BASE}/{self.region}/search/{quote(query)}"
            r = self.session.get(url, timeout=15, verify=False)
            self.last_debug = f"HTTP {r.status_code}, {len(r.text)}b"
            r.raise_for_status()
            html = r.text
        except Exception as e:
            self.last_debug = f"{type(e).__name__}: {str(e)[:100]}"
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
                pid  = node.get('id')
                name = node.get('name') or node.get('invariantName')
                if not pid or not name or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                price_info = self._extract_prices_from_cache(cache, node)
                results.append({
                    "name":                 name,
                    "id":                   pid,
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
    def _extract_platforms_from_html(html: str) -> list:
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
    def _extract_language_support_from_html(html: str) -> tuple:
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
                        "name":                 node['name'],
                        "id":                   node['id'],
                        "price":                price,
                        "original_price":       orig,
                        "discount_pct":         disc,
                        "ps_plus_price":        '',
                        "ps_plus_discount_pct": '',
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
            candidate_nodes = [
                v for k, v in cache.items()
                if isinstance(v, dict)
                and v.get('__typename') in ('Product', 'Concept')
                and product_id in k
            ]
            if not candidate_nodes:
                continue
            for prod_node in candidate_nodes:
                price_info   = self._extract_prices_from_cache(cache, prod_node)
                has_price    = bool(price_info.get('price'))
                ps_plus_val  = clean_price(price_info.get('ps_plus_price', ''))
                has_ps_price = ps_plus_val > 0
                if not has_price and not has_ps_price:
                    continue
                name = prod_node.get('name') or prod_node.get('invariantName') or ''
                platforms        = self._extract_platforms_from_html(html)
                has_ru_voice, has_ru_text = self._extract_language_support_from_html(html)
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

        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if m:
            try:
                blob = json.loads(m.group(1))
                nd_results: list = []
                seen: set = set()
                self._walk_next_data(blob, seen, nd_results)
                for item in nd_results:
                    if item.get("id") == product_id and (item.get("price") or item.get("ps_plus_price")):
                        nd_plats          = self._extract_platforms_from_html(html)
                        nd_voice, nd_text = self._extract_language_support_from_html(html)
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
