# -*- coding: utf-8 -*-
"""PlayStation Store · Поисковик цен — pywebview версия."""

import os
import sys

import webview

from ui import Bridge


def main():
    # При PyInstaller --onefile web/ распаковывается в sys._MEIPASS
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    index = os.path.join(base, "web", "index.html")

    bridge = Bridge()

    window = webview.create_window(
        title="PlayStation Store · Поисковик цен от Slava",
        url=index,
        js_api=bridge,
        width=504,
        height=630,
        min_size=(448, 420),
        background_color="#0B0E1A",
        resizable=True,
    )
    bridge.window = window
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
