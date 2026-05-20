# -*- coding: utf-8 -*-
"""Android entry point.

Запускает локальный HTTP-сервер (server.py) и показывает нативный
android.webkit.WebView, который грузит наш веб-интерфейс из web/.
На десктопе для отладки просто открывает страницу в браузере.
"""

import os
import sys
import threading

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.utils import platform

from server import start_server


HERE     = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT = os.path.join(HERE, "web")


class PSStoreApp(App):
    title = "PS Store by Slava"

    def build(self):
        # 1) поднимаем backend
        self.base_url = start_server(WEB_ROOT)

        if platform == "android":
            # 2) показываем нативный WebView поверх Kivy-активности
            self._setup_android_webview(self.base_url)
            # Возвращаем «пустышку» — реальный UI это WebView
            return BoxLayout()

        # Десктоп — просто откроем в браузере (для отладки сервера)
        import webbrowser
        webbrowser.open(self.base_url)
        return Label(
            text=f"Server: {self.base_url}\nЗакрой это окно — браузер уже открылся",
            halign="center", valign="middle",
        )

    # ── Android ──────────────────────────────────────────────────────────

    def _setup_android_webview(self, url: str):
        from jnius import autoclass
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _setup():
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            WebView        = autoclass("android.webkit.WebView")
            WebViewClient  = autoclass("android.webkit.WebViewClient")
            activity = PythonActivity.mActivity

            wv = WebView(activity)
            s = wv.getSettings()
            s.setJavaScriptEnabled(True)
            s.setDomStorageEnabled(True)
            s.setUseWideViewPort(True)
            s.setLoadWithOverviewMode(True)
            s.setSupportZoom(False)
            s.setBuiltInZoomControls(False)
            # Не уходим во внешний браузер при кликах
            wv.setWebViewClient(WebViewClient())

            activity.setContentView(wv)
            wv.loadUrl(url)
            self._webview = wv  # держим ссылку, чтобы GC не выкинул

        _setup()


if __name__ == "__main__":
    PSStoreApp().run()
