# -*- coding: utf-8 -*-
"""Локальный HTTP сервер для мобильной (Android) версии.

Раздаёт статику из web/ и проксирует POST /api/<метод> в Bridge.
Используется только при запуске через main.py (Kivy+Android). На Windows
вместо него работает обычный pywebview.
"""

import json
import mimetypes
import os
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from ui import Bridge


HOST = "127.0.0.1"
DEFAULT_PORT = 38765

# Глобальный Bridge — один на весь процесс.
bridge = Bridge()


class Handler(BaseHTTPRequestHandler):
    web_root: str = ""  # выставляется при старте

    # Заглушаем стандартный лог в stderr — он многословный.
    def log_message(self, *_):
        pass

    # ── API ──────────────────────────────────────────────────────────────

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        method_name = self.path[5:].split("?", 1)[0]
        if not method_name or method_name.startswith("_"):
            self.send_error(404, "unknown method")
            return
        method = getattr(bridge, method_name, None)
        if method is None or not callable(method):
            self.send_error(404, "unknown method")
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "[]"
        try:
            args = json.loads(raw) if raw else []
        except Exception:
            args = []
        if not isinstance(args, list):
            args = [args]

        try:
            result = method(*args)
        except Exception as e:
            self.send_error(500, str(e))
            return

        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Статика ──────────────────────────────────────────────────────────

    def do_GET(self):
        rel = self.path.lstrip("/").split("?", 1)[0] or "index.html"
        if ".." in rel or rel.startswith("api/"):
            self.send_error(403)
            return
        full = os.path.normpath(os.path.join(self.web_root, rel))
        # защита от выхода за web_root
        if not full.startswith(os.path.abspath(self.web_root)):
            self.send_error(403)
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self.send_error(404)
            return

        mime, _ = mimetypes.guess_type(full)
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def _pick_port(start: int = DEFAULT_PORT, tries: int = 20) -> int:
    """Подобрать свободный порт начиная с start (на случай конфликта)."""
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, p))
                return p
            except OSError:
                continue
    return start  # пусть упадёт явно если ни один не свободен


def start_server(web_root: str, port: int = DEFAULT_PORT) -> str:
    """Запускает HTTP-сервер в фоновом потоке. Возвращает базовый URL."""
    Handler.web_root = os.path.abspath(web_root)
    chosen_port = _pick_port(port)
    httpd = HTTPServer((HOST, chosen_port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return f"http://{HOST}:{chosen_port}/"


if __name__ == "__main__":
    # для локальной отладки сервера
    import webbrowser, time
    here = os.path.dirname(os.path.abspath(__file__))
    url = start_server(os.path.join(here, "web"))
    print("running at", url)
    webbrowser.open(url)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
