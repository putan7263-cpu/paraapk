# -*- coding: utf-8 -*-
"""
PlayStation Store - Поисковик цен (Android / iOS).
Чистый Kivy, без KivyMD. Сетевая логика в psapi.py.
"""

import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

from psapi import (
    REGIONS, DEFAULT_BRACKETS,
    PSStoreAPI, get_price_params, clean_price,
    load_settings, save_settings, _item_has_discount,
)

# ── цвета ────────────────────────────────────────────────────────────────────

def _c(h):
    return get_color_from_hex(h)

BG          = _c("#0F1020")
SURFACE     = _c("#181A35")
SURFACE_2   = _c("#1F2147")
BORDER      = _c("#2A2D5C")
ACCENT      = _c("#1E88FF")
ACCENT_DIM  = _c("#1E88FF55")
TEXT        = _c("#FFFFFF")
TEXT_DIM    = _c("#9AA0C7")
TEXT_MUTED  = _c("#6E73A0")
SUCCESS     = _c("#22C55E")
DANGER      = _c("#EF4444")
PS_PLUS_CLR = _c("#B8A9FF")
DARK_INPUT  = _c("#2A2D4A")


def _bg(widget, color):
    """Рисует цветной прямоугольник на canvas.before виджета."""
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda *_: setattr(rect, 'pos', widget.pos),
        size=lambda *_: setattr(rect, 'size', widget.size),
    )
    return rect


class TapRow(ButtonBehavior, BoxLayout):
    pass


# ── приложение ───────────────────────────────────────────────────────────────

class PSApp(App):
    _SECRET = "9094549528"

    def build(self):
        self.title = "PS Store Поисковик"
        if os.environ.get("KIVY_DESKTOP_TEST"):
            Window.size = (400, 720)
        self._init_state()
        return self._build_root()

    def on_start(self):
        path = os.path.join(self.user_data_dir, "settings.json")
        self._settings_file = path
        cfg = load_settings(path)
        if not cfg:
            bundled = os.path.join(self.directory, "settings.json")
            cfg = load_settings(bundled)
        regions_cfg = cfg.get("regions", {})
        for code, *_ in REGIONS:
            r = regions_cfg.get(code, {})
            raw = r.get("brackets")
            if raw and isinstance(raw, list) and raw:
                rows = []
                for b in raw:
                    row = list(b)
                    if len(row) == 3:
                        row.append(0)
                    rows.append(row)
                self.region_brackets[code] = rows

    def _init_state(self):
        self._region   = REGIONS[0][0]
        self._api      = PSStoreAPI(self._region)
        self._sugg     = []
        self._lock     = threading.Lock()
        self._search_ev = None
        self._pf_gen   = 0
        self._selected = None
        self._settings_file = None
        self._muting   = False
        self._sugg_popup = None
        self.region_brackets = {
            code: [list(b) for b in DEFAULT_BRACKETS]
            for code, *_ in REGIONS
        }

    # ── корневой UI ──────────────────────────────────────────────────────────

    def _build_root(self):
        root = BoxLayout(orientation="vertical")
        _bg(root, BG)

        root.add_widget(self._build_header())
        root.add_widget(self._build_region_row())
        root.add_widget(self._build_search_block())
        root.add_widget(self._build_free_price_block())
        root.add_widget(Widget())  # растяжка
        root.add_widget(self._build_result_block())

        return root

    def _build_header(self):
        hdr = BoxLayout(
            orientation="vertical",
            size_hint=(1, None), height=dp(54),
            padding=[dp(14), dp(6), dp(14), dp(6)],
        )
        _bg(hdr, SURFACE)
        hdr.add_widget(Label(
            text="PlayStation Store by Slava",
            color=TEXT, font_size=sp(17), bold=True,
            halign="left", valign="middle",
            size_hint=(1, None), height=dp(26),
        )).bind(size=lambda lbl, _: setattr(lbl, "text_size", lbl.size)) if False else None
        # лейблы — простые, без bind size→text_size, т.к. высота фиксирована
        t1 = Label(
            text="PlayStation Store by Slava",
            color=TEXT, font_size=sp(17), bold=True,
            size_hint=(1, None), height=dp(26),
        )
        t2 = Label(
            text="Поиск игр · расчёт цены в рублях",
            color=TEXT_DIM, font_size=sp(11),
            size_hint=(1, None), height=dp(18),
        )
        hdr.clear_widgets()
        hdr.add_widget(t1)
        hdr.add_widget(t2)
        return hdr

    # ── регион ───────────────────────────────────────────────────────────────

    def _build_region_row(self):
        wrap = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None), height=dp(48),
            padding=[dp(10), dp(6), dp(10), dp(6)],
            spacing=dp(6),
        )
        self._region_btns = {}
        for code, label, *_ in REGIONS:
            btn = Button(
                text=label,
                font_size=sp(13),
                background_normal="",
                background_color=(0, 0, 0, 0),
                color=TEXT_DIM,
            )
            btn._code = code
            btn.bind(on_release=lambda b: self._select_region(b._code))
            self._region_btns[code] = btn
            wrap.add_widget(btn)
        self._refresh_region_btns()
        return wrap

    def _refresh_region_btns(self):
        for code, btn in self._region_btns.items():
            if code == self._region:
                btn.background_color = ACCENT_DIM
                btn.color = TEXT
                btn.bold = True
            else:
                btn.background_color = SURFACE_2
                btn.color = TEXT_DIM
                btn.bold = False

    def _select_region(self, code):
        self._region = code
        self._api = PSStoreAPI(code)
        self._refresh_region_btns()
        self._free_hint.text = f"Цена в {self._current_sym()} (вместо поиска):"
        self._clear_results()

    def _current_sym(self):
        for c, _, _, sym in REGIONS:
            if c == self._region:
                return sym
        return ""

    # ── поиск ────────────────────────────────────────────────────────────────

    def _build_search_block(self):
        wrap = BoxLayout(
            orientation="vertical",
            size_hint=(1, None), height=dp(86),
            padding=[dp(10), dp(2), dp(10), dp(4)],
            spacing=dp(4),
        )
        wrap.add_widget(Label(
            text="Название игры (от 2 символов):",
            color=TEXT_MUTED, font_size=sp(11),
            size_hint=(1, None), height=dp(18),
            halign="left",
        ))
        self._search_tf = TextInput(
            hint_text="Введите название...",
            multiline=False,
            background_color=DARK_INPUT,
            foreground_color=TEXT,
            cursor_color=TEXT,
            hint_text_color=TEXT_MUTED,
            font_size=sp(15),
            size_hint=(1, None), height=dp(46),
            padding=[dp(10), dp(12), dp(10), dp(10)],
        )
        self._search_tf.bind(text=self._on_search_text)
        self._search_tf.bind(on_text_validate=self._on_search_submit)
        wrap.add_widget(self._search_tf)

        self._status_lbl = Label(
            text="",
            color=TEXT_MUTED, font_size=sp(11),
            size_hint=(1, None), height=dp(48),
            halign="left", valign="top",
        )
        self._status_lbl.bind(size=lambda l, _: setattr(l, "text_size", (l.width, l.height)))
        wrap.add_widget(self._status_lbl)
        wrap.height = dp(134)
        return wrap

    def _on_search_text(self, instance, value):
        if self._muting:
            return
        query = value.strip()
        if query == self._SECRET:
            self._muting = True
            instance.text = ""
            self._muting = False
            Clock.schedule_once(lambda dt: self._open_params(), 0.1)
            return
        if len(query) < 2:
            self._status_lbl.text = ""
            return
        if self._search_ev:
            self._search_ev.cancel()
        self._status_lbl.text = "Поиск..."
        self._search_ev = Clock.schedule_once(
            lambda dt: threading.Thread(
                target=self._fetch_sugg, args=(query,), daemon=True
            ).start(),
            0.4,
        )

    def _on_search_submit(self, instance):
        query = instance.text.strip()
        if query == self._SECRET:
            self._muting = True
            instance.text = ""
            self._muting = False
            self._open_params()
            return
        if len(query) >= 2:
            threading.Thread(
                target=self._fetch_sugg, args=(query,), daemon=True
            ).start()

    def _fetch_sugg(self, query):
        err = None
        results = []
        try:
            results = self._api.search(query, limit=12)
        except Exception as e:
            err = str(e)[:60]
        if self._search_tf.text.strip() != query:
            return
        with self._lock:
            self._sugg = results
        dbg = getattr(self._api, "last_debug", "")
        def _ui(_):
            if err:
                self._status_lbl.text = f"Ошибка: {err}"
            elif not results:
                self._status_lbl.text = f"Не найдено  ({dbg})" if dbg else "Не найдено"
            else:
                self._status_lbl.text = f"Найдено: {len(results)}"
                self._open_sugg_popup()
        Clock.schedule_once(_ui, 0)

    def _open_sugg_popup(self):
        with self._lock:
            items = list(self._sugg)
        if not items:
            return
        # Закрыть предыдущий попап, если открыт
        if self._sugg_popup is not None:
            try:
                self._sugg_popup.dismiss()
            except Exception:
                pass
            self._sugg_popup = None

        content = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(6))
        _bg(content, BG)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        col.bind(minimum_height=col.setter("height"))
        scroll.add_widget(col)
        content.add_widget(scroll)

        for i, game in enumerate(items):
            has_disc = _item_has_discount(game)
            name = game.get("name", "")
            row = TapRow(
                orientation="horizontal",
                size_hint=(1, None), height=dp(56),
                padding=[dp(10), dp(6)],
            )
            _bg(row, SURFACE if i % 2 == 0 else SURFACE_2)
            lbl = Label(
                text=name + ("   [color=22C55E]Скидка![/color]" if has_disc else ""),
                markup=True,
                color=SUCCESS if has_disc else TEXT,
                font_size=sp(13),
                halign="left", valign="middle",
                shorten=True, shorten_from="right",
            )
            lbl.bind(size=lambda l, _: setattr(l, "text_size", (l.width - dp(4), l.height)))
            row.add_widget(lbl)
            row.bind(on_release=lambda _, g=game: self._on_sugg_tap(g))
            col.add_widget(row)

        close_btn = Button(
            text="Закрыть",
            size_hint=(1, None), height=dp(44),
            background_normal="", background_color=SURFACE_2,
            color=TEXT_DIM, font_size=sp(13),
        )
        content.add_widget(close_btn)

        popup = Popup(
            title="Выберите игру",
            title_color=TEXT,
            title_size=sp(14),
            content=content,
            size_hint=(0.95, 0.85),
            background_color=BG,
            separator_color=BORDER,
        )
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        self._sugg_popup = popup
        popup.open()

        # фоновая предзагрузка скидок — не критично
        self._pf_gen += 1
        gen = self._pf_gen
        with self._lock:
            snap = list(self._sugg)
        threading.Thread(
            target=self._prefetch, args=(snap, gen), daemon=True
        ).start()

    def _on_sugg_tap(self, game):
        self._selected = dict(game)
        self._muting = True
        self._search_tf.text = game.get("name", "")
        self._free_tf.text = ""
        self._muting = False
        if self._sugg_popup is not None:
            try:
                self._sugg_popup.dismiss()
            except Exception:
                pass
            self._sugg_popup = None
        self._show_price()
        threading.Thread(target=self._refresh_details, daemon=True).start()

    def _prefetch(self, items, gen):
        for i, item in enumerate(items):
            if gen != self._pf_gen:
                return
            details = self._api.fetch_product_details(item.get("id", ""))
            if not details:
                continue
            with self._lock:
                if i < len(self._sugg):
                    si = self._sugg[i]
                    for f in ("discount_pct", "original_price",
                              "ps_plus_price", "ps_plus_discount_pct"):
                        nv = details.get(f)
                        if nv is not None:
                            si[f] = nv

    # ── ручная цена ──────────────────────────────────────────────────────────

    def _build_free_price_block(self):
        wrap = BoxLayout(
            orientation="vertical",
            size_hint=(1, None), height=dp(82),
            padding=[dp(10), dp(2), dp(10), dp(4)],
            spacing=dp(4),
        )
        self._free_hint = Label(
            text=f"Цена в {self._current_sym()} (вместо поиска):",
            color=TEXT_MUTED, font_size=sp(11),
            size_hint=(1, None), height=dp(18),
            halign="left",
        )
        wrap.add_widget(self._free_hint)
        self._free_tf = TextInput(
            hint_text="Ввести цену вручную...",
            multiline=False,
            input_filter="float",
            background_color=DARK_INPUT,
            foreground_color=TEXT,
            cursor_color=TEXT,
            hint_text_color=TEXT_MUTED,
            font_size=sp(15),
            size_hint=(1, None), height=dp(46),
            padding=[dp(10), dp(12), dp(10), dp(10)],
        )
        self._free_tf.bind(text=self._on_free_text)
        wrap.add_widget(self._free_tf)
        return wrap

    def _on_free_text(self, instance, value):
        if self._muting:
            return
        if value.strip():
            self._selected = None
            self._muting = True
            self._search_tf.text = ""
            self._muting = False
            self._name_lbl.text = "Ручная цена"
            self._plat_lbl.text = ""
            self._lang_lbl.text = ""
            self._trial_lbl.opacity = 0
            self._recalc()
        else:
            self._reset_display()

    # ── результат (нижний блок) ──────────────────────────────────────────────

    def _build_result_block(self):
        outer = BoxLayout(
            orientation="vertical",
            size_hint=(1, None), height=dp(190),
        )
        _bg(outer, SURFACE)

        sep = Widget(size_hint=(1, None), height=dp(1))
        _bg(sep, BORDER)
        outer.add_widget(sep)

        inner = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            padding=[dp(12), dp(6), dp(12), dp(6)],
            spacing=dp(3),
        )
        outer.add_widget(inner)

        # Строка с названием + теги
        name_row = BoxLayout(size_hint=(1, None), height=dp(24), spacing=dp(4))
        self._name_lbl = Label(
            text="—", color=TEXT, font_size=sp(13), bold=True,
            halign="left", valign="middle", shorten=True, shorten_from="right",
            size_hint=(1, 1),
        )
        self._name_lbl.bind(size=lambda l, _: setattr(l, "text_size", (l.width, l.height)))
        self._plat_lbl = Label(
            text="", color=ACCENT, font_size=sp(11),
            size_hint=(None, 1), width=dp(80),
        )
        self._lang_lbl = Label(
            text="", color=SUCCESS, font_size=sp(11),
            size_hint=(None, 1), width=dp(100),
        )
        name_row.add_widget(self._name_lbl)
        name_row.add_widget(self._plat_lbl)
        name_row.add_widget(self._lang_lbl)
        inner.add_widget(name_row)

        self._trial_lbl = Label(
            text="ДОСТУПНА ПРОБНАЯ ВЕРСИЯ",
            color=_c("#f0a500"), font_size=sp(11), bold=True,
            size_hint=(1, None), height=dp(18), opacity=0,
        )
        inner.add_widget(self._trial_lbl)

        # Оптовая цена — заголовок
        inner.add_widget(Label(
            text="ОПТОВАЯ ЦЕНА",
            color=TEXT_MUTED, font_size=sp(10), bold=True,
            size_hint=(1, None), height=dp(16),
        ))

        # Строка с ценой
        price_row = BoxLayout(size_hint=(1, None), height=dp(40), spacing=dp(4))
        self._prefix_lbl = Label(
            text="", color=TEXT_MUTED, font_size=sp(11),
            size_hint=(None, 1), width=dp(60),
        )
        self._price_lbl = Label(
            text="—", color=SUCCESS, font_size=sp(26), bold=True,
            halign="center", valign="middle",
            size_hint=(1, 1),
        )
        self._badge_lbl = Label(
            text="", color=DANGER, font_size=sp(11), bold=True,
            size_hint=(None, 1), width=dp(90),
        )
        price_row.add_widget(self._prefix_lbl)
        price_row.add_widget(self._price_lbl)
        price_row.add_widget(self._badge_lbl)
        inner.add_widget(price_row)

        self._old_lbl = Label(
            text="", markup=True,
            color=TEXT_MUTED, font_size=sp(11),
            size_hint=(1, None), height=dp(16),
        )
        inner.add_widget(self._old_lbl)

        # PS+
        ps_row = BoxLayout(size_hint=(1, None), height=dp(28), spacing=dp(4))
        self._ps_prefix = Label(
            text="", color=TEXT_DIM, font_size=sp(11), bold=True,
            size_hint=(None, 1), width=dp(36),
        )
        self._ps_price_lbl = Label(
            text="", color=PS_PLUS_CLR, font_size=sp(20), bold=True,
            halign="center", valign="middle",
            size_hint=(1, 1),
        )
        self._ps_badge = Label(
            text="", color=PS_PLUS_CLR, font_size=sp(11), bold=True,
            size_hint=(None, 1), width=dp(90),
        )
        ps_row.add_widget(self._ps_prefix)
        ps_row.add_widget(self._ps_price_lbl)
        ps_row.add_widget(self._ps_badge)
        inner.add_widget(ps_row)

        return outer

    # ── расчёт ───────────────────────────────────────────────────────────────

    def _refresh_details(self):
        if not self._selected:
            return
        details = self._api.fetch_product_details(self._selected["id"])
        if not details:
            return
        for f in ("price", "original_price", "discount_pct",
                  "ps_plus_price", "ps_plus_discount_pct", "name"):
            v = details.get(f)
            if v is not None and (v != "" or not self._selected.get(f)):
                self._selected[f] = v
        if details.get("has_trial"):
            self._selected["has_trial"] = True
        for f in ("platforms", "has_ru_voice", "has_ru_text"):
            if details.get(f) is not None:
                self._selected[f] = details[f]
        Clock.schedule_once(lambda dt: self._show_price(), 0)

    def _show_price(self):
        if not self._selected:
            return
        g = self._selected
        self._name_lbl.text = g.get("name", "")

        platforms = g.get("platforms") or []
        ps4 = any("PS4" in p.upper() for p in platforms)
        ps5 = any("PS5" in p.upper() for p in platforms)
        self._plat_lbl.text = (
            "[PS4+PS5]" if (ps4 and ps5) else
            "[PS5]"     if ps5 else
            "[PS4]"     if ps4 else ""
        )
        hv = g.get("has_ru_voice", False)
        ht = g.get("has_ru_text", False)
        self._lang_lbl.text = (
            "[Звук+Текст]" if (hv and ht) else
            "[Текст]"      if ht else
            "[Звук]"       if hv else ""
        )
        self._trial_lbl.opacity = 1 if g.get("has_trial") else 0
        self._recalc()

    def _recalc(self):
        free = self._free_tf.text.strip()
        if free:
            price_s = free
            orig_s = disc_pct = ps_s = ps_pct = ""
        elif self._selected:
            g = self._selected
            price_s = g.get("price") or ""
            orig_s  = g.get("original_price") or ""
            disc_pct = g.get("discount_pct") or ""
            ps_s    = g.get("ps_plus_price") or ""
            ps_pct  = g.get("ps_plus_discount_pct") or ""
        else:
            return

        brackets = self.region_brackets[self._region]

        def to_rub(s):
            v = clean_price(s)
            if v == 0:
                return None
            coeff, add = get_price_params(v, brackets)
            return round(round(v * coeff + add) / 10) * 10

        def fmt(a):
            return f"{a} ₽" if a is not None else ""

        reg  = to_rub(price_s)
        orig = to_rub(orig_s)
        ps   = to_rub(ps_s)

        has_disc = bool(orig_s and disc_pct)
        has_ps   = bool(ps_s)

        if reg is not None:
            self._price_lbl.text = fmt(reg)
            if has_disc:
                self._prefix_lbl.text = ""
                self._badge_lbl.text = f"СКИДКА {disc_pct}"
                self._old_lbl.text = f"[s]{fmt(orig)}[/s]"
            elif has_ps:
                self._prefix_lbl.text = "Обычная"
                self._badge_lbl.text = ""
                self._old_lbl.text = ""
            else:
                self._prefix_lbl.text = ""
                self._badge_lbl.text = ""
                self._old_lbl.text = ""
        else:
            self._price_lbl.text = "—"
            self._prefix_lbl.text = ""
            self._badge_lbl.text = ""
            self._old_lbl.text = ""

        if has_ps and ps is not None:
            self._ps_prefix.text = "PS+"
            self._ps_price_lbl.text = fmt(ps)
            self._ps_badge.text = f"СКИДКА {ps_pct}" if ps_pct else ""
        else:
            self._ps_prefix.text = ""
            self._ps_price_lbl.text = ""
            self._ps_badge.text = ""

    def _reset_display(self):
        self._name_lbl.text = "—"
        self._plat_lbl.text = ""
        self._lang_lbl.text = ""
        self._trial_lbl.opacity = 0
        self._price_lbl.text = "—"
        self._prefix_lbl.text = ""
        self._badge_lbl.text = ""
        self._old_lbl.text = ""
        self._ps_prefix.text = ""
        self._ps_price_lbl.text = ""
        self._ps_badge.text = ""

    def _clear_results(self):
        self._selected = None
        self._reset_display()

    # ── диалог параметров ────────────────────────────────────────────────────

    def _open_params(self):
        self._dlg_region = REGIONS[0][0]
        self._dlg_coeff = {}
        self._dlg_add = {}
        for code, *_ in REGIONS:
            self._dlg_coeff[code] = []
            self._dlg_add[code] = []
            for row in self.region_brackets[code]:
                v_add = row[3]
                s_add = str(int(v_add) if float(v_add) == int(float(v_add)) else v_add)
                self._dlg_coeff[code].append(TextInput(
                    text=str(row[2]), multiline=False,
                    input_filter="float",
                    background_color=DARK_INPUT, foreground_color=TEXT,
                    cursor_color=TEXT, font_size=sp(12),
                    size_hint=(None, None), width=dp(72), height=dp(38),
                    halign="center",
                    padding=[dp(4), dp(10), dp(4), dp(4)],
                ))
                self._dlg_add[code].append(TextInput(
                    text=s_add, multiline=False,
                    input_filter="float",
                    background_color=_c("#1A2A1A"), foreground_color=SUCCESS,
                    cursor_color=TEXT, font_size=sp(12),
                    size_hint=(None, None), width=dp(72), height=dp(38),
                    halign="center",
                    padding=[dp(4), dp(10), dp(4), dp(4)],
                ))

        wrap = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        _bg(wrap, BG)

        # Переключатель регионов
        reg_row = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(6))
        self._dlg_reg_btns = {}
        for code, label, *_ in REGIONS:
            b = Button(
                text=label, font_size=sp(12),
                background_normal="", color=TEXT_DIM,
            )
            b._code = code
            b.bind(on_release=lambda btn: self._dlg_switch(btn._code))
            self._dlg_reg_btns[code] = b
            reg_row.add_widget(b)
        wrap.add_widget(reg_row)
        self._dlg_refresh_btns()

        # Заголовок таблицы
        hdr = BoxLayout(size_hint=(1, None), height=dp(24), spacing=dp(4))
        for txt, w in [("Мин", 50), ("Макс", 50), ("Коэф.", 72), ("Добав.", 72)]:
            hdr.add_widget(Label(
                text=txt, color=TEXT_DIM, font_size=sp(10), bold=True,
                size_hint=(None, 1), width=dp(w),
            ))
        wrap.add_widget(hdr)

        # Скролл-таблица
        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self._dlg_col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        self._dlg_col.bind(minimum_height=self._dlg_col.setter("height"))
        scroll.add_widget(self._dlg_col)
        wrap.add_widget(scroll)
        self._dlg_draw(REGIONS[0][0])

        # Кнопки
        btn_row = BoxLayout(size_hint=(1, None), height=dp(48), spacing=dp(8))
        close_b = Button(
            text="Закрыть", font_size=sp(13),
            background_normal="", background_color=SURFACE_2, color=TEXT_DIM,
        )
        save_b = Button(
            text="Сохранить", font_size=sp(13), bold=True,
            background_normal="", background_color=ACCENT, color=TEXT,
        )
        btn_row.add_widget(close_b)
        btn_row.add_widget(save_b)
        wrap.add_widget(btn_row)

        popup = Popup(
            title="Коэффициенты расчёта",
            title_color=TEXT,
            title_size=sp(14),
            content=wrap,
            size_hint=(0.97, 0.93),
            background_color=BG,
            separator_color=BORDER,
        )
        close_b.bind(on_release=lambda *_: popup.dismiss())
        save_b.bind(on_release=lambda *_: self._params_save(popup))
        popup.open()

    def _dlg_switch(self, code):
        self._dlg_region = code
        self._dlg_refresh_btns()
        self._dlg_draw(code)

    def _dlg_refresh_btns(self):
        for code, btn in self._dlg_reg_btns.items():
            if code == self._dlg_region:
                btn.background_color = ACCENT_DIM
                btn.color = TEXT
                btn.bold = True
            else:
                btn.background_color = SURFACE_2
                btn.color = TEXT_DIM
                btn.bold = False

    def _dlg_draw(self, code):
        self._dlg_col.clear_widgets()
        brackets = self.region_brackets[code]
        for i, bkt in enumerate(brackets):
            row = BoxLayout(
                orientation="horizontal",
                size_hint=(1, None), height=dp(44), spacing=dp(4),
                padding=[dp(4), dp(2)],
            )
            _bg(row, SURFACE if i % 2 == 0 else SURFACE_2)
            row.add_widget(Label(
                text=str(int(bkt[0])), color=TEXT_DIM, font_size=sp(11),
                size_hint=(None, 1), width=dp(50),
            ))
            row.add_widget(Label(
                text=str(int(bkt[1])), color=TEXT_DIM, font_size=sp(11),
                size_hint=(None, 1), width=dp(50),
            ))
            # Снимаем старого родителя — TextInput'ы переиспользуются между регионами
            cf = self._dlg_coeff[code][i]
            af = self._dlg_add[code][i]
            if cf.parent:
                cf.parent.remove_widget(cf)
            if af.parent:
                af.parent.remove_widget(af)
            row.add_widget(cf)
            row.add_widget(af)
            self._dlg_col.add_widget(row)

    def _params_save(self, popup):
        for code, *_ in REGIONS:
            brackets = self.region_brackets[code]
            for i, (cf, af) in enumerate(zip(self._dlg_coeff[code], self._dlg_add[code])):
                try:
                    brackets[i][2] = float(cf.text.replace(",", "."))
                except ValueError:
                    pass
                try:
                    brackets[i][3] = float(af.text.replace(",", "."))
                except ValueError:
                    pass
        data = {code: {"brackets": self.region_brackets[code]} for code, *_ in REGIONS}
        if self._settings_file:
            save_settings(self._settings_file, data)
        self._recalc()
        popup.dismiss()


if __name__ == "__main__":
    PSApp().run()
